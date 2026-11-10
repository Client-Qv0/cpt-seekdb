# MiniVectorDB 队友交接（2026-11-11）

## 最新完成状态（2026-11-11）

本轮保留C1紧凑布局+C2跨记录AVX2组合，功能提交为07b3a75ec2b0434105ccfa51a03a90d07c077ee3和3490b490cfeb2b0ece00bb637f231e1b2f05ca80；交付完整SHA用当前分支git rev-parse HEAD核对。增量生产基线是9cea05e182875ae16f3f3c9c8e9cc688a65d653c。执行结果见validation/exact-scan-li-20261110/IMPLEMENTATION_REPORT.md、FINAL_GATES.json及FINAL_REVIEW.md。

最终/基线查询中位快38.413%（6/6胜），留出快40.643%（3/3胜）；写入慢3.882%、超缓存查询慢1.935%。首次查询慢54.732%（约36–47ms对23–33ms），不保证单查询或写读交错获益。20项最终门槛、百万标量/VECTOR(4)及四项真实128MiB资源回归通过；协议、事务、精度、稳定排序未放宽。二进制SHA256 b2501504b9e0b13afe6dc35c4e24bf65efaf4351e98ae3d94fc6327f1bd9ee67；源树7c09beba41c9fe64b39f66efcb5ceeb52aefb1e4f7a74410cee5126e8c33bd5e。新Agent材料122791字节，官方语义评分仍未知。

下列第1–10节是6576时期历史；其“源码/材料须与6576相同”不再约束当前候选。后续Agent先读本节、三种路线和新报告，以9cea建立增量基线，使用新输出目录。不要重做已完成的跨记录优化，不复活旧未提交向量索引；可据新profile再研究首次构建成本。真实非AVX2硬件未测，回退与收益范围如实披露。2277.870638只属于7637，本轮无正式成绩，不推算4000；由负责人决定合并/正式提测。

## 本轮结构优化选择与真实材料审计

本轮用户选择 **结构性 EXACT 优化**，仅依据当前服务器 `li@103.236.99.247:40327` 的新证据，最终候选相对当前基线必须达到查询配对降幅中位数至少 **15%**，并满足过滤/超缓存/写入/恢复/内存及留出种子的全部门槛。三条路径完整保留：

| 路径 | 用户选择 | 适用边界与风险 |
| --- | --- | --- |
| 结构性 EXACT：紧凑 AoSoA 缓存、跨记录四路 AVX2，保留逐维 double 顺序及 PK 并列规则 | 已选择并完成，按全部门槛保留C1+C2组合 | 不引入 ANN、持久化向量索引、FMA 或 fast-math；失败撤销候选生产代码并保留负证据 |
| 保守微优化 | 未选择 | 既有候选收益有限且有波动，不能承诺达到本轮 15% 目标 |
| ANN / 持久化向量索引 | 未选择 | 正式性能配置是否采用ann尚未核实，另有召回、更新一致性、持久化与恢复风险，须另开研究与验证 |

历史 early-pruning 与维度 SSE2 已有失败结果，本轮不重复。`/opt/minivectordb-v2` 未提交向量索引保持原现场，不纳入此分支。完整执行状态与结论以 `validation/exact-scan-li-20261110/IMPLEMENTATION_REPORT.md` 和 `PROGRESS.md` 为准；进行中的候选不代表已通过性能门槛。

Agent 材料新审计事实：本轮起点 `agent/conversation.json` 实际为 **119555 字节**，不是旧交接中较早快照的 101530 字节；原正式 7637 材料经父 Agent 对 immutable GitHub contents API 独立取证为 **20922 字节**、SHA256 `af4b8df2a07d1f4e464f41ee8180dfe73e01bb7011734c820bddd3c16c7cfb64`。7637 原文件严格 UTF-8、顶层对象、重复键/非有限值/非法代理项检查与 128KiB 限额均通过，原材料不超限。平台“本项没有有效原始分”的接收、语义或平台原因仍未证实；不能声称格式修订会解决评分，也不能补写用户未表达的独立理解。

本文是本轮交接入口。仓库中的 `HANDOFF.md`、`HANDOFF_HMY_20261109.md`、`HANDOFF_NEXT_GPT.md` 等旧交接文件仅保留为历史记录；其中的 HEAD、性能数据和待办状态不能替代本文及固定提交内的证据。先复现当前版本，再提出单一、可验证的优化假设。本文及可移植适配器来自 6576 之后的交接文档提交；其生产源码和 Agent 材料仍须与 6576 对应哈希一致，文档/工具版本另记，不能混称为 6576 原有文件。

