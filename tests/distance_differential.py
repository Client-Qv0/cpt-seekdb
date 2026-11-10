#!/usr/bin/env python3
"""Compare exact L2 SQL responses with a baseline and FP32 reference model."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import struct
import tempfile

import acceptance as core


def f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


def literal(values):
    return "[" + ",".join(map(str, values)) + "]"


def distance(a, b):
    total = 0.0
    for x, y in zip(a, b):
        d = float(x) - float(y)
        total += d * d
    return math.sqrt(total)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("refusing to overwrite output")
    for binary in (args.baseline, args.candidate):
        if not binary.is_file():
            parser.error(f"binary missing: {binary}")
    inputs = hashlib.sha256()
    responses = hashlib.sha256()
    count = 0
    with tempfile.TemporaryDirectory(prefix="mvdb-distance-diff-") as temp:
        core.BINARY = args.baseline.resolve()
        baseline = core.Database(Path(temp) / "baseline")
        core.BINARY = args.candidate.resolve()
        candidate = core.Database(Path(temp) / "candidate")

        def run(sql):
            nonlocal count
            inputs.update((sql + "\n").encode())
            a, b = baseline.ok(sql), candidate.ok(sql)
            if a != b:
                raise AssertionError(f"baseline/candidate response mismatch: {sql[:200]}\n{a}\n{b}")
            responses.update((json.dumps(a, sort_keys=True, allow_nan=False) + "\n").encode())
            count += 1
            return a["rows"]

        try:
            for seed in (3179, 9143, 27183):
                for dim in (1, 2, 3, 4, 5, 31, 32, 33, 127, 128, 129):
                    rng = random.Random(seed * 1000 + dim)
                    table = f"v_{seed}_{dim}"
                    run(f"CREATE TABLE {table} (id BIGINT PRIMARY KEY, grp BIGINT, v VECTOR({dim}));")
                    vectors = {}
                    for key in range(32):
                        if key < 3:
                            v = [1.0] + ([1e-8] if dim > 1 and key else [0.0] * (dim > 1)) + [0.0] * max(0, dim - 2)
                        else:
                            scale = (1e-19, 1.0, 1e19)[key % 3]
                            v = [round(rng.uniform(-1, 1), 6) * scale for _ in range(dim)]
                        vectors[key] = [f32(x) for x in v]
                    rows = [f"({key},{key % 3},'{literal(vectors[key])}')" for key in reversed(range(32))]
                    run(f"INSERT INTO {table} VALUES " + ",".join(rows) + ";")
                    queries = [[0.0] * dim, [f32(rng.uniform(-1, 1)) for _ in range(dim)]]
                    for query in queries:
                        for clause, include in (("", lambda key: True), (" WHERE grp=1", lambda key: key % 3 == 1)):
                            truth = sorted((distance(v, query), key) for key, v in vectors.items() if include(key))
                            for k in (1, 7, 32):
                                sql = f"SELECT id,L2_DISTANCE(v,'{literal(query)}') AS d FROM {table}{clause} ORDER BY d LIMIT {k};"
                                for _ in range(2):
                                    actual = run(sql)
                                    if [r[0] for r in actual] != [key for _, key in truth[:k]]:
                                        raise AssertionError(f"reference IDs/order differ: {sql[:200]}")
                                    for row, (want, _) in zip(actual, truth[:k]):
                                        if not math.isclose(row[1], want, rel_tol=1e-12, abs_tol=1e-300):
                                            raise AssertionError(f"reference distance differs: {row[1]} vs {want}")
        finally:
            baseline.close()
            candidate.close()
    result = {
        "scope": "native development-protocol differential and independent FP32 reference; not official scoring",
        "baseline_sha256": hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
        "candidate_sha256": hashlib.sha256(args.candidate.read_bytes()).hexdigest(),
        "seeds": [3179, 9143, 27183],
        "dimensions": [1, 2, 3, 4, 5, 31, 32, 33, 127, 128, 129],
        "statement_count": count,
        "sql_sha256": inputs.hexdigest(),
        "baseline_response_sha256": responses.hexdigest(),
        "exact_response_equality": True,
        "reference_filter_ids_order_and_distance_pass": True,
    }
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
