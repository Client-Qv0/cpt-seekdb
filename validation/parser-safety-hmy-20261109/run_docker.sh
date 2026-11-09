#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
out=validation/parser-safety-hmy-20261109
tag=codex-minivectordb-parser-safety:20261109
if test -e "$out/docker-build.txt"; then echo 'Docker evidence already exists.' >&2; exit 1; fi
docker build --progress plain -t "$tag" . > "$out/docker-build.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/docker-build.txt"
if test "$status" -ne 0; then exit "$status"; fi
docker image inspect "$tag" > "$out/docker-image.json" || exit 1
image=$(docker image inspect "$tag" --format '{{.Id}}') || exit 1
container=$(docker create "$image") || exit 1
temporary=$(mktemp -d "${TMPDIR:-/tmp}/mvdb-parser-image-XXXXXX") || exit 1
docker cp "$container:/app/minivectordb" "$temporary/minivectordb"
copy_status=$?
docker rm -v "$container" >/dev/null
if test "$copy_status" -ne 0; then exit "$copy_status"; fi
sha256sum "$temporary/minivectordb" > "$out/docker-binary.sha256"
cmp -s "$temporary/minivectordb" "$root/build-parser-safety/minivectordb"
printf 'image_matches_native_exit=%s\n' "$?" > "$out/docker-binary-comparison.txt"
export MVDB_PUBLIC_IMAGE="$image"
python3 tests/public_samples.py --binary validation/benchmark-public-hmy-20261109/docker_public_wrapper.sh \
  --package validation/exact-query-li-20261109/public-package/mysqltest \
  --output "$out/docker-public-samples.json" > "$out/docker-public-samples.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/docker-public-samples.txt"
exit "$status"
