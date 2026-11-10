#!/usr/bin/env bash
set -uo pipefail
dest=/mnt/e/MiniVectorDB/official-hmy-l2-20261110
log=/mnt/f/OceanBase/seekdb/cpt-seekdb/validation/l2-hmy-20261110/official-fetch.txt
if test -e "$dest" || test -e "$log"; then echo 'Refusing to overwrite official checkout or evidence' >&2; exit 1; fi
{
  git clone --filter=blob:none --sparse --single-branch --branch 2026-competition-round2 https://github.com/oceanbase/seekdb.git "$dest" || exit 1
  git -C "$dest" fetch origin f4d4e26653af823a7601668802f80e374ad6643c || exit 1
  git -C "$dest" switch --detach f4d4e26653af823a7601668802f80e374ad6643c || exit 1
  git -C "$dest" sparse-checkout set protocol_check mysqltest || exit 1
  git -C "$dest" rev-parse HEAD || exit 1
  git -C "$dest" status --short || exit 1
} > "$log" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$log"
exit "$status"
