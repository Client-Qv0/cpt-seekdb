# MiniVectorDB 验证证据审计

审计日期：2026-11-09。审计标识：`audit-20261109-42affed2e283`。

本次暂停新增性能优化，冻结生产源码并重建、回归和核对历史证据。未提交正式评测。结论是：**下面列出的本地验证通过，但没有足够证据宣布正式评测通过、性能满分或适合立即提测。**

## 被测版本与可追溯性

被测对象是尚未提交的工作树；`c842a368c3394748d0499386c18f6b465242e141` 只是 Git 基础提交，不包含本次全部实现，不能把它当作被测实现的 commit SHA。

| 对象 | SHA-256 |
|---|---|
| 12 项生产源码及构建输入清单的树摘要 | `42affed2e283c8710151931f6f419eee64210eda42245be6d357dc20ae520bb2` |
| 原生 Release 可执行文件；Docker 中可执行文件逐字节相同 | `747092fd68833b52ec80020e050d4586d443220f513d6b3d932ab3e25eea072f` |
| ASan + UBSan 可执行文件 | `dfcf87896fe94841abe6f7a936f6beae218de3c85c47b9fef159e95314480f78` |
| 独立参考计算工具 v2 | `027611ff2b8369ede8a16213ceb84c96b385c8ab7c1ec1d8ae7bade3c8b5bee1` |
| v2 全量正确性结果 JSON | `fa4fcbc428f86f74c7a0ca77455750da2004f22bd206d1338164ad2132b088bd` |

源码清单包括 `.dockerignore`、`CMakeLists.txt`、`Dockerfile` 及 `src/` 下的九个文件，逐文件长度和哈希见 [production-manifest.json](production-manifest.json)。审计收尾时重新比较了工作树、冻结副本和清单，12 项完全一致，生产代码未在本次审计中修改。

树摘要的计算方式是对清单的 `files` 数组按现有路径顺序，用 Python `json.dumps(files, sort_keys=True, separators=(',', ':')).encode('utf-8')` 序列化后计算 SHA-256；已重新计算匹配。

- [run-manifest.json](run-manifest.json)：执行文件及四个单测程序的哈希、构建参数、回归命令、报告绑定和归档哈希。该文件是运行后的归档清单，不声称为旧测试补造运行时证据。
- [source-snapshot.zip](source-snapshot.zip)：12 项生产输入的内容归档；[tests-snapshot.zip](tests-snapshot.zip)：九项原有测试文件归档。ZIP 时间戳统一归一化，文件内容以清单哈希为准。
- [test-manifest.json](test-manifest.json)：冻结测试源码清单。新增参考计算工具单独保存在 [oracle-v2.py](oracle-v2.py)，没有改变生产树摘要。
- [environment.txt](environment.txt)：WSL2 Ubuntu / Linux x86_64，GCC 13.3.0、CMake 3.28.3、Python 3.12.3、glibc 2.39、cgroup v2。参考计算使用 NumPy 2.3.3。
- [docker-image.json](docker-image.json)：真实镜像构建及包版本记录。镜像 ID 为 `sha256:27ea1213ba52ad529ba46eee11bd694b0a0a10cf36c2f9a6415f5f985376b6ef`；不是尚未发布的 registry manifest digest。

## 一、已经实测

### 功能、事务、恢复与资源回归

| 本次冻结版本的验证 | 结果 | 证据及范围 |
|---|---|---|
| Release 单元测试 | 4/4 套通过 | parser 68 项检查、storage 9 套、engine_extra 30 项、spill 9900 项；[详细输出](ctest-release-detailed.txt) |
| Release 黑盒验收 | 19/19 通过 | [acceptance-release.txt](acceptance-release.txt) |
| Release 缓存、主键路径与大输出回归 | 11/11 通过 | [optimization-release.txt](optimization-release.txt)；文件名沿用已有测试，未新增生产优化 |
| ASan + UBSan 单元测试 | 4/4 套通过 | [详细输出](ctest-sanitize-detailed.txt)；未报告消毒器错误 |
| ASan + UBSan 黑盒验收 | 18 项通过，1 项明确跳过 | [acceptance-sanitize.txt](acceptance-sanitize.txt)；大于地址空间的压力项未在该配置运行 |
| ASan + UBSan 额外回归 | 8 项通过；大输出类明确跳过 | [optimization-sanitize.txt](optimization-sanitize.txt)；不能声称三项大输出也通过消毒器 |
| 真正 Docker 镜像普通验收 | 18 项通过，1 项压力测试跳过 | [docker-acceptance.json](docker-acceptance.json)，56 次实际容器启动，2 CPU / 2 GiB / swap 0 / 无网络 |
| 真正 Docker 128 MiB 资源回归 | 4/4 通过 | [完整结果](docker-resource-regression-results.json)、[日志](docker-resource-regression-log.txt)，压力项另行运行，见下文 |

