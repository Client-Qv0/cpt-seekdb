#!/usr/bin/env python3
"""Record final local structural checks without overwriting earlier evidence."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
out = Path(__file__).resolve().parent
target = out / "final-check.json"
if target.exists():
    raise SystemExit("refusing to overwrite final checks")
agent = root / "agent/conversation.json"
dockerfile = root / "Dockerfile"
candidate = out / "Dockerfile.candidate"
if dockerfile.read_bytes() != candidate.read_bytes():
    raise SystemExit("repository Dockerfile differs from tested candidate")
if len(agent.read_bytes()) > 128 * 1024:
    raise SystemExit("learning material exceeds 128 KiB")
process = subprocess.run(["python3", str(root / "tests/test_agent_material.py"), "-v"],
                         text=True, capture_output=True)
if process.returncode:
    raise SystemExit(process.stderr)
for path in list(out.glob("*.py")) + [root / "tests/test_container_recovery.py"]:
    ast.parse(path.read_text())
for path in out.glob("*.sh"):
    subprocess.run(["bash", "-n", str(path)], check=True)
official = json.loads((out / "production-official-all/result.json").read_text())
if not official.get("passed") or len(official["cases"]) != 20:
    raise SystemExit("official public result missing or unexpected")
recovery = json.loads((out / "production-recovery/result.json").read_text())
if (recovery["status"], recovery["acknowledged_batches"], recovery["readback_rows"],
    recovery["checked_fp32_components"], recovery["uncommitted_changes_rolled_back"]) != ("PASS", 100, 10000, 1280000, True):
    raise SystemExit("production recovery evidence missing or unexpected")
raw = json.loads((out / "raw-evidence-manifest.json").read_text())
if len(raw["pairs"]) != 12:
    raise SystemExit("missing benchmark input comparisons")
result = {
    "status": "PASS",
    "dockerfile_sha256": hashlib.sha256(dockerfile.read_bytes()).hexdigest(),
    "agent_sha256": hashlib.sha256(agent.read_bytes()).hexdigest(),
    "agent_bytes": len(agent.read_bytes()),
    "agent_test_exit": process.returncode,
    "agent_test_output": process.stdout + process.stderr,
    "official_public_cases": len(official["cases"]),
    "recovery_batches": recovery["acknowledged_batches"],
    "recovery_rows": recovery["readback_rows"],
    "recovery_fp32_components": recovery["checked_fp32_components"],
    "paired_inputs_checked": len(raw["pairs"]),
    "scope": "local structural and recorded-result checks, not an official score",
}
target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({k: v for k, v in result.items() if k != "agent_test_output"}, indent=2))
