#!/usr/bin/env bash
set -uo pipefail
out=/mnt/f/OceanBase/seekdb/cpt-seekdb/validation/docker-pin-hmy-20261110
if test -e "$out/runtime-b-comparison.txt"; then echo 'Refusing to overwrite runtime evidence' >&2; exit 1; fi
docker run --rm --network none --read-only --entrypoint /bin/sh codex-hmy-pinned-candidate-b:20261110 -c \
  'dpkg-query -W; sha256sum /lib/x86_64-linux-gnu/libc.so.6 /lib/x86_64-linux-gnu/libm.so.6 /lib/x86_64-linux-gnu/libstdc++.so.6 /lib/x86_64-linux-gnu/libgcc_s.so.1' \
  > "$out/candidate-b-runtime-manifest.txt" 2>&1 || exit 1
diff -u "$out/baseline-runtime-manifest.txt" "$out/candidate-b-runtime-manifest.txt" > "$out/runtime-b-comparison.txt"
status=$?
printf 'exit=%s\n' "$status" >> "$out/runtime-b-comparison.txt"
exit "$status"
