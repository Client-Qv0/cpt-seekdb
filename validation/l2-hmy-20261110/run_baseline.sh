#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
out="$root/validation/l2-hmy-20261110"
build=/mnt/e/MiniVectorDB/build-hmy-l2-baseline-20261110
export PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH"
export LD_LIBRARY_PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if test -e "$out/baseline-environment.txt" || test -e "$build"; then
  echo 'Refusing to overwrite prior evidence or baseline build.' >&2; exit 1
fi
{
  date --iso-8601=seconds
  uname -a
  cmake --version | head -1
  g++ --version | head -1
  python3 --version
  docker version --format 'client={{.Client.Version}} server={{.Server.Version}}'
  cat /proc/self/cgroup
  grep Cpus_allowed_list /proc/self/status
  sha256sum "$root/validation/perf-20261110-stdio/scripts/bench.py" "$root/validation/perf-20261110-stdio/scripts/bench_portable.py" "$root/agent/conversation.json"
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
