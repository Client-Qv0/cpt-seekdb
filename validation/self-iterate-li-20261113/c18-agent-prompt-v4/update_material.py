import json
from pathlib import Path

path = Path('/home/li/minivectordb-self-iterate-20261113/agent/conversation.json')
doc = json.loads(path.read_text(encoding='utf-8'))

conversation = {
    'id': 'self-iterate-li-20261113',
    'scope': '2026-11-13 autonomous MiniVectorDB performance and Agent Prompt iteration',
    'messages': [
        {'id': 'negative-rule', 'source': 'student', 'authorship_verified': True,
         'content': '负结果只在本地保留，不 commit、不推送、不计入五轮上限。'},
        {'id': 'validation-rule', 'source': 'student', 'authorship_verified': True,
         'content': '每轮实验使用新的 validation 子目录，保存命令、原始数据、二进制/镜像哈希和报告。'},
        {'id': 'five-success-rule', 'source': 'student', 'authorship_verified': True,
         'content': '只有通过性能门槛并保留生产代码的成功优化才 commit；最多累计 5 个成功 commit。'},
        {'id': 'stop-rule', 'source': 'student', 'authorship_verified': True,
         'content': '达到 5 个成功 commit 后停止'},
        {'id': 'server-only', 'source': 'student', 'authorship_verified': True,
         'content': '通过mcp+ssh，所有东西都在服务器上弄，完成接手的任务'},
        {'id': 'self-iteration', 'source': 'student', 'authorship_verified': True,
         'content': '我要睡觉了，接下来的时间你来进行自迭代，自行思考下一步的“性能”和“prompt”的提升优化方案，并执行。'},
        {'id': 'invariants', 'source': 'student', 'authorship_verified': True,
         'content': '保留 V2 的内存收益、事务原子性和崩溃恢复正确性。'},
    ],
}
doc['conversations'].append(conversation)
conv_index = len(doc['conversations']) - 1

experiments = [
    {
        'id': 'server-bound-execution',
        'source': 'tool_output_summary',
        'executed': True,
        'content': '本轮构建、单元/压力/公开/Docker 验证、Git fetch/commit/push 和原始日志采集均在 li@103.236.99.247 的 MCP SSH 会话内执行；未创建 PR，未修改比赛分支，未提交正式评测。',
        'context': 'Only branch perf/self-iterate-li-20261113 received pushes.'
    },
    {
        'id': 'successful-optimizations-1-4',
        'source': 'tool_output_summary',
        'executed': True,
        'content': '保留优化：7168a647 直接紧凑视图输出，六对查询+8.688%/6胜；6c1c32d2 帧合并写，写入+6.648%/6胜；76f4df0a 语句缓冲，写入+6.755%/5胜；c8d86836 同步写提交，写入+2.096%/5胜。',
        'context': 'Local cgroup A/B measurements; not an official score.'
    },
    {
        'id': 'negative-results-local-only',
        'source': 'tool_output_summary',
        'executed': True,
        'content': 'C1、C2、C3、C4、C5、C6、C8、C9、C10、C11、C14、C15、C16 未达到各自门槛；均为本地负结果，不 commit、不推送、不计入成功轮次。',
        'context': 'Patches and raw results remain under /home/li/mvdb-negative-local-20261113.'
    },
    {
        'id': 'validation-directory-discipline',
        'source': 'tool_output_summary',
        'executed': True,
        'content': '每个保留或否决候选都有独立 validation 目录，保存 candidate patch、A/B 原始 JSON、summary、构建与测试日志、二进制/镜像哈希以及 REPORT 和 RESULTS。',
        'context': 'Negative evidence stayed local; retained evidence was committed with its successful change.'
    },
    {
        'id': 'd21-platform-report',
        'source': 'platform_user_report',
        'executed': True,
        'content': 'd21e8f85 官方结果：MySQL 正式用例通过；性能原始分 3306.163332；Agent Prompt 原始分 3.000000。该历史结果不用于声称 v4 已获得更高官方分。',
        'context': 'Platform/user report supplied before this iteration.'
    },
]
exp_base = len(doc['experiments'])
doc['experiments'].extend(experiments)

def student_evidence(index):
    return {'pointer': f'/conversations/{conv_index}/messages/{index}/content',
            'quote': conversation['messages'][index]['content']}

