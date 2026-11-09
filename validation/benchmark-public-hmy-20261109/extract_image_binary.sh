#!/usr/bin/env bash
set -euo pipefail
cd /mnt/e/MiniVectorDB/work
out=validation/benchmark-public-hmy-20261109
image=codex-minivectordb-production-hmy:20261109
container=$(docker create "$image")
trap 'docker rm -v "$container" >/dev/null' EXIT
docker cp "$container:/app/minivectordb" /mnt/e/MiniVectorDB/production-image-minivectordb
chmod +x /mnt/e/MiniVectorDB/production-image-minivectordb
sha256sum /mnt/e/MiniVectorDB/production-image-minivectordb /mnt/e/MiniVectorDB/build-release/minivectordb > "$out/image-and-native.sha256"
