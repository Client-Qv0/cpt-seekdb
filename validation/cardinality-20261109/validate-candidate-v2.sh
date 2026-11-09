#!/usr/bin/env bash
set -eu
p=validation/cardinality-20261109
s=build-cardinality/candidate-v2/source
r=build-cardinality/candidate-v2/release
z=build-cardinality/candidate-v2/sanitize
cmake -S "$s" -B "$r" -DCMAKE_BUILD_TYPE=Release > "$p/candidate-v2-configure-release.txt" 2>&1
cmake --build "$r" --parallel 4 > "$p/candidate-v2-build-release.txt" 2>&1
ctest --test-dir "$r" --output-on-failure > "$p/candidate-v2-ctest-release.txt" 2>&1
python3 "$s/tests/acceptance.py" --binary "$r/minivectordb" --stress -v > "$p/candidate-v2-acceptance-release.txt" 2>&1
python3 "$s/tests/optimization_acceptance.py" --binary "$r/minivectordb" --large -v > "$p/candidate-v2-optimization-release.txt" 2>&1
printf 'Release complete\n'
cmake -S "$s" -B "$z" -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_FLAGS="-fsanitize=address,undefined -fno-omit-frame-pointer" -DCMAKE_EXE_LINKER_FLAGS="-fsanitize=address,undefined" > "$p/candidate-v2-configure-sanitize.txt" 2>&1
cmake --build "$z" --parallel 4 > "$p/candidate-v2-build-sanitize.txt" 2>&1
ctest --test-dir "$z" --output-on-failure > "$p/candidate-v2-ctest-sanitize.txt" 2>&1
python3 "$s/tests/acceptance.py" --binary "$z/minivectordb" -v > "$p/candidate-v2-acceptance-sanitize.txt" 2>&1
python3 "$s/tests/optimization_acceptance.py" --binary "$z/minivectordb" -v > "$p/candidate-v2-optimization-sanitize.txt" 2>&1
printf 'Sanitizer complete\n'
g++ -std=c++17 -O2 -DNDEBUG -I"$s/src" "$p/checkpoint-helper.cpp" "$s/src/storage.cpp" -o "$p/checkpoint-helper-candidate-v2" > "$p/checkpoint-helper-candidate-v2-build.txt" 2>&1
python3 "$s/tests/index_compatibility.py" --baseline build-cardinality/baseline/release/minivectordb --candidate "$r/minivectordb" --baseline-helper "$p/checkpoint-helper-baseline" --candidate-helper "$p/checkpoint-helper-candidate-v2" --output "$p/index-compatibility-v2.json" > "$p/index-compatibility-v2.txt" 2>&1
printf 'Compatibility complete\n'
sha256sum "$r/minivectordb" "$z/minivectordb"
