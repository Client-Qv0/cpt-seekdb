#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111
out="$root/validation/perf-best87-20261112"
export PYTHONPATH=/mnt/e/MiniVectorDB/deps/hmy-l2-20261110/site
export OPENBLAS_NUM_THREADS=1
python3 "$out/tool/bench.py" --images base=codex-hmy-best87:20261112 candidate=codex-hmy-c22-parser:20261111 --seeds 91003 91011 91023 91003 91011 91023 --rows 10000 --dim 128 --queries 1000 --prefix hmy-best87 > "$out/runner.stdout.log" 2> "$out/runner.stderr.log"
status=$?
echo "exit=$status"
exit "$status"
