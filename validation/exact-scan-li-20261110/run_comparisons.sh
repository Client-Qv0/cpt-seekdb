#!/bin/bash
set -eu
cd /home/li/minivectordb-exact-scan-20261110
out=/home/li/minivectordb-exact-scan-20261110/validation/exact-scan-li-20261110
py=/home/li/mvdb-review-venv-20261110/bin/python
while kill -0 1674323 2>/dev/null && test ! -f "$out/c1-b-main/adapter-manifest.json" || false; do sleep 5; done
while ! "$py" -c 'import json,sys; x=json.load(open(sys.argv[1])); sys.exit(0 if "exit_code" in x else 1)' "$out/c1-b-main/adapter-manifest.json" 2>/dev/null; do
  kill -0 1674323 2>/dev/null || { echo "first job exited without completion manifest"; exit 1; }
  sleep 5
done
"$py" -c 'import json,sys; assert json.load(open(sys.argv[1]))["exit_code"] == 0' "$out/c1-b-main/adapter-manifest.json"
run() {
  name=$1; left=$2; right=$3; shift 3
  "$py" validation/perf-20261110-stdio/scripts/bench_portable.py --images "left=$left" "right=$right" --output-root "$out/$name" --data-root "/home/li/exact-scan-$name-data-20261110" --docker-host unix:///var/run/docker.sock --prefix "li-$name" "$@" > "$out/$name.log" 2>&1
}
run c1-b-overflow mvdb-li-review:9cea05e mvdb-li-exact:c1-07b3a75 --seeds 3179 3181 3187 --rows 32000 --dim 128 --queries 100
run c2-c1-main mvdb-li-exact:c1-07b3a75 mvdb-li-exact:c2-3490b49 --seeds 3179 3181 3187 3179 3181 3187 --rows 10000 --dim 128 --queries 1000
run c2-c1-overflow mvdb-li-exact:c1-07b3a75 mvdb-li-exact:c2-3490b49 --seeds 3179 3181 3187 --rows 32000 --dim 128 --queries 100
run final-b-main mvdb-li-review:9cea05e mvdb-li-exact:c2-3490b49 --seeds 3179 3181 3187 3179 3181 3187 --rows 10000 --dim 128 --queries 1000
run final-b-overflow mvdb-li-review:9cea05e mvdb-li-exact:c2-3490b49 --seeds 3179 3181 3187 --rows 32000 --dim 128 --queries 100
run final-b-holdout mvdb-li-review:9cea05e mvdb-li-exact:c2-3490b49 --seeds 65003 65011 65027 --rows 10000 --dim 128 --queries 1000
printf '0\n' > "$out/comparisons.exit"
