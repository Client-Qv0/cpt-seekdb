#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
out=validation/docker-lock-hmy-20261109
if test -e "$out/ca-probe2.txt"; then echo 'Evidence exists; refusing overwrite' >&2; exit 1; fi
timeout 300 docker build --progress plain --no-cache --file "$out/Dockerfile.ca-probe2" \
  --tag codex-minivectordb-ca-probe2:20261109 . > "$out/ca-probe2.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/ca-probe2.txt"
exit "$status"
