#!/usr/bin/env python3
"""Independent, local black-box checks for MiniVectorDB.

This uses the deliberately provisional --dev-protocol JSON-lines adapter.
It is NOT the organizer's mysqltest driver, protocol, or official acceptance suite.
Expected results come from the published SQL/transaction semantics and a small
Python reference model; they do not depend on the storage implementation.
"""

import argparse
import copy
import json
import math
import os
from pathlib import Path
import random
import select
import subprocess
import tempfile
import time
import unittest


BINARY = None
STRESS = False


def sql_string(value):
    return "'" + value.replace("'", "''") + "'"


class Database:
    def __init__(self, directory, memory_limit=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.stderr = tempfile.TemporaryFile(mode="w+b")
        preexec = None
        if memory_limit is not None:
            import resource

            def set_limit():
                resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))

            preexec = set_limit
        self.proc = subprocess.Popen(
            [str(BINARY), "--data-dir", str(directory), "--dev-protocol"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            preexec_fn=preexec,
        )

    def diagnostics(self):
        self.stderr.seek(0)
        return self.stderr.read().decode("utf-8", errors="replace")[-5000:]

    def send(self, sql):
        if "\n" in sql:
            raise ValueError("The development adapter requires one SQL statement per line")
        try:
            self.proc.stdin.write((sql + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise AssertionError(f"Database exited while sending SQL: {self.diagnostics()}") from error

    def response(self, timeout=20):
        readable, _, _ = select.select([self.proc.stdout], [], [], timeout)
        if not readable:
            raise AssertionError(f"No response within {timeout}s: {self.diagnostics()}")
        line = self.proc.stdout.readline()
        if not line:
            raise AssertionError(f"Database closed stdout (exit={self.proc.poll()}): {self.diagnostics()}")
        try:
            result = json.loads(line)
        except (UnicodeError, ValueError) as error:
            raise AssertionError(f"Malformed development-protocol response: {line!r}") from error
        if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
            raise AssertionError(f"Missing boolean 'ok' in response: {result!r}")
        return result

    def execute(self, sql, timeout=20):
        self.send(sql)
        return self.response(timeout)

    def ok(self, sql, timeout=20):
        result = self.execute(sql, timeout)
        if not result["ok"]:
            raise AssertionError(f"SQL failed: {sql[:250]}\n{result!r}\n{self.diagnostics()}")
        return result

    def rows(self, sql):
        result = self.ok(sql)
        if not isinstance(result.get("rows"), list):
            raise AssertionError(f"Query has no result rows: {result!r}")
        return result["rows"]

    def close(self, kill=False):
        if self.proc.poll() is None:
            if kill:
                self.proc.kill()
            else:
                self.proc.stdin.close()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
                if not kill:
                    raise AssertionError("Database did not terminate after EOF")
        if self.proc.stdin and not self.proc.stdin.closed:
            self.proc.stdin.close()
        if self.proc.stdout:
            self.proc.stdout.close()
        if not self.stderr.closed:
            self.stderr.close()


class Acceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mvdb-acceptance-")
        self.path = Path(self.tmp.name) / "data"
        self.db = Database(self.path)

    def tearDown(self):
        self.db.close(kill=True)
        self.tmp.cleanup()

    def restart(self, kill=False):
        self.db.close(kill=kill)
        self.db = Database(self.path)

    def fails(self, sql):
        result = self.db.execute(sql)
        self.assertFalse(result["ok"], f"Unsupported/invalid SQL unexpectedly succeeded: {sql}")
        self.assertIsInstance(result.get("code"), str)
        self.assertTrue(result.get("code"), result)

    def docs(self):
        self.db.ok("CREATE TABLE docs (id BIGINT PRIMARY KEY, category VARCHAR(32), content VARCHAR(1024), embedding VECTOR(4));")
        self.db.ok("INSERT INTO docs VALUES (1,'database','事务与恢复','[1,0,0,0]'),(2,'database','向量索引','[0,1,0,0]'),(3,'travel','旅行攻略','[0,0,1,0]');")

    def test_01_published_example_and_rollback(self):
        self.docs()
        query = "SELECT id,content,L2_DISTANCE(embedding,'[0.9,0.1,0,0]') AS distance FROM docs WHERE category='database' ORDER BY distance LIMIT 2;"
        rows = self.db.rows(query)
        self.assertEqual([r[:2] for r in rows], [[1, "事务与恢复"], [2, "向量索引"]])
        self.assertAlmostEqual(rows[0][2], math.sqrt(0.02), places=6)
        self.assertAlmostEqual(rows[1][2], math.sqrt(1.62), places=6)
        self.db.ok("BEGIN;")
        self.db.ok("UPDATE docs SET embedding='[0.8,0.2,0,0]' WHERE id=1;")
        self.db.ok("DELETE FROM docs WHERE id=2;")
        self.assertEqual([r[0] for r in self.db.rows(query)], [1])
        self.db.ok("ROLLBACK;")
        self.assertEqual(self.db.rows(query), rows)

    def test_02_bigint_precision_and_bounds(self):
        self.db.ok("CREATE TABLE integers (id BIGINT PRIMARY KEY, n BIGINT);")
        values = [-9223372036854775808, -9007199254740993, 9007199254740992, 9007199254740993, 9223372036854775807]
        self.db.ok("INSERT INTO integers VALUES " + ",".join(f"({v},{v})" for v in values) + ";")
        self.assertEqual(self.db.rows("SELECT id,n FROM integers ORDER BY n;"), [[v, v] for v in values])
        self.fails("INSERT INTO integers VALUES (9223372036854775808,0);")
        self.fails("INSERT INTO integers VALUES (-9223372036854775809,0);")
        self.fails("UPDATE integers SET n=9223372036854775808 WHERE id=9007199254740992;")
        self.assertEqual(self.db.rows("SELECT id,n FROM integers WHERE id=9007199254740992;"), [[9007199254740992, 9007199254740992]])
        self.restart()
        self.assertEqual(self.db.rows("SELECT n FROM integers ORDER BY id;"), [[v] for v in values])

    def test_03_unicode_length_and_codepoint_order(self):
        self.db.ok("CREATE TABLE unicode_text (id BIGINT PRIMARY KEY, value VARCHAR(1));")
        self.db.ok("INSERT INTO unicode_text VALUES (1,'😀'),(2,'中'),(3,'A'),(4,'\ue000');")
        self.assertEqual(self.db.rows("SELECT id,value FROM unicode_text ORDER BY value;"), [[3, "A"], [2, "中"], [4, "\ue000"], [1, "😀"]])
        self.fails("INSERT INTO unicode_text VALUES (5,'中文');")
        self.fails("INSERT INTO unicode_text VALUES (5,'e\u0301');")
        self.db.ok("INSERT INTO unicode_text VALUES (5,'');")
        self.assertEqual(self.db.rows("SELECT id FROM unicode_text WHERE value>='中' ORDER BY value;"), [[2], [4], [1]])
        self.db.ok("INSERT INTO unicode_text VALUES (6,'a');")
        # A comparison literal is not stored in the VARCHAR column. Its length
        # must not be rejected using the column's storage length constraint.
        self.assertEqual(self.db.rows("SELECT id FROM unicode_text WHERE value<'zz' ORDER BY id;"), [[3], [5], [6]])
        self.assertEqual(self.db.rows("SELECT id FROM unicode_text WHERE value='zz';"), [])

    def test_04_literals_comments_and_case(self):
        self.db.ok("CrEaTe TaBlE Quotes (ID BIGINT PRIMARY KEY, txt VARCHAR(100));")
        self.db.ok("INSERT INTO quotes (txt,id) VALUES ('it''s; not SQL -- text',1);")
        self.assertEqual(self.db.rows("/* leading */ SELECT txt FROM quotes WHERE id=1; -- trailing"), [["it's; not SQL -- text"]])
        self.fails("SELECT txt FROM quotes; DELETE FROM quotes;")
        self.assertEqual(self.db.rows("SELECT id FROM quotes;"), [[1]])

    def test_05_vectors_use_stored_float32_and_euclidean_distance(self):
        self.db.ok("CREATE TABLE vectors (id BIGINT PRIMARY KEY, v VECTOR(2));")
        self.db.ok("INSERT INTO vectors VALUES (1,'[16777217,0]'),(2,'[3,4]');")
        self.assertEqual(self.db.rows("SELECT L2_DISTANCE(v,'[16777216,0]') AS d FROM vectors WHERE id=1;"), [[0]])
        self.assertAlmostEqual(self.db.rows("SELECT L2_DISTANCE(v,'[0,0]') AS d FROM vectors WHERE id=2;")[0][0], 5.0)
        for literal in ("[1]", "[1,2,3]", "[NaN,0]", "[Infinity,0]", "[-Infinity,0]", "[1e40,0]", "[1e400,0]", "[1,]", "[1x,2]"):
            self.fails("INSERT INTO vectors VALUES (3," + sql_string(literal) + ");")
        self.fails("SELECT L2_DISTANCE(v,'[0]') AS d FROM vectors;")
        self.assertEqual(self.db.rows("SELECT id FROM vectors ORDER BY id;"), [[1], [2]])

    def test_06_filter_before_topk_and_tie_by_primary_key(self):
        self.db.ok("CREATE TABLE points (id BIGINT PRIMARY KEY, kind BIGINT, v VECTOR(2));")
        self.db.ok("INSERT INTO points VALUES (1,0,'[0,0]'),(5,1,'[5,0]'),(2,1,'[-5,0]'),(4,1,'[0,6]'),(3,0,'[0,1]');")
        query = "SELECT id,L2_DISTANCE(v,'[0,0]') AS d FROM points WHERE kind=1 ORDER BY d LIMIT 2;"
        self.assertEqual(self.db.rows(query), [[2, 5], [5, 5]])
        self.assertEqual(self.db.rows("SELECT id FROM points WHERE kind=9 ORDER BY id LIMIT 10;"), [])
        self.assertEqual(self.db.rows("SELECT id,L2_DISTANCE(v,'[0,0]') AS d FROM points WHERE kind=1 ORDER BY d LIMIT 10;"), [[2, 5], [5, 5], [4, 6]])
        self.assertEqual(self.db.rows("SELECT id,L2_DISTANCE(v,'[0,0]') AS d FROM points WHERE kind=1 ORDER BY d DESC LIMIT 3;"), [[4, 6], [2, 5], [5, 5]])
        self.assertEqual(self.db.rows("SELECT id FROM points ORDER BY kind LIMIT 0;"), [])

    def test_07_scalar_conditions_projection_and_sort(self):
        self.db.ok("CREATE TABLE scalars (id BIGINT PRIMARY KEY, n BIGINT, name VARCHAR(10));")
        self.db.ok("INSERT INTO scalars VALUES (4,8,'c'),(2,8,'b'),(1,3,'a'),(3,9,'a');")
        self.assertEqual(self.db.rows("SELECT name,id FROM scalars WHERE n>=8 AND n<10 AND name<='b' ORDER BY n DESC LIMIT 3;"), [["a", 3], ["b", 2]])
        self.assertEqual(self.db.rows("SELECT id FROM scalars ORDER BY n;"), [[1], [2], [4], [3]])
        self.assertEqual(self.db.rows("SELECT id FROM scalars WHERE n>3 AND n<=8 ORDER BY id;"), [[2], [4]])
        self.assertEqual(self.db.rows("SELECT * FROM scalars WHERE id=1;"), [[1, 3, "a"]])

    def test_08_invalid_schema_does_not_leave_partial_table(self):
        for ddl in (
            "CREATE TABLE bad (id BIGINT);",
            "CREATE TABLE bad (id VARCHAR(5) PRIMARY KEY);",
            "CREATE TABLE bad (id BIGINT PRIMARY KEY, v VECTOR(2), w VECTOR(2));",
            "CREATE TABLE bad (id BIGINT PRIMARY KEY, id BIGINT);",
            "CREATE TABLE bad (id BIGINT PRIMARY KEY, other BIGINT PRIMARY KEY);",
            "CREATE TABLE bad (id BIGINT PRIMARY KEY, v VECTOR(0));",
        ):
            self.fails(ddl)
        self.db.ok("CREATE TABLE bad (id BIGINT PRIMARY KEY);")
        self.db.ok("INSERT INTO bad VALUES (1);")
        self.assertEqual(self.db.rows("SELECT * FROM bad;"), [[1]])

    def test_09_autocommit_statement_atomicity(self):
        self.db.ok("CREATE TABLE atomic_rows (id BIGINT PRIMARY KEY, n BIGINT);")
        self.db.ok("INSERT INTO atomic_rows VALUES (1,10);")
        self.fails("INSERT INTO atomic_rows VALUES (2,20),(1,99),(3,30);")
        self.fails("INSERT INTO atomic_rows VALUES (4,40),(4,41);")
        self.assertEqual(self.db.rows("SELECT * FROM atomic_rows ORDER BY id;"), [[1, 10]])
        self.restart(kill=True)
        self.assertEqual(self.db.rows("SELECT * FROM atomic_rows ORDER BY id;"), [[1, 10]])

    def test_10_failed_statement_preserves_prior_transaction_work(self):
        self.db.ok("CREATE TABLE tx (id BIGINT PRIMARY KEY, name VARCHAR(5), v VECTOR(1));")
        self.db.ok("INSERT INTO tx VALUES (1,'old','[1]');")
        self.db.ok("BEGIN;")
        self.db.ok("INSERT INTO tx VALUES (2,'new','[2]');")
        self.fails("INSERT INTO tx VALUES (3,'three','[3]'),(1,'dupe','[4]');")
        self.fails("UPDATE tx SET name='too-long' WHERE id>=1;")
        self.fails("UPDATE tx SET id=9 WHERE id=1;")
        self.assertEqual(self.db.rows("SELECT id,name FROM tx ORDER BY id;"), [[1, "old"], [2, "new"]])
        self.db.ok("COMMIT;")
        self.restart(kill=True)
        self.assertEqual(self.db.rows("SELECT id,name FROM tx ORDER BY id;"), [[1, "old"], [2, "new"]])

    def test_11_vector_updates_deletes_and_rollback(self):
        self.db.ok("CREATE TABLE items (id BIGINT PRIMARY KEY, v VECTOR(1));")
        self.db.ok("INSERT INTO items VALUES (10,'[10]'),(20,'[20]'),(30,'[30]');")
        q = "SELECT id,L2_DISTANCE(v,'[0]') AS d FROM items ORDER BY d LIMIT 2;"
        original = self.db.rows(q)
        self.db.ok("BEGIN;")
        self.db.ok("UPDATE items SET v='[1]' WHERE id=30;")
        self.db.ok("DELETE FROM items WHERE id=10;")
        self.assertEqual(self.db.rows(q), [[30, 1], [20, 20]])
        self.db.ok("ROLLBACK;")
        self.assertEqual(self.db.rows(q), original)
        self.db.ok("BEGIN;")
        self.db.ok("UPDATE items SET v='[1]' WHERE id=30;")
        self.db.ok("DELETE FROM items WHERE id=10;")
        self.db.ok("COMMIT;")
        self.restart(kill=True)
        self.assertEqual(self.db.rows(q), [[30, 1], [20, 20]])

    def test_12_eof_rolls_back_uncommitted_rows(self):
        self.db.ok("CREATE TABLE shutdown (id BIGINT PRIMARY KEY, value BIGINT);")
        self.db.ok("INSERT INTO shutdown VALUES (1,10);")
        self.db.ok("BEGIN;")
        self.db.ok("UPDATE shutdown SET value=20 WHERE id=1;")
        self.db.ok("INSERT INTO shutdown VALUES (2,30);")
        self.restart()
        self.assertEqual(self.db.rows("SELECT * FROM shutdown ORDER BY id;"), [[1, 10]])

    def test_13_sigkill_rolls_back_uncommitted_and_keeps_acknowledged(self):
        self.db.ok("CREATE TABLE crash_rows (id BIGINT PRIMARY KEY, value BIGINT);")
        self.db.ok("BEGIN;")
        self.db.ok("INSERT INTO crash_rows VALUES (1,10),(2,20);")
        self.db.ok("COMMIT;")
        self.db.ok("BEGIN;")
        self.db.ok("UPDATE crash_rows SET value=99 WHERE id=1;")
        self.db.ok("DELETE FROM crash_rows WHERE id=2;")
        self.db.ok("INSERT INTO crash_rows VALUES (3,30);")
        self.restart(kill=True)
        self.assertEqual(self.db.rows("SELECT * FROM crash_rows ORDER BY id;"), [[1, 10], [2, 20]])
        self.db.ok("INSERT INTO crash_rows VALUES (3,30);")
        self.restart(kill=True)
        self.assertEqual(self.db.rows("SELECT * FROM crash_rows ORDER BY id;"), [[1, 10], [2, 20], [3, 30]])

    def test_14_commit_with_lost_response_is_all_or_nothing(self):
        self.db.ok("CREATE TABLE uncertain (id BIGINT PRIMARY KEY, value BIGINT);")
        expected = [[i, i * 7] for i in range(200)]
        self.db.ok("BEGIN;")
        self.db.ok("INSERT INTO uncertain VALUES " + ",".join(f"({i},{i * 7})" for i in range(200)) + ";")
        self.db.send("COMMIT;")
        self.restart(kill=True)
        actual = self.db.rows("SELECT * FROM uncertain ORDER BY id;")
        self.assertIn(actual, [[], expected], "An unacknowledged commit must never become partially visible")

    def test_15_repeated_startup_termination_preserves_committed_state(self):
        self.db.ok("CREATE TABLE restart_rows (id BIGINT PRIMARY KEY, value BIGINT);")
        for start in range(0, 1000, 100):
            self.db.ok("INSERT INTO restart_rows VALUES " + ",".join(f"({i},{i * 3})" for i in range(start, start + 100)) + ";")
        self.db.close(kill=True)
        # These kills exercise repeated startup interruption. Without an internal
        # recovery hook we do not claim that every kill lands inside WAL replay.
        for delay in (0, 0.001, 0.002, 0.004):
            self.db = Database(self.path)
            time.sleep(delay)
            self.db.close(kill=True)
        self.db = Database(self.path)
        self.assertEqual(self.db.rows("SELECT * FROM restart_rows ORDER BY id;"), [[i, i * 3] for i in range(1000)])

    def test_16_create_index_and_subsequent_exact_mutations(self):
        self.docs()
        before = self.db.rows("SELECT id,L2_DISTANCE(embedding,'[1,0,0,0]') AS d FROM docs ORDER BY d LIMIT 3;")
        self.db.ok("CREATE VECTOR INDEX docs_embedding ON docs(embedding);")
        self.assertEqual(self.db.rows("SELECT id,L2_DISTANCE(embedding,'[1,0,0,0]') AS d FROM docs ORDER BY d LIMIT 3;"), before)
        self.db.ok("UPDATE docs SET embedding='[1,0,0,0]' WHERE id=3;")
        self.db.ok("DELETE FROM docs WHERE id=1;")
        self.db.ok("INSERT INTO docs VALUES (4,'database','added','[0.5,0,0,0]');")
        q = "SELECT id,L2_DISTANCE(embedding,'[1,0,0,0]') AS d FROM docs ORDER BY d LIMIT 2;"
        self.assertEqual(self.db.rows(q), [[3, 0], [4, 0.5]])
        self.restart(kill=True)
        self.assertEqual(self.db.rows(q), [[3, 0], [4, 0.5]])

    def test_17_rejected_sql_never_silently_changes_data(self):
        self.db.ok("CREATE TABLE safe (id BIGINT PRIMARY KEY, n BIGINT);")
        self.db.ok("INSERT INTO safe VALUES (1,1);")
        for sql in (
            "INSERT INTO safe VALUES (2,NULL);",
            "SELECT SUM(n) FROM safe;",
            "SELECT a.id FROM safe a JOIN safe b ON a.id=b.id;",
            "UPDATE safe SET n=n+1 WHERE id=1;",
            "ALTER TABLE safe ADD x BIGINT;",
            "DELETE FROM safe WHERE id=1 OR id=2;",
            "SELECT id FROM safe LIMIT -1;",
            "SELECT missing FROM safe;",
            "SELECT id FROM safe WHERE missing=2;",
        ):
            self.fails(sql)
            self.assertEqual(self.db.rows("SELECT * FROM safe;"), [[1, 1]])
        self.db.ok("BEGIN;")
        self.db.ok("INSERT INTO safe VALUES (2,2);")
        self.fails("BEGIN;")
        self.db.ok("ROLLBACK;")
        self.assertEqual(self.db.rows("SELECT * FROM safe;"), [[1, 1]])

    def test_18_randomized_transaction_reference_model(self):
        self.db.ok("CREATE TABLE model (id BIGINT PRIMARY KEY, n BIGINT, v VECTOR(2));")
        rng = random.Random(7112026)
        model = {}
        saved = None
        for step in range(140):
            op = rng.choice(["insert", "update", "delete", "begin", "finish", "restart"])
            if op == "begin" and saved is None:
                self.db.ok("BEGIN;")
                saved = copy.deepcopy(model)
            elif op == "finish" and saved is not None:
                if rng.randrange(2):
                    self.db.ok("COMMIT;")
                else:
                    self.db.ok("ROLLBACK;")
                    model = saved
                saved = None
            elif op == "restart":
                self.restart(kill=bool(rng.randrange(2)))
                if saved is not None:
                    model = saved
                    saved = None
            elif op == "insert":
                key = rng.randrange(12)
                value = rng.randrange(-10, 11)
                sql = f"INSERT INTO model VALUES ({key},{value},'[{value},{key}]');"
                if key in model:
                    self.fails(sql)
                else:
                    self.db.ok(sql)
                    model[key] = [value, [value, key]]
            elif op == "update":
                threshold = rng.randrange(12)
                value = rng.randrange(-10, 11)
                self.db.ok(f"UPDATE model SET n={value},v='[{value},0]' WHERE id>={threshold};")
                for key in model:
                    if key >= threshold:
                        model[key] = [value, [value, 0]]
            elif op == "delete":
                threshold = rng.randrange(12)
                self.db.ok(f"DELETE FROM model WHERE id<{threshold};")
                model = {key: value for key, value in model.items() if key >= threshold}
            self.assertEqual(self.db.rows("SELECT id,n FROM model ORDER BY id;"), [[key, model[key][0]] for key in sorted(model)], f"reference-model step {step}")
            expected = sorted(((math.hypot(*value[1]), key) for key, value in model.items() if value[0] >= 0))[:4]
            actual = self.db.rows("SELECT id,L2_DISTANCE(v,'[0,0]') AS d FROM model WHERE n>=0 ORDER BY d LIMIT 4;")
            self.assertEqual([row[0] for row in actual], [key for _, key in expected], f"vector reference step {step}")
            for row, (distance, _) in zip(actual, expected):
                self.assertAlmostEqual(row[1], distance, places=6)

    @unittest.skipUnless(os.name == "posix", "Memory limits require Linux/POSIX")
    def test_19_disk_data_larger_than_address_space(self):
        if not STRESS:
            self.skipTest("Enable --stress for >memory data test")
        self.db.close(kill=True)
        limit = 128 * 1024 * 1024
        self.db = Database(self.path, memory_limit=limit)
        self.db.ok("CREATE TABLE large_rows (id BIGINT PRIMARY KEY, payload VARCHAR(20000));")
        payload = "x" * 20000
        for batch in range(96):
            values = ",".join(f"({batch * 100 + i},'{payload}')" for i in range(100))
            self.db.ok("INSERT INTO large_rows VALUES " + values + ";", timeout=60)
        self.db.close(kill=True)
        self.db = Database(self.path, memory_limit=limit)
        self.assertEqual(self.db.rows("SELECT id FROM large_rows WHERE id>=9590 ORDER BY id;"), [[i] for i in range(9590, 9600)])
        self.assertEqual(self.db.rows("SELECT payload FROM large_rows WHERE id=0;"), [[payload]])


def main():
    global BINARY, STRESS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--stress", action="store_true", help="Also store 192 MB under a 128 MiB address-space limit")
    args, unittest_args = parser.parse_known_args()
    BINARY = args.binary.resolve()
    STRESS = args.stress
    if not BINARY.is_file():
        parser.error(f"Executable does not exist: {BINARY}")
    unittest.main(argv=[__file__] + unittest_args)


if __name__ == "__main__":
    main()
