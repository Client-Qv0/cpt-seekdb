#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
out=validation/docker-lock-hmy-20261109
if test -e "$out/ca-probe.txt"; then echo 'Evidence exists; refusing overwrite' >&2; exit 1; fi
timeout 300 docker build --progress plain --no-cache --file "$out/Dockerfile.ca-probe" \
  --tag codex-minivectordb-ca-probe:20261109 . > "$out/ca-probe.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/ca-probe.txt"
exit "$status"
