"""Development-only paired V5/candidate checks on independent synthetic data.

This is not the organizer's harness or either official evaluation dataset.
Uses the published SQL shape with 4096 individual Top-10/100 queries.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import numpy as np
import pymysql


def vector(row):
    return '[' + ','.join(format(float(x), '.9g') for x in row) + ']'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--binary', required=True, type=Path)
    ap.add_argument('--bridge-dir', required=True, type=Path)
    ap.add_argument('--root', required=True, type=Path)
    ap.add_argument('--data-root', required=True, type=Path)
    ap.add_argument('--label', required=True, choices=['candidate', 'baseline'])
    ap.add_argument('--port', type=int, default=2992)
    ap.add_argument('--dims', type=int, choices=[128, 256], nargs='+')
    ap.add_argument('--skip-lifecycle', action='store_true')
    ap.add_argument('--build-only', action='store_true')
    ap.add_argument('--baseline-ready-s', type=float)
    ap.add_argument('--min-build-speedup', type=float, default=3.0)
    ap.add_argument('--baseline-result', type=Path)
    ap.add_argument('--min-query-speedup', type=float, default=0.90)
    args = ap.parse_args()
    root = args.root.resolve()
    root.mkdir(exist_ok=False, parents=True)
    runtime = root / 'runtime'
    runtime.mkdir()
    report = {'label': args.label, 'official_score': False,
              'data': 'independent_normal_unit_f32', 'nq': 4096,
              'runs': [], 'complete': False}
    reference = json.loads(args.baseline_result.read_text()) if args.baseline_result else None
    process = None
    connection = None
    samples = []
    stop_monitor = threading.Event()

    def monitor():
        paths = [Path('/sys/class/drm') / device.name / 'device/mem_info_vram_used'
                 for device in Path('/dev/dri').glob('card[0-9]*')
                 if device.name[4:].isdigit()]
        while not stop_monitor.wait(0.05):
            try:
                samples.append(sum(int(p.read_text()) for p in paths))
            except OSError:
                pass

    monitor_thread = threading.Thread(target=monitor, daemon=True)

    def save():
        (root / 'result.json').write_text(json.dumps(report, indent=2) + '\n')

    def execute(sql, params=None):
        with connection.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def stop():
        nonlocal connection, process
        if connection is not None:
            connection.close()
            connection = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise RuntimeError('Server required forced shutdown')

    def start():
        nonlocal connection, process
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1', args.port)) == 0:
                raise RuntimeError('Audit port is already in use')
        env = os.environ.copy()
        env['LD_LIBRARY_PATH'] = f'{args.bridge_dir.resolve()}:/opt/hipvs/lib:/opt/rocm/lib'
        env['TELEMETRY_ENABLED'] = 'false'
        command = [str(args.binary.resolve()), '--nodaemon', f'--port={args.port}',
                   f'--base-dir={runtime}', '--log-level=INFO']
        for parameter in ('cpu_count=16', 'memory_limit=16G', 'datafile_size=4G',
                          'datafile_maxsize=12G', 'log_disk_size=4G'):
            command += ['--parameter', parameter]
        with (root / 'server.log').open('ab') as out:
            process = subprocess.Popen(command, cwd=runtime, env=env,
                                       stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError('Audit server exited during startup')
            try:
                connection = pymysql.connect(host='127.0.0.1', port=args.port,
                    user='root', autocommit=True, local_infile=True,
                    connect_timeout=2, read_timeout=600, write_timeout=600)
                execute('SET ob_query_timeout=600000000')
                execute('SET ob_trx_timeout=600000000')
                execute('SET ob_hnsw_ef_search=64')
                return
            except pymysql.MySQLError:
                if connection is not None:
                    connection.close()
                    connection = None
                time.sleep(1)
        raise RuntimeError('Audit server startup timeout')

    try:
        start()
        monitor_thread.start()
        report['version'] = execute('SELECT VERSION()')[0][0]
        execute('ALTER SYSTEM SET ob_vector_memory_limit_percentage=50')
        execute('CREATE DATABASE amd_audit')
        execute('USE amd_audit')
        dimensions = args.dims or ((128, 256) if args.label == 'baseline' else (256, 128))
        for dim in dimensions:
            data = args.data_root / f'data-{dim}'
            manifest = json.loads((data / 'manifest.json').read_text())
            report['data'] = manifest['config']['distribution']
            queries = np.load(data / 'queries.npy')
            query_literals = [vector(row) for row in queries]
            truth = np.load(data / 'truth.npy')
            table = f'items_{dim}'
            execute(f'CREATE TABLE {table}(id BIGINT PRIMARY KEY,v VECTOR({dim}))')
            execute(f"LOAD DATA LOCAL INFILE %s INTO TABLE {table} FIELDS TERMINATED BY '\\t' LINES TERMINATED BY '\\n' (id,v)",
                    (str((data / 'base.tsv').resolve()),))
            warnings = execute('SHOW WARNINGS')
            if warnings or execute(f'SELECT COUNT(*) FROM {table}')[0][0] != 250000:
                raise RuntimeError(f'Data import failed: {warnings[:3]}')
            t = time.perf_counter()
            execute(f'CREATE VECTOR INDEX idx_items ON {table}(v) WITH '
                    '(distance=l2,type=hnsw,lib=cuvs,m=16,ef_construction=200,ef_search=64)')
            ddl_s = time.perf_counter() - t
            t = time.perf_counter()
            first = execute(f'SELECT id FROM {table} ORDER BY l2_distance(v,%s) APPROXIMATE LIMIT 10',
                            (query_literals[0],))
            first_s = time.perf_counter() - t
            if len(first) != 10 or len(set(first)) != 10:
                raise RuntimeError('First query returned invalid IDs')
            run = {'dim': dim, 'rows': 250000, 'ddl_s': ddl_s,
                   'first_query_s': first_s, 'ready_s': ddl_s + first_s, 'queries': {}}
            report['runs'].append(run)
            save()
            if args.baseline_ready_s is not None:
                run['build_speedup'] = args.baseline_ready_s / run['ready_s']
                save()
                if run['build_speedup'] < args.min_build_speedup:
                    raise RuntimeError(f"Build speedup {run['build_speedup']:.3f}x is below {args.min_build_speedup}x; stopping this candidate")
            if args.build_only:
                report['complete'] = True
                return
            for k in (10, 100):
                times, recalls = [], []
                statement = f'SELECT id FROM {table} ORDER BY l2_distance(v,%s) APPROXIMATE LIMIT {k}'
                for query, expected in zip(query_literals, truth):
                    t = time.perf_counter()
                    ids = [int(r[0]) for r in execute(statement, (query,))]
                    times.append(time.perf_counter() - t)
                    if len(ids) != k or len(set(ids)) != k or min(ids) < 0 or max(ids) >= 250000:
                        raise RuntimeError(f'Invalid Top-{k} result')
                    recalls.append(len(set(ids).intersection(expected[:k])) / k)
                run['queries'][str(k)] = {'count': len(times), 'qps': len(times) / sum(times),
                    'recall': float(np.mean(recalls)), 'p95_ms': float(np.percentile(times, 95) * 1000),
                    'result_integrity': True}
                print(json.dumps({'label': args.label, 'dim': dim, 'topk': k, **run['queries'][str(k)]}), flush=True)
                save()
                if reference:
                    ref = next(r for r in reference['runs'] if r['dim'] == dim)
                    absolute = 0.95 if dim == 128 else (0.90 if k == 10 else 0.85)
                    lower = max(absolute, ref['queries'][str(k)]['recall'] - 0.005)
                    if run['queries'][str(k)]['recall'] < lower:
                        raise RuntimeError(f'Top-{k} Recall below development quality gate; stopping this candidate')
            if reference:
                ref = next(r for r in reference['runs'] if r['dim'] == dim)
                run['query_speedup'] = float(np.sqrt(np.prod([
                    run['queries'][str(k)]['qps'] / ref['queries'][str(k)]['qps'] for k in (10, 100)])))
                save()
                if run['query_speedup'] < args.min_query_speedup:
                    raise RuntimeError(f"Query speedup {run['query_speedup']:.3f}x is below {args.min_query_speedup}x; stopping this candidate")
            execute(f'DROP TABLE {table}')
        if args.skip_lifecycle:
            report['complete'] = True
            return
        execute('CREATE TABLE cpu_items(id BIGINT PRIMARY KEY,v VECTOR(128))')
        base = np.load(args.data_root / 'data-128/base.npy', mmap_mode='r')
        for i in range(512):
            execute('INSERT INTO cpu_items VALUES(%s,%s)', (i + 1000000, vector(base[i])))
        execute('CREATE VECTOR INDEX cpu_idx ON cpu_items(v) WITH '
                '(distance=l2,type=hnsw,lib=vsag,m=16,ef_construction=200,ef_search=64)')
        cpu = execute('SELECT id FROM cpu_items ORDER BY l2_distance(v,%s) APPROXIMATE LIMIT 10', (vector(base[0]),))
        assert len(cpu) == 10 and int(cpu[0][0]) == 1000000
        report['cpu_sql_path'] = 'PASS'
        subset = root / 'lifecycle.tsv'
        with (args.data_root / 'data-128/base.tsv').open() as src, subset.open('w') as dst:
            for _ in range(4096):
                dst.write(next(src))
        execute('CREATE TABLE lifecycle(id BIGINT PRIMARY KEY,v VECTOR(128))')
        execute("LOAD DATA LOCAL INFILE %s INTO TABLE lifecycle FIELDS TERMINATED BY '\\t' LINES TERMINATED BY '\\n' (id,v)", (str(subset),))
        execute('CREATE VECTOR INDEX lifecycle_idx ON lifecycle(v) WITH '
                '(distance=l2,type=hnsw,lib=cuvs,m=16,ef_construction=200,ef_search=64)')
        statement = 'SELECT id FROM lifecycle ORDER BY l2_distance(v,%s) APPROXIMATE LIMIT 10'
        before = execute(statement, (vector(base[0]),))
        assert len(before) == 10 and int(before[0][0]) == 0
        stop()
        start()
        execute('USE amd_audit')
        after = execute(statement, (vector(base[0]),))
        assert after == before, 'Snapshot query changed after restart'
        report['restart_snapshot_query'] = 'PASS'
        filtered = execute('SELECT id FROM lifecycle WHERE id>=4000 ORDER BY l2_distance(v,%s) APPROXIMATE LIMIT 10', (vector(base[0]),))
        assert len(filtered) == 10 and all(int(row[0]) >= 4000 for row in filtered)
        report['lazy_host_filter_fallback'] = 'PASS'
        execute('DELETE FROM lifecycle WHERE id=0')
        execute('INSERT INTO lifecycle VALUES(9000000000,%s)', (vector(base[0]),))
        updated = execute(statement, (vector(base[0]),))
        assert len(updated) == 10 and int(updated[0][0]) == 9000000000
        assert all(int(row[0]) != 0 for row in updated)
        report['lazy_host_delete_insert'] = 'PASS'
        report['complete'] = True
    except Exception as exc:
        report['error'] = repr(exc)
        raise
    finally:
        stop_monitor.set()
        if monitor_thread.is_alive():
            monitor_thread.join(timeout=2)
        report['sampled_visible_gpu_vram_peak_bytes'] = max(samples) if samples else None
        if process is not None and Path(f'/proc/{process.pid}/status').exists():
            status = Path(f'/proc/{process.pid}/status').read_text()
            report['server_memory_status'] = [line for line in status.splitlines()
                if line.startswith(('VmHWM:', 'VmRSS:'))]
        try:
            stop()
        finally:
            save()
            print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
