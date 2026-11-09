#!/usr/bin/env bash
# Verify that the new regression fails on the unchanged V2 control binary.
set -uo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
out=validation/parser-safety-hmy-20261109
binary=${BINARY:-"$root/build-hmy-f/minivectordb"}
if test -e "$out/baseline-test.txt"; then echo 'Baseline evidence already exists.' >&2; exit 1; fi
sha256sum "$binary" > "$out/baseline-binary.sha256"
python3 tests/acceptance.py --binary "$binary" -v Acceptance.test_20_double_dash_without_space_cannot_silently_mutate > "$out/baseline-test.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/baseline-test.txt"
cat "$out/baseline-test.txt"
if test "$status" -eq 0; then echo 'Unexpected: baseline regression passed.' >&2; exit 1; fi
