#!/usr/bin/env python3
"""Independent regression checks for caching, indexed access, and disk spilling.

Uses the local --dev-protocol only. This is not the official assessment suite.
Run --large in Linux to test responses larger than the database memory budget.
The driver streams each result row from a file rather than loading the response.
"""

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import struct
import subprocess
import tempfile
import unittest

import acceptance as core


LARGE = False
MEMORY_LIMIT = 128 * 1024 * 1024


class JsonStream:
    """Small incremental JSON reader. The largest decoded value is one row."""

    def __init__(self, source):
        self.source = source
        self.buffer = ""
        self.pos = 0
        self.eof = False
        self.decoder = json.JSONDecoder()

    def more(self):
        if self.eof:
            return False
        self.buffer = self.buffer[self.pos:]
        self.pos = 0
        chunk = self.source.read(65536)
        if not chunk:
            self.eof = True
            return False
        self.buffer += chunk
        if len(self.buffer) > 4 * 1024 * 1024:
            raise AssertionError("Individual JSON value exceeds test reader's 4 MiB bound")
        return True

    def peek(self):
        while True:
            while self.pos < len(self.buffer) and self.buffer[self.pos].isspace():
                self.pos += 1
            if self.pos < len(self.buffer):
                return self.buffer[self.pos]
            if not self.more():
                return ""

    def expect(self, expected):
        actual = self.peek()
        if actual != expected:
            raise AssertionError(f"Expected JSON delimiter {expected!r}; got {actual!r}")
        self.pos += 1

    def value(self):
        if not self.peek():
            raise AssertionError("Unexpected EOF before JSON value")
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer, self.pos)
            except json.JSONDecodeError as error:
                if not self.more():
                    raise AssertionError("Invalid/incomplete result JSON") from error
            else:
                # A numeric token at the buffer boundary may continue in the next
                # chunk. Quoted values/arrays/objects have explicit terminators.
                if end == len(self.buffer) and not self.eof and isinstance(value, (int, float)):
                    self.more()
                    continue
                self.pos = end
                return value

    def response(self, consume_row):
        self.expect("{")
        fields = {}
        seen = set()
        count = 0
        while self.peek() != "}":
            key = self.value()
            if not isinstance(key, str) or key in seen:
                raise AssertionError(f"Invalid or repeated JSON key: {key!r}")
            seen.add(key)
            self.expect(":")
            if key == "rows":
                self.expect("[")
                while self.peek() != "]":
                    row = self.value()
                    if not isinstance(row, list):
                        raise AssertionError(f"Expected row array, got {type(row).__name__}")
                    consume_row(count, row)
                    count += 1
                    if self.peek() != ",":
                        break
                    self.pos += 1
                    if self.peek() == "]":
                        raise AssertionError("Trailing comma in result rows")
                self.expect("]")
            else:
                fields[key] = self.value()
            if self.peek() != ",":
                break
            self.pos += 1
            if self.peek() == "}":
                raise AssertionError("Trailing comma in result object")
        self.expect("}")
        if self.peek():
            raise AssertionError("Unexpected extra stdout after result")
        if fields.get("ok") is not True or "rows" not in seen:
            raise AssertionError(f"SQL did not return a successful row result: {fields!r}")
        return fields, count


class StreamingReaderChecks(unittest.TestCase):
    def test_incremental_reader_checks_all_rows_and_suffix(self):
        import io
        data = {"ok": True, "columns": ["id", "payload"], "rows": [[i, "a\\\"中" * 15000] for i in range(3)], "affected": 0}
        observed = []
        fields, count = JsonStream(io.StringIO(json.dumps(data, ensure_ascii=False))).response(lambda index, row: observed.append((index, row)))
        self.assertEqual(count, 3)
        self.assertEqual([row for _, row in observed], data["rows"])
        self.assertEqual(fields["columns"], data["columns"])
        with self.assertRaises(AssertionError):
            JsonStream(io.StringIO('{"ok":true,"rows":[]}trailing')).response(lambda *_: None)
        with self.assertRaises(AssertionError):
            JsonStream(io.StringIO('{"ok":true,"rows":[[1]')).response(lambda *_: None)


class CacheAndIndexAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mvdb-opt-")
        self.db = core.Database(Path(self.tmp.name) / "data")

    def tearDown(self):
        self.db.close(kill=True)
        self.tmp.cleanup()

    def fails(self, sql):
        answer = self.db.execute(sql)
        self.assertFalse(answer["ok"], sql)

    def seed(self, table="items"):
        self.db.ok(f"CREATE TABLE {table} (id BIGINT PRIMARY KEY, bucket BIGINT, label VARCHAR(20), v VECTOR(2));")
        self.db.ok(f"INSERT INTO {table} VALUES (1,1,'one','[1,0]'),(2,1,'two','[2,0]'),(3,2,'three','[3,0]');")
        self.db.ok(f"CREATE VECTOR INDEX {table}_v ON {table}(v);")

    def query(self, table="items", where="", vector="[0,0]", limit=20):
        return self.db.rows(f"SELECT id,label,L2_DISTANCE(v,'{vector}') AS d FROM {table} {where} ORDER BY d LIMIT {limit};")

    def warm(self, table="items"):
        result = self.query(table)
        for _ in range(6):
            self.assertEqual(self.query(table), result)
        return result

    def test_hot_cache_insert_update_delete_commit_and_rollback(self):
        self.seed()
        original = self.warm()
        self.db.ok("INSERT INTO items VALUES (4,1,'four','[0.5,0]');")
        self.assertEqual([r[0] for r in self.warm()], [4, 1, 2, 3])
        self.db.ok("UPDATE items SET v='[0,0]',label='changed' WHERE id=3;")
        self.assertEqual(self.query()[0], [3, "changed", 0])
        self.db.ok("DELETE FROM items WHERE id=4;")
        stable = self.warm()
        self.db.ok("BEGIN;")
        self.db.ok("DELETE FROM items WHERE id=3;")
        self.db.ok("UPDATE items SET label='tx',v='[0,0]' WHERE id=2;")
        self.db.ok("INSERT INTO items VALUES (9,0,'tx-insert','[0.25,0]');")
        self.assertEqual([r[0] for r in self.warm()], [2, 9, 1])
        self.db.ok("ROLLBACK;")
        self.assertEqual(self.warm(), stable)
        self.db.ok("BEGIN;")
        self.db.ok("DELETE FROM items WHERE id=1;")
        self.db.ok("UPDATE items SET label='committed',v='[0.1,0]' WHERE id=2;")
        visible = self.warm()
        self.db.ok("COMMIT;")
        self.assertEqual(self.warm(), visible)
        self.assertNotEqual(visible, original)

    def test_failed_statement_does_not_leave_cache_ghosts(self):
        self.seed()
        stable = self.warm()
        self.fails("INSERT INTO items VALUES (8,8,'ghost','[0,0]'),(1,0,'duplicate','[0,0]');")
        self.assertEqual(self.warm(), stable)
        self.db.ok("BEGIN;")
        self.db.ok("UPDATE items SET bucket=9,v='[0,0]' WHERE id=2;")
        tx_visible = self.warm()
        self.fails("INSERT INTO items VALUES (8,8,'ghost','[0,0]'),(2,0,'duplicate','[0,0]');")
        self.fails("UPDATE items SET v='[1e40,0]' WHERE id>=1;")
        self.fails("UPDATE items SET label='this literal exceeds twenty characters' WHERE id>=1;")
        self.assertEqual(self.warm(), tx_visible)
        self.db.ok("COMMIT;")
        self.assertEqual(self.warm(), tx_visible)
        self.assertEqual([r[0] for r in self.query(where="WHERE bucket=9")], [2])

    def test_different_queries_filters_orders_and_tables_do_not_share_answers(self):
        self.seed("alpha")
        self.seed("beta")
        self.db.ok("UPDATE beta SET v='[20,0]',label='beta' WHERE id=1;")
        first = self.warm("alpha")
        second = self.warm("beta")
        self.assertNotEqual(first, second)
        for _ in range(8):
            self.assertEqual(self.query("alpha"), first)
            self.assertEqual(self.query("beta"), second)
            self.assertEqual([r[0] for r in self.query("alpha", "WHERE bucket=2")], [3])
            self.assertEqual([r[0] for r in self.query("beta", "WHERE bucket=1")], [2, 1])
            self.assertEqual([r[0] for r in self.query("alpha", vector="[3,0]", limit=1)], [3])
            self.assertEqual([r[0] for r in self.query("alpha", vector="[0,0]", limit=1)], [1])
            self.assertEqual(self.db.rows("SELECT label FROM alpha WHERE id=2;"), [["two"]])
            self.assertEqual(self.db.rows("SELECT id FROM alpha ORDER BY label DESC LIMIT 2;"), [[2], [3]])
        self.db.ok("BEGIN;")
        self.db.ok("UPDATE alpha SET label='new-alpha' WHERE id=1;")
        self.assertEqual(self.query("beta"), second)
        self.assertEqual(self.query("alpha")[0][1], "new-alpha")
        self.db.ok("ROLLBACK;")
        self.assertEqual(self.query("alpha"), first)
        self.assertEqual(self.query("beta"), second)

    def test_primary_key_fast_path_respects_all_predicates_and_transaction_overlay(self):
        self.seed()
        for where, expected in (
            ("id=2", [[2]]),
            ("bucket=2 AND id=2", []),
            ("id=2 AND id=3", []),
            ("id=2 AND id>2", []),
            ("id=2 AND id<=2 AND label<'zz'", [[2]]),
            ("id=9", []),
            ("id>=2 AND id<3", [[2]]),
        ):
            self.assertEqual(self.db.rows(f"SELECT id FROM items WHERE {where};"), expected)
        self.db.ok("BEGIN;")
        self.db.ok("DELETE FROM items WHERE id=2;")
        self.assertEqual(self.db.rows("SELECT label FROM items WHERE id=2;"), [])
        self.db.ok("INSERT INTO items VALUES (2,9,'replacement','[0,0]');")
        self.assertEqual(self.db.rows("SELECT label FROM items WHERE id=2;"), [["replacement"]])
        self.db.ok("ROLLBACK;")
        self.assertEqual(self.db.rows("SELECT label FROM items WHERE id=2;"), [["two"]])
        self.db.ok("INSERT INTO items VALUES (-9223372036854775808,0,'min','[0,0]'),(9223372036854775807,0,'max','[0,0]');")
        self.assertEqual(self.db.rows("SELECT label FROM items WHERE id=-9223372036854775808;"), [["min"]])
        self.assertEqual(self.db.rows("SELECT label FROM items WHERE id=9223372036854775807;"), [["max"]])

    def test_alias_projection_multi_key_sort_and_vector_ties(self):
        self.db.ok("CREATE TABLE ordering (id BIGINT PRIMARY KEY, a BIGINT, b VARCHAR(5), v VECTOR(1));")
        self.db.ok("INSERT INTO ordering VALUES (4,1,'x','[-1]'),(1,2,'z','[1]'),(5,1,'x','[1]'),(2,2,'a','[-1]'),(3,2,'a','[2]');")
        self.assertEqual(self.db.rows("SELECT id FROM ordering ORDER BY a DESC,b ASC;"), [[2], [3], [1], [4], [5]])
        self.assertEqual(self.db.rows("SELECT id,L2_DISTANCE(v,'[0]') AS d FROM ordering ORDER BY d,a DESC,b ASC LIMIT 18446744073709551615;"), [[2, 1], [1, 1], [4, 1], [5, 1], [3, 2]])
        self.assertEqual(self.db.rows("SELECT a AS x,id FROM ordering ORDER BY x DESC,b ASC LIMIT 3;"), [[2, 2], [2, 3], [2, 1]])

    def test_randomized_hot_read_reference_model(self):
        rng = random.Random(20261110)
        model = {}
        snapshot = None
        self.db.ok("CREATE TABLE random_rows (id BIGINT PRIMARY KEY, bucket BIGINT, v VECTOR(2));")
        for step in range(240):
            key = rng.randrange(40)
            op = rng.choice(["insert", "update", "delete", "begin", "finish"])
            if op == "begin" and snapshot is None:
                self.db.ok("BEGIN;")
                snapshot = copy.deepcopy(model)
            elif op == "finish" and snapshot is not None:
                if rng.randrange(2):
                    self.db.ok("COMMIT;")
                else:
                    self.db.ok("ROLLBACK;")
                    model = snapshot
                snapshot = None
            elif op == "insert":
                bucket, x, y = rng.randrange(4), rng.randrange(-9, 10), rng.randrange(-9, 10)
                sql = f"INSERT INTO random_rows VALUES ({key},{bucket},'[{x},{y}]');"
                if key in model:
                    self.fails(sql)
                else:
                    self.db.ok(sql)
                    model[key] = [bucket, [x, y]]
            elif op == "update":
                bucket, x, y = rng.randrange(4), rng.randrange(-9, 10), rng.randrange(-9, 10)
                self.db.ok(f"UPDATE random_rows SET bucket={bucket},v='[{x},{y}]' WHERE id={key};")
                if key in model:
                    model[key] = [bucket, [x, y]]
            elif op == "delete":
                self.db.ok(f"DELETE FROM random_rows WHERE id={key};")
                model.pop(key, None)
            probe = rng.randrange(40)
            self.assertEqual(self.db.rows(f"SELECT bucket FROM random_rows WHERE id={probe};"), [[model[probe][0]]] if probe in model else [])
            for bucket, qx, qy, k in ((0, 0, 0, 5), (2, -3, 4, 11), (3, 7, 8, 2)):
                expected = sorted((math.hypot(v[1][0] - qx, v[1][1] - qy), i) for i, v in model.items() if v[0] >= bucket)[:k]
                sql = f"SELECT id,L2_DISTANCE(v,'[{qx},{qy}]') AS d FROM random_rows WHERE bucket>={bucket} ORDER BY d LIMIT {k};"
                first = self.db.rows(sql)
                self.assertEqual(first, self.db.rows(sql), f"repeated hot read step {step}")
                self.assertEqual([r[0] for r in first], [i for _, i in expected], f"reference result step {step}")
                for row, (distance, _) in zip(first, expected):
                    self.assertAlmostEqual(row[1], distance, places=6)

    def test_vector_reference_multiple_dimensions_filters_and_ties(self):
        # Compute from the SQL inputs after FP32 quantization, independently of
        # the database. Repeated queries exercise a warmed cache as well.
        def f32(value):
            return struct.unpack("f", struct.pack("f", value))[0]

        for seed, dimension in ((9143, 1), (27183, 3), (3179, 17)):
            rng = random.Random(seed)
            table = f"vectors_{dimension}"
            self.db.ok(f"CREATE TABLE {table} (id BIGINT PRIMARY KEY, grp BIGINT, v VECTOR({dimension}));")
            model = {}
            tuples = []
            for key in range(48):
                # The first two rows deliberately tie and are inserted in the
                # opposite order to verify the primary-key tie breaker.
                vector = [0.0] * dimension if key < 2 else [round(rng.uniform(-3, 3), 6) for _ in range(dimension)]
                group = key % 5
                model[key] = (group, [f32(x) for x in vector])
                literal = ",".join(map(str, vector))
                tuples.append(f"({key},{group},'[{literal}]')")
            self.db.ok(f"INSERT INTO {table} VALUES " + ",".join(reversed(tuples)) + ";")
            queries = [[0.0] * dimension] + [[round(rng.uniform(-2, 2), 6) for _ in range(dimension)] for _ in range(4)]
            for vector in queries:
                query = [f32(x) for x in vector]
                literal = ",".join(map(str, vector))
                for condition, predicate in (("", lambda group: True), (" WHERE grp=2", lambda group: group == 2),
                                             (" WHERE grp>=3", lambda group: group >= 3), (" WHERE grp=99", lambda group: group == 99)):
                    expected = []
                    for key, (group, stored) in model.items():
                        if predicate(group):
                            distance = math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(stored, query)))
                            expected.append((distance, key))
                    expected.sort()
                    expected = expected[:13]
                    sql = f"SELECT id,L2_DISTANCE(v,'[{literal}]') AS d FROM {table}{condition} ORDER BY d LIMIT 13;"
                    for _ in range(2):
                        actual = self.db.rows(sql)
                        self.assertEqual([row[0] for row in actual], [key for _, key in expected])
                        for row, (distance, _) in zip(actual, expected):
                            self.assertAlmostEqual(row[1], distance, places=10)

    def test_topk_reference_at_distance_loop_boundaries(self):
        # The oracle uses FP32 inputs but accumulates in ordinary Python double
        # precision, in the same component order; it does not use the TopK path.
        def f32(value):
            return struct.unpack("f", struct.pack("f", value))[0]

        for dim in (31, 32, 33, 64, 65, 127, 128, 129):
            rng = random.Random(20261110 + dim)
            table = f"distance_boundary_{dim}"
            self.db.ok(f"CREATE TABLE {table} (id BIGINT PRIMARY KEY, grp BIGINT, v VECTOR({dim}));")
            vectors = {}
            for key in range(48):
                if key < 3:
                    # Equal final distances, including values close enough that
                    # a strict partial-distance cutoff must retain ties.
                    vector = [1.0, (0.0 if key == 0 else 1e-8)] + [0.0] * (dim - 2)
                else:
                    scale = (1e-19, 1.0, 1e19)[key % 3]
                    vector = [round(rng.uniform(-1, 1), 6) * scale for _ in range(dim)]
                vectors[key] = [f32(x) for x in vector]
            tuples = [
                f"({key},{key % 3},'[" + ",".join(map(str, vectors[key])) + "]')"
                for key in reversed(range(48))
            ]
            self.db.ok(f"INSERT INTO {table} VALUES " + ",".join(tuples) + ";")
            for query in ([0.0] * dim, [f32(rng.uniform(-0.5, 0.5)) for _ in range(dim)]):
                literal = ",".join(map(str, query))
                for where, eligible in (("", lambda key: True), (" WHERE grp=1", lambda key: key % 3 == 1)):
                    expected = sorted(
                        (math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(vec, query))), key)
                        for key, vec in vectors.items() if eligible(key)
                    )
                    for k in (1, 3, 10):
                        sql = f"SELECT id,L2_DISTANCE(v,'[{literal}]') AS d FROM {table}{where} ORDER BY d LIMIT {k};"
                        for _ in range(2):
                            rows = self.db.rows(sql)
                            self.assertEqual([row[0] for row in rows], [key for _, key in expected[:k]])
                            for row, (distance, _) in zip(rows, expected[:k]):
                                self.assertTrue(math.isclose(row[1], distance, rel_tol=1e-12, abs_tol=1e-300))

    def test_vector_string_filter_cache_transaction_lifecycle(self):
        self.db.ok("CREATE TABLE col_lifecycle (id BIGINT PRIMARY KEY, grp VARCHAR(10), v VECTOR(2));")
        self.db.ok("INSERT INTO col_lifecycle VALUES (3,'a','[0,1]'),(1,'','[0,-1]'),(2,'a','[0,1]');")
        def query(condition=""):
            sql = f"SELECT id,grp,L2_DISTANCE(v,'[0,0]') AS d FROM col_lifecycle {condition} ORDER BY d LIMIT 10;"
            first = self.db.rows(sql)
            self.assertEqual(first, self.db.rows(sql))
            return first
        self.assertEqual(query(), [[1, "", 1], [2, "a", 1], [3, "a", 1]])
        self.assertEqual(query("WHERE grp='a'"), [[2, "a", 1], [3, "a", 1]])
        self.assertEqual(query("WHERE grp=''"), [[1, "", 1]])
        self.assertEqual(query("WHERE grp>='a'"), [[2, "a", 1], [3, "a", 1]])
        self.db.ok("BEGIN;")
        self.db.ok("UPDATE col_lifecycle SET grp='b',v='[0,0]' WHERE id=3;")
        self.assertEqual(query("WHERE grp='b'"), [[3, "b", 0]])
        self.fails("INSERT INTO col_lifecycle VALUES (4,'b','[0,0]'),(2,'b','[0,0]');")
        self.assertEqual(query("WHERE grp='b'"), [[3, "b", 0]])
        self.db.ok("ROLLBACK;")
        self.assertEqual(query("WHERE grp='b'"), [])
        self.db.ok("BEGIN;")
        self.db.ok("DELETE FROM col_lifecycle WHERE id=1;")
        self.db.ok("COMMIT;")
        self.assertEqual(query(), [[2, "a", 1], [3, "a", 1]])
        directory = self.db.directory
        self.db.close()
        self.db = core.Database(directory)
        self.assertEqual(query(), [[2, "a", 1], [3, "a", 1]])

    def test_vector_scan_beyond_cache_budget_remains_correct(self):
        dimension, count = 1024, 3100
        zero = "[" + ",".join(["0"] * dimension) + "]"
        self.db.ok(f"CREATE TABLE large_vectors (id BIGINT PRIMARY KEY, grp BIGINT, v VECTOR({dimension}));")
        for start in range(0, count, 100):
            values = ",".join(f"({key},{key % 2},'{zero}')" for key in range(start, min(start + 100, count)))
            self.db.ok("INSERT INTO large_vectors VALUES " + values + ";", timeout=60)
        sql = f"SELECT id,L2_DISTANCE(v,'{zero}') AS d FROM large_vectors WHERE grp=1 ORDER BY d LIMIT 5;"
        for _ in range(2):
            self.assertEqual(self.db.rows(sql), [[key, 0] for key in (1, 3, 5, 7, 9)])
        self.db.ok("BEGIN;")
        self.db.ok("DELETE FROM large_vectors WHERE id=1;")
        self.assertEqual(self.db.rows(sql), [[key, 0] for key in (3, 5, 7, 9, 11)])
        self.db.ok("ROLLBACK;")
        self.assertEqual(self.db.rows(sql), [[key, 0] for key in (1, 3, 5, 7, 9)])


