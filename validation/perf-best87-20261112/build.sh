#!/usr/bin/env bash
set -eu
root=/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111
out="$root/validation/perf-best87-20261112"
while pgrep -f '^python3 /mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111/validation/perf-recheck-20261112/tool/bench.py' >/dev/null; do sleep 2; done
python3 "$root/validation/c14-hmy-20261111/summarize_pairs.py" "$root/validation/perf-recheck-20261112" hmy-recheck 6 > "$root/validation/perf-recheck-20261112/summary.txt"
echo 'b68 paired run complete'
docker build --progress=plain -t codex-hmy-best87:20261112 /mnt/e/MiniVectorDB/perf-best87-20261112/source > "$out/build.txt" 2>&1
echo 'best87 build complete'
docker image inspect codex-hmy-best87:20261112 > "$out/image.json"
docker run --rm --entrypoint sha256sum codex-hmy-best87:20261112 /app/minivectordb > "$out/binary.sha256"
