"""Read retained evidence and render every paired summary metric; no DB execution."""
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
summary_path = root / "summary.json"
summary = json.loads(summary_path.read_text())
io_path = root / "io-last-live-summary.json"
io_summary = json.loads(io_path.read_text())


def number(value):
    return "—" if value is None else format(value, ".8g")


def values(items):
    return ", ".join(number(item) for item in items)


def stat_columns(stat):
    return [values(stat.get("values", [])), number(stat.get("median")),
            number(stat.get("minimum")) + "–" + number(stat.get("maximum")),
            number(stat.get("coefficient_of_variation"))]


def row(cells):
    return "| " + " | ".join(str(cell).replace("|", "\\|") for cell in cells) + " |"


lines = ["# V2 完整配对结果", "",
         "来源为完整 summary.json；不筛选轮次，不更改原始记录。每个负载顺序为第1组 B→C、第2组 C→B、第3组 B→C。B/C 为基线耗时除以候选耗时，小于1表示候选更慢。", "",
         "耗时单位为秒；CV 为总体标准差/均值。仅有三次重复，小毫秒阶段可能有较大相对波动。恢复指标包含 Docker 启动、数据库初始化/恢复、首条探针及响应消费；不是单独 WAL 重放时间。首次读不是 OS 冷缓存实验，没有全局 drop_caches。", "",
         "资源数字单位为字节，来自真实 cgroup。memory.peak 是内核全生命周期峰值；anon/file 是连续采样及阶段快照的最大值。分项峰值并不同时发生，memory.stat 也可能短时滞后，不能将不同分项峰值相加或以短时下降声称释放。", "",
         f"summary SHA256: `{hashlib.sha256(summary_path.read_bytes()).hexdigest()}`", "",
         f"本生成脚本 SHA256: `{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}`", ""]

for name, workload in summary["workloads"].items():
    lines += ["## " + name, "",
              "全部6轮通过：" + str(workload["all_six_runs_passed"]) + "；有效配对数：" + str(workload["valid_pairs"]), "",
              "### 全部耗时指标", "",
              row(["指标", "B三轮", "B中位数", "B范围", "B CV", "C三轮", "C中位数", "C范围", "C CV", "配对B/C三值", "配对B/C中位数"]),
              row(["---"] * 11)]
    for metric, paired in workload["paired_ratios"].items():
        baseline = workload["variants"]["baseline"]["timings"][metric]
        candidate = workload["variants"]["candidate"]["timings"][metric]
        lines.append(row([metric] + stat_columns(baseline) + stat_columns(candidate)
                         + [values(paired.get("values", [])), number(paired.get("median"))]))
    lines += ["", "负收益指标（配对B/C中位数 < 1，全部列出）：", ""]
    negatives = workload["negative_median_timing_benefit"]
    lines += ["- `" + metric + "`：" + number(workload["paired_ratios"][metric]["median"]) for metric in negatives] or ["- 无。"]
    lines += ["", "### 资源原始三轮值与汇总", "",
              row(["进程", "版本", "指标", "三轮原值", "中位数", "范围", "CV"]), row(["---"] * 7)]
    for process in ("main", "restart"):
        for variant in ("baseline", "candidate"):
            resource = workload["variants"][variant]["resources"][process]
            for metric, stat in resource["sampled_and_kernel_maxima"].items():
                lines.append(row([process, variant, metric] + stat_columns(stat)))
    lines += ["", row(["进程", "版本", "轮次", "memory.events 原始最大计数"]), row(["---"] * 4)]
    for process in ("main", "restart"):
        for variant in ("baseline", "candidate"):
            resource = workload["variants"][variant]["resources"][process]
            for index, counters in enumerate(resource["events_by_run"], 1):
                lines.append(row([process, variant, index, "`" + json.dumps(counters, sort_keys=True) + "`"] ))
    lines.append("")

lines += ["## io.stat 最后存活样本", "",
          io_summary["interpretation"], "",
          "以下 rbytes/wbytes 为对应 cgroup 最后存活样本的设备累计计数。没有执行结束后全程写回清算，也未做专用设备归因校准；不是数据库文件字节数，不是官方物理 I/O 评分值。不同设备分别保留，不做可能重复计数的堆叠设备求和。", "",
          f"IO JSON SHA256: `{hashlib.sha256(io_path.read_bytes()).hexdigest()}`", "",
          row(["运行", "进程", "最后采样阶段", "设备 major:minor", "rbytes", "wbytes"]), row(["---"] * 6)]
for entry in io_summary["entries"]:
    devices = entry["device_counters"] or [{"device_major_minor": "未报告"}]
    for device in devices:
        lines.append(row([entry["run"], entry["role"], entry.get("last_live_stage"), device["device_major_minor"],
                          device.get("rbytes", "未报告"), device.get("wbytes", "未报告")]))

lines += ["", "初始容器创建耗时仅保存在各 run.json 的 initial_container_launch_seconds 元数据中，不在冻结工具的 summary 对比指标内。上表包含 summary 中全部计时指标；未将进程就绪或单独重放时间从容器创建时间中猜测扣除。", ""]
(root / "TABLES.md").write_text("\n".join(lines), encoding="utf-8")
print(json.dumps({"table": str(root / "TABLES.md"), "summary_unchanged_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
                  "io_entries": io_summary["entry_count"]}, indent=2))
