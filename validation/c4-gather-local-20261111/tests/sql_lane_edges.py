#!/usr/bin/env python3
"""Default JSONL exact-distance lane/tail regression, with an independent oracle.

Run baseline and candidate sequentially. This is a correctness test, not a timing
benchmark. BIGINT is the only supported primary-key type; VARCHAR is covered as
a filter/projection type. No development protocol or test bridge is used.
"""
import argparse
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import select
import struct
import subprocess
import time
import traceback


DIMENSIONS = (1, 3, 5, 33, 129)
SEED = 69203
KEY_BASE = 9007199254740993


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fp32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def vector(values):
    return '[' + ','.join(repr(x) for x in values) + ']'


def l2(a, b):
    # Deliberately scalar, sequential FP64 operations on FP32 inputs; no engine
    # imports, NumPy, vectorized reduction, cached database results or ANN.
    total = 0.0
    for x, y in zip(a, b):
        difference = float(x) - float(y)
        total = total + difference * difference
    return math.sqrt(total)


class Session:
    def __init__(self, binary, data, trace, stderr_path, label):
        self.trace = trace
        self.label = label
        self.number = 0
        self.buffer = b''
        self.stderr = stderr_path.open('wb')
        self.command = [str(binary), '--data-dir', str(data)]
        self.trace.write(json.dumps({'event': 'start', 'label': label,
                                     'command': self.command}) + '\n')
        self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=self.stderr,
                                        bufsize=0)
        assert self.line() == {'type': 'ready'}, 'incorrect ready handshake'

    def line(self):
        deadline = time.monotonic() + 30
        while b'\n' not in self.buffer:
            ready, _, _ = select.select([self.process.stdout], [], [],
                                         max(0, deadline - time.monotonic()))
            assert ready, 'response or flush timeout'
            chunk = self.process.stdout.read(65536)
            assert chunk, 'unexpected EOF, exit=' + str(self.process.poll())
            self.buffer += chunk
        raw, self.buffer = self.buffer.split(b'\n', 1)
        self.trace.write(json.dumps({'event': 'response', 'label': self.label,
                                     'raw': raw.decode('utf-8')}, ensure_ascii=False) + '\n')
        return json.loads(raw)

    def request(self, sql=None, op='execute', context=None):
        self.number += 1
        identity = {'test': 'C4 lane edges', 'n': self.number}
        message = {'id': identity, 'op': op}
        if sql is not None:
            message.update(sql=sql, search_mode='exact')
        self.trace.write(json.dumps({'event': 'request', 'label': self.label,
                                     'context': context, 'message': message},
                                    ensure_ascii=False, allow_nan=False) + '\n')
        payload = (json.dumps(message, ensure_ascii=False, allow_nan=False,
                              separators=(',', ':')) + '\n').encode('utf-8')
        while payload:
            count = self.process.stdin.write(payload)
            assert count, 'short pipe write'
            payload = payload[count:]
        self.process.stdin.flush()
        response = self.line()
        assert response.get('id') == identity, response
        assert response.get('ok') is True, response
        return response

    def close(self):
        self.request(op='shutdown')
        self.process.stdin.close()
        assert self.process.wait(timeout=20) == 0
        assert not self.buffer and self.process.stdout.read() == b'', 'extra stdout'
        self.stderr.close()

    def abort(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=20)
        self.stderr.close()


def initial_rows(dim):
    rng = random.Random(SEED + dim)
    rows = {}
    for seq in range(40):
        # Exact binary fractions keep input parsing independently checkable.
        values = [fp32(rng.randrange(-128, 129) / 8.0) for _ in range(dim)]
        if seq in (0, 1, 5, 10, 15):
            values = [0.0] * dim  # noncontiguous equal-distance rows, PK ties
        rows[KEY_BASE + seq] = {'seq': seq, 'grp': seq % 5,
                               'label': 'g' + str(seq % 5),
                               'mark': 'cross' if seq in (3, 4, 7, 8) else 'other',
                               'v': values}
    return rows


def row_literal(key, row):
    return (f"({key},{row['seq']},{row['grp']},'{row['label']}',"
            f"'{row['mark']}','{vector(row['v'])}')")