def result_evidence(index):
    return {'pointer': f'/experiments/{exp_base + index}/content',
            'quote': experiments[index]['content']}

new_units = [
    {
        'id': 'evidence-directory-discipline',
        'chain_id': 'candidate-evidence-directories',
        'dimension': 'problem_understanding',
        'score': 1.5,
        'reason': '用户为每轮实验规定了新的 validation 目录和证据包内容。Agent 按该要求分别保存成功与否决候选，保留了提交绑定、原始测量、哈希和报告，能够支持独立复核。',
        'student_evidence': [student_evidence(1)],
        'result_evidence': [result_evidence(3), result_evidence(1)],
    },
    {
        'id': 'server-only-execution',
        'chain_id': 'mcp-ssh-server-execution',
        'dimension': 'technical_transfer',
        'score': 1.0,
        'reason': '用户要求全部工作通过 MCP SSH 在服务器执行。实际构建、测试、Docker、Git 和证据采集均在该路径完成，并把远端分支限制落实为可核对的执行结果；学生证据只计其执行边界要求。',
        'student_evidence': [student_evidence(4)],
        'result_evidence': [result_evidence(0)],
    },
    {
        'id': 'negative-results-not-counted',
        'chain_id': 'negative-results-excluded',
        'dimension': 'independent_validation',
        'score': 2.0,
        'reason': '用户明确否定了用失败实验凑提交的做法。后续十三项候选未过门槛时均保留本地证据但不提交；只有独立满足目标指标的候选进入分支，形成了学生约束与工具结果的完整验证链。',
        'student_evidence': [student_evidence(0)],
        'result_evidence': [result_evidence(2), result_evidence(1)],
    },
    {
        'id': 'bounded-self-iteration',
        'chain_id': 'five-success-stop-loop',
        'dimension': 'experimental_iteration',
        'score': 2.0,
        'reason': '用户要求自主循环同时设置五成功提交停止线。实际过程先形成四个保留优化，并在多个失败候选后继续按证据调整；材料和最终提交按停止规则收束，没有把负结果计入轮次。',
        'student_evidence': [student_evidence(2), student_evidence(3)],
        'result_evidence': [result_evidence(1), result_evidence(2)],
    },
    {
        'id': 'performance-prompt-balance',
        'chain_id': 'performance-and-material-balance',
        'dimension': 'tradeoff_reflection',
        'score': 2.0,
        'reason': '用户同时要求性能与 prompt 推进，并保留内存、事务原子性和恢复正确性。四轮保留改动分别覆盖查询与写入，且都通过恢复、公开和 Docker 回归；材料同步记录历史有效 Agent 分但不提前宣称 v4 官方提升。',
        'student_evidence': [student_evidence(6), student_evidence(5)],
        'result_evidence': [result_evidence(1), result_evidence(4)],
    },
]
doc['units'].extend(new_units)

dimension_units = {
    'problem_understanding': ['evidence-directory-discipline'],
    'technical_transfer': ['server-only-execution'],
    'independent_validation': ['negative-results-not-counted'],
    'experimental_iteration': ['bounded-self-iteration'],
    'tradeoff_reflection': ['performance-prompt-balance'],
}
for dimension in doc['dimensions']:
    dimension['unit_ids'].extend(dimension_units[dimension['id']])

doc['summary'] = ('MiniVectorDB v4 材料：保留真实用户约束、四轮成功性能证据、十三项本地负结果和'
                  'd21 的历史官方反馈。学生原话、Agent 执行与工具结果分开归因；性能数字均为本地证据，'
                  '不宣称 v4 已获得新的官方分数。')
doc['coverage']['source_version'] = ('生产源码绑定 c8d86836bdf4e9b69b2836d047cb839878f0caa7；'
                                     'v4 材料修订随第五个成功提交另行提交。')
doc['coverage']['material_revision'] = 'agent-learning-evidence-v4'
doc['limitations'] = [
    '所有引用均来自材料内真实原话；四个性能数字是本地 cgroup A/B 配对结果，不是官方成绩。',
    'd21 的 Agent Prompt 3.000000 是历史平台结果；本材料尚未正式评测，不保证排名或分数提升。',
    'Agent 生成的算法、代码、测量和解释没有转记为学生贡献。',
    '负结果证据保留在服务器本地目录，未包含在 fork 分支提交中。',
]

path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(path.stat().st_size)
