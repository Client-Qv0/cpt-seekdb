#!/bin/sh
set -eu
cd /opt/minivectordb-v2-query
p=validation/exact-query-li-20261109
python3 validation/cardinality-20261109/paired-candidate-v2/tools/paired_benchmark.py --baseline-binary /opt/minivectordb-v2/build-handoff/minivectordb --baseline-source /opt/minivectordb-v2 --baseline-manifest /opt/minivectordb-v2/validation/cardinality-20261109/candidate-v2-production-manifest.json --baseline-lock "$p/control-lock.json" --candidate-binary build-query/minivectordb --candidate-source "$p/prototype-blocked-source" --candidate-manifest "$p/candidate-manifest.json" --benchmark-script validation/cardinality-20261109/paired-candidate-v2/tools/benchmark_local.py --oracle validation/cardinality-20261109/paired-candidate-v2/tools/oracle.py --image minivectordb-li-runtime:20261109 --socket unix:///var/run/docker.sock --cpuset 0,1 --workloads vector128 --output-dir "$p/${1:?new-output-name}"
