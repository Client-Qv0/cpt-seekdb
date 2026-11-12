#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111
out="$root/validation/c22-hmy-20261111"
official=/mnt/e/MiniVectorDB/official-hmy-l2-archive-20261110
image=codex-hmy-c22-parser:20261111
if test -e "$out/c14-public.txt" || test -e "$out/c14-recovery.txt"; then echo 'refusing to overwrite checks' >&2; exit 1; fi
run() {
  local name=$1; shift
  "$@" > "$out/$name.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$out/$name.txt"
  printf '%s exit=%s\n' "$name" "$status"
  return "$status"
}
failed=0
run c14-public python3 "$official/protocol_check/run.py" --image "$image" --output "$out/c14-public" || failed=1
run c14-recovery python3 "$root/tests/test_container_recovery.py" --image "$image" --data-root /var/tmp/mvdb-hmy-c22-submit-recovery-20261111 --output "$out/c14-recovery" || failed=1
exit "$failed"
