import json
from pathlib import Path
path=Path('/home/li/minivectordb-self-iterate-20261113/agent/conversation.json')
doc=json.loads(path.read_text(encoding='utf-8'))
if not any(e['id']=='v4-local-structural-validation' for e in doc['experiments']):
    doc['experiments'].append({
        'id':'v4-local-structural-validation',
        'source':'tool_output_summary',
        'executed':True,
        'content':'v4 本地结构审计：tests/test_agent_material.py 8 tests passed；严格 JSON、五维 unit、pointer、原文匹配、跨维度去重、分数档和 128 KiB 上限检查均通过；不代表官方语义评分。',
        'context':'Local structural check after v4 content update.'
    })
path.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
