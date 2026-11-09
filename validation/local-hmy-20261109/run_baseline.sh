#!/usr/bin/env bash
set -uo pipefail
cd /mnt/e/MiniVectorDB/work
run_dir=validation/local-hmy-20261109
export TMPDIR=/mnt/e/MiniVectorDB/tmp
export LD_LIBRARY_PATH=/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu
export PATH=/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH
{
  date -Is
  uname -a
  g++ --version
  cmake --version
  python3 --version
  git --version
  taskset -pc $$
  cat /proc/self/cgroup
  df -h . "$TMPDIR"
} > "$run_dir/environment.txt" 2>&1
run() {
  local label=$1
  shift
  printf 'Command:' > "$run_dir/$label.txt"
  printf ' %q' "$@" >> "$run_dir/$label.txt"
  printf '\n' >> "$run_dir/$label.txt"
  "$@" >> "$run_dir/$label.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$run_dir/$label.txt"
  printf '%s exit=%s\n' "$label" "$status"
  return "$status"
}
run configure cmake -S . -B /mnt/e/MiniVectorDB/build-release -DCMAKE_BUILD_TYPE=Release || exit 1
run build cmake --build /mnt/e/MiniVectorDB/build-release --parallel 2 || exit 1
sha256sum /mnt/e/MiniVectorDB/build-release/minivectordb > "$run_dir/binary.sha256"
run ctest ctest --test-dir /mnt/e/MiniVectorDB/build-release --output-on-failure
run public-bridge-unit python3 tests/test_public_bridge.py
run acceptance python3 tests/acceptance.py --binary /mnt/e/MiniVectorDB/build-release/minivectordb -v
run optimization python3 tests/optimization_acceptance.py --binary /mnt/e/MiniVectorDB/build-release/minivectordb -v
run public-samples python3 tests/public_samples.py --binary /mnt/e/MiniVectorDB/build-release/minivectordb --package validation/exact-query-li-20261109/public-package/mysqltest --output "$run_dir/public-samples.json"
