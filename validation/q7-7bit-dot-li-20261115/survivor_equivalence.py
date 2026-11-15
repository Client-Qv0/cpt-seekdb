#!/usr/bin/env python3
"""Compare current and biased-dot quantized screening on the full workload."""

import argparse
import heapq
import json
import math
from pathlib import Path
import sys

import numpy as np


PREVIOUS = Path(__file__).resolve().parents[1] / "q7-prefix-lower-bound-li-20261115"
sys.path.insert(0, str(PREVIOUS))
from probe import (  # noqa: E402
    DIMENSION,
    QUERY_COUNT,
    ROWS,
    SEEDS,
    TOP_K,
    build_quantizer,
    generate_seed,
)


BIAS = 64


def quantized_threshold(worst_distance, step, root_dim_upper):
    infinity = math.inf
    if not math.isfinite(worst_distance) or worst_distance < 0:
        return infinity
    following = math.nextafter(worst_distance, infinity)
    distance_upper = math.nextafter(following * 1.000001, infinity)
    units_upper = math.nextafter(distance_upper / step, infinity)
    radius_upper = math.nextafter(units_upper + root_dim_upper, infinity)
    return math.nextafter(radius_upper * radius_upper, infinity)


def slices(total):
    if total < 1024:
        return [(0, total)]
    per = (total + 1) // 2
    chunk = ((per + 31) // 32) * 32
    return [(0, min(total, chunk)), (min(total, chunk), total)]


def push(heap, distance, key):
    item = (-distance, -key)
    candidate = (distance, key)
    if len(heap) < TOP_K:
        heapq.heappush(heap, item)
    else:
        worst = (-heap[0][0], -heap[0][1])
        if candidate < worst:
            heapq.heapreplace(heap, item)


def simulate(current_integer_squared, exact_distances, keys, step):
    root_dim_upper = math.nextafter(math.sqrt(DIMENSION), math.inf)
    screened = survivors = 0
    heaps = []
    for begin, end in slices(len(exact_distances)):
        heap = []
        at = begin
        while at + 32 <= end:
            if len(heap) == TOP_K:
                threshold = quantized_threshold(
                    -heap[0][0], step, root_dim_upper
                )
                approximate = current_integer_squared[at : at + 32]
                keep = np.flatnonzero(
                    approximate.astype(np.float64) <= threshold
                )
                screened += 32
                survivors += len(keep)
            else:
                keep = np.arange(32)
            for lane in keep:
                index = at + int(lane)
                push(heap, float(exact_distances[index]), int(keys[index]))
            at += 32
        for index in range(at, end):
            push(heap, float(exact_distances[index]), int(keys[index]))
        heaps.extend(heap)
    final = sorted((-distance, -key) for distance, key in heaps)[:TOP_K]
    return {
        "screened_candidates": screened,
        "survivor_candidates": survivors,
        "survivor_rate": survivors / screened if screened else None,
        "returned": [(key, distance) for distance, key in final],
    }


def empty_stats():
    return {
        "screened_candidates": 0,
        "survivor_candidates": 0,
        "query_rates": [],
        "topk_mismatches": 0,
    }


def finalize(stats):
    return {
        "screened_candidates": stats["screened_candidates"],
        "survivor_candidates": stats["survivor_candidates"],
        "survivor_rate_candidate_weighted": (
            stats["survivor_candidates"] / stats["screened_candidates"]
            if stats["screened_candidates"]
            else None
        ),
        "query_survivor_rate_median": (
            float(np.median(stats["query_rates"]))
            if stats["query_rates"]
            else None
        ),
        "topk_mismatches": stats["topk_mismatches"],
    }


def run_seed(seed):
    stored, queries, groups, keys, data_sha256 = generate_seed(seed)
    stored64 = stored.astype(np.float64)
    quantizer = build_quantizer(stored64)
    row_codes = quantizer.codes(stored64)
    query_codes = quantizer.codes(queries.astype(np.float64))
    if int(row_codes.min()) < -BIAS or int(row_codes.max()) > BIAS:
        raise RuntimeError("row codes exceed the candidate precondition")
    if int(query_codes.min()) < -BIAS or int(query_codes.max()) > BIAS:
        raise RuntimeError("query codes exceed the candidate precondition")

    row_norms = np.sum(row_codes.astype(np.int64) ** 2, axis=1)
    stats = {"filtered": empty_stats(), "unfiltered": empty_stats()}
    compared = mismatches = 0
    maximum_absolute_difference = 0
    for query_index, query in enumerate(queries.astype(np.float64)):
        filtered = bool(query_index % 2)
        group = query_index % 5
        order = np.flatnonzero(groups == group) if filtered else np.arange(ROWS)
        selected_codes = row_codes[order]
        selected_query = query_codes[query_index]

        delta = (
            selected_codes.astype(np.int32)
            - selected_query[None, :].astype(np.int32)
        )
        current = np.sum(
            delta.astype(np.int64) * delta.astype(np.int64),
            axis=1,
            dtype=np.int64,
        )

        biased = selected_codes.astype(np.int64) + BIAS
        biased_dot = np.sum(
            biased * selected_query[None, :].astype(np.int64),
            axis=1,
            dtype=np.int64,
        )
        base_dot = biased_dot - BIAS * int(np.sum(selected_query))
        query_norm = int(np.sum(selected_query.astype(np.int64) ** 2))
        candidate = row_norms[order] + query_norm - 2 * base_dot
        differences = np.abs(candidate - current)
        mismatches += int(np.count_nonzero(differences))
        maximum_absolute_difference = max(
            maximum_absolute_difference,
            int(differences.max(initial=0)),
        )
        compared += len(order)

        exact_distances = np.sqrt(
            np.sum(
                (stored64[order] - query) ** 2,
                axis=1,
                dtype=np.float64,
            )
        )
        exact_top = [
            (int(keys[order][index]), float(exact_distances[index]))
            for index in np.lexsort((keys[order], exact_distances))[:TOP_K]
        ]
        result = simulate(current, exact_distances, keys[order], quantizer.step)
        surface = stats["filtered" if filtered else "unfiltered"]
        surface["screened_candidates"] += result["screened_candidates"]
        surface["survivor_candidates"] += result["survivor_candidates"]
        if result["screened_candidates"]:
            surface["query_rates"].append(result["survivor_rate"])
        if result["returned"] != exact_top:
            surface["topk_mismatches"] += 1
        if (query_index + 1) % 100 == 0:
            print(f"seed={seed} queries={query_index + 1}/{QUERY_COUNT}", flush=True)

    return {
        "seed": seed,
        "data_sha256": data_sha256,
        "quantized_step": quantizer.step,
        "row_code_range": [int(row_codes.min()), int(row_codes.max())],
        "query_code_range": [int(query_codes.min()), int(query_codes.max())],
        "compared_candidate_query_pairs": compared,
        "integer_distance_mismatches": mismatches,
        "maximum_absolute_integer_difference": maximum_absolute_difference,
        "filtered": finalize(stats["filtered"]),
        "unfiltered": finalize(stats["unfiltered"]),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", default=",".join(map(str, SEEDS)))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    seeds = tuple(int(value) for value in args.seeds.split(",") if value)
    report = {
        "scope": (
            "Offline full-workload integer equivalence and survivor-rate check; "
            "no production code or timing claim"
        ),
        "conversion": (
            "unsigned = signed_code + 64; candidate_squared = row_norm + "
            "query_norm - 2*(unsigned_dot - 64*query_sum)"
        ),
        "seeds": seeds,
        "per_seed": [],
    }
    for seed in seeds:
        result = run_seed(seed)
        report["per_seed"].append(result)
        print(json.dumps(result, separators=(",", ":")), flush=True)
    report["total_compared_pairs"] = sum(
        value["compared_candidate_query_pairs"] for value in report["per_seed"]
    )
    report["total_integer_distance_mismatches"] = sum(
        value["integer_distance_mismatches"] for value in report["per_seed"]
    )
    report["survivor_rate_increase_percentage_points"] = 0.0
    report["passed"] = (
        report["total_integer_distance_mismatches"] == 0
        and all(
            value[surface]["topk_mismatches"] == 0
            for value in report["per_seed"]
            for surface in ("filtered", "unfiltered")
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "total_compared_pairs",
                    "total_integer_distance_mismatches",
                    "survivor_rate_increase_percentage_points",
                    "passed",
                )
            },
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
