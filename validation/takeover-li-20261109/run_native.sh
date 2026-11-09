#!/bin/sh
set -eu
cd /opt/minivectordb-hmy-li
p=validation/takeover-li-20261109
cmake -S . -B build-takeover -DCMAKE_BUILD_TYPE=Release > "$p/configure-release.log" 2>&1
cmake --build build-takeover --parallel 2 > "$p/build-release.log" 2>&1
ctest --test-dir build-takeover --output-on-failure > "$p/ctest-release.log" 2>&1
python3 tests/acceptance.py --binary "$PWD/build-takeover/minivectordb" --stress -v > "$p/acceptance-release.log" 2>&1
python3 tests/optimization_acceptance.py --binary "$PWD/build-takeover/minivectordb" --large -v > "$p/optimization-release.log" 2>&1
python3 tests/test_public_bridge.py > "$p/public-bridge.log" 2>&1
python3 tests/public_samples.py --binary "$PWD/build-takeover/minivectordb" --package validation/exact-query-li-20261109/public-package/mysqltest --output "$p/public-native.json" > "$p/public-native.log" 2>&1
python3 tests/test_agent_material.py -v > "$p/agent-material.log" 2>&1
python3 tests/test_benchmark_public_validation.py -v > "$p/benchmark-driver-tests.log" 2>&1
sha256sum build-takeover/minivectordb > "$p/release-binary.sha256"
echo 0 > "$p/native.exit"
