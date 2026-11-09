#!/bin/sh
set -eu
test "$1" = --data-dir
test "$3" = --dev-protocol
exec docker run --rm -i --network none --cpus 2 --memory 128m --memory-swap 128m --mount "type=bind,src=$2,dst=/data" minivectordb-li-production:20261109 --data-dir /data --dev-protocol
