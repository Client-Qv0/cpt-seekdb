"""Append only real, attributed excerpts and local results to learning material."""
import json
from pathlib import Path

path = Path('agent/conversation.json')
raw = path.read_bytes()
original = json.loads(raw)
key = 'local_hmy_round_20261109'
if key in original:
    raise SystemExit('record already exists; refusing to overwrite')
record = {
    'scope': '本轮真实用户指令摘录、Agent 工作和本机工具结果；不是完整聊天导出，不推断学生的技术理解。',
    'user_excerpts': [
        {'source': 'student', 'content': '让我接着他的做。如果要下载什么环境的话尽量不要下在C盘，在E盘新建个文件夹可以下那里面。'},
        {'source': 'student', 'content': '对文件的修改先不要提交到远端Github仓库，先做好等我看完确认我自己手动提交。'},
    ],
    'agent_work': [
        '在 E 盘独立工作区重建 V2，扩展参考模型，实验列式缓存并保留在隔离快照；生产源码维持 V2。',
        '对照的查询时间有改善也有退化，未达到预设目标；原型预算峰值和磁盘 I/O 仍缺证据。',
    ],
    'tool_results': [
        '只读清单检查 13、49、320、141、206 项均零失败；本机 Release CTest 使用 Linux 临时目录 5/5 通过；公开桥 20 例、95 条 SQL 通过。',
        '128 MiB cgroup 下三组对照热查询秒数（V2/原型）：1.238757/1.198919、1.132450/1.340345、1.225005/1.281727。数据目录位于 tmpfs，不能作为磁盘物理 I/O 测量。',
    ],
    'limitations': '本记录仅摘要当前会话；用户没有对实验作技术解释或学习反馈。未提交、未推送、未参加正式评测。',
}
# Keep all earlier bytes intact and add a top-level property immediately before
# the closing brace. Validate both JSON and the contest size limit before write.
closing = raw.rfind(b'}')
if closing < 0 or raw[closing + 1:].strip():
    raise ValueError('unexpected JSON ending')
addition = (',\n  ' + json.dumps(key) + ': ' + json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
updated = raw[:closing] + addition + raw[closing:]
json.loads(updated)
if len(updated) > 128 * 1024:
    raise ValueError('learning material exceeds 128 KiB')
path.write_bytes(updated)
print(f'learning material: {len(updated)} bytes')
