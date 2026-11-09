# 目标分支本地提交前核对

日期：2026-11-09。基于 `944c08ee3549a625706801565fe570d804e58928` 创建本地 `2026-competition-round2`。该基础已包含 `handoff/minivectordb-v2`、`perf/update-latency-li-20261109` 与 `perf/exact-query-li-20261109` 三个当时远端分支的提交，无需重复合并。默认生产源码仍是 V2，列式方案及精确剪枝留在实验快照。

从 F 盘源码构建的 Release 二进制 SHA-256 为 `78996ec9a6d15c5357b5111a4fd78ed28bf1cde174538dee81ae5de1b2daf26c`。本轮本地提交前检查：CTest 5/5；Agent 学习材料检查 5/5；公开桥单元检查 4/4；常规优化回归 11 项通过、大输出类 1 项跳过；公开样例 20 例、95 条 SQL 通过。历史清单 13、49、320 项与近期 103 项证据文件均匹配；学习材料因本轮真实追加而改变，旧哈希与新哈希的关系见 `previous-evidence.txt`。这些不是正式平台的结果。

对 237 个本次工作文件及 12 个 gzip 内容执行了有限的常见凭据格式扫描，未发现所列模式（`scan-result.json`）。该扫描不能保证发现全部敏感数据。F 盘既有未跟踪文件 `rust/Cargo.lock` 与本任务无关，不应暂存。

本地性能验证及限制见 `validation/benchmark-public-hmy-20261109/REPORT.md`；学习材料与限制见 `validation/agent-learning-hmy-20261109/REPORT.md`。官方通信协议和 29 个正式准入用例尚未验证，不能推断性能得分或官方成绩。没有调用正式评测。
