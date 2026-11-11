"""Local material and provenance checks. This is not the official semantic grader."""
from pathlib import Path
import argparse, hashlib, json, math, re

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent/'oceanbase-c4-review-20261111/prompt-navigation/agent/conversation.json'
CANDIDATE = ROOT/'agent/conversation.json'

def strict_json(raw):
    def pairs(items):
        obj={}
        for key,val in items:
            if key in obj: raise ValueError('duplicate JSON key')
            obj[key]=val
        return obj
    def constant(value): raise ValueError('non-standard numeric constant')
    doc=json.loads(raw.decode('utf8'),object_pairs_hook=pairs,parse_constant=constant)
    if not isinstance(doc,dict): raise ValueError('top level must be an object')
    if len(raw)>131072: raise ValueError('over 128 KiB')
    for _,v in leaves(doc):
        if isinstance(v,float) and not math.isfinite(v): raise ValueError('non-finite number')
        if isinstance(v,str): v.encode('utf8')
    return doc

def leaves(value,path=''):
    if isinstance(value,dict):
        for k,v in value.items():
            yield from leaves(v,path+'/'+k.replace('~','~0').replace('/','~1'))
    elif isinstance(value,list):
        for i,v in enumerate(value): yield from leaves(v,path+'/'+str(i))
    else: yield path,value

def resolve(root,pointer):
    if pointer=='': return root
    if not isinstance(pointer,str) or not pointer.startswith('/'): raise ValueError('invalid pointer')
    cur=root
    for raw in pointer[1:].split('/'):
        if re.search(r'~(?![01])',raw): raise ValueError('bad escape')
        token=raw.replace('~1','/').replace('~0','~')
        if isinstance(cur,list):
            if not re.fullmatch(r'0|[1-9][0-9]*',token): raise ValueError('invalid array index')
            cur=cur[int(token)]
        elif isinstance(cur,dict): cur=cur[token]
        else: raise ValueError('cannot traverse scalar')
    return cur

def main(material_path=CANDIDATE,base_path=BASE,context_source_root=None,output_path=ROOT/'validation-result.json'):
    raw=material_path.read_bytes(); doc=strict_json(raw); base=strict_json(base_path.read_bytes())
    preserved=0
    for pointer,value in leaves(base):
        actual=resolve(doc,pointer)
        assert type(actual) is type(value) and actual==value,pointer
        preserved+=1
    # No structural rewrite or array reordering may erase the original quotations.
    strings_preserved=sum(isinstance(v,str) for _,v in leaves(base))
    negative=0
    for sample in [b'{"a":1,"a":2}',b'{"x":{"a":1,"a":2}}',b'{"a":NaN}',b'{"a":Infinity}',b'{"a":1e999}',b'[]',b'{"a":"\xff"}',b'{"a":"\\ud800"}',b'{"x":"'+b'x'*131072+b'"}']:
        try: strict_json(sample)
        except (ValueError,UnicodeError): negative+=1
        else: raise AssertionError('invalid fixture accepted')
    assert resolve({'a/b':{'~':['ok']}},'/a~1b/~0/0')=='ok'
    for pointer in ['/a~2b','/a~1b/~0/01']:
        try: resolve({'a/b':{'~':['ok']}},pointer)
        except (ValueError,KeyError): pass
        else: raise AssertionError('invalid pointer accepted')
    text=raw.decode('utf8')
    for pattern in [r'-----BEGIN [A-Z ]*PRIVATE KEY-----',r'github_pat_[A-Za-z0-9_]{20,}',r'gh[pousr]_[A-Za-z0-9]{20,}',r'sk-(?:proj-)?[A-Za-z0-9_-]{20,}',r'AKIA[0-9A-Z]{16}']:
        assert not re.search(pattern,text),'Possible credential pattern; inspect without printing it'
    trace=json.loads((ROOT/'provenance/source-trace.json').read_bytes())
    context=json.loads((ROOT/'provenance/context-repair.json').read_bytes())
    for item in trace['verified_origins']:
        assert resolve(doc,item['material_pointer'])==item['content']
        record=resolve(doc,item['material_pointer'].rsplit('/',1)[0])
        origin=record['verified_origin_20261111']
        assert origin['wording_author']=='advisory_agent'
        assert origin['original_message_id']==item['origin']['message_id']
        assert origin['original_thread_id']==item['origin']['thread_id']
        assert origin['original_role']=='assistant'
    assert doc['verified_user_feedback_20261111']['episodes']==trace['authentic_correction_episodes']
    for src in context['sources']:
        source_path=(context_source_root/src['repository_path']) if context_source_root is not None else Path(src['local_path'])
        source_raw=source_path.read_bytes()
        assert hashlib.sha256(source_raw).hexdigest()==src['sha256']
    for i,item in enumerate(context['records']):
        assert resolve(doc,item['material_user_pointer'])==item['material_user_content']
        entry=resolve(doc,item['material_user_pointer'].rsplit('/',1)[0])
        recovered=(resolve(doc,entry['context_pointer_20261111']) if i<3 else entry['recovered_context_20261111'])
        assert recovered['source']=='agent_authored_record_in_frozen_repository'
        assert recovered['original_question_text_recovered'] is False
        assert recovered['original_message_id_recovered'] is False
        if i<3:
            excerpts=[context['records'][0]['context_excerpts'][0]['content'],context['records'][0]['context_excerpts'][1]['content'].split(' Record current server')[0]]
            assert recovered['content']=='\n\n'.join(excerpts)
        else:
            assert recovered['content']==item['context_excerpts'][0]['content']
    scoped=0
    for episode in doc['official_protocol_repair_20261110']['raw_protocol_examples']['records']:
        for fragment in episode['fragments']:
            if 'json_pointer' in fragment:
                assert fragment['json_pointer_scope']=='source_artifact_identified_by_source_id'
                assert isinstance(fragment['content'],str) and fragment['content']
                scoped+=1
    assert scoped==7
    report={'scope':'Local structure, source preservation and captured provenance checks; no official semantic grade.','bytes':len(raw),'headroom':131072-len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'base_sha256':hashlib.sha256(base_path.read_bytes()).hexdigest(),'old_scalar_leaves_preserved':preserved,'old_string_leaves_preserved':strings_preserved,'negative_fixture_checks':negative,'strict_json':True,'common_credential_pattern_scan':True,'agent_wording_origins_matched':len(trace['verified_origins']),'feedback_episodes_matched':len(trace['authentic_correction_episodes']),'context_record_checks':len(context['records']),'frozen_context_source_hashes_verified':len(context['sources']),'external_artifact_pointer_scopes':scoped}
    output_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--material',type=Path,default=CANDIDATE)
    parser.add_argument('--base-material',type=Path,default=BASE)
    parser.add_argument('--context-source-root',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'validation-result.json')
    args=parser.parse_args()
    main(args.material,args.base_material,args.context_source_root,args.output)
