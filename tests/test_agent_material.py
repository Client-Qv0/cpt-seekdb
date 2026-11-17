#!/usr/bin/env python3
"""Local structural checks for truthful learning material, not official scoring."""
import json
import hashlib
import math
from pathlib import Path
import re
import unittest


MATERIAL = Path(__file__).resolve().parent.parent / 'agent' / 'conversation.json'
MAX_BYTES = 126 * 1024
DIMENSIONS = {'problem_understanding', 'technical_transfer', 'independent_validation',
              'experimental_iteration', 'tradeoff_reflection'}
NEW_UNITS = {
    'cache-tail-latency-boundary',
    'table-index-recovery-boundary',
    'corrupt-commit-ready-boundary',
    'range-scan-tombstone-boundary',
}
BASE_CONVERSATIONS_SHA256 = (
    '3f24dc34c9837f3bf46b39828fca4a658ab8cea99b15b46b3a3ce38bac39d2d1'
)
BASE_UNIT_HASHES = {
    'exact-route-gated-choice': '3a11dd5a9ca5f81e4d2e8c51098d16e16c8134ea7ac0ac9f2489e4ac7bf97e1f',
    'quota-policy-boundary': '8a9bb145686f1d5aeb7e469a7960b4e0b56016226977ba65fe23447480e3776d',
    'topk-parallel-boundary-counterexample': 'c297a369882882f81ffdbc0e3c34bbaece629fa6bbcab94612024b998ceeb70f',
    'cross-chunk-insert-atomicity': '57f1513b5aef1b95c21652ee8d40451be635928692d68d1d1f058eab5fefa0a2',
    'cache-fallback-layers': '996ce04d4db85d2867a8bc6515fd0347a77fdab5364e9ae94de234a06d8beaa0',
    'coalesced-read-layout-boundary': '9c020661fb12291ff0e78fe069d7a311eb23d9832460c6d11e0f7291fd74ad74',
    'commit-state-without-response': '2f1db062de9cf390c0459b0e212bca927e3be2e5e767ab1350a084549e90cc41',
    'filtered-topk-counterexample': '987f0782f79d5bdba507d6964fb22e9e02c34a3d2e00e6919165cbcf12ce7f80',
    'c22-parser-prediction-and-test': 'deb7bf3007410342838b62c78be4673839def60c511892f24a76413ddd8d4a73',
    'declared-width-projection-budget': '1690d53c9e79f04e67d38557b6e76a62cdcbd985846dcf8c45d197d29ff2457f',
    'residual-bound-work-count': '2c33651f6459b56bffe701d6d6ece365e91cf8f8f894c6f4949588956828e818',
    'fp32-input-fp64-oracle-transfer': '8544ddac293ec251f3e28b77f924224f66aabf8c1830424620616eda73990768',
    'memory-limit-report-vs-startup-snapshot': '4a8e86f4be7c2d3e03bf4857d6df53056094edd808c512565e3d837c3d2abfed',
    'descending-screen-test-sensitivity': '0e69c4ca2fd94f502d398512f10b734cdbc53c6e168d72a0ea2be68f5cfe6f32',
    'spill-stream-oversized-row-verifier': '9f71dae1ec8c9419571ea9abc6ee2543aa2177af77b3b64f7e49a83845eebc43',
    'same-source-score-aa-detection': '724da74b6cc6cc720a17ab17d08118ee389aa867cd3098e28341c727b60286cc',
    'sql-rejection-before-write': '0ae5a021de2440606ab9f8f8c4900a14fb4f3255f52c65ab8aed5dd672f5a87f',
    'topk-warm-projection-binding': '661a5e9a6dbc411b9fbe76ba510e0aa4eeede66e0c5b38f137d70294b2984062',
    'w2-row-materialization': 'cdb299c8a6ada38089d89b8a13f7e35a0ac6045fab4d65673e250ee8b75dea20',
    'q7-integer-guard': 'b19fe09c508cfa662d0a6d2ef18b7f886b90ebceab5c4799d82495002c8c4b46',
    'recover-interrupted-tail': '85c3ef0423967389933dec92925322025674b72cc27241e8c7fa4902c7223eca',
    'compact-pk-capacity-tradeoff': '721a5f0a73031442369fad3127195f62538bb7f30c28487d1ab0e6c62e3c29db',
}


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

    def test_aggressive_campaign_invariants(self):
        units = {unit['id']: unit for unit in self.doc['units']}
        self.assertEqual(len(units), 26)
        self.assertEqual(sum(unit['score'] for unit in units.values()), 43.0)
        base_conversations = self.doc['conversations'][:30]
        raw_conversations = json.dumps(
            base_conversations, ensure_ascii=False, separators=(',', ':')
        ).encode('utf-8')
        self.assertEqual(
            hashlib.sha256(raw_conversations).hexdigest(),
            BASE_CONVERSATIONS_SHA256,
        )
        self.assertTrue(NEW_UNITS.issubset(units))
        for unit_id, expected_hash in BASE_UNIT_HASHES.items():
            raw = json.dumps(
                units[unit_id], ensure_ascii=False, separators=(',', ':')
            ).encode('utf-8')
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected_hash, unit_id)
        for unit_id in NEW_UNITS:
            unit = units[unit_id]
            self.assertEqual(unit['score'], 1.5)
            self.assertGreaterEqual(len(unit['student_evidence']), 2)
            self.assertGreaterEqual(len(unit['result_evidence']), 2)

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

    def test_excluded_evidence_is_not_scored(self):
        # Workflow instructions remain inspectable but must not simultaneously
        # be offered as scored technical learning instances.
        unit_ids = {unit['id'] for unit in self.doc['units']}
        exclusions = self.doc.get('review_exclusions', [])
        excluded_ids = [item['id'] for item in exclusions]
        self.assertEqual(len(excluded_ids), len(set(excluded_ids)))
        self.assertTrue(unit_ids.isdisjoint(excluded_ids))
        for item in exclusions:
            self.assertTrue(isinstance(item['reason'], str) and item['reason'].strip())

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
