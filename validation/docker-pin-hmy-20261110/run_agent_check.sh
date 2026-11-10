#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/cpt-seekdb
out="$root/validation/docker-pin-hmy-20261110"
log="$out/agent-check.txt"
if test -e "$log"; then echo 'Refusing to overwrite agent evidence' >&2; exit 1; fi
{
  sha256sum "$root/agent/conversation.json"
  wc -c "$root/agent/conversation.json"
  python3 "$root/tests/test_agent_material.py" -v
} > "$log" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$log"
exit "$status"
