#!/usr/bin/env bash
set -uo pipefail
out=/mnt/f/OceanBase/seekdb/cpt-seekdb/validation/l2-hmy-20261110
official=/mnt/e/MiniVectorDB/official-hmy-l2-archive-20261110
if test -e "$out/official-baseline-all.txt"; then echo 'Refusing to overwrite official evidence' >&2; exit 1; fi
cd "$official" || exit 1
sha256sum STDIO_PROTOCOL.md protocol_check/*.py protocol_check/config.json mysqltest/manifest.json > "$out/official-tool-sha256.txt"
failed=0
run() {
  local label=$1; shift
  python3 protocol_check/run.py --image codex-hmy-l2-baseline:20261110 "$@" --output "$out/official-baseline-$label" > "$out/official-baseline-$label.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$out/official-baseline-$label.txt"
  printf 'official-baseline-%s exit=%s\n' "$label" "$status"
  return "$status"
}
run handshake --handshake-only || failed=1
run crud --case sql_crud || failed=1
run all || failed=1
exit "$failed"
