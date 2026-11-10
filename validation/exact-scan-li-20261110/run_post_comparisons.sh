#!/bin/bash
set -eu
cd /home/li/minivectordb-exact-scan-20261110
out=/home/li/minivectordb-exact-scan-20261110/validation/exact-scan-li-20261110
while test ! -f "$out/comparisons.exit"; do
 kill -0 1676636 2>/dev/null || { echo "comparison runner stopped without success marker"; exit 1; }
 sleep 10
done
test "$(cat "$out/comparisons.exit")" = 0
tar -xf "$out/7637-source.tar" -C "$out/source-7637"
docker build --network host -t mvdb-li-exact:7637-rebuilt "$out/source-7637" > "$out/7637-build.log" 2>&1
docker image inspect mvdb-li-exact:7637-rebuilt > "$out/7637-image.json"
docker run --rm --network=none --entrypoint sha256sum mvdb-li-exact:7637-rebuilt /app/minivectordb > "$out/7637-binary.sha256"
cd /home/li/official-git-f4d4e266-20261110
git -c safe.directory=/home/li/official-git-f4d4e266-20261110 rev-parse HEAD > "$out/official-commit.txt"
sha256sum STDIO_PROTOCOL.md protocol_check/*.py protocol_check/config.json mysqltest/manifest.json > "$out/official-tools.sha256"
python3 protocol_check/run.py --image mvdb-li-exact:c2-3490b49 --output "$out/c2-official-all" > "$out/c2-official-all.log" 2>&1
cd /home/li/minivectordb-exact-scan-20261110
python3 tests/test_container_recovery.py --image mvdb-li-exact:c2-3490b49 --data-root /home/li/exact-scan-c2-recovery-data-20261110 --output "$out/c2-recovery" > "$out/c2-recovery.log" 2>&1
/home/li/mvdb-review-venv-20261110/bin/python validation/perf-20261110-stdio/scripts/bench_portable.py --images original=mvdb-li-exact:7637-rebuilt final=mvdb-li-exact:c2-3490b49 --output-root "$out/7637-final-main" --data-root /home/li/exact-scan-7637-final-data-20261110 --docker-host unix:///var/run/docker.sock --prefix li-7637-final --seeds 3179 3181 3187 --rows 10000 --dim 128 --queries 1000 > "$out/7637-final-main.log" 2>&1
python3 tests/cardinality_probe.py --binary /home/li/minivectordb-review-20261110/build-server-review/minivectordb --image mvdb-li-review:9cea05e --socket unix:///var/run/docker.sock --cpuset 0,1 --sizes 1000000 --kinds scalar --stage-seconds 300 --case-seconds 1200 --output "$out/million-baseline" > "$out/million-baseline.log" 2>&1
python3 tests/cardinality_probe.py --binary /home/li/minivectordb-exact-scan-20261110/build-exact-c2/minivectordb --image mvdb-li-exact:c2-3490b49 --socket unix:///var/run/docker.sock --cpuset 0,1 --sizes 1000000 --kinds scalar --stage-seconds 300 --case-seconds 1200 --output "$out/million-c2" > "$out/million-c2.log" 2>&1
python3 "$out/cardinality_eligible_probe.py" --binary /home/li/minivectordb-review-20261110/build-server-review/minivectordb --image mvdb-li-review:9cea05e --socket unix:///var/run/docker.sock --cpuset 0,1 --sizes 1000000 --kinds vector4 --stage-seconds 300 --case-seconds 1200 --output "$out/million-vector-baseline" > "$out/million-vector-baseline.log" 2>&1
python3 "$out/cardinality_eligible_probe.py" --binary /home/li/minivectordb-exact-scan-20261110/build-exact-c2/minivectordb --image mvdb-li-exact:c2-3490b49 --socket unix:///var/run/docker.sock --cpuset 0,1 --sizes 1000000 --kinds vector4 --stage-seconds 300 --case-seconds 1200 --output "$out/million-vector-c2" > "$out/million-vector-c2.log" 2>&1
printf '0\n' > "$out/post-comparisons.exit"
