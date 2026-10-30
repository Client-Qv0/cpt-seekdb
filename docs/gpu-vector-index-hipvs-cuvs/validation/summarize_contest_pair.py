"""Apply the published weights to actual local SQL measurements.

The second development dataset is explicitly not the organizer's Hidden250K.
This script reports local thresholds; it does not issue an official score.
"""
import argparse
import json
import math
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--sift-baseline', type=Path, required=True)
parser.add_argument('--sift-candidate', type=Path, required=True)
parser.add_argument('--other-baseline', type=Path, required=True)
parser.add_argument('--other-candidate', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
datasets = []
for dim, weight, base_path, candidate_path in (
    (128, 0.4, args.sift_baseline, args.sift_candidate),
    (256, 0.6, args.other_baseline, args.other_candidate),
):
    baseline = json.loads(base_path.read_text())
    candidate = json.loads(candidate_path.read_text())
    if not baseline['complete'] or not candidate['complete']:
        raise ValueError('Only completed runs may enter the final summary')
    b = next(run for run in baseline['runs'] if run['dim'] == dim)
    c = next(run for run in candidate['runs'] if run['dim'] == dim)
    if b['rows'] != 250000 or c['rows'] != 250000 or baseline['data'] != candidate['data']:
        raise ValueError('Mismatched input datasets')
    checks = {}
    for k in (10, 100):
        base_query = b['queries'][str(k)]
        query = c['queries'][str(k)]
        absolute = 0.95 if dim == 128 else (0.90 if k == 10 else 0.85)
        checks[f'recall_at_{k}'] = query['recall'] >= max(absolute, base_query['recall'] - 0.005)
        checks[f'complete_ids_at_{k}'] = query['result_integrity'] and query['count'] == 4096
    query_speedup = math.sqrt(math.prod(c['queries'][str(k)]['qps'] / b['queries'][str(k)]['qps']
                                      for k in (10, 100)))
    checks['query_no_regression'] = query_speedup >= 0.90
    vram_ratio = (candidate['sampled_visible_gpu_vram_peak_bytes'] /
                  baseline['sampled_visible_gpu_vram_peak_bytes'])
    checks['sampled_relative_vram'] = vram_ratio <= 1.25
    checks['sampled_physical_vram'] = candidate['sampled_visible_gpu_vram_peak_bytes'] <= 45 * 1024**3
    datasets.append({'data': candidate['data'], 'dimension': dim, 'weight': weight,
        'build_speedup': b['ready_s'] / c['ready_s'], 'query_speedup': query_speedup,
        'baseline_ready_s': b['ready_s'], 'candidate_ready_s': c['ready_s'],
        'candidate_recall_10': c['queries']['10']['recall'],
        'candidate_recall_100': c['queries']['100']['recall'],
        'sampled_vram_ratio': vram_ratio, 'observed_checks': checks})
build = math.prod(d['build_speedup'] ** d['weight'] for d in datasets)
query = math.prod(d['query_speedup'] ** d['weight'] for d in datasets)
passed = build >= 3 and query >= 1.5 and all(all(d['observed_checks'].values()) for d in datasets)
report = {'official_score': None, 'hidden_dataset_tested': False,
    'baseline_commit': '634888d9b037153fa143d2c913ba4b25503e1d62',
    'source_parent_commit': 'f4d10eee8817fbe60c693c0f75005f330e65875a',
    'nn_descent_iterations': 12, 'datasets': datasets,
    'weighted_build_speedup': build, 'weighted_query_speedup': query,
    'development_thresholds_met': passed,
    'limits': 'Independent development data and sampled VRAM; official hidden data, profiler and final score remain organizer-validated.'}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
raise SystemExit(0 if passed else 1)
