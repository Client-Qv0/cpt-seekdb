#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111
out="$root/validation/c22-hmy-20261111"
build=/mnt/e/MiniVectorDB/build-hmy-c22-parser-20261111
export PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH"
export LD_LIBRARY_PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$root/tests"
export TMPDIR=$(mktemp -d /dev/shm/mvdb-c22-XXXXXX)
run(){ name=$1; shift; "$@" > "$out/$name.txt" 2>&1; status=$?; echo "exit=$status" >> "$out/$name.txt"; echo "$name exit=$status"; return "$status"; }
run configure cmake -S "$root" -B "$build" -DCMAKE_BUILD_TYPE=Release || exit 1
run build cmake --build "$build" --parallel 2 || exit 1
sha256sum "$build/minivectordb" > "$out/binary.sha256"
run ctest ctest --test-dir "$build" --output-on-failure || exit 1
run acceptance python3 "$root/tests/acceptance.py" --binary "$build/minivectordb" --stress -v || exit 1
run optimization python3 "$root/tests/optimization_acceptance.py" --binary "$build/minivectordb" --large -v || exit 1
handoff="$root/validation/c14-hmy-20261111/teammate-handoff/evidence"
run differential python3 "$handoff/candidate-tests/distance_differential.py" --baseline /mnt/e/MiniVectorDB/build-hmy-c14-team-20261111/minivectordb --candidate "$build/minivectordb" --output "$out/differential.json" || exit 1
run docker-build docker build --progress=plain -t codex-hmy-c22-parser:20261111 "$root" || exit 1
docker image inspect codex-hmy-c22-parser:20261111 > "$out/image.json"