class OutputFailureAcceptance(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix" and Path("/dev/full").exists(), "/dev/full requires Linux/POSIX")
    def test_stdout_failure_stops_before_next_statement(self):
        with tempfile.TemporaryDirectory(prefix="mvdb-stdout-failure-") as directory:
            sql = (
                "CREATE TABLE stdout_boundary (id BIGINT PRIMARY KEY, value BIGINT);\n"
                "INSERT INTO stdout_boundary VALUES (1,99);\n"
            )
            # /dev/full reliably fails the first output write. Both statements
            # are already available on stdin, so a loop that ignores stdout
            # failure would incorrectly execute the INSERT before exiting.
            with open("/dev/full", "wb", buffering=0) as output:
                process = subprocess.run(
                    [str(core.BINARY), "--data-dir", directory, "--dev-protocol"],
                    input=sql.encode("utf-8"),
                    stdout=output,
                    stderr=subprocess.PIPE,
                    timeout=20,
                )
            self.assertNotEqual(process.returncode, 0, "A failed response channel must terminate with failure")
            self.assertTrue(process.stderr, "Output failure should have a stderr diagnostic")
            db = core.Database(directory)
            try:
                result = db.execute("SELECT id,value FROM stdout_boundary;")
                # The CREATE had no successful response. It may have persisted,
                # but the queued INSERT must never have been executed.
                if result["ok"]:
                    self.assertEqual(result["rows"], [])
                else:
                    self.assertEqual(result.get("code"), "TABLE", result)
            finally:
                db.close(kill=True)


class LargeResponseAcceptance(unittest.TestCase):
    ROWS = 9600
    PAYLOAD_LENGTH = 20000

    @classmethod
    def payload(cls, key):
        prefix = f"row-{key:08d}-"
        # Includes escapes and Unicode while keeping exactly 20,000 characters.
        return prefix + ("中\\\"" if key % 137 == 0 else "xyz") + "x" * (cls.PAYLOAD_LENGTH - len(prefix) - 3)

    @classmethod
    def setUpClass(cls):
        if not LARGE or os.name != "posix":
            raise unittest.SkipTest("Enable --large in Linux for bounded-memory output tests")
        cls.tmp = tempfile.TemporaryDirectory(prefix="mvdb-spill-")
        cls.directory = Path(cls.tmp.name) / "data"
        db = core.Database(cls.directory, memory_limit=MEMORY_LIMIT)
        try:
            db.ok("CREATE TABLE large_rows (id BIGINT PRIMARY KEY, bucket BIGINT, label VARCHAR(5), payload VARCHAR(20000), v VECTOR(1));")
            for start in range(0, cls.ROWS, 100):
                values = []
                for key in range(start, min(start + 100, cls.ROWS)):
                    # SQL backslash needs escaping independently of SQL apostrophe.
                    payload = cls.payload(key).replace("\\", "\\\\").replace("'", "''")
                    label = chr(ord("a") + (key // 7) % 5)
                    values.append(f"({key},{key % 7},'{label}','{payload}','[{key - 4000}]')")
                db.ok("INSERT INTO large_rows VALUES " + ",".join(values) + ";", timeout=60)
        finally:
            db.close(kill=True)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmp"):
            cls.tmp.cleanup()

    def run_streaming_query(self, sql, callback):
        import resource

        def set_limit():
            resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, MEMORY_LIMIT))

        with tempfile.TemporaryFile(mode="w+b") as output, tempfile.TemporaryFile(mode="w+b") as errors:
            process = subprocess.run(
                [str(core.BINARY), "--data-dir", str(self.directory), "--dev-protocol"],
                input=(sql + "\n").encode("utf-8"),
                stdout=output,
                stderr=errors,
                preexec_fn=set_limit,
                timeout=120,
            )
            errors.seek(0)
            self.assertEqual(process.returncode, 0, errors.read().decode("utf-8", errors="replace"))
            output.seek(0, os.SEEK_END)
            byte_count = output.tell()
            output.seek(0)
            import io
            reader = io.TextIOWrapper(output, encoding="utf-8")
            try:
                fields, count = JsonStream(reader).response(callback)
            finally:
                reader.detach()
        return fields, count, byte_count

    def test_no_limit_select_star_streams_beyond_memory_budget(self):
        seen = set()
        observed_hash = hashlib.sha256()
        expected_hash = hashlib.sha256()

        def check_row(index, row):
            self.assertEqual(len(row), 5)
            key, bucket, label, payload, vector = row
            self.assertNotIn(key, seen)
            self.assertGreaterEqual(key, 0)
            self.assertLess(key, self.ROWS)
            seen.add(key)
            self.assertEqual(bucket, key % 7)
            self.assertEqual(label, chr(ord("a") + (key // 7) % 5))
            self.assertEqual(vector, [key - 4000])
            observed_hash.update(payload.encode("utf-8"))
            expected_hash.update(self.payload(key).encode("utf-8"))

        fields, count, size = self.run_streaming_query("SELECT * FROM large_rows;", check_row)
        self.assertEqual(count, self.ROWS)
        self.assertEqual(len(seen), self.ROWS)
        self.assertEqual(fields["columns"], ["id", "bucket", "label", "payload", "v"])
        self.assertEqual(observed_hash.digest(), expected_hash.digest())
        self.assertGreater(size, MEMORY_LIMIT)

    def test_large_limit_multikey_order_spills_without_changing_order(self):
        expected_keys = sorted(range(self.ROWS), key=lambda key: (-(key % 7), chr(ord("a") + (key // 7) % 5), key))
        digest = hashlib.sha256()
        expected_digest = hashlib.sha256()

        def check_row(index, row):
            key, payload = row
            self.assertEqual(key, expected_keys[index])
            digest.update(payload.encode("utf-8"))
            expected_digest.update(self.payload(key).encode("utf-8"))

        _, count, size = self.run_streaming_query("SELECT id,payload FROM large_rows ORDER BY bucket DESC,label ASC LIMIT 18446744073709551615;", check_row)
        self.assertEqual(count, self.ROWS)
        self.assertEqual(digest.digest(), expected_digest.digest())
        self.assertGreater(size, MEMORY_LIMIT)

    def test_distance_topk_with_large_payload_exceeds_heap_budget(self):
        expected_keys = sorted(range(self.ROWS), key=lambda key: (abs(key - 4000), key))[:8000]
        digest = hashlib.sha256()
        expected_digest = hashlib.sha256()

        def check_row(index, row):
            key, payload, distance = row
            self.assertEqual(key, expected_keys[index])
            self.assertEqual(distance, abs(key - 4000))
            digest.update(payload.encode("utf-8"))
            expected_digest.update(self.payload(key).encode("utf-8"))

        _, count, size = self.run_streaming_query("SELECT id,payload,L2_DISTANCE(v,'[0]') AS d FROM large_rows ORDER BY d LIMIT 8000;", check_row)
        self.assertEqual(count, 8000)
        self.assertEqual(digest.digest(), expected_digest.digest())
        self.assertGreater(size, MEMORY_LIMIT)


def main():
    global LARGE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--large", action="store_true")
    args, rest = parser.parse_known_args()
    core.BINARY = args.binary.resolve()
    LARGE = args.large
    if not core.BINARY.is_file():
        parser.error(f"Executable does not exist: {core.BINARY}")
    unittest.main(argv=[__file__] + rest)


if __name__ == "__main__":
    main()