功能覆盖 BIGINT 精度和边界、Unicode 长度与排序、SQL 字面量和大小写、FP32 存储与欧氏距离、过滤后 TopK、同距离主键排序、非法输入、索引声明后的修改及精确查询。事务覆盖自动提交语句原子性、显式事务中失败语句不撤销先前工作、更新/删除/回滚、EOF 未提交回滚、缓存失效和随机参考模型。

崩溃恢复覆盖 SIGKILL 后保留已确认提交、丢弃未提交事务、提交响应丢失时全有或全无、反复启动终止、截断提交记录、恢复重放中断，以及 checkpoint 的写入前、写入中、rename 前、rename 后和目录同步后的崩溃边界。单测详细日志没有报告 ptrace 不可用导致的跳过；Release 的 storage 测试显式启用了 assert，不受 `NDEBUG` 取消检查。这些是已覆盖的进程终止/文件边界，不等于真实断电或任意存储设备故障验证。

### 真正 cgroup 资源回归的解释

四项测试实际设置并读取 `memory.max=134217728`、`memory.swap.max=0`、`cpu.max="200000 100000"`。没有把外层 Python 的 RLIMIT_AS 当作容器内存限制。测试驱动和响应解析位于容器之外。

| 用例 | 已核对内容 | 数据或响应规模 |
|---|---|---|
| 大载荷向量 TopK | 全部 ID、距离、顺序、载荷摘要及完整响应 | 响应 160,116,974 字节 |
| 大 LIMIT 多键排序 | 全部行、排序、载荷及完整响应 | 响应 192,095,235 字节 |
| 无 LIMIT 的 SELECT * | 全部行、载荷及完整响应 | 响应 192,221,839 字节 |
| 存储超过内存限额 | 写入、主动强杀、重启后抽查末尾 10 个 ID 及首行完整载荷；未全量回读 9600 条 | 数据载荷 192,000,000 字节 |

**三项大输出的 cgroup `memory.peak` 均达到 134,217,728 字节，`memory.events.max` 非零。** 所有七个相关容器记录的 `oom/oom_kill` 均为零，Docker `OOMKilled=false`。结论只是“这些用例在限额下完成”，不是“内存余量充足”或“没有回收压力”。主动 SIGKILL 导致的退出码 137 已与 OOM 区分。部分进程退出后 cgroup 已被删除，采样错误和最后存活采样原样保留，没有补造最终计数。

资源报告保存真实 cgroup `io.stat` 的原始观测，但 WSL `/dev/sdd` 为共享 ext4 设备，独立设备及回写归因尚未校准。因此不据此给出正式物理 I/O 成绩；上表数据/响应字节也仅用于描述负载，**不作为物理 I/O**。进程 VmHWM/RSS、RUSAGE_CHILDREN、RLIMIT_AS、cgroup memory.peak 是不同指标，不互相替代。

容器进程适配器及哈希见 [docker-resource-regression-harness.json](docker-resource-regression-harness.json)；继承冻结测试断言，只适配进程启动、流传输及采样。测试结束后专用 Docker daemon 已停止、容器已清理，见 [cleanup](docker-resource-regression-cleanup.json)。

### 实际性能负载的独立参考计算

采用现有性能脚本真实产生的负载：固定 seed 3179，10,000 条 128 维向量、100 行一批插入、1,000 次 Top-10 查询，其中过滤/无过滤各 500 次。参考工具先截获冻结性能脚本产生的 1,101 条 SQL，与审计工具重建的 SQL 逐条比对；此处 mock **仅核对负载文本一致**。随后所有插入和查询由真实冻结可执行文件执行，未用 mock 响应充当数据库结果。

整组 SQL SHA-256 为 `1ef9f505060732d3186226dcbf578f7c4e3be672409fee58df55320cfbd29d80`。原性能脚本 SHA-256 为 `9580021fa540b59add07ce946a20aec539db3b3913f08c965159d709d7fdda94`。

参考计算独立解析实际 SQL 的十进制向量字面量，先量化为 FP32，再转换为 FP64 穷举欧氏距离；先应用过滤条件，再按距离和主键排序。未调用数据库自身解析器、距离、缓存或 TopK 实现。每条响应检查：合法整数 ID、重复 ID、过滤谓词、每个距离、TopK 集合、完整顺序和 Recall，而不只是数量与排序。

| 指标 | 有过滤 | 无过滤 |
|---|---:|---:|
| 完成并通过的查询 | 500/500 | 500/500 |
| Recall@10 最小值 | 1.0 | 1.0 |
| Recall@10 平均值 | 1.0 | 1.0 |

总计 1,000/1,000 通过，零失败、零未运行；最大绝对距离误差 `7.105427357601002e-15`，检查容差为 `atol=1e-10, rtol=1e-12`。执行前后 binary SHA 一致。报告包含每条查询的实际和参考 ID/距离，各 10,000 行，并再次离线核对，见 [performance-correctness.json](performance-correctness.json) 和 [运行日志](performance-correctness.txt)。

