#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
out=validation/docker-lock-hmy-20261109
if test -e "$out/snapshot-probe.txt"; then echo 'Evidence exists; refusing overwrite' >&2; exit 1; fi
timeout 180 docker build --progress plain --no-cache --file "$out/Dockerfile.probe" \
  --tag codex-minivectordb-snapshot-probe:20261109 . > "$out/snapshot-probe.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/snapshot-probe.txt"
exit "$status"
