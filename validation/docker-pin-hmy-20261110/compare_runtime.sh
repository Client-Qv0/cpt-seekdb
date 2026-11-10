#!/usr/bin/env bash
set -uo pipefail
out=/mnt/f/OceanBase/seekdb/cpt-seekdb/validation/docker-pin-hmy-20261110
if test -e "$out/runtime-comparison.txt"; then echo 'Refusing to overwrite runtime evidence' >&2; exit 1; fi
for label in baseline candidate-a; do
  case "$label" in
    baseline) image=codex-hmy-l2-baseline:20261110;;
    candidate-a) image=codex-hmy-pinned-candidate-a:20261110;;
  esac
  docker run --rm --network none --read-only --entrypoint /bin/sh "$image" -c \
    'dpkg-query -W; sha256sum /lib/x86_64-linux-gnu/libc.so.6 /lib/x86_64-linux-gnu/libm.so.6 /lib/x86_64-linux-gnu/libstdc++.so.6 /lib/x86_64-linux-gnu/libgcc_s.so.1' \
    > "$out/$label-runtime-manifest.txt" 2>&1 || exit 1
done
diff -u "$out/baseline-runtime-manifest.txt" "$out/candidate-a-runtime-manifest.txt" > "$out/runtime-comparison.txt"
status=$?
printf 'exit=%s\n' "$status" >> "$out/runtime-comparison.txt"
exit "$status"
