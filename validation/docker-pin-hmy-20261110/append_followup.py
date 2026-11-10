#!/usr/bin/env python3
"""Append only the user's actual replies and the surrounding agent questions."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
material = root / "agent/conversation.json"
manifest = Path(__file__).with_name("agent-followup-manifest.json")
before = "7cc5d7003b16cd418e3d94732d1b56a26dbf66db95d6164081d2730ad79fc891"
key = "user_followup_20261110"
if manifest.exists():
    raise SystemExit("refusing to overwrite evidence")
raw = material.read_bytes()
if hashlib.sha256(raw).hexdigest() != before:
    raise SystemExit("material changed; preserve and reassess rather than overwrite")
old = json.loads(raw)
if key in old:
    raise SystemExit("follow-up already present")
entry = {
    "scope": "Actual user and assistant excerpts; no student understanding inferred.",
    "messages": [
        {"role": "user", "source": "user_message", "content": "还差什么，继续做。"},
        {"role": "assistant", "source": "request_user_input_async", "content": "为了补充真实的 Agent 学习材料：看过上一轮两种 L2 方案的结果后，你自己会怎样判断要不要合入？请按实际理解回答；如果还不确定，直接写“不确定”即可。"},
        {"role": "user", "source": "user_answer", "content": "不确定。"},
        {"role": "assistant", "source": "commentary", "content": "没关系。判断时要同时看正确性和多轮对照：两种方案虽然通过了已做的正确性检查，但六组里都只有三组更快，且存在明显退化，所以目前不合入更稳妥。你的回答会按原样记录，不会写成你已经掌握了这些判断。"},
        {"role": "assistant", "source": "request_user_input_async", "content": "之前截图里 Agent Prompt 显示“本项没有有效原始分”。平台是否还能展开该项的评测报告或错误码？如果有，请复制原文；如果没有，回复“没有”即可。"},
        {"role": "user", "source": "user_answer", "content": "有这项"},
        {"role": "assistant", "source": "commentary", "content": "了解，平台上有这个评价项目。要判断为什么没有有效原始分，还需要看该项目展开后的具体提示；目前仅凭“有这项”无法确定原因。"},
        {"role": "assistant", "source": "request_user_input_async", "content": "请复制 Agent Prompt 项目展开后的错误提示或评测报告原文；如果只有“本项没有有效原始分”、不能展开，请回复“不能展开”。"},
        {"role": "user", "source": "user_answer", "content": "本项没有有效原始分  ，只有这个"},
        {"role": "assistant", "source": "commentary", "content": "明白，平台只显示“本项没有有效原始分”，没有更具体的错误信息；因此现在无法判断是材料、评审还是平台读取环节造成的。我会把这一限制和你的原话如实保留，同时完成本地材料与构建检查。"}
    ],
    "limitations": [
        "该片段仅记录本轮真实提问和回答；不把 Agent 的解释归因于用户。",
        "用户表示对优化合入判断不确定，本片段不证明用户独立理解或设计验证。",
        "没有进一步的官方评测报告或错误码；Agent 无有效原始分的原因尚未知。"
    ]
}
prefix = raw.rstrip()
if not prefix.endswith(b"}"):
    raise SystemExit("invalid object")
addition = (",\n  " + json.dumps(key) + ": " + json.dumps(entry, ensure_ascii=False, indent=2).replace("\n", "\n  ") + "\n}\n").encode()
new = prefix[:-1].rstrip() + addition
if len(new) > 128 * 1024:
    raise SystemExit("material exceeds 128 KiB")
updated = json.loads(new)
if updated[key] != entry or any(updated[k] != v for k, v in old.items()):
    raise SystemExit("previous material values changed")
material.write_bytes(new)
result = {"previous_sha256": before, "sha256": hashlib.sha256(new).hexdigest(),
          "bytes": len(new), "previous_values_unchanged": True,
          "student_understanding_inferred": False, "official_score_available": False}
manifest.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
