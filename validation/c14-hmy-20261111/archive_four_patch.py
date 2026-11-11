#!/usr/bin/env python3
"""Record only the four-row experiment relative to the verified C14 snapshot."""
import difflib
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[1]
original = out / "teammate-handoff/changes"
target = out / "four-experiment.patch"
if target.exists():
    raise SystemExit("refusing to overwrite prior experiment")
parts = []
for name in ("src/engine.cpp", "src/exact_cache.hpp", "tests/test_exact_cache.cpp"):
    before = (original / name).read_text().splitlines(keepends=True)
    after = (root / name).read_text().splitlines(keepends=True)
    parts.extend(difflib.unified_diff(before, after, fromfile="a/" + name, tofile="b/" + name))
if not parts:
    raise SystemExit("no experimental changes found")
target.write_text("".join(parts))
print(target)
