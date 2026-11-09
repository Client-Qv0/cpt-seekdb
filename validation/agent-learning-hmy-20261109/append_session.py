"""Append attributed excerpts from this actual session, preserving prior bytes."""
import hashlib
import json
from pathlib import Path

path = Path('agent/conversation.json')
raw = path.read_bytes()
key = 'current_session_hmy_20261109'
if key in json.loads(raw):
    raise SystemExit('Session record already exists; refusing to overwrite it.')

offline = Path('validation/benchmark-public-hmy-20261109/offline-audit.txt').read_text(encoding='utf-8')
crash = Path('validation/benchmark-public-hmy-20261109/crash-recovery.txt').read_text(encoding='utf-8')
public = Path('validation/worktree-migration-hmy-20261109/public-samples.txt').read_text(encoding='utf-8')
assert 'seed-2468-audit round 1: passed' in offline and 'exit=0' in offline
assert '"readback_rows": 10000' in crash and 'exit=0' in crash
assert '{"passed": true, "cases": 20, "statements": 95}' in public

dialogue = [
    {'id': 'student-benchmark-question', 'source': 'student',
     'content': '### 3.3 小型性能 benchmark（40 分）这个完成了吗/'},
    {'id': 'agent-benchmark-answer', 'source': 'agent',
     'content': '目前通过的是 20 个公开样例、95 条 SQL；正式的 29 个 MySQL case 尚未全部验证通过。'},
    {'id': 'student-vscode-question', 'source': 'student',
     'content': '你改了什么，为什么我vscode里面资源管理器没有显示有什么修改？'},
    {'id': 'student-submission-question', 'source': 'student',
     'content': '可是我后面提交不是要测试seekdb 仓库的 `2026-competition-round2`，你写在E:\\MiniVectorDB\\work我怎么git提交？'},
    {'id': 'agent-worktree-answer', 'source': 'agent',
     'content': 'E 盘目录虽然是独立工作区，但它仍然连接着同一个 Git 仓库，可以正常提交。'},
    {'id': 'student-branch-question', 'source': 'student',
     'content': '是不是要创立`2026-competition-round2`  分支，然后给这些分支的内容整理到`2026-competition-round2`里面去？'},
    {'id': 'agent-branch-answer', 'source': 'agent',
     'content': '最新的 `perf/exact-query-li-20261109` 已经包含前两条分支的提交。'},
    {'id': 'student-move-request', 'source': 'student',
     'content': 'E:\\MiniVectorDB\\work能不能给这部分内容搞到F:\\OceanBase\\seekdb\\cpt-seekdb，分两个地方看起来费劲'},
    {'id': 'agent-move-answer', 'source': 'agent',
     'content': '文件已经复制到 F 盘，212 个文件与 E 盘副本的哈希逐一一致，原生产源码的历史清单也通过了校验。'},
    {'id': 'student-next-task', 'source': 'student',
     'content': '队友在创建分支，我先继续做下一个任务。'},
]
observations = [
    {'id': 'six-round-offline-audit', 'source': 'tool_output',
     'content': offline, 'context': '本地 seed 3179 三轮，以及 9143、27183、2468 各一轮；原始输出摘录，非官方驱动。'},
    {'id': 'post-commit-kill', 'source': 'tool_output',
     'content': crash, 'context': '100 批确认写入后主动 SIGKILL，单独重启并回读 10000 条；不是断电测试。'},
    {'id': 'git-worktrees', 'source': 'tool_output_excerpt',
     'content': 'F:/OceanBase/seekdb/cpt-seekdb 75214d472 [2026-competition]\nE:/MiniVectorDB/work           944c08ee3 [codex/minivectordb-hmy-20261109]',
     'context': '用户提出提交路径问题时只读检查的结果；这是当时状态。'},
    {'id': 'worktree-copy-verification', 'source': 'tool_output',
     'content': 'Verified 212 files in both worktrees.',
     'context': '根据迁移前 SHA-256 清单逐项复核 E、F 两个工作区的 212 个本轮文件。'},
    {'id': 'f-worktree-public', 'source': 'tool_output_excerpt',
     'content': '{"passed": true, "cases": 20, "statements": 95}\nexit=0',
     'context': '从 F 盘源码本机重建后的本地公开样例桥；不是正式 29 例准入。'},
]
record = {
    'scope': '本次会话的可核对摘录；保留学生、Agent 和工具来源，非完整聊天导出。',
    'historical_attribution': '此前条目来自队友交接或更早工作记录，身份和完整会话无法在本次会话中独立验证；不得自动归为当前学生的技术理解。',
    'prior_material_sha256': hashlib.sha256(raw).hexdigest(),
    'dialogue': dialogue,
    'tool_observations': observations,
    'evidence_links': [
        {'context': '本地 benchmark 任务及事后核验；任务指令本身不自动证明学生技术理解。',
         'student_pointer': '/public_benchmark_hmy_20261109/user_excerpt/content',
         'student_excerpt': '继续做先把3.3 小型性能 benchmark（40 分）完成，至少要把已经公开的能够跑通过。',
         'result_pointer': f'/{key}/tool_observations/0/content',
         'result_excerpt': 'seed-3179 round 1: passed\nseed-3179 round 2: passed\nseed-3179 round 3: passed'},
        {'context': '用户提出分离工作区与提交位置的疑问，工具结果记录当时两个工作区。',
         'student_pointer': f'/{key}/dialogue/3/content',
         'student_excerpt': '可是我后面提交不是要测试seekdb 仓库的 `2026-competition-round2`，你写在E:\\MiniVectorDB\\work我怎么git提交？',
         'result_pointer': f'/{key}/tool_observations/2/content',
         'result_excerpt': 'E:/MiniVectorDB/work           944c08ee3 [codex/minivectordb-hmy-20261109]'},
        {'context': '用户要求把工作集中到 F 盘；工具检查迁移后文件与备份一致。',
         'student_pointer': f'/{key}/dialogue/7/content',
         'student_excerpt': 'E:\\MiniVectorDB\\work能不能给这部分内容搞到F:\\OceanBase\\seekdb\\cpt-seekdb，分两个地方看起来费劲',
         'result_pointer': f'/{key}/tool_observations/3/content',
         'result_excerpt': 'Verified 212 files in both worktrees.'},
    ],
    'limitations': [
        '引用链接仅辅助定位真实材料，不是评分或保证得分；泛泛任务指令不自动构成有效实例。',
        '没有把用户的问题当成已掌握数据库机制；没有将 Agent 方案、解释或验证自动归因给学生。',
        '公开 20 例/95 SQL 与本地性能实验不等于正式 29 例、正式通信协议或官方得分。',
        '本次对话和历史队友对话均非完整导出；缺失的学习过程不能补造。',
    ],
}
closing = raw.rfind(b'}')
if closing < 0 or raw[closing + 1:].strip():
    raise ValueError('unexpected JSON ending')
addition = (',\n  ' + json.dumps(key) + ': ' + json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
updated = raw[:closing] + addition + raw[closing:]
json.loads(updated)
if len(updated) > 128 * 1024:
    raise ValueError('learning material exceeds 128 KiB')
path.write_bytes(updated)
print(f'appended {key}; prior_sha256={record["prior_material_sha256"]}; bytes={len(updated)}')
