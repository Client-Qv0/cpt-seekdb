import json
from pathlib import Path

path = Path('/home/li/minivectordb-self-iterate-20261113/agent/conversation.json')
doc = json.loads(path.read_text(encoding='utf-8'))
existing = {experiment['id'] for experiment in doc['experiments']}
new_experiments = [
    {
        'id': 'retained-c7-query',
        'source': 'tool_output_summary',
        'executed': True,
        'content': '成功提交 7168a647 将 TopK winner 直接从紧凑视图投影：最终源码六对查询中位+8.688%、6/6胜；写入+0.794%、数据字节不变；完整 Release、公开和 Docker 矩阵通过。',
        'context': 'Local cgroup A/B, not official.'
    },
    {
        'id': 'retained-c12-pwritev',
        'source': 'tool_output_summary',
        'executed': True,
        'content': '成功提交 6c1c32d2 将每帧三次 pwrite64 合并为一次 pwritev：六对写入中位+6.648%、6/6胜；1000 行帧写系统调用从 3015 降到 1012，崩溃与恢复测试通过。',
        'context': 'Local syscall and cgroup evidence, not official.'
    },
    {
        'id': 'retained-c13-statement-buffer',
        'source': 'tool_output_summary',
        'executed': True,
        'content': '成功提交 76f4df0a 按语句缓冲 journal 帧：六对写入中位再降6.755%、5/6胜；1000 行的相关 traced syscall 从 1026 降到 36，语句内读、回滚与恢复通过。',
        'context': 'Local syscall and cgroup evidence, not official.'
    },
    {
        'id': 'retained-c17-dsync',
        'source': 'tool_output_summary',
        'executed': True,
        'content': '成功提交 c8d86836 用小语句 pwritev2(RWF_DSYNC) 合并数据与 commit marker：写入中位+2.096%、5/6胜；1000 行 traced syscall 从 36 降到 14。',
        'context': 'Durability and public matrices passed; not an official score.'
    },
]
for experiment in new_experiments:
    if experiment['id'] not in existing:
        doc['experiments'].append(experiment)

exp_by_id = {experiment['id']: (i, experiment)
             for i, experiment in enumerate(doc['experiments'])}

def result_ref(experiment_id):
    index, experiment = exp_by_id[experiment_id]
    return {'pointer': f'/experiments/{index}/content', 'quote': experiment['content']}

unit_results = {
    'evidence-directory-discipline': ['retained-c7-query', 'validation-directory-discipline'],
    'server-only-execution': ['server-bound-execution'],
    'negative-results-not-counted': ['negative-results-local-only'],
    'bounded-self-iteration': ['retained-c12-pwritev', 'retained-c13-statement-buffer'],
    'performance-prompt-balance': ['retained-c17-dsync', 'd21-platform-report'],
}
for unit in doc['units']:
    if unit['id'] in unit_results:
        unit['result_evidence'] = [result_ref(item) for item in unit_results[unit['id']]]

path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(path.stat().st_size)