def filters():
    result = []
    for n in range(6):
        upper = 5 * (n - 1)
        for kind, condition in (('BIGINT', 'grp=0'), ('VARCHAR', "label='g0'")):
            result.append((f'{kind}-initial-{n}-eligible',
                           f' WHERE {condition} AND seq<={upper}',
                           lambda r, u=upper, k=kind: r['seq'] <= u and
                           (r['grp'] == 0 if k == 'BIGINT' else r['label'] == 'g0')))
    result.extend([
        ('mod5-bigint-all', ' WHERE grp=1', lambda r: r['grp'] == 1),
        ('mod5-varchar-all', " WHERE label='g1'", lambda r: r['label'] == 'g1'),
        ('cross-adjacent-block', ' WHERE seq>=1 AND seq<=4', lambda r: 1 <= r['seq'] <= 4),
        ('cross-noncontiguous-block', " WHERE mark='cross'", lambda r: r['mark'] == 'cross'),
        ('unfiltered', '', lambda r: True),
    ])
    return result


def verify(session, table, rows, dim, stage, stats, trace):
    rng = random.Random(SEED * 3 + dim)
    queries = [[0.0] * dim,
               [fp32(rng.randrange(-64, 65) / 16.0) for _ in range(dim)]]
    other = [fp32((d % 7 - 3) / 4.0) for d in range(dim)]
    for query_index, query in enumerate(queries):
        for name, clause, include in filters():
            selected = [(key, row) for key, row in rows.items() if include(row)]
            ordered = sorted((l2(row['v'], query), key, row) for key, row in selected)
            if stage == 'initial' and '-initial-' in name:
                asserted_count = int(name.split('-initial-')[1].split('-')[0])
                assert len(selected) == asserted_count
                stats['initial_eligible_counts'].add(len(selected))
            for k in (1, 3, 7):
                expected = [[key, row['seq'], row['grp'], row['label'], dist,
                             l2(row['v'], other)] for dist, key, row in ordered[:k]]
                sql = (f"SELECT id,seq,grp,label,L2_DISTANCE(v,'{vector(query)}') AS d,"
                       f"L2_DISTANCE(v,'{vector(other)}') AS other_d FROM {table}{clause} "
                       f'ORDER BY d LIMIT {k};')
                # Both executions are checked independently: the first request
                # after create/update/restart may build the cache; repeat is hot.
                for repetition in (0, 1):
                    context = {'table': table, 'dimension': dim, 'stage': stage,
                               'filter': name, 'eligible_count': len(selected),
                               'query': query_index, 'k': k, 'repetition': repetition}
                    response = session.request(sql, context=context)
                    assert response['columns'] == ['id', 'seq', 'grp', 'label', 'd', 'other_d']
                    actual = response['rows']
                    assert len(actual) == len(expected), context
                    ids = [r[0] for r in actual]
                    assert all(type(x) is int for x in ids), context
                    assert len(ids) == len(set(ids)), context
                    assert ids == [r[0] for r in expected], context
                    for observed, wanted in zip(actual, expected):
                        assert observed[:4] == wanted[:4], (context, observed, wanted)
                        for at in (4, 5):
                            assert math.isfinite(observed[at]), (context, observed)
                            assert struct.pack('<d', float(observed[at])) == struct.pack('<d', wanted[at]), (
                                context, observed, wanted)
                    recall = 1.0 if not expected else len(set(ids) & {r[0] for r in expected}) / len(expected)
                    assert recall == 1.0, context
                    trace.write(json.dumps({'event': 'oracle', 'label': session.label,
                                            'context': context, 'expected_rows': expected,
                                            'ordered_ids_pass': True, 'duplicate_ids': 0,
                                            'filter_fields_pass': True,
                                            'distance_bitwise_pass': True, 'recall': recall},
                                           ensure_ascii=False, allow_nan=False) + '\n')
                    stats['queries'] += 1
                    stats['distance_checks'] += len(expected) * 2
                    stats['stages'].add(stage)


