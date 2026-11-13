#!/usr/bin/env python3
"""Local structural checks for truthful learning material, not official scoring."""
import json
import math
from pathlib import Path
import re
import unittest


MATERIAL = Path(__file__).resolve().parent.parent / 'agent' / 'conversation.json'
MAX_BYTES = 128 * 1024
DIMENSIONS = {'problem_understanding', 'technical_transfer', 'independent_validation',
              'experimental_iteration', 'tradeoff_reflection'}


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


def validate_v3(doc):
    def require(ok, message):
        if not ok:
            raise ValueError(message)
    require(doc.get('rule_version') == 'agent-learning-evidence-v3-unbounded', 'rule version')
    require(isinstance(doc.get('summary'), str) and doc['summary'].strip(), 'material summary')
    require(isinstance(doc.get('conversations'), list) and isinstance(doc.get('experiments'), list), 'records')
    dimensions=doc.get('dimensions', [])
    require(isinstance(dimensions, list) and len(dimensions)==5, 'five dimensions')
    require({d['id'] for d in dimensions}==DIMENSIONS, 'dimension identities')
    require(isinstance(doc.get('units'), list), 'units list')
    seen_ids, seen_chains, seen_quotes, used = set(), set(), set(), []
    memberships={d:set() for d in DIMENSIONS}
    for unit in doc['units']:
        require(unit['id'] not in seen_ids and unit['chain_id'] not in seen_chains, 'duplicate unit/chain')
        seen_ids.add(unit['id']); seen_chains.add(unit['chain_id'])
        require(unit['dimension'] in DIMENSIONS, 'single valid dimension')
        require(type(unit['score']) in (int,float) and unit['score'] in (0.5,1,1.5,2), 'one tier')
        require(isinstance(unit.get('reason'), str) and unit['reason'], 'reason')
        memberships[unit['dimension']].add(unit['id'])
        require(bool(unit['student_evidence']), 'student evidence required')
        require(bool(unit['result_evidence']) == (unit['score']>0.5), 'plan/result tier')
        for role in ('student','result'):
            require(isinstance(unit[role+'_evidence'],list), 'evidence list')
            for evidence in unit[role+'_evidence']:
                pointer,quote=evidence['pointer'],evidence['quote']
                require(pointer.startswith(('/conversations/','/experiments/')), 'source record pointer')
                value=resolve_pointer(doc,pointer)
                require(isinstance(value,str) and isinstance(quote,str) and 0<len(quote)<=240, 'string quote length')
                require(quote in value, 'quote not found')
                require(quote not in seen_quotes, 'reused quote')
                seen_quotes.add(quote)
                start=value.index(quote);end=start+len(quote)
                require(not any(p==pointer and max(a,start)<min(b,end) for p,a,b in used), 'overlapping evidence')
                used.append((pointer,start,end))
                parent=resolve_pointer(doc,pointer.rsplit('/',1)[0])
                source=parent.get('source','')
                if role=='student':
                    require(source=='student' and parent.get('authorship_verified') is True, 'student attribution')
                else:
                    require(source.startswith('tool_output') or source=='platform_user_report', 'executed result source')
    for dimension in dimensions:
        require(len(dimension['unit_ids'])==len(set(dimension['unit_ids'])), 'duplicate membership')
        require(set(dimension['unit_ids'])==memberships[dimension['id']], 'dimension membership')
    return sum(unit['score'] for unit in doc['units'])


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

    def test_v3_units_and_exact_evidence(self):
        validate_v3(self.doc)

    def test_all_five_dimensions_have_candidate_units(self):
        # A material-level "insufficient evidence" marker makes the official
        # v3 review return NEEDS_REVIEW instead of a numeric score.
        for dimension in self.doc['dimensions']:
            with self.subTest(dimension=dimension['id']):
                self.assertTrue(dimension['unit_ids'])
                self.assertNotEqual(dimension.get('evidence_status'),
                                    'insufficient_student_evidence_in_selected_material')

    def test_unbounded_total_and_invalid_evidence(self):
        import copy
        d = copy.deepcopy(self.doc)
        # Synthetic test fixtures only: exercise an actual total above 100.
        fixture=copy.deepcopy(d)
        fixture['synthetic']=True
        fixture['conversations']=[{'messages':[]}]
        fixture['experiments']=[]
        fixture['units']=[]
        for dimension in fixture['dimensions']:
            dimension['unit_ids']=[]
        for i in range(60):
            student=f'synthetic student fixture {i:03d}'
            result=f'synthetic executed fixture {i:03d}'
            fixture['conversations'][0]['messages'].append(
                {'source':'student','authorship_verified':True,'content':student})
            fixture['experiments'].append({'source':'tool_output_fixture','content':result})
            unit=copy.deepcopy(d['units'][0])
            unit.update(id=f'fixture-{i}',chain_id=f'fixture-chain-{i}',score=2)
            unit['student_evidence']=[{'pointer':f'/conversations/0/messages/{i}/content','quote':student}]
            unit['result_evidence']=[{'pointer':f'/experiments/{i}/content','quote':result}]
            fixture['units'].append(unit)
            next(x for x in fixture['dimensions'] if x['id']==unit['dimension'])['unit_ids'].append(unit['id'])
        self.assertEqual(validate_v3(fixture),120)
        for mutate in (
            lambda x: x['units'][0].update(score=3),
            lambda x: x['units'][0]['student_evidence'][0].update(quote='missing exact quote'),
            lambda x: next(u for u in x['units'] if u['score'] > 0.5).update(result_evidence=[]),
            lambda x: x['units'].append(copy.deepcopy(x['units'][0])),
        ):
            bad=copy.deepcopy(d)
            mutate(bad)
            with self.assertRaises((ValueError, KeyError, IndexError)):
                validate_v3(bad)

    def test_current_iteration_records_present(self):
        unit_ids={unit['id'] for unit in self.doc['units']}
        # The four discipline units were merged into one chain, as the rubric
        # counts a single chain once regardless of how it is split.
        for expected in ('working-discipline','server-only-execution'):
            with self.subTest(expected=expected):
                self.assertIn(expected, unit_ids)
        self.assertIn('f5a7e3e2373742eee40268cf20ef7837b91da655',
                      self.doc['coverage']['source_version'])

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
