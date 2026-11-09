# MiniVectorDB V2 当前进度与下一位 GPT 的交接说明

更新日期：2026-11-09（北京时间）。本文面向接手人及其 GPT。**无需原服务器、服务器账号、部署密钥或原聊天记录。** 通过 GitHub 克隆即可取得源码、公开样例、实验脚本、原型快照和已提交证据；本机 WSL 可以重新构建验证。

## 1. 先看结论

- **生产实现仍然是 V2。** 后两轮没有把实验优化合入默认 `src/`、`CMakeLists.txt`、`Dockerfile`。
- V2 的紧凑主键树保留了百万短记录约 32 MB 匿名内存收益，但仍是 O(N) 常驻索引，不能声称固定内存支持任意容量。
- 已新增公开样例自测桥：原生 V2、实际 Docker 入口及第二版精确剪枝原型均通过 **20 个公开用例、95 条 SQL**。
- 两版精确剪枝原型在本机三组配对中的查询耗时中位改善约 **5.17% / 9.38%**；第二版有一组退化约 1.88%。均未达到上一轮预设的 20% 工程目标，因此保留证据、恢复生产 V2。
- 独立列式组件原型已验证连续向量布局和等值过滤 postings 的基本结果；**尚未接入 Engine**，没有证明完整缓存失效、事务可见性、严格实际内存预算或数据库端到端收益。
- 单行 UPDATE 出现过孤立慢例，但历史稳定约两倍退化的根因仍未确定。没有声称已经修复。
- **未提交正式评测，未证明正式 29 例准入通过，未实现真正 ANN，也没有官方成绩。**

## 2. 仓库、分支和版本

团队仓库：https://github.com/Client-Qv0/cpt-seekdb

当前交接分支：`perf/exact-query-li-20261109`

| 层次 | 完整 commit SHA | 含义 |
|---|---|---|
| 最初 V2 交接 | `e5093aec5ce443d863a92a684eae7ed8f90a736e` | V2 源码、最初两轮证据、旧 HANDOFF |
| UPDATE 调查 | `75ecbf3e60a68de7d833aa899bc0fcb4c48df47e` | 同机重建、原始历史复现、诊断与回归；生产未改 |
| 当前代码/证据基线 | `08e5f5518fd6583189d34072bb2af40447d7a6a5` | 公开桥、Docker 核验、两版剪枝和列式组件实验；生产未改 |

本交接文档加入后，分支 HEAD 会比最后一行多一个文档提交，这是正常的。它不是新的生产候选。若分支以后又有源码变更，应先审查新增提交，不要擅自回退别人工作。

**旧 `HANDOFF.md` 是上一阶段交接，末尾提示词仍以 UPDATE 为主。先了解历史，但下一步任务以本文第 8 节为准。**

服务器上旧目录 `/opt/minivectordb-v2`、当前工作目录 `/opt/minivectordb-v2-query` 只是原执行位置。接手人没有这些目录完全正常；不要在本机照建 /opt 或等待连接服务器。

## 3. 比赛要求与当前缺口

