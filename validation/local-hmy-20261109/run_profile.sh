#!/usr/bin/env bash
set -euo pipefail
cd /mnt/e/MiniVectorDB/work
run_dir=$PWD/validation/local-hmy-20261109
export LD_LIBRARY_PATH=/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu
export PATH=/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH
export TMPDIR=/dev/shm/mvdb-hmy-test
cmake -S . -B /mnt/e/MiniVectorDB/build-profile -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS_RELEASE='-O2 -g -pg -DNDEBUG' -DCMAKE_EXE_LINKER_FLAGS=-pg > "$run_dir/profile-build.txt" 2>&1
cmake --build /mnt/e/MiniVectorDB/build-profile --parallel 2 >> "$run_dir/profile-build.txt" 2>&1
sha256sum /mnt/e/MiniVectorDB/build-profile/minivectordb > "$run_dir/profile-binary.sha256"
python3 - "$run_dir" <<'PY'
import gzip
from pathlib import Path
import sys
out = Path(sys.argv[1])
with gzip.open('validation/exact-query-li-20261109/paired-initial/workload.sql.gz', 'rt') as source, (out / 'profile-load.sql').open('w') as load, (out / 'profile-query.sql').open('w') as query:
    counts = [0, 0]
    for line in source:
        index = int(line.startswith('SELECT'))
        (query if index else load).write(line)
        counts[index] += 1
print('load statements, query statements:', *counts)
PY
mkdir -p /dev/shm/mvdb-hmy-profile-db
/mnt/e/MiniVectorDB/build-release/minivectordb --dev-protocol --data-dir /dev/shm/mvdb-hmy-profile-db < "$run_dir/profile-load.sql" > "$run_dir/profile-load-output.jsonl"
cd "$run_dir"
GMON_OUT_PREFIX="$run_dir/gmon" /mnt/e/MiniVectorDB/build-profile/minivectordb --dev-protocol --data-dir /dev/shm/mvdb-hmy-profile-db < profile-query.sql > profile-query-output.jsonl
gprof /mnt/e/MiniVectorDB/build-profile/minivectordb gmon.* > gprof.txt
