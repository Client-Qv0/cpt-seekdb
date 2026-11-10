# L2 查询热点复核与候选结果（2026-11-10）

## 结论和版本

- 本轮从 df451b5dd6f3653eb3d0a1ed16e20a527252c6f9 创建个人分支；它的 src、CMakeLists.txt、Dockerfile 和 .dockerignore 与生产基线 6576b24e0774eb11352ab5bca3372cda32f8efd9 相同。本轮结束后这些生产文件仍与 6576 相同。队友的 [TEAM_HANDOFF.md](../../TEAM_HANDOFF.md) 是历史基线说明。
- 两个候选都未显示稳定收益，**均未保留在生产源码**。已保存 [提前终止实验补丁](early-pruning-experiment.patch) 和 [SSE2 实验补丁](simd-experiment.patch)，供审阅，不参与默认构建。新增参考模型与逐响应对照测试留在 tests 目录。
- 用户截图对应的正式通过版本，据队友交接为 7637a037e8a44c9da8e3bd65694e4474075b5657：MySQL 正式用例通过，性能原始分 2277.870638，Agent Prompt 显示没有有效原始分。这个成绩不能套到 6576、本次提交或实验候选。本轮没有正式提测，也未得到官方新成绩。

## 本机与产物绑定

WSL2 Ubuntu x86_64，GCC 13.3.0、CMake 3.28.3、Python 3.12.3、NumPy 2.3.3、Docker 29.9.2，cgroup v2。源码在 F 盘，构建及新安装依赖放在 E 盘；数据库配对数据使用 WSL Linux 文件系统的独立目录。baseline-environment.txt 记录本机版本和工具哈希。此机器有其他容器运行；没有中断它们，也没有做整机冷缓存控制，可能影响耗时波动。

| 产物 | SHA-256 / 镜像 ID |
|---|---|
| 6576 原生 Release 二进制 | 1d36080209fc61c2d4c5b65fdf2a0587048939b3c51e2eca34644bf848ec98b9 |
| 本机基线 Docker 镜像 | sha256:e1375a443979c6ca1a91d22a166a4c1be149dfdfc3c181839567585bef9fca84 |
| 提前终止候选 Release 二进制 | db45a9852f84eb3d693b83ce94a6cd93c1fdfd7e2bc0172aa378d89ffa360ec4 |
| 提前终止候选 Docker 镜像 | sha256:cc4c8c05b0835262e4984ad26c37aacbb85aa74537856690e1c82a5f6ca3d671 |
| SSE2 候选 Release 二进制 | 60b4110ec7f3c1d09cf35e3b4d5d41c355fe6c74dbde9ef3e3bc9018ef33b858 |
| SSE2 候选 Docker 镜像 | sha256:2d817f8627837e0950f018ff168f6cad398f855b881d2dc2267a0c6fb8d084e3 |
| 本轮 agent/conversation.json | 7cc5d7003b16cd418e3d94732d1b56a26dbf66db95d6164081d2730ad79fc891，109865 字节 |

baseline-image-binary.txt、early-image-binary.txt、simd-image-binary.txt 分别记录镜像内二进制与对应本机 Release 二进制逐字节比较通过。Docker 构建使用缓存和默认 Dockerfile；这不是固定依赖的无缓存重建证明。不同机器重建得到不同镜像 ID 是可能的，应重新记录并同机比较。

## 热点和两个假设

本机基线对旧 seed 3179 的 10,000 行×128 维数据执行 1,000 条查询重复 5 次，使用显式开发协议和原生 Release 二进制作 perf cpu-clock:u 199 Hz 诊断。共有 539 个样本、0 丢失；429 个样本（79.59%）落在 project，profile-annotate-all.txt 中其样本主要落在向量转换、减法、乘法与逐项累加循环。首次 perf report 因 F 盘文件所有权检查失败，针对本次自己生成的文件使用 --force 重跑成功；保留两份日志。采样和开发协议都不是平台端到端成绩；样本占比有统计和采样位置误差。原始输入 gzip 的 SHA-256 为 6af8ab0a40b33457caee4c1282808aed2eee3551c74fea11bec1b08694afc829。

1. **提前终止**：TopK 堆满后每 32 个分量对当前部分和开方，仅在严格大于最差胜出距离时跳过该行，保留并列主键排序及原始 double 顺序；堆未满和一般查询保留原路径。主负载 3/6 组更快，中位配对耗时降幅 3.57%，一组退化 **30.18%**；超缓存 2/3 组更快，中位降幅 0.43%。证据不足以证明稳定收益，撤回。
2. **SSE2 乘积**：并行计算四个 FP32 分量对应的 double 差值/乘积，但仍按原顺序逐项累加；未改变 fast-math、未有意重排加法，非 SSE2 编译路径保留标量算法。主负载 3/6 组更快，中位配对耗时**增加 0.72%**；超缓存 1/3 组更快，中位耗时**增加 2.90%**。撤回。

