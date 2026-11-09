#!/usr/bin/env bash
set -eu
cd /opt/minivectordb-v2
python3 validation/cardinality-20261109/paired-candidate-v2/tools/paired_benchmark.py \
 --baseline-binary build-update-baseline/release/minivectordb \
 --baseline-source build-update-baseline/source \
 --baseline-manifest validation/cardinality-20261109/baseline-production-manifest.json \
 --baseline-lock validation/cardinality-20261109/baseline-lock.json \
 --candidate-binary build-handoff/minivectordb --candidate-source . \
 --candidate-manifest validation/cardinality-20261109/candidate-v2-production-manifest.json \
 --benchmark-script validation/cardinality-20261109/paired-candidate-v2/tools/benchmark_local.py \
 --oracle validation/cardinality-20261109/paired-candidate-v2/tools/oracle.py \
 --adapter validation/cardinality-20261109/paired-candidate-v2/tools/cardinality_probe.py \
 --image minivectordb-li-runtime:20261109 --socket unix:///var/run/docker.sock \
 --cpuset 0,1 --workloads both --output-dir "${1:?Supply a NEW empty validation output directory}"