该 oracle 未逐条回读所有插入向量，也未核对响应列名；不能把这些未做事项描述为已测。其他功能测试单独覆盖了持久化、投影等行为。此次 oracle 是结果正确性核验，耗时含独立参考计算，**不是新性能成绩**。

## 二、尚未验证或不能从现有证据推出

1. **旧加速比不能归给当前版本。** `validation/optimization-comparison.json` 的候选二进制 SHA 为 `bb774b68b2e926b51303bc4146db70e07b69657a494c043964db3b672f1df7c2`，与本次 `747092fd…a072f` 不同。旧 9.679× 查询加速比只属于旧报告对象；当前版本没有完成同口径、隔离资源下的成对性能比较。
2. 未验证当前完整性能负载的正式 cgroup 内存与物理 I/O 归因及评分。四项容器资源回归证明限额下的特定行为，不替代正式性能负载，也不证明相对基线资源无退化。
3. 高基数短记录的内存边界仍未穷尽。主键到偏移的映射驻留内存，不能因“大载荷超过内存”通过便推断“任意数量的小记录”也在固定内存下可用。
4. 当前 `CREATE INDEX` 仍主要保存索引声明，查询为精确扫描/缓存路径；尚无已验证的真正近似向量索引。已有索引声明后查询测试通过，不等于 ANN 功能与性能通过。
5. 未完成真实断电、磁盘满、所有 fsync/rename 错误组合和任意损坏介质的验证；进程 SIGKILL 测试不能替代这些故障模型。
6. Dockerfile 的基础标签和 apt 包版本尚未固定；本次确实构建成功并记录了实际 digest 和包版本，但不能保证未来联网重建得到相同二进制。
7. 固定 seed、10k×128、Top-10 的全量 oracle 不证明所有数据集、维度、过滤选择率、TopK、SQL 或隐藏用例正确。学习材料是否满足正式评分也不在本次正确性审计结论内。

### 历史报告对应关系

| 历史材料 | 审计判定 |
|---|---|
| `optimization-comparison.json` | 有候选二进制哈希，明确不同于本次版本；保留为旧版本报告 |
| `source-manifest.json` / `source-manifest-initial.json` | 两份相同但已滞后：12 条中 7 条与当前不同，且缺少 spill 和构建输入；不能标识当前源码 |
| 旧 CTest、黑盒、消毒器及 stdout 故障日志 | 没有当次完整源码、二进制、测试工具绑定，不能追溯为当前版本；本次冻结后重新运行取代其当前版本证明作用 |
| `local-benchmark.json` | 无可执行文件及工具哈希；旧检查主要为数量/去重/排序，不独立证明 Recall |
| 本次 Docker 构建记录 | 12 项输入与 builder 中实际 COPY 内容均匹配冻结清单，生成的二进制与本次 native Release 相同，可绑定本次版本 |
| `STATUS.md` | 旧阶段说明，仍含过时测试数和 Docker 状态；当前判断以本审计为准 |

旧 RSS 数据来自 RUSAGE_CHILDREN，可能夹带启动器/历史子进程峰值，不是 cgroup 内存峰值；不据此保留“资源未增加”的结论。旧文件大小数据不转换成物理 I/O。

[legacy-evidence-inventory.json](legacy-evidence-inventory.json) 是旧文件取样清单，不是旧运行证明。其中 Docker build 日志取样后继续追加 309 字节：原 32,636 字节 SHA 为 `a6bf54aace01f63dfc6cffe4748a0e90fef5e5ddfbb433cd497224feb3ce71df`；完成后的 32,945 字节 SHA 为 `c49f7c3b801408344d77ef4a7882834a5d14b5d2b6c47f7b779b168f85da6f97`，其前 32,636 字节仍匹配原哈希。保留原取样记录，不倒改历史。

参考工具最初的 harness 配置错误以及 v2 启动前临时 venv 缺失也保留在相应 failure 日志。这些不是数据库失败；修正测试环境后真实执行的完整成功记录与失败记录分开保存。

## 三、等待官方题包

- 正式 stdin/stdout 协议、启动就绪信号、响应格式、错误码及驱动控制方式；当前 `--dev-protocol` 是本地验证接口，不能先认定兼容官方驱动。
- 正式 SQL 和近似索引语法/语义的完整边界、公开功能与恢复用例，以及隐藏测试约束。
- 正式性能数据生成方式、固定基线、资源隔离/采样口径和评分驱动。不能用本地负载、RSS、文件字节或未经归因的 I/O 推算官方成绩或排名。

官方材料到位后，需要对最终选定的 commit 重新构建并运行相应验收。本次没有生成可供正式提测的“已核实通过”承诺，也没有提交正式评测。

## 证据完整性

[evidence-manifest.json](evidence-manifest.json) 列出审计目录中归档文件的 SHA-256，排除清单自身；其作用是发现之后的改动，不是第三方签名或官方认证。生产源码、测试源码、独立计算脚本、逐查询结果、容器资源原始观测及构建/回归日志均已保存，可相互核查。
