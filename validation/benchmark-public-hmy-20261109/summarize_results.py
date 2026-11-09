"""Build a compact summary from recorded run files, preserving raw counters."""
import json
from pathlib import Path
import statistics

root = Path('validation/benchmark-public-hmy-20261109')
runs = []
for folder, count in [('seed-3179', 3), ('seed-9143', 1), ('seed-27183', 1), ('seed-2468-audit', 1)]:
    for index in range(1, count + 1):
        run = json.loads((root / folder / f'round-{index}/run-with-readback.json').read_text())
        snapshots = {entry['label']: entry['snapshot'] for entry in run['snapshots']}
        runs.append({'folder': folder, 'round': index, 'passed': run['overall_passed'],
                     'write_seconds': run['timings']['write_batches_seconds'],
                     'warm_query_seconds': run['timings']['warm_queries_seconds'],
                     'first_query_seconds': run['timings']['process_first_query_seconds'],
                     'after_write_memory_peak_bytes': int(snapshots['after_write']['memory.peak']),
                     'after_queries_memory_peak_bytes': int(snapshots['after_warm_queries']['memory.peak']),
                     'first_io_stat': snapshots['container_started']['io.stat'],
                     'after_write_io_stat': snapshots['after_write']['io.stat'],
                     'after_queries_io_stat': snapshots['after_warm_queries']['io.stat'],
                     'filtered_recall': run['correctness']['warm_query_recall']['filtered']['mean_recall_at_10'],
                     'unfiltered_recall': run['correctness']['warm_query_recall']['unfiltered']['mean_recall_at_10'],
                     'verified_rows': run['full_readback']['checked_rows']})
primary = [r for r in runs if r['folder'] == 'seed-3179']
result = {'scope': 'local only; initial I/O sample is after launch; shared device and no final syncfs',
          'primary_write_seconds_median': statistics.median(r['write_seconds'] for r in primary),
          'primary_warm_query_seconds_median': statistics.median(r['warm_query_seconds'] for r in primary),
          'primary_after_write_memory_peak_bytes_median': statistics.median(r['after_write_memory_peak_bytes'] for r in primary),
          'primary_after_queries_memory_peak_bytes_median': statistics.median(r['after_queries_memory_peak_bytes'] for r in primary),
          'runs': runs, 'all_passed': len(runs) == 6 and all(r['passed'] for r in runs)}
(root / 'metrics.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
print(json.dumps(result, indent=2, allow_nan=False))
