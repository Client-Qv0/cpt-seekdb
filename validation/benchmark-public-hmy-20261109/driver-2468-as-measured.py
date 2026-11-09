#!/usr/bin/env python3
"""Local validation of the published 10k/128D workload shape, not an official driver.

Runs a frozen local workload under separate Docker cgroups and checks every
query against an independent exhaustive oracle. After the measured container
has stopped, a new container reads and verifies every persisted record. This
does not claim the unpublished official generator, protocol, baseline or score.
"""
import argparse
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import audit_performance as oracle
import cardinality_probe as adapter
import paired_benchmark as paired


def docker_socket():
    if os.environ.get('DOCKER_HOST'):
        return os.environ['DOCKER_HOST']
    context = subprocess.check_output(['docker', 'context', 'show'], text=True).strip()
    return subprocess.check_output(['docker', 'context', 'inspect', context, '--format',
                                    '{{.Endpoints.docker.Host}}'], text=True).strip()


def check_image_binary(image, path, image_binary, output):
    """Bind benchmark identity to the executable actually inside the image."""
    name = subprocess.check_output(['docker', 'create', '--entrypoint', image_binary, image], text=True).strip()
    try:
        subprocess.run(['docker', 'cp', f'{name}:{image_binary}', str(output)], check=True)
    finally:
        subprocess.run(['docker', 'rm', name], stdout=subprocess.DEVNULL, check=True)
    actual, expected = paired.sha256_file(output), paired.sha256_file(path)
    if actual != expected:
        raise RuntimeError(f'image binary SHA {actual} differs from supplied binary SHA {expected}')
    return actual


