#!/usr/bin/env bash
set -euo pipefail
RUN=/home/li/mvdb-negative-local-20261113/c17-dsync-write/functional-20261113
REPO=/home/li/minivectordb-self-iterate-20261113
BUILD=/home/li/build-self-iterate-c2-20261113
BIN="$BUILD/minivectordb"
PACKAGE=/home/li/official-git-f4d4e266-20261110/mysqltest
mkdir -p "$RUN/native-public"
rm -f "$RUN/functional.exit"
cmake --build "$BUILD" -j4 > "$RUN/build-release.log" 2>&1
cd "$REPO"
{
  date --iso-8601=seconds
  git rev-parse HEAD
  git status --short --branch
  c++ --version | head -1
  cmake --version | head -1
  uname -a
} > "$RUN/environment.txt"
sha256sum "$BIN" "$BUILD/test_storage" src/storage.cpp tests/test_storage.cpp \
  > "$RUN/source-binary.sha256"
ctest --test-dir "$BUILD" --output-on-failure > "$RUN/ctest.log" 2>&1
echo "ctest_exit=0" > "$RUN/ctest.exit"
python3 tests/acceptance.py --binary "$BIN" --stress -v > "$RUN/acceptance-stress.log" 2>&1
echo "acceptance_exit=0" > "$RUN/acceptance-stress.exit"
python3 tests/optimization_acceptance.py --binary "$BIN" --large -v > "$RUN/optimization-large.log" 2>&1
echo "optimization_exit=0" > "$RUN/optimization-large.exit"
python3 tests/test_public_bridge.py > "$RUN/public-bridge.log" 2>&1
echo "public_bridge_exit=0" > "$RUN/public-bridge.exit"
python3 tests/public_samples.py --binary "$BIN" --package "$PACKAGE" --output "$RUN/native-public/result.json" > "$RUN/native-public.log" 2>&1
echo "native_public_exit=0" > "$RUN/native-public.exit"
echo "0" > "$RUN/functional.exit"
