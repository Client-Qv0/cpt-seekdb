#!/usr/bin/env bash
# Adapter for the existing local public-sample bridge. Uses the image's actual
# ENTRYPOINT and creates a fresh container for each bridge start/restart.
set -euo pipefail
if [ "$#" -ne 3 ] || [ "$1" != '--data-dir' ] || [ "$3" != '--dev-protocol' ]; then
  echo 'Expected --data-dir PATH --dev-protocol' >&2
  exit 2
fi
data=$(realpath "$2")
exec docker run --rm -i --network none --cpus 2 --memory 128m --memory-swap 128m \
  --user "$(id -u):$(id -g)" --mount "type=bind,src=$data,dst=/data" \
  "${MVDB_PUBLIC_IMAGE:?set MVDB_PUBLIC_IMAGE}" --data-dir /data --dev-protocol
