#!/usr/bin/env python3
"""Offline safe-rejection probe for quantized vector prefixes.

This file does not alter or import production C++ code. It reproduces the
benchmark data distribution, the current global int8 quantization, a
conservative per-dimension lower bound, and the current two-slice TopK scan
shape. Distances and rejection counters are produced only for experiment
selection; they are not an implementation or official score.
"""

import argparse
from dataclasses import dataclass
import hashlib
import heapq
import json
import math
from pathlib import Path
import random
import statistics
import time

import numpy as np


ROWS = 10000
DIMENSION = 128
QUERY_COUNT = 1000
BATCH_SIZE = 100
TOP_K = 10
PARALLEL_MIN_ROWS = 1024
PREFIXES = (16, 32, 64, 96)
SEEDS = (3179, 3181, 3187)
METHODS = ("coarse", "tight")


@dataclass(frozen=True)
class Quantizer:
    step: float
    inverse: float

    def codes(self, values):
        values = np.asarray(values, dtype=np.float64)
        rounded = np.rint(values * self.inverse)
        if (
            not np.all(np.isfinite(rounded))
            or np.any(rounded < -127)
            or np.any(rounded > 127)
        ):
            raise ValueError("value does not fit the production int8 code range")
        return rounded.astype(np.int16)


def build_quantizer(values):
    values = np.asarray(values, dtype=np.float64)
    if not values.size or not np.all(np.isfinite(values)):
        raise ValueError("quantizer needs finite, nonempty values")
    maximum = float(np.max(np.abs(values)))
    step = 1.0
    inverse = 1.0
    if maximum > 0:
        _, exponent = math.frexp(maximum)
        exponent -= 7
        step = math.ldexp(1.0, exponent)
        if maximum > 127 * step:
            exponent += 1
            step *= 2
        inverse = math.ldexp(1.0, -exponent)
    return Quantizer(step, inverse)


def _conservative_scale(values):
    # Prefix sums contain at most 96 nonnegative terms. Two orders of magnitude
    # more than the worst binary64 accumulation error keeps the comparison
    # strictly on the low side of the mathematical bound.
    return np.maximum(values * (1.0 - 1e-12), 0.0)