以上两个方案依次单独测量，第二个不包含第一个的代码。下面的百分比为 100 × (1 - 候选查询耗时 / 基线查询耗时)，负数表示退化；**中位数取每组百分比的中位数，不是两列中位数相除**。

| 场景 / 种子 | 提前终止：基线 → 候选（秒） | 降幅 | SSE2：基线 → 候选（秒） | 降幅 |
|---|---:|---:|---:|---:|
| 主 1 / 3179 | 1.168957 → 1.079745 | 7.63% | 1.111304 → 1.163886 | -4.73% |
| 主 2 / 3181 | 1.219387 → 1.273528 | -4.44% | 1.082821 → 1.249398 | -15.38% |
| 主 3 / 3187 | 1.173810 → 1.017921 | 13.28% | 1.121480 → 1.070583 | 4.54% |
| 主 4 / 3179 | 1.023835 → 0.916089 | 10.52% | 1.018997 → 1.038032 | -1.87% |
| 主 5 / 3181 | 1.080758 → 1.086012 | -0.49% | 1.062725 → 1.058099 | 0.44% |
| 主 6 / 3187 | 0.990474 → 1.289432 | -30.18% | 1.065651 → 1.034811 | 2.89% |
| 超缓存 1 / 3179 | 1.770300 → 1.762755 | 0.43% | 1.784082 → 1.858913 | -4.19% |
| 超缓存 2 / 3181 | 1.850495 → 1.773113 | 4.18% | 1.837269 → 1.890622 | -2.90% |
| 超缓存 3 / 3187 | 1.818060 → 1.870721 | -2.90% | 1.808723 → 1.783768 | 1.38% |

每个主实验为 10,000×128、每批 100 行写入、1,000 个 TopK 10 查询且一半等值过滤；三个种子各重复两次，顺序交替。每个超缓存实验为 32,000×128、100 查询、三组交替配对。全部候选和基线均使用各自新容器与数据目录，2 CPU、128 MiB、0 swap，并限制 CPU 0、1。每轮计时区间之外独立 NumPy 参考验证所有计时查询的 ID、顺序、距离、过滤、重复 ID 和 Recall；主实验各 **12,144** 条检查、超缓存各 **672** 条检查，Recall 均为 1.0。重启后核对了全部 ID 和过滤列；该项没有逐一重读所有向量分量，不应冒充完整向量回读。旧版本的完整向量重启检查见历史报告。

每次主测试同一容器的 memory.peak 中位值：提前终止基线/候选 14,047,232 / 14,010,368 字节，SSE2 基线/候选 14,096,384 / 14,077,952 字节；超缓存分别为 31,469,568 / 31,342,592 和 31,289,344 / 31,408,128 字节。全部已采样容器的 memory.events 在采样终点均为 max/oom/oom_kill 0。这些是测试范围内的容器峰值，不代表所有输入或整个平台峰值安全。

各实验的 paired-summary.json、runner.stdout.log 保存每轮结果和限制。io.stat 仅覆盖 ready 至 shutdown 前采样，缺少独立数据设备与完整写回窗口；**不能作为正式物理 I/O 或综合性能指标**。每次性能容器之后再启动容器核对持久化 ID；重启时间包含 Docker 启动。没有计算官方分数或排名。

完整本机原始输入、每轮请求与大体积 workload 文件保存在本工作目录的各实验子目录；[原始证据清单](raw-evidence-manifest.json) 保存其路径、大小和哈希，并逐对核对实际请求解压后的哈希一致。为避免大文件淹没团队仓库，完整输入文件没有随本提交推送，其他机器需要按下文命令重新生成；不能把这些本机路径说成远端已有原始文件。每轮汇总和资源记录另行纳入提交。

## 本机正确性和实际边界

