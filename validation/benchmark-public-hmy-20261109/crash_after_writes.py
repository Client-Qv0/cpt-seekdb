#!/usr/bin/env python3
"""Kill the production-image DB after all benchmark writes are acknowledged."""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path('tests').resolve()))
import numpy as np
import audit_performance as oracle
import benchmark_public_validation as benchmark
import cardinality_probe as adapter
import paired_benchmark as paired

out = Path('validation/benchmark-public-hmy-20261109')
metadata = json.loads((out / 'seed-3179/metadata.json').read_text())
image, socket, cpuset = metadata['image_id'], metadata['docker_socket'], metadata['cpuset']
binary = Path('/mnt/e/MiniVectorDB/production-image-minivectordb')
oracle.SEED = 3179
batches, queries = oracle.generate_sql()
ids, groups, vectors, _ = oracle.parse_oracle_inputs(batches, queries, np)
data = Path(tempfile.mkdtemp(prefix='mvdb-public-crash-', dir='/var/tmp')) / 'data'
report = {'data_directory': str(data), 'image_id': image, 'seed': oracle.SEED,
          'scope': 'post-acknowledgement SIGKILL recovery check; not timed benchmark',
          'acknowledged_batches': 0, 'failure': None}

class ProductionContainer(adapter.ContainerDatabase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, image_binary='/app/minivectordb', **kwargs)

db = None
try:
    db = ProductionContainer(binary, data, image=image, socket=socket, label='kill-after-writes', cpuset=cpuset)
    paired.validate_runtime_snapshot(db.capture('initial'), cpuset)
    db.query(oracle.CREATE_SQL, timeout=120)
    for statement in batches:
        response = db.query(statement, timeout=120)
        if response.get('affected') != oracle.BATCH_SIZE:
            raise AssertionError(f'bad batch acknowledgement: {response!r}')
        report['acknowledged_batches'] += 1
    db.close(kill=True)
    report['killed_container'] = db.record
    report['killed_resources'] = paired.resources(db.record)
    if not report['killed_resources']['healthy']:
        raise AssertionError('container termination was not the requested non-OOM SIGKILL')
    readback = benchmark.readback(ProductionContainer, binary, data, image, socket, cpuset,
                                  (ids, groups, vectors), out / 'crash-full-readback.json.gz')
    report['readback'] = readback
    if not readback['passed']:
        raise AssertionError(f'restart readback failed: {readback.get("failure")}')
except Exception as error:
    report['failure'] = f'{type(error).__name__}: {error}'
finally:
    if db and not db.closed:
        db.close(kill=True)
        report['killed_container'] = db.record
report['passed'] = report['failure'] is None and report['acknowledged_batches'] == 100
paired.write_json(out / 'crash-recovery.json', report)
print(json.dumps({'passed': report['passed'], 'batches': report['acknowledged_batches'],
                  'readback_rows': report.get('readback', {}).get('checked_rows'),
                  'failure': report['failure']}))
raise SystemExit(0 if report['passed'] else 1)
