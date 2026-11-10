#!/usr/bin/env python3
"""Append genuine continuation evidence without rewriting existing JSON values."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
out = Path(__file__).resolve().parent
material = root / "agent/conversation.json"
manifest = out / "agent-append-manifest.json"
prior_sha = "e5e0ebd2f17ac717ae4e2b711dd700cc2e1b15014d3ab2ea24d0610e88d4f702"
if manifest.exists():
    raise SystemExit("refusing to overwrite append manifest")
raw = material.read_bytes()
if hashlib.sha256(raw).hexdigest() != prior_sha:
    raise SystemExit("existing material changed; preserve it and reassess before appending")
doc = json.loads(raw)
key = "hmy_l2_followup_20261110"
if key in doc:
    raise SystemExit("continuation already present")
results = []
for name in ("paired-main", "paired-overflow", "simd-paired-main", "simd-paired-overflow"):
    source = out / name / "paired-summary.json"
    item = json.loads(source.read_text())
    results.append({
        "experiment": name,
        "summary_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "faster_pairs": item["faster_query_pairs"],
        "pairs": len(item["pairs"]),
        "median_paired_query_reduction": item["median_paired_query_reduction"],
        "oracle_checks": item["total_oracle_checks"],
        "rounds": [
            {"round": p["round"], "base_query_s": p["base"]["times"]["query_s"],
             "candidate_query_s": p["candidate"]["times"]["query_s"],
             "paired_reduction": p["query_reduction"]}
            for p in item["pairs"]
        ],
    })
entry = {
    "scope": "Actual user request, agent actions and recorded local tool results; no student technical understanding inferred.",
    "messages": [
        {"role": "user", "content": "这是我队友完成情况介绍，现在交接到我手上了。先把我队友做的内容拉去下来。再接着完成任务。图片是我们现在进度的测评结果。"},
        {"role": "assistant", "content": "我会先保护当前本地未提交的文件，拉取并核对队友的交接提交，再按交接文档复现基线、调查 L2 热点和检查 Agent Prompt 材料。"},
        {"role": "tool", "content": "远端交接 HEAD 为 df451b5dd6f3653eb3d0a1ed16e20a527252c6f9；本机重建的 6576 生产基线 Release 二进制 SHA256 为 1d36080209fc61c2d4c5b65fdf2a0587048939b3c51e2eca34644bf848ec98b9。Release CTest 6/6，黑盒 21/21，额外回归 14/14；官方原版 f4d4e266 驱动的本机基线镜像握手、CRUD 和全部 20 公开用例通过。"},
        {"role": "tool", "content": "原生开发协议 10k×128 热查询采样 539 个 cpu-clock:u 样本、0 丢失；其中 429 个样本落在 project 函数，反汇编显示其主要落在距离循环。这是诊断而非官方性能指标。"},
        {"role": "assistant", "content": "先增加独立 FP32 距离参考与基线逐响应比较，再依次验证严格大于阈值的分块提前终止和保持标量累加顺序的 SSE2 产品计算。两种方案单独运行，完成后均将生产源码恢复。"},
        {"role": "tool", "content": "新增差分检查在三个种子与 11 个维度执行 858 条 SQL；SIMD 与基线返回完全一致，独立参考核验 ID、过滤、顺序和距离通过。两种候选的逐轮性能结果见本对象内 paired_experiments；这些仅为本机对照。"},
        {"role": "assistant", "content": "两种候选在六组主负载各只有 3 组查询更快，收益不稳定；因此均未保留生产改动。共享机器其他容器可能干扰，不能从本地结果推断官方排名或分数。"}
    ],
    "paired_experiments": results,
    "limitations": [
        "用户截图和队友交接把正式通过及性能原始分 2277.870638 关联到旧提交 7637a037e8a44c9da8e3bd65694e4474075b5657，不归给本次版本。",
        "用户截图显示 Agent Prompt 当时没有有效原始分，具体原因未证实；本地格式检查不是官方语义评分。",
        "公开 20 例通过不证明当前版本通过全部隐藏正式用例。本次没有正式提测。",
        "io.stat 仅记录 ready 到 shutdown 前的原始计数，不是完整生命周期、专用设备物理 I/O。",
        "本轮没有新增用户自行解释、验证或复盘技术假设的记录，不把 Agent 的解释归因于用户。"
    ]
}
prefix, closing = raw.rstrip()[:-1].rstrip(), raw.rstrip()[-1:]
if closing != b"}":
    raise SystemExit("unexpected material structure")
addition = (",\n  " + json.dumps(key) + ": " + json.dumps(entry, ensure_ascii=False, indent=2).replace("\n", "\n  ") + "\n}\n").encode()
new = prefix + addition
if len(new) > 128 * 1024:
    raise SystemExit("material would exceed 128 KiB")
updated = json.loads(new)
if updated[key] != entry or any(updated[k] != v for k, v in doc.items()):
    raise SystemExit("existing evidence changed unexpectedly")
material.write_bytes(new)
record = {
    "prior_sha256": prior_sha,
    "new_sha256": hashlib.sha256(new).hexdigest(),
    "new_bytes": len(new),
    "previous_object_values_unchanged": True,
    "student_understanding_inferred": False,
    "official_scoring_performed": False,
}
manifest.write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record, indent=2))