- 基线 Release：CTest 6/6；原有黑盒含压力项 21/21；加入新测试后的额外回归含大输出 15/15。官方固定提交 f4d4e26653af823a7601668802f80e374ad6643c 原版 Docker 驱动：握手、sql_crud、20 个公开用例全部通过。官方配置为 2 CPU、2 GiB；不可用该项代替上面的 128 MiB 性能资源检查。
- 新增 tests/distance_differential.py：3 个种子、11 个维度、858 条 SQL，逐响应比较基线与基线、提前终止及 SSE2 两个实验二进制，并核对独立 FP32 参考、过滤、ID、距离和顺序；全部通过。新增 tests/optimization_acceptance.py 参考测试覆盖分块边界、极小和极大数值以及并列。用更严格的小数绝对误差阈值复测通过。
- 基线 ASan/UBSan Debug：CTest 6/6；黑盒 21 项中 20 通过、1 个压力测试跳过；额外回归 12 个测试通过、另有大输出测试类跳过。没有在 sanitizer 下执行被放弃候选的完整回归。
- 原生默认 JSONL 流测试首次将数据放在 F 盘挂载目录时失败，错误为 truncate sort temporary file: No such file or directory，见 final-stdio.txt；改用新的 Linux 文件系统目录后八种流边界测试对同一基线二进制两轮均通过，见 final-stdio-ext4-result.json。这与路径/文件系统差异相关，未单独证明底层根因。容器 broken-stdout 注入没有在本轮单独验证；原生验证不能替代它。
- Agent 材料追加了本轮真实用户原话、Agent 操作、实验事实及失败结果；未编造用户对技术的理解，旧 JSON 对象值不变。材料为严格 JSON，5/5 本地结构检查通过。**本地检查不代表官方 Agent 语义评审有效，更不能承诺得分。**

## 复现与下一步

先确认干净生产源码与工具起点，不覆盖旧目录。基线、两个候选分别建立独立 worktree；只在实验 worktree 应用对应补丁。每个实验独立构建本机镜像，记录源码、二进制、镜像与工具哈希，先跑 CTest、tests/optimization_acceptance.py 及 tests/distance_differential.py（分别指定基线和候选二进制及新输出文件），再运行原版官方驱动。

本目录中的候选构建脚本记录了本机路径，需要根据新环境调整。完成实验后才为它们增加了补丁反向试应用检查，防止在未应用实验补丁时误把基线标记为候选；这个后加的检查不属于当时测量过程。

在同一 Linux Docker daemon 且能读取对应 PID/cgroup 的机器上，使用交接工具 validation/perf-20261110-stdio/scripts/bench_portable.py，分别指定基线与候选镜像、全新 output-root 和 Linux 文件系统上的 data-root；主负载使用种子 3179、3181、3187 各两次、10000 行、128 维、1000 查询，超缓存用三个种子各一次、32000 行、128 维、100 查询。先执行 preflight-only，确保 2 CPU、128 MiB、0 swap 和真实 cgroup 可见；不同机器 CPU 编号需要先核对工具限制。运行期间不要并行运行其他性能任务。工具版本及详细命令见 TEAM_HANDOFF.md 第 6–8 节。

例如在 Linux shell 中，从含交接工具的 checkout 运行下列命令；事先设置好 BASE_IMAGE、CANDIDATE_IMAGE 和全新的绝对路径 OUT_ROOT、DATA_ROOT，DATA_ROOT 应在 Docker 宿主 Linux 文件系统上。每次预检和试验均使用不同子目录，且各路径尚不存在：

    TOOL=validation/perf-20261110-stdio/scripts/bench_portable.py
    python3 "$TOOL" --images base="$BASE_IMAGE" candidate="$CANDIDATE_IMAGE" --output-root "$OUT_ROOT/preflight" --data-root "$DATA_ROOT/preflight" --prefix reproduce-preflight --preflight-only
    python3 "$TOOL" --images base="$BASE_IMAGE" candidate="$CANDIDATE_IMAGE" --output-root "$OUT_ROOT/main" --data-root "$DATA_ROOT/main" --prefix reproduce-main --seeds 3179 3181 3187 3179 3181 3187 --rows 10000 --dim 128 --queries 1000
    python3 "$TOOL" --images base="$BASE_IMAGE" candidate="$CANDIDATE_IMAGE" --output-root "$OUT_ROOT/overflow" --data-root "$DATA_ROOT/overflow" --prefix reproduce-overflow --seeds 3179 3181 3187 --rows 32000 --dim 128 --queries 100

环境需要 NumPy，并按本机权限读取容器所属 cgroup；仅有远程 Docker socket 并不能保证该数据可用。各输出目录的 adapted 工具和 manifest 记录了原工具的哈希、路径替换与镜像 ID。

后续可在更安静的专用机器复测或提出新的独立假设；不要默认把本轮两个方案当成提升，也不要修改 WAL、正式协议、排序/事务规则来换取性能。官方 Agent 无有效原始分的具体原因尚未确认，保留原结果并由用户决定是否联系平台或再次正式提测。
