#!/usr/bin/env python3
"""Recheck archived inputs, all query responses and all post-restart rows."""
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path('tests').resolve()))
import numpy as np
import audit_performance as oracle
import paired_benchmark as paired

root = Path('validation/benchmark-public-hmy-20261109')
sets = [('seed-3179', 3179, 3), ('seed-9143', 9143, 1), ('seed-27183', 27183, 1),
        ('seed-2468-audit', 2468, 1)]
report = []
for folder, seed, count in sets:
    oracle.SEED = seed
    batches, queries = oracle.generate_sql()
    statements = [oracle.CREATE_SQL] + batches + queries
    with gzip.open(root / folder / 'workload.sql.gz', 'rt', encoding='utf-8') as stream:
        archived = stream.read().splitlines()
    if archived != statements:
        raise AssertionError(f'{folder}: archived workload differs from generated workload')
    metadata = json.loads((root / folder / 'metadata.json').read_text())
    assert metadata['workload_sha256'] == oracle.sequence_sha256(statements)
    truth, _ = paired.prepare_oracle(oracle, batches, queries)
    ids, groups, vectors, _ = oracle.parse_oracle_inputs(batches, queries, np)
    for index in range(1, count + 1):
        run = root / folder / f'round-{index}'
        responses = json.loads((run / 'responses.json').read_text())
        checks, recall = paired.check_responses(responses['queries'], truth, oracle)
        assert len(checks) == 1011 and all(item['passed'] for item in checks)
        assert len(responses['writes']) == 100 and all(item.get('affected') == 100 for item in responses['writes'])
        assert recall['filtered']['queries'] == recall['unfiltered']['queries'] == 500
        with gzip.open(run / 'full-readback.json.gz', 'rt', encoding='utf-8') as stream:
            rows = json.load(stream)
        assert rows['ok'] is True and rows['columns'] == ['id', 'grp', 'v'] and len(rows['rows']) == 10000
        for position, (key, group, vector) in enumerate(rows['rows']):
            assert type(key) is int and key == int(ids[position]) and group == f'g{int(groups[position])}'
            assert np.array_equal(np.asarray(vector, dtype=np.float32), vectors[position].astype(np.float32))
        report.append({'seed': seed, 'round': index, 'query_results_checked': len(checks),
                       'write_batches_checked': len(responses['writes']), 'persisted_rows_checked': len(rows['rows']),
                       'filtered_recall': recall['filtered']['mean_recall_at_10'],
                       'unfiltered_recall': recall['unfiltered']['mean_recall_at_10'], 'passed': True})
        print(f'{folder} round {index}: passed', flush=True)
paired.write_json(root / 'offline-audit.json', {'runs': report, 'all_passed': len(report) == 6})