def prefix_squared_lower_bound(
    row_codes, query_codes, query_values, step, prefix, method
):
    row_codes = np.asarray(row_codes, dtype=np.int16)
    query_codes = np.asarray(query_codes, dtype=np.int16)
    query_values = np.asarray(query_values, dtype=np.float64)
    if row_codes.shape[1] != query_codes.shape[1]:
        raise ValueError("row/query code dimensions differ")
    if query_codes.shape != query_values.shape:
        raise ValueError("query code/value shapes differ")
    if not 0 <= prefix <= row_codes.shape[1]:
        raise ValueError("prefix outside vector dimension")
    if prefix == 0:
        return np.zeros((row_codes.shape[0], query_codes.shape[0]), dtype=np.float64)
    if method not in METHODS:
        raise ValueError(f"unknown lower-bound method: {method}")

    query_count, rows = query_codes.shape[0], row_codes.shape[0]
    result = np.empty((rows, query_count), dtype=np.float64)
    block_rows = max(1, 2_000_000 // max(1, query_count * prefix))
    query_error = query_values[:, :prefix] - step * query_codes[:, :prefix].astype(
        np.float64
    )
    for begin in range(0, rows, block_rows):
        end = min(rows, begin + block_rows)
        delta = (
            row_codes[begin:end, None, :prefix]
            - query_codes[None, :, :prefix]
        ).astype(np.int16)
        if method == "coarse":
            magnitude = np.maximum(np.abs(delta.astype(np.int32)) - 1, 0)
            summed = np.sum(
                magnitude.astype(np.float64) ** 2,
                axis=2,
                dtype=np.float64,
            )
            result[begin:end] = _conservative_scale(summed * step * step)
        else:
            real_delta = step * delta.astype(np.float64) + query_error[None, :, :]
            magnitude = np.maximum(np.abs(real_delta) - step * 0.5, 0.0)
            result[begin:end] = _conservative_scale(
                np.sum(magnitude * magnitude, axis=2, dtype=np.float64)
            )
    return result


def prefix_bounds_for_query(
    row_codes, query_codes, query_values, step, prefixes=PREFIXES
):
    row_codes = np.asarray(row_codes, dtype=np.int16)
    query_codes = np.asarray(query_codes, dtype=np.int16)
    query_values = np.asarray(query_values, dtype=np.float64)
    maximum = max(prefixes)
    delta = row_codes[:, :maximum].astype(np.int32) - query_codes[:maximum]

    coarse_terms = np.maximum(np.abs(delta) - 1, 0).astype(np.float64) ** 2
    coarse_sum = np.cumsum(coarse_terms, axis=1, dtype=np.float64) * step * step

    query_error = query_values[:maximum] - step * query_codes[:maximum].astype(
        np.float64
    )
    real_delta = step * delta.astype(np.float64) + query_error[None, :]
    magnitude = np.maximum(np.abs(real_delta) - step * 0.5, 0.0)
    tight_sum = np.cumsum(magnitude * magnitude, axis=1, dtype=np.float64)

    return {
        method: {
            prefix: _conservative_scale(summed[:, prefix - 1].copy())
            for prefix in prefixes
        }
        for method, summed in (("coarse", coarse_sum), ("tight", tight_sum))
    }


def safe_above(lower_distance, worst_distance):
    if not math.isfinite(lower_distance) or lower_distance <= 0:
        return False
    # Callers round sqrt downward first. Requiring a value above nextup(worst)
    # leaves the final production sqrt tie resolved in the candidate's favor.
    return lower_distance > math.nextafter(worst_distance, math.inf)


def safe_rejection_mask(lower_squared, worst_distance):
    roots = np.sqrt(np.maximum(lower_squared, 0.0))
    roots = np.nextafter(roots, -np.inf)
    return roots > math.nextafter(worst_distance, math.inf)


def _push(heap, distance, key):
    item = (-distance, -key)
    candidate = (distance, key)
    if len(heap) < TOP_K:
        heapq.heappush(heap, item)
    else:
        worst = (-heap[0][0], -heap[0][1])
        if candidate < worst:
            heapq.heapreplace(heap, item)


def _slices(total):
    width = 2 if total >= PARALLEL_MIN_ROWS else 1
    if width == 1:
        return [(0, total)]
    per = (total + 1) // 2
    chunk = ((per + 31) // 32) * 32
    return [
        (0, min(total, chunk)),
        (min(total, chunk), total),
    ]


def simulate_prefixes(exact_distances, keys, lower_by_method_prefix):
    output = {}
    for method in METHODS:
        for prefix, lowered in lower_by_method_prefix[method].items():
            heaps = []
            screened = 0
            rejected = 0
            for begin, end in _slices(len(exact_distances)):
                heap = []
                at = begin
                while at + 32 <= end:
                    if len(heap) == TOP_K:
                        threshold = -heap[0][0]
                        lower = lowered[at : at + 32]
                        mask = safe_rejection_mask(lower, threshold)
                        screened += 32
                        rejected += int(np.count_nonzero(mask))
                        survivors = np.flatnonzero(~mask)
                    else:
                        survivors = np.arange(32)
                    for lane in survivors:
                        index = at + int(lane)
                        _push(
                            heap,
                            float(exact_distances[index]),
                            int(keys[index]),
                        )
                    at += 32
                for index in range(at, end):
                    _push(
                        heap,
                        float(exact_distances[index]),
                        int(keys[index]),
                    )
                heaps.extend((-distance, -key) for distance, key in heap)
            final = sorted(heaps)[:TOP_K]
            output[(method, prefix)] = {
                "screened_candidates": screened,
                "rejected_candidates": rejected,
                "rejection_rate": rejected / screened if screened else None,
                "returned": [(key, distance) for distance, key in final],
            }
    return output


def generate_seed(seed):
    rng = random.Random(seed)
    stored = np.empty((ROWS, DIMENSION), dtype=np.float32)
    queries = np.empty((QUERY_COUNT, DIMENSION), dtype=np.float32)
    groups = np.arange(ROWS, dtype=np.int64) % 5
    keys = np.arange(ROWS, dtype=np.int64)
    for row in range(ROWS):
        stored[row] = np.asarray(
            [round(rng.uniform(-1, 1), 6) for _ in range(DIMENSION)],
            dtype=np.float32,
        )
    for query in range(QUERY_COUNT):
        queries[query] = np.asarray(
            [round(rng.uniform(-1, 1), 6) for _ in range(DIMENSION)],
            dtype=np.float32,
        )
    digest = hashlib.sha256()
    digest.update(stored.astype("<f4").tobytes())
    digest.update(queries.astype("<f4").tobytes())
    digest.update(groups.astype("<i8").tobytes())
    return stored, queries, groups, keys, digest.hexdigest()


def empty_accumulator():
    return {
        method: {
            prefix: {
                "screened_candidates": 0,
                "rejected_candidates": 0,
                "per_query_ratios": [],
                "topk_mismatches": 0,
            }
            for prefix in PREFIXES
        }
        for method in METHODS
    }


def finalize_accumulator(accumulator):
    result = {}
    for method in METHODS:
        result[method] = {}
        for prefix in PREFIXES:
            item = accumulator[method][prefix]
            ratios = item["per_query_ratios"]
            screened = item["screened_candidates"]
            rejected = item["rejected_candidates"]
            result[method][prefix] = {
                "screened_candidates": screened,
                "rejected_candidates": rejected,
                "rejection_rate_candidate_weighted": (
                    rejected / screened if screened else None
                ),
                "queries_with_screened_batches": len(ratios),
                "query_rejection_rate_median": (
                    statistics.median(ratios) if ratios else None
                ),
                "query_rejection_rate_minimum": min(ratios) if ratios else None,
                "query_rejection_rate_maximum": max(ratios) if ratios else None,
                "topk_mismatches": item["topk_mismatches"],
            }
    return result


def run_seed(seed):
    start = time.perf_counter()
    stored, queries, groups, keys, data_sha256 = generate_seed(seed)
    stored64 = stored.astype(np.float64)
    quantizer = build_quantizer(stored64)
    row_codes = quantizer.codes(stored64)
    query_codes = quantizer.codes(queries.astype(np.float64))
    accumulators = {"filtered": empty_accumulator(), "unfiltered": empty_accumulator()}
    sign_counts = {"positive": 0, "negative": 0}

    for query_index, query in enumerate(queries.astype(np.float64)):
        filtered = bool(query_index % 2)
        group = query_index % 5
        order = np.flatnonzero(groups == group) if filtered else np.arange(ROWS)
        distances = np.sqrt(
            np.sum(
                (stored64[order] - query) ** 2,
                axis=1,
                dtype=np.float64,
            )
        )
        exact_order = np.lexsort((keys[order], distances))[:TOP_K]
        exact_top = [
            (int(keys[order][index]), float(distances[index]))
            for index in exact_order
        ]
        lowered = prefix_bounds_for_query(
            row_codes[order],
            query_codes[query_index],
            query,
            quantizer.step,
        )
        simulated = simulate_prefixes(distances, keys[order], lowered)
        surface = accumulators["filtered" if filtered else "unfiltered"]
        sign_counts["negative" if float(np.mean(query)) < 0 else "positive"] += 1
        for method in METHODS:
            for prefix in PREFIXES:
                item = simulated[(method, prefix)]
                aggregate = surface[method][prefix]
                aggregate["screened_candidates"] += item["screened_candidates"]
                aggregate["rejected_candidates"] += item["rejected_candidates"]
                if item["screened_candidates"]:
                    aggregate["per_query_ratios"].append(item["rejection_rate"])
                if item["returned"] != exact_top:
                    aggregate["topk_mismatches"] += 1
        if (query_index + 1) % 100 == 0:
            print(f"seed={seed} queries={query_index + 1}/{QUERY_COUNT}", flush=True)

    return {
        "seed": seed,
        "data_sha256": data_sha256,
        "quantized_step": quantizer.step,
        "minimum_code": int(row_codes.min()),
        "maximum_code": int(row_codes.max()),
        "query_sign_counts": sign_counts,
        "filtered": finalize_accumulator(accumulators["filtered"]),
        "unfiltered": finalize_accumulator(accumulators["unfiltered"]),
        "elapsed_seconds": time.perf_counter() - start,
    }


def aggregate_seeds(seed_results):
    aggregate = {"filtered": {}, "unfiltered": {}}
    for surface in ("filtered", "unfiltered"):
        for method in METHODS:
            aggregate[surface][method] = {}
            for prefix in PREFIXES:
                entries = [
                    result[surface][method][prefix] for result in seed_results
                ]
                rates = [
                    entry["rejection_rate_candidate_weighted"]
                    for entry in entries
                    if entry["rejection_rate_candidate_weighted"] is not None
                ]
                aggregate[surface][method][prefix] = {
                    "seed_rejection_rates": rates,
                    "median_seed_rejection_rate": (
                        statistics.median(rates) if rates else None
                    ),
                    "minimum_seed_rejection_rate": min(rates) if rates else None,
                    "maximum_seed_rejection_rate": max(rates) if rates else None,
                    "topk_mismatches": sum(
                        entry["topk_mismatches"] for entry in entries
                    ),
                }
    tight64 = aggregate["filtered"]["tight"][64]["median_seed_rejection_rate"]
    tight64_unfiltered = aggregate["unfiltered"]["tight"][64][
        "median_seed_rejection_rate"
    ]
    return {
        "surfaces": aggregate,
        "decision": {
            "threshold": 0.70,
            "filtered_tight_64_median": tight64,
            "unfiltered_tight_64_median": tight64_unfiltered,
            "continue_to_production_kernel": (
                tight64 is not None
                and tight64_unfiltered is not None
                and min(tight64, tight64_unfiltered) >= 0.70
            ),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", default=",".join(map(str, SEEDS)))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    seeds = tuple(int(value) for value in args.seeds.split(",") if value)
    if not seeds:
        parser.error("at least one seed is required")
    report = {
        "scope": (
            "Offline conservative-prefix rejection probe; no production code, "
            "timing claim, ANN approximation, or official score"
        ),
        "rows": ROWS,
        "dimension": DIMENSION,
        "queries": QUERY_COUNT,
        "top_k": TOP_K,
        "prefixes": PREFIXES,
        "scan_shape": (
            "Two independent slices when candidate count >= 1024; 32-row batch "
            "thresholds match the current quantized screening loop"
        ),
        "bounds": {
            "coarse": "step^2 * sum(max(abs(row_code-query_code)-1, 0)^2)",
            "tight": (
                "sum(max(abs(step*(row_code-query_code)+query_residual)"
                " - step/2, 0)^2); row residual bounded by +/-step/2"
            ),
            "rounding": (
                "Squared sums are scaled down by 1e-12; sqrt is moved down one "
                "binary64 value; comparison requires more than nextafter(worst)"
            ),
        },
        "seeds": seeds,
        "per_seed": [],
    }
    for seed in seeds:
        result = run_seed(seed)
        report["per_seed"].append(result)
        print(
            json.dumps(
                {
                    "seed": seed,
                    "elapsed_seconds": result["elapsed_seconds"],
                    "filtered": result["filtered"],
                    "unfiltered": result["unfiltered"],
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    report["aggregate"] = aggregate_seeds(report["per_seed"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["aggregate"], ensure_ascii=False, indent=2))
    no_mismatches = all(
        report["aggregate"]["surfaces"][surface][method][prefix]["topk_mismatches"]
        == 0
        for surface in ("filtered", "unfiltered")
        for method in METHODS
        for prefix in PREFIXES
    )
    return 0 if no_mismatches else 2


if __name__ == "__main__":
    raise SystemExit(main())
