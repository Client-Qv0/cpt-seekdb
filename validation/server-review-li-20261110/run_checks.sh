#!/usr/bin/env bash
set -eu
repo=/home/li/minivectordb-review-20261110
out=$repo/validation/server-review-li-20261110
py=/home/li/mvdb-review-venv-20261110/bin/python
cd "$repo"
for marker in docker-build.exit base-docker-build.exit numpy-install.exit; do
 for round in $(seq 1 240); do test -f "$out/$marker" && break; sleep 5; done
 test -f "$out/$marker"
 test "$(cat "$out/$marker")" = 0
done
"$py" -c 'import numpy; print(numpy.__version__)' > "$out/numpy-version.txt"
docker image inspect mvdb-li-review:9cea05e mvdb-li-review:base6576 > "$out/images.json"
for image in 9cea05e base6576; do
 docker run --rm --network=none --entrypoint sha256sum mvdb-li-review:$image /app/minivectordb > "$out/$image-binary.txt"
done
cd /home/li/official-git-f4d4e266-20261110
git -c safe.directory=/home/li/official-git-f4d4e266-20261110 rev-parse HEAD > "$out/official-commit.txt"
sha256sum STDIO_PROTOCOL.md protocol_check/*.py protocol_check/config.json mysqltest/manifest.json > "$out/official-tools.sha256"
python3 protocol_check/run.py --image mvdb-li-review:9cea05e --handshake-only --output "$out/official-handshake" > "$out/official-handshake.log" 2>&1
python3 protocol_check/run.py --image mvdb-li-review:9cea05e --case sql_crud --output "$out/official-crud" > "$out/official-crud.log" 2>&1
python3 protocol_check/run.py --image mvdb-li-review:9cea05e --output "$out/official-all" > "$out/official-all.log" 2>&1
cd "$repo"
python3 tests/test_container_recovery.py --image mvdb-li-review:9cea05e --data-root /home/li/mvdb-review-recovery-data-20261110 --output "$out/container-recovery" > "$out/container-recovery.log" 2>&1
"$py" validation/perf-20261110-stdio/scripts/bench_portable.py --images base=mvdb-li-review:base6576 candidate=mvdb-li-review:9cea05e --output-root "$out/preflight" --data-root /home/li/mvdb-review-preflight-data-20261110 --prefix li-review-preflight --docker-host unix:///var/run/docker.sock --preflight-only > "$out/preflight.log" 2>&1
"$py" validation/perf-20261110-stdio/scripts/bench_portable.py --images base=mvdb-li-review:base6576 candidate=mvdb-li-review:9cea05e --output-root "$out/paired-main" --data-root /home/li/mvdb-review-main-data-20261110 --prefix li-review-main --docker-host unix:///var/run/docker.sock --seeds 3179 3181 3187 3179 3181 3187 --rows 10000 --dim 128 --queries 1000 > "$out/paired-main.log" 2>&1
"$py" validation/perf-20261110-stdio/scripts/bench_portable.py --images base=mvdb-li-review:base6576 candidate=mvdb-li-review:9cea05e --output-root "$out/paired-overflow" --data-root /home/li/mvdb-review-overflow-data-20261110 --prefix li-review-overflow --docker-host unix:///var/run/docker.sock --seeds 3179 3181 3187 --rows 32000 --dim 128 --queries 100 > "$out/paired-overflow.log" 2>&1
echo 0 > "$out/pipeline.exit"