def run(binary, root, label):
    root.mkdir()
    stats = {'queries': 0, 'distance_checks': 0, 'initial_eligible_counts': set(), 'stages': set()}
    session = None
    with gzip.open(root / 'trace.jsonl.gz', 'wt', encoding='utf-8') as trace:
        try:
            session = Session(binary, root / 'data', trace, root / 'stderr-initial.log', label)
            persisted = {}
            for dim in DIMENSIONS:
                table = f'lanes_{dim}'
                rows = initial_rows(dim)
                session.request(f'CREATE TABLE {table}(id BIGINT PRIMARY KEY,seq BIGINT,grp BIGINT,'
                                f'label VARCHAR(32),mark VARCHAR(32),v VECTOR({dim}));')
                shuffled = list(rows)
                random.Random(SEED + dim * 7).shuffle(shuffled)
                session.request(f'INSERT INTO {table} VALUES ' + ','.join(row_literal(key, rows[key]) for key in shuffled))
                verify(session, table, rows, dim, 'initial', stats, trace)

                updated = [fp32((d % 3 - 1) / 2.0) for d in range(dim)]
                session.request(f"UPDATE {table} SET v='{vector(updated)}',grp=4,label='g4' WHERE id={KEY_BASE + 5}")
                rows[KEY_BASE + 5].update(v=updated, grp=4, label='g4')
                verify(session, table, rows, dim, 'after-update', stats, trace)

                session.request('BEGIN')
                tentative = copy.deepcopy(rows)
                changed = [fp32(2.25)] * dim
                session.request(f"UPDATE {table} SET v='{vector(changed)}',grp=1,label='g1' WHERE id={KEY_BASE + 10}")
                tentative[KEY_BASE + 10].update(v=changed, grp=1, label='g1')
                session.request(f'DELETE FROM {table} WHERE id={KEY_BASE + 15}')
                del tentative[KEY_BASE + 15]
                verify(session, table, tentative, dim, 'inside-rollback-transaction', stats, trace)
                session.request('ROLLBACK')
                verify(session, table, rows, dim, 'after-rollback', stats, trace)

                session.request('BEGIN')
                session.request(f"UPDATE {table} SET v='{vector(changed)}',grp=0,label='g0' WHERE id={KEY_BASE + 20}")
                rows[KEY_BASE + 20].update(v=changed, grp=0, label='g0')
                session.request(f'DELETE FROM {table} WHERE id={KEY_BASE + 25}')
                del rows[KEY_BASE + 25]
                extra = {'seq': 40, 'grp': 0, 'label': 'g0', 'mark': 'cross', 'v': [0.0] * dim}
                session.request(f'INSERT INTO {table} VALUES ' + row_literal(KEY_BASE + 40, extra))
                rows[KEY_BASE + 40] = extra
                session.request('COMMIT')
                verify(session, table, rows, dim, 'after-commit', stats, trace)
                persisted[dim] = rows
            session.close()
            session = Session(binary, root / 'data', trace, root / 'stderr-restart.log', label + '-restart')
            for dim in DIMENSIONS:
                verify(session, f'lanes_{dim}', persisted[dim], dim, 'after-clean-restart', stats, trace)
            session.close()
            session = None
        finally:
            if session is not None:
                session.abort()
    stats['initial_eligible_counts'] = sorted(stats['initial_eligible_counts'])
    stats['stages'] = sorted(stats['stages'])
    stats.update(binary=str(binary), binary_sha256=sha(binary), trace_sha256=sha(root / 'trace.jsonl.gz'))
    for path in root.glob('stderr-*.log'):
        assert path.stat().st_size == 0, f'unexpected stderr: {path}'
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new evidence directory')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('refusing to overwrite output')
    for path in (args.baseline, args.candidate):
        if not path.is_file():
            parser.error(f'binary missing: {path}')
    args.output.mkdir(parents=True)
    report = {'scope': 'native default JSONL correctness; no development bridge, timing or official scoring',
              'seed': SEED, 'dimensions': list(DIMENSIONS), 'primary_key_type': 'BIGINT only (official schema)',
              'filter_types': ['BIGINT', 'VARCHAR'], 'key_base': KEY_BASE,
              'tool_sha256': sha(__file__), 'independent_oracle': 'FP32 inputs, sequential FP64 L2, sqrt, PK tie',
              'limitations': ['No crash injection or resource measurement in this supplemental test',
                              'No claim of branch coverage; AVX2 dispatch requires separate binary/CPU evidence',
                              'Cache cold/warm is inferred from normal lifecycle, no diagnostic switch'],
              'status': 'running'}
    try:
        report['baseline'] = run(args.baseline.resolve(), args.output / 'baseline', 'baseline')
        report['candidate'] = run(args.candidate.resolve(), args.output / 'candidate', 'candidate')
        report['status'] = 'pass'
    except BaseException:
        report['status'] = 'fail'
        report['failure'] = traceback.format_exc()
        raise
    finally:
        (args.output / 'report.json').write_bytes((json.dumps(report, ensure_ascii=False, indent=2,
                                                             allow_nan=False) + '\n').encode('utf-8'))
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
