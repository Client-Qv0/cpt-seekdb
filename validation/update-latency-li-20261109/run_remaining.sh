#!/usr/bin/env bash
set -eu
cd /opt/minivectordb-v2
p=validation/update-latency-li-20261109
python3 -m py_compile "$p/diagnose_update.py" "$p/resource_driver.py"
for mode in split trace; do
 for version in baseline v2; do
  binary=build-handoff/minivectordb
  if [ "$version" = baseline ]; then binary=build-update-baseline/release/minivectordb; fi
  trace_arg=()
  if [ "$mode" = trace ]; then trace_arg=(--trace); fi
  python3 "$p/diagnose_update.py" --binary "$binary" --output "$p/diagnostic-$mode-$version" --image minivectordb-li-runtime:20261109 "${trace_arg[@]}" > "$p/diagnostic-$mode-$version.log" 2>&1
 done
done
g++ -std=c++17 -O3 -DNDEBUG -Isrc "$p/diagnostic_main.cpp" build-handoff/libmvdb.a -o build-handoff/minivectordb-diagnostic > "$p/diagnostic-v2-build.log" 2>&1
g++ -std=c++17 -O3 -DNDEBUG -Ibuild-update-baseline/source/src "$p/diagnostic_main.cpp" build-update-baseline/release/libmvdb.a -o build-update-baseline/release/minivectordb-diagnostic > "$p/diagnostic-baseline-build.log" 2>&1
for version in baseline v2; do
 binary=build-handoff/minivectordb-diagnostic
 if [ "$version" = baseline ]; then binary=build-update-baseline/release/minivectordb-diagnostic; fi
 python3 "$p/diagnose_update.py" --binary "$binary" --output "$p/diagnostic-instrumented-$version" --image minivectordb-li-runtime:20261109 > "$p/diagnostic-instrumented-$version.log" 2>&1
done
ctest --test-dir build-update-baseline/release --output-on-failure > "$p/ctest-baseline.log" 2>&1
python3 tests/acceptance.py --binary ./build-handoff/minivectordb --stress -v > "$p/acceptance-release-full.log" 2>&1
python3 tests/optimization_acceptance.py --binary ./build-handoff/minivectordb --large -v > "$p/optimization-release-full.log" 2>&1
cmake -S . -B build-update-sanitize -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer' -DCMAKE_EXE_LINKER_FLAGS='-fsanitize=address,undefined' > "$p/configure-sanitize.log" 2>&1
cmake --build build-update-sanitize --parallel 2 > "$p/build-sanitize.log" 2>&1
export ASAN_OPTIONS=detect_leaks=1:halt_on_error=1
export UBSAN_OPTIONS=halt_on_error=1
ctest --test-dir build-update-sanitize --output-on-failure > "$p/ctest-sanitize.log" 2>&1
python3 tests/acceptance.py --binary ./build-update-sanitize/minivectordb -v > "$p/acceptance-sanitize.log" 2>&1
python3 tests/optimization_acceptance.py --binary ./build-update-sanitize/minivectordb -v > "$p/optimization-sanitize.log" 2>&1
unset ASAN_OPTIONS UBSAN_OPTIONS
python3 "$p/resource_driver.py" --binary build-handoff/minivectordb --expected-binary-sha256 78996ec9a6d15c5357b5111a4fd78ed28bf1cde174538dee81ae5de1b2daf26c --source-root . --source-manifest validation/cardinality-20261109/candidate-v2-production-manifest.json --output "$p/resource-regression" > "$p/resource-regression.log" 2>&1
g++ -std=c++17 -O2 -DNDEBUG -Ibuild-update-baseline/source/src validation/cardinality-20261109/checkpoint-helper.cpp build-update-baseline/source/src/storage.cpp -o build-update-baseline/checkpoint-helper > "$p/checkpoint-helper-baseline-build.log" 2>&1
g++ -std=c++17 -O2 -DNDEBUG -Isrc validation/cardinality-20261109/checkpoint-helper.cpp src/storage.cpp -o build-handoff/checkpoint-helper > "$p/checkpoint-helper-v2-build.log" 2>&1
python3 tests/index_compatibility.py --baseline build-update-baseline/release/minivectordb --candidate build-handoff/minivectordb --baseline-helper build-update-baseline/checkpoint-helper --candidate-helper build-handoff/checkpoint-helper --output "$p/index-compatibility.json" > "$p/index-compatibility.log" 2>&1
python3 tools/handoff/verify.py > "$p/handoff-verify-after.txt"
echo 0 > "$p/remaining.exit"
