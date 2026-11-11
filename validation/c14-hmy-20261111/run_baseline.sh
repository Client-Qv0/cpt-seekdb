#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111
out="$root/validation/c14-hmy-20261111"
build=/mnt/e/MiniVectorDB/build-hmy-c14-base-20261111
export PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH"
export LD_LIBRARY_PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if test -e "$out/baseline-environment.txt" || test -e "$build"; then echo 'refusing to overwrite baseline' >&2; exit 1; fi
export TMPDIR
TMPDIR=$(mktemp -d /dev/shm/mvdb-c14-base-XXXXXX) || exit 1
{
  date --iso-8601=seconds
  uname -a
  cmake --version | head -1
  g++ --version | head -1
  python3 --version
  docker version --format 'client={{.Client.Version}} server={{.Server.Version}}'
  cat /proc/self/cgroup
  grep Cpus_allowed_list /proc/self/status
  sha256sum "$root"/src/*.cpp "$root"/src/*.hpp "$root"/Dockerfile "$root"/CMakeLists.txt
} > "$out/baseline-environment.txt" 2>&1
run() {
  local name=$1; shift
  "$@" > "$out/$name.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$out/$name.txt"
  printf '%s exit=%s\n' "$name" "$status"
  return "$status"
}
run baseline-configure cmake -S "$root" -B "$build" -DCMAKE_BUILD_TYPE=Release || exit 1
run baseline-build cmake --build "$build" --parallel 2 || exit 1
sha256sum "$build/minivectordb" > "$out/baseline-binary.sha256"
failed=0
run baseline-ctest ctest --test-dir "$build" --output-on-failure || failed=1
run baseline-acceptance python3 "$root/tests/acceptance.py" --binary "$build/minivectordb" --stress -v || failed=1
run baseline-optimization python3 "$root/tests/optimization_acceptance.py" --binary "$build/minivectordb" --large -v || failed=1
run baseline-agent python3 "$root/tests/test_agent_material.py" -v || failed=1
exit "$failed"
