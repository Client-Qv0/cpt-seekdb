#!/usr/bin/env bash
set -uo pipefail
out=/mnt/f/OceanBase/seekdb/cpt-seekdb/validation/l2-hmy-20261110/numpy-setup.txt
base=/mnt/e/MiniVectorDB/deps/hmy-l2-20261110
if test -e "$base" || test -e "$out"; then echo 'Refusing to overwrite setup' >&2; exit 1; fi
mkdir -p "$base/tmp" "$base/cache" "$base/pip" "$base/site"
export TMPDIR="$base/tmp" PIP_CACHE_DIR="$base/cache" PIP_DISABLE_PIP_VERSION_CHECK=1
{
  curl --fail --location --retry 2 --output "$base/get-pip.py" https://bootstrap.pypa.io/get-pip.py || exit 1
  sha256sum "$base/get-pip.py"
  python3 "$base/get-pip.py" --no-warn-script-location --target "$base/pip" || exit 1
  PYTHONPATH="$base/pip" python3 -m pip install --no-warn-script-location --target "$base/site" 'numpy==2.3.3' || exit 1
  PYTHONPATH="$base/site" python3 -c 'import numpy; print("numpy", numpy.__version__, numpy.__file__)'
} > "$out" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out"
exit "$status"
