#!/usr/bin/env python3
"""Default JSONL stream/flush regression; native binaries, not a benchmark."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import select
import signal
import subprocess
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Session:
    def __init__(self, binary, directory, trace, name):
        self.trace, self.name, self.sequence = trace, name, 0
        self.process = subprocess.Popen([binary, '--data-dir', str(directory)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.buffer = b''
        assert self.line() == {'type': 'ready'}

    def line(self):
        deadline = time.monotonic() + 30
        while b'\n' not in self.buffer:
            ready, _, _ = select.select([self.process.stdout], [], [], max(0, deadline - time.monotonic()))
            assert ready, 'response/flush timeout'
            chunk = self.process.stdout.read(65536)
            assert chunk, f'EOF: {self.process.poll()}'
            self.buffer += chunk
        raw, self.buffer = self.buffer.split(b'\n', 1)
        self.trace.write(json.dumps({'case': self.name, 'response_raw': raw.decode('utf-8')}, ensure_ascii=False) + '\n')
        return json.loads(raw)

    def write(self, raw):
        while raw:
            n = self.process.stdin.write(raw)
            assert n
            raw = raw[n:]

    def request(self, sql=None, op='execute', ok=True, split=False):
        self.sequence += 1
        identity = ['请求🙂', 9007199254740993, None, {'中': ['x', 2]}][self.sequence % 4]
        request = {'id': identity, 'op': op}
        if sql is not None:
            request.update(sql=sql, search_mode='exact')
        raw = json.dumps(request, ensure_ascii=False, separators=(',', ':')).encode()
        self.trace.write(json.dumps({'case': self.name, 'request': request}, ensure_ascii=False) + '\n')
        self.write(raw)
        if split:
            assert not self.buffer
            assert not select.select([self.process.stdout], [], [], 0.1)[0], 'request executed before JSONL newline'
        self.write(b'\n')
        response = self.line()
        assert response['id'] == identity and type(response['id']) is type(identity), response
        assert response['ok'] is ok, response
        return response

    def close(self):
        self.request(op='shutdown')
        self.process.stdin.close()
        assert self.process.wait(timeout=20) == 0
        assert not self.buffer and self.process.stdout.read() == b''
        assert self.process.stderr.read() == b''


def run(binary, out, label):
    out.mkdir(parents=True)
    cases = []
    with gzip.open(out / 'trace.jsonl.gz', 'wt', encoding='utf-8') as trace:
        data = out / 'data'
        s = Session(binary, data, trace, 'ready-no-input')
        assert s.process.poll() is None
        cases.append('ready emitted before input')
        s.request('CREATE TABLE t(id BIGINT PRIMARY KEY,s VARCHAR(4096))', split=True)
        cases.append('newline framing and response flush before next request')
        s.request("INSERT INTO t VALUES(1,'Unicode 中🙂')")
        s.request('INVALID STATEMENT', ok=False)
        response = s.request('SELECT id,s FROM t ORDER BY id')
        assert response['columns'] == ['id', 's'] and response['rows'] == [[1, 'Unicode 中🙂']]
        cases.append('error response then Unicode/BIGINT/object-ID continued communication')
        text = 'x' * 4096
        for begin in range(2, 1202, 50):
            inserted = s.request('INSERT INTO t VALUES ' + ','.join(f"({i},'{text}')" for i in range(begin, begin + 50)))
            assert inserted['affected_rows'] == 50
        large = s.request('SELECT id,s FROM t ORDER BY id')
        assert large['columns'] == ['id', 's']
        assert len(large['rows']) == 1201
        assert large['rows'][0] == [1, 'Unicode 中🙂']
        assert large['rows'][1:] == [[i, text] for i in range(2, 1202)]
        cases.append('large streamed result >4MiB consumed completely without next request')
        s.close()
        cases.append('explicit shutdown response flush then exit0, no extra stdout')
        empty = Session(binary, out / 'empty-data', trace, 'empty-EOF')
        empty.process.stdin.close()
        assert empty.process.wait(timeout=20) == 0
        assert empty.process.stdout.read() == b'' and empty.process.stderr.read() == b''
        cases.append('empty EOF after ready exits0')
        s = Session(binary, data, trace, 'EOF-transaction')
        s.request('BEGIN')
        s.request("INSERT INTO t VALUES(2000,'uncommitted-EOF')")
        s.process.stdin.close()
        assert s.process.wait(timeout=20) == 0
        assert s.process.stdout.read() == b'' and s.process.stderr.read() == b''
        s = Session(binary, data, trace, 'EOF-recovery')
        assert s.request('SELECT id FROM t WHERE id=2000')['rows'] == []
        s.close()
        cases.append('EOF shutdown rolls back uncommitted transaction and reopens')
        s = Session(binary, data, trace, 'broken-stdout')
        s.request('BEGIN')
        s.request("INSERT INTO t VALUES(2001,'uncommitted-broken-output')")
        s.process.stdout.close()
        s.write(b'{"id":"broken","op":"execute","sql":"SELECT id FROM t WHERE id=1"}\n')
        code = s.process.wait(timeout=20)
        assert code != 0, code
        stderr = s.process.stderr.read().decode()
        trace.write(json.dumps({'case': 'broken-stdout', 'exit_code': code, 'stderr': stderr}) + '\n')
        s.process.stdin.close()
        s = Session(binary, data, trace, 'broken-stdout-recovery')
        assert s.request('SELECT id FROM t WHERE id=2001')['rows'] == []
        assert s.request('SELECT id,s FROM t WHERE id=1')['rows'] == [[1, 'Unicode 中🙂']]
        s.close()
        cases.append('closed stdout causes nonzero exit; committed data preserved and uncommitted discarded')
    result = {'label': label, 'status': 'PASS', 'binary': binary, 'binary_sha256': sha(binary),
              'cases': cases, 'broken_stdout_exit_code': code, 'trace_sha256': sha(out / 'trace.jsonl.gz'),
              'scope': 'Native default formal JSONL entry, correctness only. No Docker or performance claims.'}
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    results = [run(binary, output / label, label) for label, binary in [('baseline', args.baseline), ('candidate', args.candidate)]]
    report = {'tool_sha256': sha(__file__), 'status': 'PASS', 'versions': results}
    (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))
