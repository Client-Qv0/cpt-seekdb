#!/bin/bash
set -eu
cd /home/li/minivectordb-exact-scan-20261110
out=/home/li/minivectordb-exact-scan-20261110/validation/exact-scan-li-20261110
while test ! -f "$out/post-comparisons.exit"; do
 kill -0 1684308 2>/dev/null || { echo "post-comparisons runner stopped without success marker"; exit 1; }
 sleep 10
done
test "$(cat "$out/post-comparisons.exit")" = 0
if test ! -e "$out/million-vector-baseline"; then
 python3 "$out/cardinality_eligible_probe.py" --binary /home/li/minivectordb-review-20261110/build-server-review/minivectordb --image mvdb-li-review:9cea05e --socket unix:///var/run/docker.sock --cpuset 0,1 --sizes 1000000 --kinds vector4 --stage-seconds 300 --case-seconds 1200 --output "$out/million-vector-baseline" > "$out/million-vector-baseline.log" 2>&1
fi
if test ! -e "$out/million-vector-c2"; then
 python3 "$out/cardinality_eligible_probe.py" --binary /home/li/minivectordb-exact-scan-20261110/build-exact-c2/minivectordb --image mvdb-li-exact:c2-3490b49 --socket unix:///var/run/docker.sock --cpuset 0,1 --sizes 1000000 --kinds vector4 --stage-seconds 300 --case-seconds 1200 --output "$out/million-vector-c2" > "$out/million-vector-c2.log" 2>&1
fi
python3 -c 'import json,sys; assert all(json.load(open(p))["cases"][0]["passed"] for p in sys.argv[1:])' "$out/million-vector-baseline" "$out/million-vector-c2"
printf '0\n' > "$out/million-vector.exit"