答题仓库：[Client-Qv0/cpt-seekdb](https://github.com/Client-Qv0/cpt-seekdb)。答题分支为 `2026-competition-round2`。每位队友使用自己的唯一开发分支，经 PR 汇总；正式评测由用户操作，不由 Agent 或队友自行触发。

## 1. 三个版本分别代表什么

| 版本 | 完整 commit SHA | 已确认状态 |
| --- | --- | --- |
| 正式通过版本 7637 | `7637a037e8a44c9da8e3bd65694e4474075b5657` | 用户已确认实际提测版本；MySQL 正式用例通过，性能原始分 **2277.870638**；Agent 显示“本项没有有效原始分”。成绩来源为用户提供并确认的正式结果。 |
| 材料修订基线 f2 | `f2c17157db8c678f9165ae98519d03d935b4beb1` | 相对 7637 只改 `agent/conversation.json`，生产源码不变；材料本地严格格式与来源审计通过，不代表 Agent 已获得官方有效分。本轮已完成性能实验以此为基线。 |
| 当前代码版本 6576 | `6576b24e0774eb11352ab5bca3372cda32f8efd9` | 以 f2 为父提交，保留候选 D；已正常推送并按固定 SHA 取回核对源码。当前答题分支和 `perf/round2-jsonl-streams-20261110` 均曾核对指向此提交；**本轮未重新提交正式评测**，不能把 7637 的成绩归给此版本。 |

备份标签：`accepted/round2-mysql-7637a037` 指向 7637，`baseline/round2-f2c17157` 指向 f2。不得移动这些标签来冒充新的通过版本。

当前 6576 的 Git tree 为 `731a04c28e8c348c62471e8d89cc5984599aed61`。生产代码只改 `src/main.cpp`：在任何输入输出开始前调用 `std::ios::sync_with_stdio(false)` 和 `std::cin.tie(nullptr)`，保留原有每条 JSONL 响应的显式 flush。存储格式、持久化同步、事务、SQL、距离计算及缓存算法均未改变。其它提交文件为定向测试、Agent 材料和证据摘要/工具。

| 产物 | 冻结标识 |
| --- | --- |
| f2/7637 基线 Release 二进制 SHA256 | `ade3e37de3f87723aad5fda8be8f9cb1809c714eac46edeb1d24ec2c4bbc68d7` |
| 基线镜像 ID | `sha256:0ac647537c7a602213d4b8d896db59572e751bb6495e9328ed15cc42aee004cd` |
| 6576 Release 二进制 SHA256 | `1d36080209fc61c2d4c5b65fdf2a0587048939b3c51e2eca34644bf848ec98b9` |
| 6576 实测镜像 ID | `sha256:9bc58b1037dabd597e1a5fd51a6f37d3adc3d88582680b58206b07bbd09f1310` |
| 冻结 `bench.py` SHA256 | `2bf78d1307197b23f08e02f842594e0d8c271b706cd9ac8c303673db0b5bf5ed` |
| 6576 `agent/conversation.json` | 101530 字节；SHA256 `e5e0ebd2f17ac717ae4e2b711dd700cc2e1b15014d3ab2ea24d0610e88d4f702` |

这些镜像 ID 和二进制哈希对应已保存的那次构建，不要求另一台机器从浮动系统依赖重建后自动产生相同哈希。队友重建时必须另记源码、编译器、二进制与镜像标识，并在同一构建环境下比较两版；不得把新构建标成原冻结二进制。

## 2. 已测收益及其适用范围

主负载是 10000 条、128 维向量，100 条/次 INSERT，1000 次 TopK10 查询（一半带过滤），随机种子 3179、3181、3187 各运行两次。六轮在 baseline→D→DE 与 DE→D→baseline 之间交替，提取 D 对 baseline 的配对结果。两者使用相同数据、输出消费方式、默认 Docker JSONL 入口及独立 `/data` 目录。

六轮逐对耗时降幅的中位数：**写入 26.5%，查询 4.1%**。计算为 `median(1 - candidate_time / baseline_time)`，精确值分别为 26.453244% 和 4.149224%。这不是“双方耗时中位数的比值”，也不是官方性能原始分或排名提升。

| 轮次 / 种子 | 基线写入 s | D 写入 s | 基线查询 s | D 查询 s |
| --- | ---: | ---: | ---: | ---: |
| 1 / 3179 | 0.855337 | 0.701907 | 0.800745 | 0.731339 |
| 2 / 3181 | 0.906365 | 0.664003 | 0.775353 | 0.728770 |
| 3 / 3187 | 0.912292 | 0.660563 | 0.756606 | 0.725911 |
| 4 / 3179 | 0.913311 | 0.674330 | 0.769221 | 0.736595 |
| 5 / 3181 | 0.917811 | 0.624670 | 0.778848 | 0.763340 |
| 6 / 3187 | 0.912937 | 0.674206 | 0.773721 | 0.750605 |
| 各自耗时中位数 | 0.912615 | 0.669104 | 0.774537 | 0.733967 |

六轮写入、查询均更快；配对加速比中位数分别为 1.359700×、1.043289×。主场景 `memory.peak` 中位数为 15325184→15290368 字节，但最大值为 15560704→15917056 字节，有小幅上升，不能宣称内存全面改善。

超缓存负载为 32000 条×128 维、100 次查询、三组交替配对；原始向量字节数已超过 12MiB 行缓存预算。写入耗时中位数 2.902876→2.152890 秒，查询 1.557363→1.538872 秒；**其中一组查询退化 2.62%**。含 Docker 启动开销的重启耗时中位数 0.546685→0.554616 秒，**退化 1.45%**。`memory.peak` 中位数 32559104→32411648 字节；采样中没有 max/OOM/oom_kill 事件。该实验不能证明最大可支持规模或所有高基数负载均有收益。

计时从请求字节写入到完整响应读取结束；JSON 解析、正确性核验、资源采样和日志在计时外对两版对称执行。首次查询的进程行缓存为空，但未清空系统页缓存，因此不能称为全系统冷缓存测试。重启区间包含 Docker/CLI 开销，不能全归因于数据库恢复。

资源来自真实 cgroup v2：2 CPU、128MiB 内存、0 swap，CPU 固定为 0、1，容器根目录只读、网络关闭、`/data` 独立持久化。`memory.peak` 与 `memory.stat` 的匿名/文件缓存采样分开记录；RSS 仅为辅助。`io.stat` 保留原始计数，区间为 ready 到 shutdown 前，不是完整生命周期物理 I/O；存在页缓存归属和延迟写回限制。文件大小不等于物理 I/O，不用这些数估算官方分数。

完整表和限制见固定提交中的 `validation/perf-20261110-stdio/REPORT.txt`、`results/paired-main-summary.json`、`results/paired-overflow-summary.json`、`results/decision.json`。旧的 9.679× 等其它负载数字不得沿用为本轮结论。

## 3. 已试方案及取舍

| 候选 | 改动 | 已有证据与决定 |
| --- | --- | --- |
| A | pwritev 合并每帧三次写入，保留磁盘字节/CRC/同步语义 | 短写、EINTR、故障恢复验证通过；三轮写入配对加速比中位数约 1.057×、查询约 0.966×。收益/风险不够稳定，未合入。 |
| B | 完整行缓存中的 TopK 胜出项复用，避免重复解包及距离投影 | 有缓存边界、过滤、相同距离、事务失效回滚测试；三轮查询中位数约 1.016×，有一轮退化。未合入。 |
| C | 向量词法解析减少复制、预留空间 | 三轮写入约 0.99981×、查询约 0.97456×，未合入；不能将有短字符串优化的字段一律描述为堆分配。 |
| D | 关闭 C/C++ 流同步并解绑 cin/cout，保留显式 flush | 六轮主负载稳定收益，修改范围小，保留于 6576。 |
| E | 对已经按 FP32 解析的查询向量预先转 double，减少内层重复转换 | DE 对 D 的六轮增量比较四胜两负，中位数约 1.027290×，另有 O(D) 临时空间。未合入；DE 相对原基线的总收益不能直接归给 E。 |
| AB | A+B 组合 | 只构建过组合镜像，未做性能评测，未选用；不能写成“已测失败”或稳定收益。 |

仅 D 进入生产提交。A/B/C/E/AB 的局部实现和原始实验留在封存证据包，仓库所交付摘要不等于包含全部原始实验目录；需要重做候选时先拿到相应源码清单，不从摘要臆造实现。

## 4. 正确性与未覆盖范围

已实测：

- 官方原版 `f4d4e26653af823a7601668802f80e374ad6643c` 驱动的 handshake-only、sql_crud、全部 20 个公开用例通过。
- 实际默认容器入口补充验证 6 项通过、1 项明确跳过，24757 个断言；覆盖事务、错误后继续、shutdown 回滚、SIGKILL 后恢复、72 组独立向量参考查询、2 万行大输出及 128MiB 限额。
- 性能实际负载全部查询由计时区间和被测 cgroup 外的独立 NumPy 参考计算核对 ID、距离、过滤、重复 ID、顺序/类型及 Recall；该精确负载的 Recall 为 1.0。
- Release CTest 6/6、ASan/UBSan Debug CTest 6/6；基线与 D 的原生流边界测试 8 项，包括无输入 ready、逐响应 flush、Unicode/id 类型、错误后继续、大于 4MiB 输出、EOF 回滚、shutdown、关闭 stdout 后的 SIGPIPE 与恢复。

尚未验证：6576 的新正式 MySQL/性能/Agent 成绩、所有环境的稳定性、最大高基数容量。Docker 的 broken-stdout 注入受日志管线限制而跳过，原生 SIGPIPE 测试不能冒充该容器路径已覆盖。

等待官方公开工具或规范：隐藏正式负载细节、Agent 语义评分器及未公开的边界。公开测试通过不能保证隐藏正式用例全部通过，也不能保证特定分数。

`CREATE INDEX` 当前仍为元数据实现，ANN 模式仍走精确回退，属于独立实现缺口。不要在微优化分支里顺带引入复杂 ANN 或降低 Recall。

## 5. 下一轮优先研究什么

已做的一次原生 `perf cpu-clock:u` 199Hz 采样有 970 个样本、0 丢失，其中 L2 距离循环 595 个样本（61.34%），投影函数合计约 66.60%。这是固定二进制的原生诊断，不是 Docker 性能成绩；优化克隆导致 gprof 曾把热点错归到 `pack_row`，该解释已弃用。

下一步先在新的固定版本和目标负载上重新定位 L2 开销，然后一次只验证一项：精确向量计算的安全向量化、重复工作消除，或过滤条件提前裁剪。保持 FP32 输入转换、既有 double 累加语义、稳定并列顺序、过滤和 ID 完整性；未证明等价前不启用 fast-math、重排累加或融合乘加。ANN/索引结构另开研究分支，单独设计召回、持久化与更新一致性验证。

## 6. 队友环境与固定版本工作流

以下命令在 Linux Bash 或 WSL2 的 Linux shell 执行。性能资源脚本需要 Linux x86_64、本机 Docker Engine、cgroup v2，以及能够读取 Docker 容器宿主 PID 对应的 `/proc` 和 `/sys/fs/cgroup`。WSL2 应在同一发行版运行本地 dockerd，数据目录放 Linux ext4（例如用户目录），不将 `/mnt/c` 作为性能数据盘。需要 Git、Python 3/NumPy、Docker CLI；原生验证还需要 CMake、C++17 编译器和 make。

Docker Desktop 或远端 Docker 的 daemon 与脚本通常不在同一 PID/cgroup 命名空间；即使功能容器能运行，也不能用本机 `/proc/<inspect-pid>` 宣称取得完整容器资源数据。预检不通过时换用同一 Linux 内的本地 Engine，或明确资源未知；不要删除检查、用 RSS 代替 `memory.peak`，也不要放宽 128MiB 限额以得到更好结果。

先创建全新的本地实验根目录；下面姓名与主题由队友替换为自己的唯一值。两版不共享数据库目录，也不要并发跑性能负载。个人开发分支从包含本文与可移植适配器的交接文档提交创建，生产基线另开 worktree 固定 6576，避免把主目录切回 6576 后丢失新交接工具。获取最新远端后先检查文件和提交说明，确认是交接版本，再记录 `TOOL_COMMIT`；若之后有其它代码提交，不能把任意最新 HEAD 默认当作同一交接版本。

```bash
BASE=6576b24e0774eb11352ab5bca3372cda32f8efd9
TOP="$HOME/mvdb-team-yourname-20261110"
BRANCH=perf/yourname/l2-investigation
mkdir "$TOP"
git clone --filter=blob:none --sparse --single-branch --branch 2026-competition-round2 \
  https://github.com/Client-Qv0/cpt-seekdb.git "$TOP/repository"
REPO="$TOP/repository"
git -C "$REPO" sparse-checkout set src tests agent validation/perf-20261110-stdio
TOOL_COMMIT=$(git -C "$REPO" rev-parse HEAD)
test -f "$REPO/validation/perf-20261110-stdio/scripts/bench_portable.py"
git -C "$REPO" log -1 --oneline
git -C "$REPO" fetch origin "$BASE"
git -C "$REPO" cat-file -e "$BASE^{commit}"
git -C "$REPO" worktree add --no-checkout --detach "$TOP/baseline" "$BASE"
git -C "$TOP/baseline" sparse-checkout set src tests agent validation/perf-20261110-stdio
git -C "$TOP/baseline" checkout --detach "$BASE"
git -C "$REPO" worktree add --no-checkout -b "$BRANCH" "$TOP/candidate" "$TOOL_COMMIT"
git -C "$TOP/candidate" sparse-checkout set src tests agent validation/perf-20261110-stdio validation/handoff-20261110
git -C "$TOP/candidate" checkout "$BRANCH"
git -C "$TOP/baseline" rev-parse HEAD
git -C "$TOP/candidate" rev-parse HEAD
git -C "$REPO" diff --exit-code "$BASE" "$TOOL_COMMIT" -- src CMakeLists.txt Dockerfile .dockerignore agent/conversation.json
```

已有 clone 时，不必重新 clone：将 `REPO` 指向已有目录，先运行 `git -C "$REPO" status --short` 并记录，再 `git -C "$REPO" fetch origin 2026-competition-round2`，从取回的交接文档提交记录 `TOOL_COMMIT`（可用 `git -C "$REPO" rev-parse FETCH_HEAD`，并核对其文件与说明），再 fetch 固定的 `BASE`。然后使用同样的两个 `git worktree add` 命令创建新目录并核对生产差异为空。已有未提交工作不执行 reset/clean/覆盖；使用独立 worktree 保留原现场。不要 force push、改写他人的分支或移动已通过版本标签。

仓库大时可以在新 worktree 中启用 cone 模式 sparse checkout，只取 `src`、`tests`、`agent`、`validation/perf-20261110-stdio`；根目录文件会保留。官方题包另建固定版本 checkout，完整保留 protocol_check 与 mysqltest 两个目录及根协议文件，避免稀疏范围漏掉公开测试依赖。

先原样构建 baseline，候选修改后构建 candidate；使用不同标签并记录各自 image ID。此处下一轮基线为 **6576**，不是上一轮实验的 f2。

```bash
docker build -t mvdb-team-yourname:base-6576 "$TOP/baseline"
docker build -t mvdb-team-yourname:candidate "$TOP/candidate"
docker image inspect --format '{{.Id}}' mvdb-team-yourname:base-6576
docker image inspect --format '{{.Id}}' mvdb-team-yourname:candidate
cmake -S "$TOP/baseline" -B "$TOP/baseline/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$TOP/baseline/build" --parallel 2
cmake -S "$TOP/candidate" -B "$TOP/candidate/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$TOP/candidate/build" --parallel 2
ctest --test-dir "$TOP/candidate/build" --output-on-failure
sha256sum "$TOP/baseline/build/minivectordb" "$TOP/candidate/build/minivectordb"
python3 "$TOP/candidate/validation/perf-20261110-stdio/scripts/stdio_correctness.py" \
  --baseline "$TOP/baseline/build/minivectordb" \
  --candidate "$TOP/candidate/build/minivectordb" \
  --output "$TOP/stdio-new"
```

原生 CTest 的六项为 parser、storage、engine_extra、spill、compact_rows、protocol。若改动涉及事务、恢复、磁盘结构，须另补相应中断故障及实际默认容器入口验证，不能只跑这六项。

## 7. 官方原版验证顺序

官方仓库单独固定版本，保留原 `STDIO_PROTOCOL.md`、`protocol_check/` 的脚本、依赖和 `config.json`，以及公开 mysqltest 题包。不得修改驱动或测试桥来迁就程序。

```bash
git clone --filter=blob:none --sparse --single-branch --branch 2026-competition-round2 \
  https://github.com/oceanbase/seekdb.git "$TOP/official"
git -C "$TOP/official" fetch origin f4d4e26653af823a7601668802f80e374ad6643c
git -C "$TOP/official" switch --detach f4d4e26653af823a7601668802f80e374ad6643c
git -C "$TOP/official" sparse-checkout set protocol_check mysqltest
cd "$TOP/official"
VECTORDB_IMAGE=mvdb-team-yourname:candidate
python3 protocol_check/run.py --image "$VECTORDB_IMAGE" --handshake-only \
  --output "$TOP/official-handshake-new"
python3 protocol_check/run.py --image "$VECTORDB_IMAGE" --case sql_crud \
  --output "$TOP/official-crud-new"
python3 protocol_check/run.py --image "$VECTORDB_IMAGE" \
  --output "$TOP/official-all-new"
```

官方公开驱动配置为 2 CPU、2GiB 内存、128 PID；本地配对性能脚本使用 2 CPU、128MiB、0 swap。二者目的和资源条件不同，必须分别报告，不得用官方 2GiB 测试替代 128MiB 资源验证。每个输出目录使用新名称，保留原始 stdout/stderr、退出码及工具哈希。

## 8. 可移植配对基线入口

本次交接另提供 `validation/perf-20261110-stdio/scripts/bench_portable.py`；它来自新的交接文档提交，不在原 6576 提交内。使用已记录的 `TOOL_COMMIT` checkout 中的工具，另记适配器哈希。冻结 `bench.py` 保持上述 SHA256 不变。适配工具只在新 `output-root/tool` 中生成路径和环境适配副本，保存冻结原始脚本、差异与哈希；不回写旧审计证据，不改变 2 CPU/128MiB/0 swap 或性能计时、数据、参考计算口径。

适配器已完成 200 行×8 维、4 条查询、两个标签使用同一冻结镜像的小规模烟测，以及参数拒绝/仅预检验证；这不是新性能实验。摘要见 `validation/handoff-20261110/PORTABLE_VALIDATION.json`。首次预检对缺失的辅助 `/proc/PID/io` 过于严格，修正为与冻结脚本一样记空值；真实 cgroup 文件仍为必检。`-O`、`-OO`、`PYTHONOPTIMIZE` 会禁用冻结脚本的断言，因此适配器拒绝优化模式。

在新的实验目录准备依赖（示例基于已装 Python 3 与 venv 的 Linux；不要覆盖已有环境）：

```bash
python3 -m venv "$TOP/venv"
"$TOP/venv/bin/python" -m pip install 'numpy==2.3.3'
source "$TOP/venv/bin/activate"
python3 -c 'import numpy; print(numpy.__version__)'
```

Docker socket 可用不等于 `/proc/PID/io` 可读。若预检因权限失败，在自己的可信源码上用 `sudo "$TOP/venv/bin/python" ...` 运行同样命令，或由管理员授予相应读取权限；不要取消资源检查。需要至少可用 CPU 0、1；本工具不自行更改固定资源限制。

先运行预检。新 clone 的 `$REPO` 保留交接工具版本；已有 clone 若本地 checkout 不是 `TOOL_COMMIT`，则将 `TOOLS` 指向新 candidate worktree 的同一路径，并保留其工具文件不变。全部输出和数据目录必须是新的绝对路径。若预检占用了某个输出目录，正式运行另换名称。

```bash
TOOLS="$TOP/candidate/validation/perf-20261110-stdio/scripts"
python3 "$TOOLS/bench_portable.py" \
  --images base=mvdb-team-yourname:base-6576 candidate=mvdb-team-yourname:candidate \
  --output-root "$TOP/preflight-new" --data-root "$TOP/preflight-data-new" \
  --prefix yourname-preflight --docker-host unix:///var/run/docker.sock --preflight-only

python3 "$TOOLS/bench_portable.py" \
  --images base=mvdb-team-yourname:base-6576 candidate=mvdb-team-yourname:candidate \
  --output-root "$TOP/paired-main-new" --data-root "$TOP/data-main-new" \
  --prefix yourname-main --docker-host unix:///var/run/docker.sock \
  --seeds 3179 3181 3187 3179 3181 3187 --rows 10000 --dim 128 --queries 1000

python3 "$TOOLS/bench_portable.py" \
  --images base=mvdb-team-yourname:base-6576 candidate=mvdb-team-yourname:candidate \
  --output-root "$TOP/paired-overflow-new" --data-root "$TOP/data-overflow-new" \
  --prefix yourname-overflow --docker-host unix:///var/run/docker.sock \
  --seeds 3179 3181 3187 --rows 32000 --dim 128 --queries 100
```

`--docker-host` 可省略，使用工具所记录的本地 Docker 环境。命令是后续复现步骤，不表示已替队友运行成功。先看预检报告；不得并发运行其它性能任务。正式配对至少保留六轮主负载、三轮超缓存负载及每轮结果，不选择性丢弃较慢轮次。独立参考计算必须在计时和被测 cgroup 外，核对实际测量查询的 TopK、距离、过滤、重复 ID、Recall，而不是只检查数量与排序。

## 9. Agent 材料与 PR 交付

当前官方路径为 `agent/conversation.json`，要求严格 UTF-8、合法 JSON 顶层对象、总文件大小不超过 **128KiB（131072 字节）**。拒绝重复键、NaN/Infinity 和不合法 Unicode；检查固定 commit 中实际提交的字节，不能只看工作树文件。6576 的材料为 101530 字节；继续增补前重算大小，不能假定一直有余量。

真实用户发言、Agent 分析、工具调用与工具结果必须明确分开。关键学习/验证证据直接写入 JSON 字符串，不只提供外部日志路径或一句“全部通过”。本轮技术假设、分析和实现选择由 Agent 作出，用户没有给出的技术理解不能补成学生独立贡献；问答工具的 Agent 问题不能一起归到 user，只有真实 answer 属于用户发言。保留负结果、证据缺口及“尝试→验证→保留/放弃”的真实过程，不伪造历史交互、实验反馈或学生反思。

本地格式审计通过不能代替官方 Agent 语义评审；当前公开工具不提供该评分器。不要承诺有效原始分或满分。若材料符合规范却仍无有效分，保留固定 SHA、路径、字节数、哈希及原始平台文案，明确原因尚未证实；不要自行联系外部人员或编造原因。

队友 PR 应包含：固定起点与候选 commit、源码清单、二进制/镜像/工具哈希、单一优化假设、每轮配对表、中位数与波动、内存和 I/O 原始指标及限制、正确性/事务/恢复结果、跳过项、负结果与是否保留。没有稳定收益或出现正确性/资源回归时保留实验记录并撤销候选代码；不要包装成提升。

```bash
git -C "$TOP/candidate" status --short
# 先检查将提交的差异及是否包含凭据，再显式 git add 需要的文件并 commit。
git -C "$TOP/candidate" push -u origin "$BRANCH"
```

向答题仓库 `2026-competition-round2` 发 PR，交由用户/负责人复核；不直接覆盖共享分支，不 force push，不代替用户提交正式评测。克隆和推送使用各自 GitHub 授权、系统凭据管理或 SSH；**不共享 PAT，不把用户名:令牌嵌入仓库链接、脚本、材料或日志**。

## 10. 可转发给队友 Agent 的执行提示词

> 请先完整阅读 TEAM_HANDOFF.md，以及固定提交 `6576b24e0774eb11352ab5bca3372cda32f8efd9` 内的 `validation/perf-20261110-stdio/REPORT.txt` 和 paired summaries。正式通过并得原始分 2277.870638 的是 `7637a037e8a44c9da8e3bd65694e4474075b5657`，不能给新版本套用旧成绩。以 6576 建立独立基线 worktree；从包含本交接工具、且生产/材料哈希仍匹配 6576 的交接文档提交创建个人唯一分支，分别记录代码基准和工具版本。保留已通过版本与旧证据，不改共享答题分支、不 force push、不自行正式提测。先用同一 Linux/WSL2 内本地 Docker Engine、真实 cgroup v2 建立可复现基线；Docker Desktop 资源命名空间不匹配时不能用 RSS 代替 cgroup 数据。先做精确 L2 热点诊断，再选择安全向量化、重复工作消除或过滤裁剪中的一项；ANN 另列，不同时引入。保持正式 JSONL、持久性、事务、精确计算与稳定排序；用官方原版固定 f4d4e266 驱动，并在计时外用独立参考核验实际负载全部结果。主负载至少六组交替配对，并跑超缓存、恢复与资源回归，报告退化和跳过项，不只报最快轮次。Agent 材料只能记录真实用户发言、Agent 判断和工具证据，严格区分归因，路径 `agent/conversation.json`，不超过 128KiB，不伪造学生贡献。最后提交个人分支并发 PR，提供完整 SHA、所有被测产物与工具哈希、可复现命令和证据目录，由用户决定正式提测。
