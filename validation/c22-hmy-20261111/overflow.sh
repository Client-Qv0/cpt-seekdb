#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111
out="$root/validation/c22-hmy-20261111/overflow"
export PYTHONPATH=/mnt/e/MiniVectorDB/deps/hmy-l2-20261110/site
export OPENBLAS_NUM_THREADS=1
python3 "$out/tool/bench.py" --images base=codex-hmy-c14-team:20261111 candidate=codex-hmy-c22-parser:20261111 --seeds 71003 --rows 32000 --dim 128 --queries 100 --prefix hmy-parser22-overflow > "$out/runner.stdout.log" 2> "$out/runner.stderr.log"
status=$?
echo "exit=$status"
exit "$status"
