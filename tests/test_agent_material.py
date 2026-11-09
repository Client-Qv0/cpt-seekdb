#!/usr/bin/env python3
"""Local structural checks for truthful learning material, not official scoring."""
import json
import math
from pathlib import Path
import re
import unittest


MATERIAL = Path(__file__).resolve().parent.parent / 'agent' / 'conversation.json'
SESSION = 'current_session_hmy_20261109'
MAX_BYTES = 128 * 1024


def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f'non-standard JSON constant: {value}')


def strict_json(data):
    document = json.loads(data.decode('utf-8'), object_pairs_hook=reject_duplicates,
                          parse_constant=reject_constant)
    def check_finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('number exceeds finite floating-point range')
        if isinstance(value, dict):
            for item in value.values():
                check_finite(item)
        elif isinstance(value, list):
            for item in value:
                check_finite(item)
    check_finite(document)
    return document


def resolve_pointer(root, pointer):
    if pointer == '':
        return root
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise ValueError('JSON pointer must be empty or start with /')
    node = root
    for raw in pointer[1:].split('/'):
        if re.search(r'~(?![01])', raw):
            raise ValueError('invalid JSON pointer escape')
        token = raw.replace('~1', '/').replace('~0', '~')
        if isinstance(node, list):
            if not re.fullmatch(r'0|[1-9][0-9]*', token):
                raise ValueError('invalid array index')
            node = node[int(token)]
        elif isinstance(node, dict):
            node = node[token]
        else:
            raise ValueError('JSON pointer traverses a scalar')
    return node


class AgentMaterialChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = MATERIAL.read_bytes()
        cls.doc = strict_json(cls.raw)

    def test_size_encoding_and_top_level_object(self):
        self.assertLessEqual(len(self.raw), MAX_BYTES)
        self.assertIsInstance(self.doc, dict)

    def test_strict_decoder_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for sample in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":-Infinity}', b'{"a":1e9999}'):
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                strict_json(sample)

    def test_pointer_resolves_and_rejects_bad_escape(self):
        example = {'a/b': {'~': ['ok']}}
        self.assertEqual(resolve_pointer(example, '/a~1b/~0/0'), 'ok')
        with self.assertRaises(ValueError):
            resolve_pointer(example, '/a~2b')

    def test_session_links_are_exact_attributed_and_distinct(self):
        links = self.doc[SESSION]['evidence_links']
        self.assertTrue(links)
        seen = set()
        for link in links:
            for role in ('student', 'result'):
                pointer, excerpt = link[f'{role}_pointer'], link[f'{role}_excerpt']
                value = resolve_pointer(self.doc, pointer)
                self.assertIsInstance(value, str)
                self.assertIsInstance(excerpt, str)
                self.assertGreater(len(excerpt), 0)
                self.assertLessEqual(len(excerpt), 240)
                self.assertIn(excerpt, value)
                self.assertNotIn((pointer, excerpt), seen)
                seen.add((pointer, excerpt))
                parent = resolve_pointer(self.doc, pointer.rsplit('/', 1)[0])
                if role == 'student':
                    self.assertEqual(parent.get('source'), 'student')
                else:
                    self.assertTrue(parent.get('source', '').startswith('tool_output'))
            self.assertNotEqual(link['student_pointer'], link['result_pointer'])

    def test_obvious_secret_formats_are_absent(self):
        # This is only a narrow check for common complete secret formats.
        text = self.raw.decode('utf-8')
        for pattern in (r'-----BEGIN [A-Z ]*PRIVATE KEY-----', r'github_pat_[A-Za-z0-9_]{20,}',
                        r'gh[pousr]_[A-Za-z0-9]{20,}', r'sk-(?:proj-)?[A-Za-z0-9_-]{20,}',
                        r'AKIA[0-9A-Z]{16}'):
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, text), 'Possible secret format found; review manually.')


if __name__ == '__main__':
    unittest.main()
