#!/usr/bin/env python3
"""Verify the Agent Prompt material repair and its published evidence."""
from hashlib import sha256
from pathlib import Path
import json
import math
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(__file__).resolve().parent
MATERIAL = ROOT / 'agent' / 'conversation.json'
BASE = 'c6617860ef56f8672f881ae1e1c40d8a05433638'
EXPECTED_MATERIAL_SHA = '1a40923e38105638c7c9b045f2c9f07cfa5e1e8d2337f791c4f12ebf619ae6fc'
EXPECTED_BINARY_SHA = '0fc4d430b70a32367b42d2a68eae54c0f0e4416bc6585aa77914444fe44a8e6b'


def check(ok, message):
    if not ok:
        raise AssertionError(message)


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            check(key not in value, f'duplicate JSON key: {key}')
            value[key] = item
        return value

    def constant(value):
        raise ValueError(f'non-finite constant: {value}')

    doc = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                     parse_constant=constant)

    def finite(value):
        check(not isinstance(value, float) or math.isfinite(value),
              'non-finite number')
        if isinstance(value, dict):
            for item in value.values():
                finite(item)
        elif isinstance(value, list):
            for item in value:
                finite(item)
    finite(doc)
    return doc


def main():
    raw = MATERIAL.read_bytes()
    check(len(raw) <= 128 * 1024, 'material exceeds 128 KiB')
    check(sha256(raw).hexdigest() == EXPECTED_MATERIAL_SHA,
          'material hash differs from published evidence')
    doc = strict_json(raw)
    check(doc.get('rule_version') == 'agent-learning-evidence-v3-unbounded',
          'wrong rule version')
    check(doc.get('synthetic') is False, 'material must not be synthetic')
    dims = doc.get('dimensions', [])
    check(len(dims) == 5, 'expected five dimensions')
    for dimension in dims:
        check(dimension.get('unit_ids'), f"missing units: {dimension.get('id')}")
        check(dimension.get('evidence_status') !=
              'insufficient_student_evidence_in_selected_material',
              f"insufficient marker remains: {dimension.get('id')}")
    units = doc.get('units', [])
    check(len(units) == 5, 'expected five candidate units')
    check(abs(sum(unit['score'] for unit in units) - 4.0) < 1e-9,
          'candidate score changed unexpectedly')
    check('3413.755039' in raw.decode('utf-8'),
          'c661 performance feedback missing')
    check('agents prompt 依旧还拿不到分数' in raw.decode('utf-8'),
          'c661 failure feedback missing')

    test = subprocess.run(
        [sys.executable, str(ROOT / 'tests' / 'test_agent_material.py'), '-v'],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    check(test.returncode == 0, 'material tests failed:\n' + test.stdout)
    check('Ran 7 tests' in test.stdout and 'OK' in test.stdout,
          'unexpected material test summary')

    result = json.loads((EVIDENCE / 'RESULTS.json').read_text(encoding='utf-8'))
    check(result['candidate_base_commit'] == BASE, 'wrong base commit')
    check(result['material']['sha256'] == EXPECTED_MATERIAL_SHA,
          'RESULTS material hash mismatch')
    check(result['material']['bytes'] == len(raw), 'RESULTS size mismatch')
    check(result['material']['dimensions_with_units'] == 5,
          'RESULTS dimension count mismatch')

    public = json.loads((EVIDENCE / 'official-public' / 'result.json')
                        .read_text(encoding='utf-8'))
    check(public.get('passed') is True, 'official public check failed')
    statuses = public.get('cases', [])
    check(len(statuses) == 20, 'expected 20 official public cases')
    check(all(case.get('status') == 'PASS' for case in statuses),
          'official public case not PASS')

    binary = (EVIDENCE / 'binary-sha256.txt').read_text(encoding='ascii')
    check(binary.count(EXPECTED_BINARY_SHA) == 2,
          'native/image binary hashes do not both match')

    diff = subprocess.run(
        ['git', '-c', f'safe.directory={ROOT}', '-C', str(ROOT),
         'diff', '--name-only', BASE, '--', 'src', 'CMakeLists.txt', 'Dockerfile'],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    check(diff.returncode == 0, 'git diff failed:\n' + diff.stdout)
    check(not diff.stdout.strip(), 'production inputs differ from c661')

    patterns = [
        r'-----BEGIN [A-Z ]*PRIVATE KEY-----',
        r'github_pat_[A-Za-z0-9_]{20,}',
        r'gh[pousr]_[A-Za-z0-9]{20,}',
        r'sk-(?:proj-)?[A-Za-z0-9_-]{20,}',
        r'AKIA[0-9A-Z]{16}',
    ]
    for pattern in patterns:
        check(not re.search(pattern, raw.decode('utf-8')),
              f'possible secret format: {pattern}')

    print('PASS: five dimensions covered; material 7/7; no production diff')
    print(f'material bytes={len(raw)} sha256={EXPECTED_MATERIAL_SHA}')
    print(f'binary sha256={EXPECTED_BINARY_SHA}; official public=20/20')


if __name__ == '__main__':
    main()