- [加赛赛题](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/lg8enxlmwg69unt6)
- [加赛算分](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/dbf6uzmwsuupp7hn)
- [已核对的公开题包](https://github.com/oceanbase/seekdb/tree/9f6df2ba5acf871376e22b64a3d0724e4b575044/mysqltest)

公开题包固定提交为 `9f6df2ba5acf871376e22b64a3d0724e4b575044`，版本 `minivectordb-public-v4`。其 README 说明：20 个公开样例、95 条 SQL；正式共 29 例，其余具体输入保留。公开包本身没有完整进程通信驱动。

功能准入必须全部通过，才有两项加赛计分资格。性能和 Agent 材料各占 40 分、分别排名。性能写入/查询权重为 1:2，每项再按耗时/I/O/内存 60%/20%/20% 合成排名指标；索引装载、准备和预热的内存、I/O 不能隐藏到统计范围外。缺少官方冻结基线和校准 I/O，不预测分数或名次。

当前程序只支持显式 `--dev-protocol` 的逐行 SQL / JSON 开发接口。公开 `.result` 是断言数据，不意味着正式输出也必须是 JSON。
`tests/public_samples.py` 对 `--mode ann` 明确采用现有精确后端回退；这不是 ANN 实现验证。未冻结正式错误映射时，桥按公开 README 检查失败和非空错误码，不声称已核验正式语义码映射。

两份官方网页对“未指定最终版本时”的默认选择有差异（最近通过/最优通过），应在正式提交前确认；本阶段不选择、不提交正式版本。

## 4. 必读材料与证据导航

按以下顺序读，不需要逐条阅读全部大型 JSON：

1. 本文。
2. `validation/exact-query-li-20261109/REPORT.md`：最新结论、两版负结果、原型范围及复现限制。
3. `validation/exact-query-li-20261109/paired-initial/summary.json` 与 `paired-blocked/summary.json`：全部配对指标。
4. `validation/update-latency-li-20261109/REPORT.md` 与 `VALIDATION.md`：UPDATE 调查和 V2 同机重建证据。
5. `validation/cardinality-20261109/REPORT.md`、`paired-candidate-v2/TABLES.md`、`run-manifest.json`。
6. `validation/audit-20261109-42affed2e283/AUDIT.md`。
7. `agent/conversation.json`：真实材料，来源已有区分；不得把 Agent 判断改写成学生理解。
8. `src/engine.cpp`、`storage.cpp`、`main.cpp`、`tests/optimization_acceptance.py`。

最新实验目录中的重点文件：

| 文件 | 用途 |
|---|---|
| `public-package/mysqltest/` | 已归档公开题包，不依赖重新下载 |
| `public-baseline.json`、`public-docker.json`、`public-prototype.json` | 每条 SQL 的期望与实际响应 |
| `docker-production-build.log`、`docker-production-image.json`、`docker-binary.sha256` | 生产 Dockerfile 的当次构建与实际可执行文件绑定 |
| `query-profile-result.json`、`query-profile-wall.json`、`query_profile_main.cpp` | 独立诊断，不能当默认性能成绩 |
| `prototype-initial-source/`、`prototype-blocked-source/` | 被拒绝的实验源码，不是默认生产源码 |
| `candidate-initial-manifest.json`、`candidate-manifest.json` | 分别对应两个源码快照的生产文件哈希 |
| `oracle-seed-9143.json`、`oracle-seed-27183.json` | 额外 seed 的独立正确性验证 |
| `columnar_probe.cpp`、`columnar-*.json` | 尚未集成的列式组件及有限探针结果 |
| `resource-prototype/`、`million-memory.json` | 原型的真实 cgroup 回归和百万行内存对照 |
| `evidence-manifest.json` | 已提交证据文件的字节校验清单 |

## 5. 已执行结果：不能当成本机验证

原测试环境为 Ubuntu/Linux x86_64、GCC 13.3、CMake 3.28、Python 3.12，当前服务器约 4 核/8 GiB。以下均是**原服务器或报告指定的历史环境**结果；接手人的机器需要重新执行。

| 被测对象/验证 | 已有结果 |
|---|---|
| V2 公开样例：原生和实际容器 | 各 20/20 用例、95/95 SQL |
| V2 生产 Dockerfile 无缓存重建 | 成功，镜像可执行文件与冻结 V2 同哈希 |
| 第二版剪枝原型 Release | CTest 6/6，黑盒 19/19，额外回归 11/11 |
| 第二版原型 ASan/UBSan | CTest 6/6；黑盒 18 通过+1 压力跳过；额外 8 通过+大输出类跳过 |
| 两次剪枝配对实验 | 各 6 轮，分别 6066 条向量响应独立核对通过 |
| 额外 seed 9143/27183 | 各 1000 条独立核对，过滤/无过滤 Recall=1 |
| 原型真实 128 MiB 资源测试 | 4/4，无容器 OOM；部分 peak 触顶，不能说内存余量充足 |
| 百万行控制/原型内存 | 两类差异至多约 4 KiB；不是完整百万行恢复 oracle |
| UPDATE 调查中的 V2 | Release 5/19/11、资源 4/4、双向 WAL/checkpoint 验证通过 |

**注意：默认生产源码现在是 V2，CTest 是 5 套；6 套属于带 exact_distance 测试的实验快照。**

查询诊断一次观测：1000 查询端到端约 2.468 s，Engine 约 2.182 s，序列化/输出/flush 约 0.046 s；尚未把 Engine 内部进一步分解成解析、过滤、距离、堆选择。该诊断不是对所有负载的归因。

第一版/第二版热查询配对中位改善为 5.17%/9.38%；第二版一组退化约 1.88%。只有三组、顺序非完全均衡，不是稳定跨机器保证。20% 是上一轮工程接纳目标，不是比赛官方门槛。

列式组件的 10k×128 探针只有一次进程内比较，行路径先测、列路径后测，且同时持有参考行数据；其约 5.32 MB 是容量估算，不是容器峰值。不要把这些数字包装成生产收益或严格预算证明。

上一轮子代理审查未返回可用结果，报告未声称独立代码审查批准；实际有主代理自审和数值 oracle。后续正式候选应补独立代码审查。

## 6. 接手人使用本机 WSL 的步骤

以下步骤已核对仓库中的路径与接口，但尚未在接手人的另一台 WSL 上实测；执行结果须由新机器重新记录。

### 6.1 准备环境、克隆和开个人分支

使用 WSL2 Ubuntu，项目放在 Linux 文件系统（如 `~/projects`），不要放在 `/mnt/c`。至少需要 Git、C++17 编译器、CMake、make、Python 3；NumPy 用于独立向量参考，Docker 用于容器/真实资源测试。

如未安装基础工具，可在自己的 Ubuntu 中安装：

```bash
sudo apt-get update
sudo apt-get install -y git build-essential cmake python3 python3-venv

mkdir -p ~/projects
cd ~/projects
git clone --config core.autocrlf=false --branch perf/exact-query-li-20261109 --single-branch \
  https://github.com/Client-Qv0/cpt-seekdb.git minivectordb-next
cd minivectordb-next

git status --short --branch
git rev-parse HEAD
git merge-base --is-ancestor 08e5f5518fd6583189d34072bb2af40447d7a6a5 HEAD
git diff --exit-code 08e5f5518fd6583189d34072bb2af40447d7a6a5 -- src CMakeLists.txt Dockerfile

# 把 alice 换成自己的标识，避免与别人同名。
git switch -c perf/columnar-alice
```

若最后的源码差异检查失败，先审查新增提交，不能直接覆盖/重置。GitHub 推送使用接手人自己的身份和团队写权限，**不要索取或复制原服务器的 deploy key**。

### 6.2 只读校验历史证据

先运行原只读工具：

```bash
python3 tools/handoff/verify.py
```

当前应显示 13 项生产文件、49 项旧审计证据、320 项 cardinality 证据均零失败。它不包含后两轮全部新证据，另执行下列可迁移只读校验：

```bash
python3 - <<'PY'
from pathlib import Path
import hashlib, json

for folder in ("update-latency-li-20261109", "exact-query-li-20261109"):
    root = Path("validation") / folder
    manifest = json.loads((root / "evidence-manifest.json").read_text())
    failures = []
    for entry in manifest["files"]:
        path = root / entry["path"]
        if not path.is_file():
            failures.append("missing: " + str(path))
            continue
        data = path.read_bytes()
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            failures.append("mismatch: " + str(path))
    print(folder, len(manifest["files"]), "files;", len(failures), "failures")
    assert not failures, failures

# 对当前学习材料只匹配最新轮清单；旧清单记录的是当时的历史版本。
latest = json.loads(Path("validation/exact-query-li-20261109/evidence-manifest.json").read_text())
assert hashlib.sha256(Path("agent/conversation.json").read_bytes()).hexdigest() == latest["learning_sha256"]
PY
```

预计后两轮分别校验 141 和 206 个清单文件。清单自身不计入自身；Git 中还保存清单文件。不要为“通过校验”修改旧清单或日志。后续有意修改生产代码后，应生成新候选清单，不能继续要求它匹配旧 V2 的 13 项清单。

**不要直接运行 `finalize.py`、`finalize_evidence.py` 或旧一键脚本来校验。** 它们可能重写清单、依赖未归档二进制或服务器绝对路径。上述代码只读，不重写材料。

### 6.3 本机重新构建和基础回归

```bash
RUN_DIR="validation/local-handoff-$(date +%Y%m%d-%H%M%S)"
mkdir "$RUN_DIR"

cmake -S . -B build-handoff-local -DCMAKE_BUILD_TYPE=Release
cmake --build build-handoff-local --parallel 2
ctest --test-dir build-handoff-local --output-on-failure

python3 tests/test_public_bridge.py
python3 tests/acceptance.py --binary ./build-handoff-local/minivectordb -v
python3 tests/optimization_acceptance.py --binary ./build-handoff-local/minivectordb -v

python3 tests/public_samples.py \
  --binary ./build-handoff-local/minivectordb \
  --package validation/exact-query-li-20261109/public-package/mysqltest \
  --output "$RUN_DIR/public-samples.json"

sha256sum build-handoff-local/minivectordb
g++ --version
cmake --version
python3 --version
```

基础黑盒默认跳过压力项，额外回归默认跳过大输出类；先报告实际跳过，不当作完整覆盖。有足够时间/内存时另跑：

```bash
python3 tests/acceptance.py --binary ./build-handoff-local/minivectordb --stress -v
python3 tests/optimization_acceptance.py --binary ./build-handoff-local/minivectordb --large -v

python3 -m venv build-handoff-venv
. build-handoff-venv/bin/activate
python -m pip install numpy
python -m pip freeze > "$RUN_DIR/python-packages.txt"
```

本地重建哈希可能因工具链/运行库不同而变化，记录自己的哈希及实际测试，**不要求所有机器都生成历史 `78996ec9...` 二进制**。这不影响先按源码清单核对生产输入。

### 6.4 可选：复现实验快照

不要把快照直接覆盖到当前生产 src。第二版快照可以在独立 build 中构建：

```bash
cmake -S validation/exact-query-li-20261109/prototype-blocked-source \
  -B build-prototype-local -DCMAKE_BUILD_TYPE=Release
cmake --build build-prototype-local --parallel 2
ctest --test-dir build-prototype-local --output-on-failure
```

此处才应有 6 套 CTest。第一版快照没有完整测试副本，不能仅凭其 CMake 自动跳过测试而声称同等覆盖。

### 6.5 Docker 与 WSL 的特殊注意事项

Docker 是独立前置条件，不应阻止先完成原生构建/公开样例自测。确认 `docker info` 可用后再从生产 Dockerfile 构建自己的新标签，记录源/镜像/二进制及依赖版本。

Docker Desktop 的引擎可能位于另一 VM：WSL 中看到的 `/proc/<pid>` 和 `/sys/fs/cgroup` 不一定是引擎宿主视图。旧 adapter 依赖宿主 PID/cgroup 路径，**不能默认直接可用**。若无法读取实际 cgroup，应明确只完成普通容器测试，不声称已完成真实 memory.peak/io.stat 核验；原生 RLIMIT_AS、RSS、文件大小均不能替代这些指标。

旧脚本中的镜像 ID、Docker socket、CPU 0,1、绝对 /opt 路径只是原机器配置。先复制到新的验证目录再参数化；读取本机可用 CPU 集合及实际限额。不能执行全局 drop_caches，也不能启停别人的 Docker 服务。

## 7. 下一步计划与验收

### 优先任务：集成可回退的单预算列式缓存

1. 冻结当前 V2 为本机控制版本，所有新实验写入新的 validation 子目录。
2. 进一步分解解析/过滤/距离/TopK 开销；诊断构建和默认构建分开。不要因已有组件微基准便认定瓶颈。
3. 在总缓存预算内，以连续 FP32 向量、主键及所需过滤列替代相应整行缓存；避免两套完整向量长期重复持有，计入 capacity、临时峰值、postings 和分配器开销。
4. 运行时普通列等值过滤可使用 postings，但不能写死组名/组数/维度/数据规模；复杂谓词、预算不足和大数据回退原通用精确扫描。
5. 保留 FP32 量化、FP64 距离、过滤后 TopK、距离并列主键升序；不要默认启用 fast-math，也不要无条件用距离平方替代带舍入并列规则的比较。
6. 正确处理 INSERT/UPDATE/DELETE、失败语句、显式事务读己之写、BEGIN/COMMIT/ROLLBACK 和重启后的缓存重建。可先沿用保守整表失效，不先追求复杂增量更新。
7. 增加预算拒绝、各种维度/分组、空集/不足 K、同距离、极值、投影、失败语句和随机事务参考模型测试，再做端到端对照。

验收：控制/候选在**同一台机器、同资源、独立数据目录**比较；至少三组，建议预先固定更充分且均衡的配对顺序。默认 seed 与多个新 seed 分开验证。先明确接纳门槛，20% 是上轮工程目标而非官方规则；保存所有退化样本，不追加运行直到出现有利结果。

完整候选回归至少包含公开20例、默认 Release、适用 sanitizer、真正 cgroup 资源回归和独立 FP32/FP64 oracle；若触及持久化，再增加相应 crash/checkpoint 和双向兼容检查。解释每项跳过和未测范围。保持百万短记录内存收益，不以 RSS 替代 cgroup。

只有端到端和完整生命周期资源证据支持净收益时才合入；否则保留原型及报告、恢复生产。后续才考虑独立的 pwritev 写入实验或自研 ANN，不在同一候选同时重写三层。

UPDATE 尾延迟保持独立问题：有需要时在完整原写入/查询历史下捕获实际慢例的系统调用及调度证据；不能预设紧凑树、fsync、GIL 为根因。

### 交付与协作规则

使用自己的个人分支。提交前检查 diff、明确暂存本轮文件并做独立审查；推送自己的 origin 分支，返回完整 SHA、默认/候选结果、退化、跳过和剩余问题。不要强推，不覆盖别人的分支，不自动提交正式评测。

agent/conversation.json 只追加真实人/Agent/工具记录，不含凭据，不编造学生学习、解释或实验反馈；注意最新规则的 128 KiB 限额。历史材料路径/日志不可改写成新机器结果。

## 8. 可直接复制给下一位 GPT 的提示词

> 你要接手 OceanBase 加赛 MiniVectorDB。工作环境是我当前的本机 Linux/WSL，不要求原服务器。
>
> 先完整阅读 HANDOFF_NEXT_GPT.md，核对当前分支、Git 提交和文中必读材料。当前代码/证据基线为 08e5f5518fd6583189d34072bb2af40447d7a6a5；若其后仅增加本交接文档，生产基线不变。旧 HANDOFF.md 用于历史背景，不直接沿用其以 UPDATE 为主的旧任务。
>
> 当前默认生产仍是 V2；两版精确剪枝只留在实验快照，不能当作已合入。列式组件只是尚未接入 Engine 的独立探针。现有20例/95SQL公开桥通过不能称为正式29例准入，ANN指令当前明确精确回退，正式通信驱动仍需核对。
>
> 先在本机执行只读哈希校验、Release 构建、CTest、公开桥及基础回归，建立新的 validation 输出目录，记录工具链和本机二进制哈希。不要把旧报告当成本机验证，不运行会覆盖旧清单的 finalize 脚本。不要直接使用 /opt 绝对路径、旧镜像 ID、CPU编号或Docker socket；先参数化并核对本机环境。WSL/Docker Desktop 的宿主PID和cgroup视图需要实测确认。
>
> 本轮优先完成单预算、可回退列式缓存的 Engine 集成：连续 FP32 向量、主键与必要过滤列，通用谓词/超预算/大数据回退；保持精确过滤后TopK、稳定排序、事务可见性和失败语句/事务边界缓存失效。先用细分profile验证瓶颈；不要因微基准就承诺生产收益，不同时引入ANN或修改WAL。
>
> 先写有意义的回归和参考模型，再实施最小改动。控制和候选必须同机同资源交替运行，固定轮数和完整原始输入，独立核对多个seed、分组、维度、距离、ID和顺序。默认构建、插桩、参考计算分别记录；统计完整准备阶段资源，不把文件大小当物理I/O。
>
> 完成实际适用的Release、sanitizer、资源和恢复回归，明确跳过/未测，保存所有负结果。证据不足或未达到工程目标就保留实验并恢复生产，不包装成提升。旧UPDATE慢例仍未定位，除非新证据明确，否则不预设原因或删除提交同步。
>
> 普通实现选择自行推进。用我的个人开发分支提交推送，返回完整commit SHA、验证、收益/退化和剩余问题；不要强推、覆盖其他人的工作或提交正式评测。只记录真实交互，不能把你的工作冒充学生理解。

## 9. 文件迁移边界

Git 中已有可迁移：默认源码、测试桥、公开包、原型源码快照、逐查询结果、SQL gzip、报告、脚本及清单。

Git 不含、也不要求取得：原机器 build 目录/可执行文件、大型临时数据库、正在运行的容器、Docker 镜像缓存、原服务器凭据和原聊天完整导出。它们应在本机重新生成。部分 JSON 中的旧绝对路径是历史运行元数据，不代表接手人需要同名目录或这些文件现在仍存在。

目前仓库中的原始学习材料是摘要/摘录，不是完整聊天导出；缺失部分不能由 GPT 补造。本文即为无需原服务器即可开始工作的交接入口。
