"""Append this round's real user request and measured local results."""
import json
from pathlib import Path

path = Path('agent/conversation.json')
raw = path.read_bytes()
key = 'public_benchmark_hmy_20261109'
if key in json.loads(raw):
    raise SystemExit('record already exists; refusing to overwrite')
record = {
    'scope': '真实用户指令摘录、Agent 工作与本机工具结果；不是完整聊天导出，不推断学生技术理解。',
    'user_excerpt': {'source': 'student', 'content': '继续做先把3.3 小型性能 benchmark（40 分）完成，至少要把已经公开的能够跑通过。'},
    'agent_work': '按题面公开规模编写本地验证驱动，重建生产镜像，独立验证查询和重启后全部记录；正式驱动和官方基线未取得。',
    'tool_results': [
        '种子3179三轮及种子9143、27183、2468各一轮通过；每轮100批写入、1000个计时查询，过滤和无过滤平均Recall@10均为1.0，重启后核对全部10000条记录。',
        '提交确认后强杀：100批写入均已确认，重启后完整核对10000条记录通过；生产镜像公开功能桥20例、95条SQL通过。',
        'WSL共享ext4设备的16MiB同步写入校准观测到该容器io.stat写入增量16MiB；它不是官方独占数据设备统计。',
    ],
    'limitations': '仅本地开发协议及本地生成负载，未证明正式29例准入、正式驱动兼容、官方性能分数或名次；未提交或推送。',
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
print(f'learning material: {len(updated)} bytes')
