#!/usr/bin/env python3
"""Retrieve only the public protocol files at a fixed Git tree, verifying blob IDs."""
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

COMMIT = "f4d4e26653af823a7601668802f80e374ad6643c"
API = "https://api.github.com/repos/oceanbase/seekdb"
DEST = Path("/mnt/e/MiniVectorDB/official-hmy-l2-tree-20261110")
LOG = Path(__file__).with_name("official-tree-manifest.json")


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "MiniVectorDB-validation"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def tree(sha, recursive=False):
    suffix = "?recursive=1" if recursive else ""
    data = json.loads(fetch(f"{API}/git/trees/{sha}{suffix}"))
    if data.get("truncated"):
        raise RuntimeError("GitHub tree response truncated")
    return data["tree"]


def main():
    if DEST.exists() or LOG.exists():
        raise RuntimeError("Refusing to overwrite source files or manifest")
    commit = json.loads(fetch(f"{API}/git/commits/{COMMIT}"))
    if commit["sha"] != COMMIT:
        raise RuntimeError("commit mismatch")
    root = tree(commit["tree"]["sha"])
    selected = []
    for entry in root:
        if entry["path"] in {"protocol_check", "mysqltest"} and entry["type"] == "tree":
            for child in tree(entry["sha"], recursive=True):
                if child["type"] == "blob":
                    selected.append((entry["path"] + "/" + child["path"], child["sha"]))
        elif entry["path"] == "STDIO_PROTOCOL.md" and entry["type"] == "blob":
            selected.append((entry["path"], entry["sha"]))
    if not any(p.startswith("protocol_check/") for p, _ in selected):
        raise RuntimeError("protocol_check missing")
    if not any(p.startswith("mysqltest/") for p, _ in selected):
        raise RuntimeError("mysqltest missing")
    if not any(p == "STDIO_PROTOCOL.md" for p, _ in selected):
        raise RuntimeError("STDIO_PROTOCOL.md missing")
    DEST.mkdir(parents=True)
    items = []
    for path, sha in selected:
        url = f"https://raw.githubusercontent.com/oceanbase/seekdb/{COMMIT}/" + urllib.parse.quote(path)
        data = fetch(url)
        actual = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if actual != sha:
            raise RuntimeError(f"Git blob mismatch: {path}")
        target = DEST / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        items.append({"path": path, "git_blob_sha1": sha, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    LOG.write_text(json.dumps({"commit": COMMIT, "tree": commit["tree"]["sha"], "files": items}, indent=2) + "\n")
    print(f"verified {len(items)} Git blobs from commit {COMMIT}")


if __name__ == "__main__":
    main()
