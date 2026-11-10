#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/cpt-seekdb
out="$root/validation/docker-pin-hmy-20261110"
official=/mnt/e/MiniVectorDB/official-hmy-l2-archive-20261110
if test "$#" -ne 2; then echo "Usage: $0 LABEL IMAGE" >&2; exit 2; fi
label=$1; image=$2
case "$label" in *[!a-zA-Z0-9_-]*|'') exit 2;; esac
if test -e "$out/$label-official-all.txt"; then echo 'Refusing to overwrite official evidence' >&2; exit 1; fi
cd "$official" || exit 1
sha256sum STDIO_PROTOCOL.md protocol_check/*.py protocol_check/config.json mysqltest/manifest.json > "$out/$label-official-tool-sha256.txt"
docker image inspect "$image" --format '{{.Id}}' > "$out/$label-official-image.txt" || exit 1
failed=0
run() {
  local part=$1; shift
  python3 protocol_check/run.py --image "$image" "$@" --output "$out/$label-official-$part" > "$out/$label-official-$part.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$out/$label-official-$part.txt"
  printf '%s-official-%s exit=%s\n' "$label" "$part" "$status"
  return "$status"
}
run handshake --handshake-only || failed=1
run crud --case sql_crud || failed=1
run all || failed=1
exit "$failed"
