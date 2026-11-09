"""Read-only postprocessing of original paired evidence and sampler controls."""
from pathlib import Path
import hashlib
import json
import statistics
import sys

control, original = map(Path, sys.argv[1:3])


def ints(text):
    result = {}
    for line in (text or "").splitlines():
        fields = line.split()
        if len(fields) == 2:
            try:
                result[fields[0]] = int(fields[1])
            except ValueError:
                pass
    return result


def io(text):
    return {fields[0]: {key: int(value) for key, value in [field.split("=") for field in fields[1:]]}
            for fields in [line.split() for line in (text or "").splitlines()]}


def pressure(text):
    result = {}
    for line in (text or "").splitlines():
        fields = line.split()
        for field in fields[1:]:
            if field.startswith("total="):
                result[fields[0]] = int(field.split("=")[1])
    return result


def delta(before, after):
    return {key: after[key] - before[key] for key in after if key in before}


def metrics(before, after):
    bi, ai = io(before.get("io.stat")), io(after.get("io.stat"))
    return {"cpu_stat_present": "cpu.stat" in before and "cpu.stat" in after,
            "cpu_delta": delta(ints(before.get("cpu.stat")), ints(after.get("cpu.stat"))),
            "memory_pressure_total_delta_usec": delta(pressure(before.get("memory.pressure")), pressure(after.get("memory.pressure"))),
            "cpu_pressure_total_delta_usec": delta(pressure(before.get("cpu.pressure")), pressure(after.get("cpu.pressure"))),
            "io_pressure_total_delta_usec": delta(pressure(before.get("io.pressure")), pressure(after.get("io.pressure"))),
            "io_device_counter_delta": {device: delta(bi[device], ai[device]) for device in ai if device in bi}}


analysis = {"script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "conclusion": "The cause of the original consistent UPDATE slowdown remains unknown. Sampler on/off controls show large outliers and do not establish Python GIL/sampling as a sufficient cause. Neither the earlier negative observation nor the complete paired evidence is overwritten.",
            "limitations": ["Original adapter did not record cpu.stat; a sampler timestamp marks snapshot start, not the full thread execution interval.",
                            "Counter deltas are observations, not syscall service times. Small intervals can expose accounting granularity or lag.",
                            "Controls copy/recover frozen WAL rather than rebuild the original write-then-read allocator and page-cache history.",
                            "Controls add synchronous before/after captures outside individual SQL timers. Transaction sums exclude those gaps and are not identical to the original grouped timer.",
                            "Only three pairs per control; no post hoc selection or further runs were used."],
            "original": [], "controls": []}
for path in sorted(original.glob("cardinality-vector4-1000000-pair-*/run.json")):
    run = json.loads(path.read_text())
    snapshots = {entry["label"]: entry["snapshot"] for entry in run["snapshots"]}
    for phase in ("process_first_pk_query", "update_cache_invalidation", "transaction_rollback_commit_restore"):
        before, after = snapshots[phase + ":before"], snapshots[phase + ":after"]
        entry = {"run": run["run_label"], "variant": run["variant"], "phase": phase,
                 "seconds": run["timings"][phase + "_seconds"],
                 "run_json_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                 "sampler_snapshot_starts_within_phase_window": [sample["monotonic"] for sample in run["container_record"]["samples"]
                     if before["monotonic"] <= sample["monotonic"] <= after["monotonic"]],
                 **metrics(before, after)}
        analysis["original"].append(entry)

for path in sorted(control.glob("pair-*/run.json")):
    run = json.loads(path.read_text())
    snapshots = {entry["label"]: entry["values"] for entry in run["snapshots"]}
    observed = []
    for response in run["responses"]:
        phase = response["phase"]
        if response["target_measurement"]:
            observed.append({"phase": phase, "seconds": response["elapsed_seconds"],
                             **metrics(snapshots[phase + ":before"], snapshots[phase + ":after"])})
    combined = []
    for index in range(5):
        combined.append(sum(entry["elapsed_seconds"] for entry in run["responses"]
                            if entry["phase"] in (f"iteration-{index}:update", f"iteration-{index}:verify")))
    analysis["controls"].append({"run": run["label"], "variant": run["variant"], "sampler": run["sampler"],
                                  "pair": run["pair"], "passed": run["passed"],
                                  "run_json_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                  "update_verify_sum_seconds_excluding_captures": combined,
                                  "per_sql_observations": observed})

(control / "analysis.json").write_text(json.dumps(analysis, indent=2) + "\n")
lines = ["# 单行更新延迟调查", "", analysis["conclusion"], "", "## 原18轮中相关观测", "",
         "| 运行 | 阶段 | 毫秒 | CPU计数存在 | io.stat阶段增量 | sampler起始时间戳落入窗口数 |",
         "| --- | --- | ---: | --- | --- | ---: |"]
for entry in analysis["original"]:
    lines.append("| " + " | ".join([entry["run"], entry["phase"], f"{entry['seconds'] * 1000:.4f}", str(entry["cpu_stat_present"]),
                                   "`" + json.dumps(entry["io_device_counter_delta"]) + "`",
                                   str(len(entry["sampler_snapshot_starts_within_phase_window"]))]) + " |")
lines += ["", "## 12次固定对照：每次5个UPDATE+SELECT", "",
          "两个SQL耗时求和，排除中间同步采样；不是原来连续分组计时的替代值。", "",
          "| 运行 | 五次合计耗时（毫秒） | 中位数（毫秒） | UPDATE CPU usage_usec阶段增量 | UPDATE nr_throttled阶段增量 |",
          "| --- | --- | ---: | --- | --- |"]
for entry in analysis["controls"]:
    updates = [item for item in entry["per_sql_observations"] if item["phase"].endswith(":update") and item["phase"].startswith("iteration-")]
    elapsed = [value * 1000 for value in entry["update_verify_sum_seconds_excluding_captures"]]
    lines.append("| " + " | ".join([entry["run"], ", ".join(f"{value:.4f}" for value in elapsed), f"{statistics.median(elapsed):.4f}",
                                   str([item["cpu_delta"].get("usage_usec") for item in updates]),
                                   str([item["cpu_delta"].get("nr_throttled") for item in updates])]) + " |")
lines += ["", "## 证据边界", ""] + ["- " + item for item in analysis["limitations"]] + [""]
(control / "ANALYSIS.md").write_text("\n".join(lines), encoding="utf-8")
print(json.dumps({"original_phase_observations": len(analysis["original"]), "control_runs": len(analysis["controls"]),
                  "all_controls_passed": all(entry["passed"] for entry in analysis["controls"]), "conclusion": analysis["conclusion"]}, indent=2))
