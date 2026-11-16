# 瘦视图：从原日志精算的本地实验

基线：`f9a61047e4fb8a6fa2f63768d603065f05b2de93`。结论：**内存收益成立；本机未能证明查询退化不超过 3%，暂停生产接入。** 只提交实验材料。没有官方提测，也没有修改 Agent Prompt 材料。

## 原型和对照

- A：原版交织 FP32 视图和 AVX2 精算。
- B：保留同大小的 FP32 副本，改为行主序。
- C：用每行偏移和只读映射代替 FP32 副本，B/C 共用同一个转置后精算内核。int8 码和 postings 的算法相同，也不写额外的重排文件。
- `make_probe.py` 只用于修改独立构建副本；它不是可直接上线的补丁。原型未覆盖生产接入所需的完整生命周期验证。

本机 WSL2、ext4 `/dev/sdd`（8:48）、数据库 cgroup v2 独立于驱动、CPU 0/2、2 CPU 配额、2 GiB、零 swap。10,000×128、100 批自动提交、10 条预热、1,000 条正式 JSONL 查询，过滤和无过滤各半，种子 3179／3181／3187。确认轮驱动绑 CPU 4。同轮各组用新数据目录。写入在每次成功回包前完成原有同步；IO 是本地 cgroup 读数，并未复刻平台冷缓存、独立写回流程。

## 结果

耗时差用候选 / 对照 − 1 表示，负值更快。六轮 A/B/C 筛查：B 比 A 混合查询中位 −7.04%，C 比 A −3.15%，两者区间都很宽，不据此把差异归给布局或缺页。C 比 A 峰值内存中位少 5.09 MiB。

随后做 20 轮错开次序的 A/A′/C 确认，其中 A 和 A′ 用完全相同的控制二进制：

| 项目 | C 对同轮两份基线的几何平均 | 配对中位差的描述性 95% bootstrap 区间 |
|---|---:|---:|
| 混合查 | −2.29% | −7.36% 到 +4.39% |
| 有过滤 | −1.09% | −7.80% 到 +5.95% |
| 无过滤 | −3.34% | −7.17% 到 +4.31% |
| 写入 | −1.80% | −4.45% 到 +1.13% |

- A/A′ 混合查询中位差 +2.28%，IQR 15.42 个百分点。C 对单份 A 的混合中位差 −1.53%，区间 −9.80% 到 +8.54%。两种分母都不能排除 3% 以上退化。
- C 对 A 的数据库 `memory.peak` **20/20 轮降低**，中位 **−4.88 MiB**，单轮至少降低 4.50 MiB。达到内存门槛。
- 20 轮三组在目标设备上都记到 6,049,792 B 写入；C 未观察到物理读取，A 一轮记到额外读取。仅说明本地这批运行里没有观测到 C 增加 I/O。
- 确认轮的 20,000 条查询，三组完整有序 JSONL 回包的逐轮 SHA-256 都相同。基线和诊断构建分别通过 Release CTest 9/9。
- 独立标量参考另外核对 30 条查询的 ID、顺序和距离位模式，包含乱序写入、等距、向量投影、降序、查询码域回退、显式事务回滚及删除后重建；命中三次映射视图。未跑发布候选才需要的完整 128 MiB、checkpoint／SIGKILL 和官方公开包矩阵。

## 后备：写入阶段拆分

在相同的 100 批自动提交内做六轮诊断。日志 durably flush 约 295–394 ms；转换和打包约 73–80 ms；CRC 约 23–28 ms；重复键、`account_live`、`overlay` 合计约 9–12 ms。计时包括创建表的少量固定成本，且 CRC 是 append 的子阶段，不重复相加。诊断流程中没有改变同步次数、回包时机或事务策略。单项 CRC 即使完全消掉也不到本地写入 T 的 5%，索引操作更少，不写性能候选。

## 复现与后续

`first/`、`aa/`、`confirm/` 和 `write-profile/` 保留逐轮 JSON；`binary-sha256.txt` 记录实测二进制。用相同 Release 配置构建原始树和两个独立副本，在副本根目录分别执行 `make_probe.py`、`make_write_probe.py`。然后运行：

```bash
python3 bench.py --binary "$probe" --control "$base" --output fresh-confirm \
  --modes base repeat mapped --rounds 20 --driver-cpu 4
python3 summarize.py fresh-confirm --device 8:48
python3 oracle.py "$probe"
python3 bench.py --binary "$write_probe" --control "$base" --output fresh-write \
  --modes base profile --rounds 6 --queries 0 --write-only --driver-cpu 4
```

`bench.py` 需在受控 Linux 环境以 root 设置独立 cgroup；设备号按 `findmnt -T /tmp` 改。后续优先在更稳定的本机时段复核这条已有真实 M 收益的路径。先把 A/A 的波动降到足以判别 3%，再比较 A/C；仍无法确认非劣就保留证据，继续使用比赛基线。

