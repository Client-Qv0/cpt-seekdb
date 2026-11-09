#!/usr/bin/env python3
"""Bidirectional WAL/checkpoint compatibility, with full small-data reference.

Local correctness test only. No measured throughput or official assessment.
"""
import argparse
import hashlib
import json
from pathlib import Path
import select
import subprocess
import tempfile


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Database:
    def __init__(self, binary, directory):
        self.p = subprocess.Popen([str(binary), "--data-dir", str(directory),
                                   "--dev-protocol"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, bufsize=1)

    def query(self, sql, success=True):
        self.p.stdin.write(sql + "\n")
        self.p.stdin.flush()
        if not select.select([self.p.stdout], [], [], 15)[0]:
            raise TimeoutError("Compatibility SQL timeout")
        response = json.loads(self.p.stdout.readline())
        assert response.get("ok") is success, (sql, response)
        return response

    def close(self, kill=False):
        if kill:
            self.p.kill()
        else:
            self.p.stdin.close()
        code = self.p.wait(timeout=15)
        assert code == (-9 if kill else 0), self.p.stderr.read()


def direction(first, second, helper):
    with tempfile.TemporaryDirectory(prefix="mvdb-compatibility-") as directory:
        db = Database(first, directory)
        db.query("CREATE TABLE items (id BIGINT PRIMARY KEY,x BIGINT,v VECTOR(4));")
        expected = {}
        for start in range(0, 1000, 100):
            values = []
            for key in range(start, start + 100):
                vector = [key % 31, key % 17, key % 7, key % 3]
                expected[key] = [key, key % 97, vector]
                values.append(f"({key},{key % 97},'{json.dumps(vector)}')")
            db.query("INSERT INTO items VALUES " + ",".join(values) + ";")
        db.query("BEGIN;")
        db.query("UPDATE items SET x=777 WHERE id<100;")
        db.close(kill=True)

        db = Database(second, directory)
        assert db.query("SELECT id,x,v FROM items ORDER BY id;")["rows"] == list(expected.values())
        db.query("BEGIN;")
        db.query("UPDATE items SET x=888 WHERE id<100;")
        db.query("INSERT INTO items VALUES (2000,1,'[1,2,3,4]'),(7,1,'[1,2,3,4]');", success=False)
        db.query("DELETE FROM items WHERE id=7;")
        db.query("COMMIT;")
        for key in range(100):
            expected[key][1] = 888
        del expected[7]
        assert db.query("SELECT id FROM items WHERE id=2000;")["rows"] == []
        assert db.query("SELECT id,x,v FROM items ORDER BY id;")["rows"] == list(expected.values())
        db.close()

        checkpoint = subprocess.run([str(helper), "--data-dir", directory],
                                    input="READY\nCHECKPOINT\n", text=True,
                                    capture_output=True, timeout=30, check=True)
        assert [json.loads(line)["phase"] for line in checkpoint.stdout.splitlines()] == ["recovered", "checkpoint_complete"]
        db = Database(first, directory)
        actual = db.query("SELECT id,x,v FROM items ORDER BY id;")["rows"]
        assert actual == list(expected.values())
        db.close()
        return {"passed": True, "all_rows_before_mutation_verified": 1000,
                "all_rows_after_mutation_and_checkpoint_verified": len(actual),
                "uncommitted_sigkill_rollback": True,
                "failed_multivalue_statement_rollback_inside_commit": True,
                "checkpoint_helper_stdout": checkpoint.stdout}


def main():
    parser = argparse.ArgumentParser()
    for name in ("baseline", "candidate", "baseline-helper", "candidate-helper", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    paths = {key: value.resolve() for key, value in vars(args).items() if key != "output"}
    report = {"tool_sha256": sha(__file__), "binaries": {key: {"path": str(value), "sha256": sha(value)} for key, value in paths.items()},
              "official_assessment": False, "directions": {}}
    report["directions"]["baseline_to_candidate_checkpoint_to_baseline"] = direction(paths["baseline"], paths["candidate"], paths["candidate_helper"])
    report["directions"]["candidate_to_baseline_checkpoint_to_candidate"] = direction(paths["candidate"], paths["baseline"], paths["baseline_helper"])
    report["passed"] = True
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print("Both directions passed: full rows/vectors, statement/transaction rollback, SIGKILL and checkpoint")


if __name__ == "__main__":
    main()