def copy_evidence(source, destination):
    for path in source.rglob('*'):
        relative = path.relative_to(source)
        if 'data' in relative.parts or not path.is_file():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def readback(client_class, binary, data, image, socket, cpuset, expected, artifact):
    import numpy as np
    ids, groups, vectors = expected
    db = None
    report = {'phase': 'post-measurement separate container', 'expected_rows': len(ids),
              'checked_rows': 0, 'failure': None}
    try:
        db = client_class(binary, data, image=image, socket=socket, label='full-readback', cpuset=cpuset)
        response = db.query('SELECT id,grp,v FROM bench ORDER BY id;', timeout=180)
        # Preserve the entire response, not just a summary or file size.
        with gzip.open(artifact, 'wt', encoding='utf-8') as stream:
            json.dump(response, stream, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        if response.get('columns') != ['id', 'grp', 'v']:
            raise AssertionError(f"unexpected columns: {response.get('columns')!r}")
        rows = response.get('rows')
        if not isinstance(rows, list) or len(rows) != len(ids):
            raise AssertionError(f'expected {len(ids)} rows, got {len(rows) if isinstance(rows, list) else None}')
        for index, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != 3:
                raise AssertionError(f'invalid row shape at {index}')
            key, group, vector = row
            if type(key) is not int or key != int(ids[index]) or group != f'g{int(groups[index])}':
                raise AssertionError(f'ID/group mismatch at {index}: {row[:2]!r}')
            if (not isinstance(vector, list) or
                    any(type(x) not in (int, float) or not math.isfinite(x) for x in vector)):
                raise AssertionError(f'invalid vector values at row {index}')
            actual = np.asarray(vector, dtype=np.float32)
            if actual.shape != (oracle.DIMENSION,) or not np.array_equal(actual, vectors[index].astype(np.float32)):
                raise AssertionError(f'vector mismatch at row {index}')
            report['checked_rows'] += 1
        report['response_sha256'] = paired.sha256_file(artifact)
    except Exception as error:
        report['failure'] = f'{type(error).__name__}: {error}'
    finally:
        if db:
            try:
                db.close(kill=report['failure'] is not None, timeout=30)
            except Exception as error:
                report['close_failure'] = repr(error)
            report['container_record'] = db.record
            report['resources'] = paired.resources(db.record)
    report['passed'] = (report['failure'] is None and 'close_failure' not in report
                        and report['checked_rows'] == len(ids) and report.get('resources', {}).get('healthy') is True)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True, help='Binary extracted from, and hash-checked against, the image')
    p.add_argument('--image', required=True)
    p.add_argument('--image-binary', default='/app/minivectordb')
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--data-parent', type=Path, required=True, help='Linux ext4 directory for task-owned DB files')
    p.add_argument('--seed', type=int, default=3179)
    p.add_argument('--rounds', type=int, default=3)
    args = p.parse_args()
    if args.rounds < 1:
        p.error('--rounds must be positive')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    fs = subprocess.check_output(['findmnt', '-n', '-o', 'FSTYPE', '-T', str(args.data_parent)], text=True).strip()
    if fs != 'ext4':
        raise RuntimeError(f'data parent must be ext4 for this disk experiment, got {fs}')
    socket = docker_socket()
    image = subprocess.check_output(['docker', 'image', 'inspect', args.image, '--format', '{{.Id}}'], text=True).strip()
    binary = args.binary.resolve()
    binary_hash = check_image_binary(image, binary, args.image_binary, out / 'image-binary-copy')
    identity = paired.identity(binary, args.source, args.manifest)
    affinity = sorted(os.sched_getaffinity(0))
    if len(affinity) < 2:
        raise RuntimeError('at least two allowed CPUs are required')
    cpuset = ','.join(map(str, affinity[:2]))
    oracle.SEED = args.seed
    batches, queries = oracle.generate_sql()
    sql = [oracle.CREATE_SQL] + batches + queries
    with gzip.open(out / 'workload.sql.gz', 'wt', encoding='utf-8') as stream:
        stream.write('\n'.join(sql) + '\n')
    truth, oracle_info = paired.prepare_oracle(oracle, batches, queries)
    paired.write_json(out / 'oracle-truth.json', truth)
    import numpy as np
    ids, groups, vectors, _ = oracle.parse_oracle_inputs(batches, queries, np)
    data_root = Path(tempfile.mkdtemp(prefix='mvdb-public-benchmark-', dir=args.data_parent))
    tool_paths = [Path(__file__).resolve(), Path(oracle.__file__).resolve(),
                  Path(adapter.__file__).resolve(), Path(paired.__file__).resolve()]
    tool_hashes = {str(path): paired.sha256_file(path) for path in tool_paths}
    metadata = {'scope': 'local development protocol; published workload shape only; not official benchmark',
                'seed': args.seed, 'rounds': args.rounds, 'rows': oracle.ROWS, 'dimension': oracle.DIMENSION,
                'queries': oracle.QUERY_COUNT, 'batch_size': oracle.BATCH_SIZE, 'top_k': oracle.TOP_K,
                'filtered_queries': sum(' WHERE ' in q for q in queries), 'data_filesystem': fs,
                'data_root': str(data_root), 'image_id': image, 'image_binary': args.image_binary,
                'image_binary_sha256': binary_hash, 'source_and_binary': identity, 'docker_socket': socket,
                'cpuset': cpuset, 'workload_sha256': oracle.sequence_sha256(sql), 'oracle': oracle_info,
                'tool_sha256': tool_hashes,
                'limitations': ['Official generator/seed, driver/protocol, baseline and limits not supplied.',
                                'Shared WSL ext4 device; cgroup I/O is raw, not a calibrated exclusive data-device score.',
                                'Cgroup first sample is after container launch; no global cache drops or filesystem-wide sync.']}
    paired.write_json(out / 'metadata.json', metadata)

    class ProductionContainer(adapter.ContainerDatabase):
        def __init__(self, *a, **kw):
            super().__init__(*a, image_binary=args.image_binary, **kw)
    class ProductionAdapter:
        ContainerDatabase = ProductionContainer

    results = []
    for index in range(args.rounds):
        label = f'round-{index + 1}'
        print(f'Starting {label} seed={args.seed}', flush=True)
        path = data_root / label
        result = paired.run_one(ProductionAdapter, label, 'production-image', identity, path,
                                batches, queries, truth, oracle, image, socket, cpuset)
        verification = readback(ProductionContainer, binary, path / 'data', image, socket, cpuset,
                                (ids, groups, vectors), path / 'full-readback.json.gz') if result['passed'] else {'passed': False, 'reason': 'measured run failed'}
        paired.write_json(path / 'full-readback-report.json', verification)
        result['full_readback'] = {key: value for key, value in verification.items() if key not in ('container_record',)}
        result['overall_passed'] = result['passed'] and verification['passed']
        paired.write_json(path / 'run-with-readback.json', result)
        copy_evidence(path, out / label)
        results.append({'round': index + 1, 'passed': result['overall_passed'],
                        'timings': result['timings'], 'correctness': result['correctness'],
                        'readback_rows': verification.get('checked_rows'),
                        'main_resources': result['resources']['main'], 'failure': result['failure'] or verification.get('failure')})
        paired.write_json(out / 'summary.json', {'runs': results, 'planned_rounds': args.rounds,
                                                'all_passed': len(results) == args.rounds and all(r['passed'] for r in results)})
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    tools_unchanged = all(paired.sha256_file(path) == tool_hashes[str(path)] for path in tool_paths)
    paired.write_json(out / 'completion.json', {'tools_unchanged': tools_unchanged,
                                                'completed_rounds': len(results), 'planned_rounds': args.rounds})
    return 0 if len(results) == args.rounds and all(result['passed'] for result in results) and tools_unchanged else 1


if __name__ == '__main__':
    raise SystemExit(main())
