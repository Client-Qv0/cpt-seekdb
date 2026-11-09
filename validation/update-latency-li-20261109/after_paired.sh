#!/usr/bin/env bash
cd /opt/minivectordb-v2
p=validation/update-latency-li-20261109
while ps -p 684856 -o stat= | grep -qv '^Z'; do sleep 5; done
python3 -c 'import json; from pathlib import Path; d=json.loads(Path("validation/update-latency-li-20261109/paired-original/summary.json").read_text()); assert d["all_planned_runs_passed"] and d["identities_unchanged"]' && bash "$p/run_remaining.sh"
rc=$?
echo "$rc" > "$p/pipeline.exit"
exit "$rc"
