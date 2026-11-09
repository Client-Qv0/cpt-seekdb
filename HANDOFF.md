# MiniVectorDB V2 队友交接（2026-11-09）

## 先操作，再把文末提示词发给你的执行 Agent

团队仓库：https://github.com/Client-Qv0/cpt-seekdb
交接分支：`handoff/minivectordb-v2`。这是开发交接，不是正式评测提交。
当前原始工作副本的 origin 是 OceanBase 官方仓库，team 才是团队仓库；
队友按下列 URL 新 clone 后，自己的 origin 就是团队仓库。

1. 使用 Linux x86_64，或 Windows 的 WSL2 Ubuntu。原实验为 Ubuntu 24.04、
   GCC 13.3、CMake 3.28、Python 3.12；基本构建需要 C++17、CMake、make 和 Python 3。
   资源复测另需 Docker/cgroup v2；独立向量参考计算需 NumPy（原环境 2.3.3）。
   Windows 用户把项目放在 WSL 的 Linux 文件系统内，例如 `~/projects`。
2. 使用自己的 GitHub 身份；推送需要团队仓库写权限。若提示无权限，由仓库管理员
   添加 collaborator。不要共享其他人的令牌、SSH 私钥或完整用户目录。
3. 在选定项目父目录执行：

```sh
git clone --branch handoff/minivectordb-v2 --single-branch https://github.com/Client-Qv0/cpt-seekdb.git minivectordb-round2
cd minivectordb-round2
git rev-parse HEAD
python3 tools/handoff/verify.py
git switch -c perf/update-latency-yourname
cmake -S . -B build-handoff -DCMAKE_BUILD_TYPE=Release
cmake --build build-handoff --parallel 2
ctest --test-dir build-handoff --output-on-failure
python3 tests/acceptance.py --binary ./build-handoff/minivectordb -v
python3 tests/optimization_acceptance.py --binary ./build-handoff/minivectordb -v
```

将 `yourname` 替换为自己的标识。先核对 `git rev-parse HEAD` 与交接者给出的完整 SHA。
初次校验应通过 13 项生产输入、49 项旧审计证据、320 项本轮证据。
后续生产源码修改后，不再要求匹配旧 V2 清单，应为新候选单独生成清单。
上述普通验收会明确跳过部分压力项，不等于已经复现全部资源测试。

4. 在这个项目根目录打开编码 Agent，粘贴文末提示词。无需拿到原聊天会话或旧电脑目录。
5. 完成验证后，检查实际变更，显式暂存本轮源码、测试、新报告及真实学习记录，再提交：

```sh
git diff --check
git status --short
# git add <本轮审阅过的文件路径>
git commit -m "perf: investigate and improve single-row update latency"
git push -u origin HEAD
git rev-parse HEAD
```

把自己的分支、完整 SHA、验证结果和剩余问题回传给交接者。多人分别使用各自分支，
由一人汇总；不 force-push，不把本分支直接当作正式参评分支。

## 当前进度与证据

- V2 的紧凑主键树将百万短记录的匿名内存峰值从约 72–73 MB 降至 40–41 MB。
  两类 200 万短记录在 128 MiB 下完成本轮阶段，基线在首扫 OOM；V2 仍为 O(N)
  常驻索引，并在 200 万时存在回收压力。
- UPDATE 加点查原三组配对从约 5.4–6.7 ms 增至 12.7–13.3 ms。12 次采样开关
  对照未确定根因，不能认定只是噪声。写入也有小幅退化；不是全面提速。
- V2 Release：CTest 5/5、验收 19/19、扩展回归 11/11；真实资源回归 4/4。
  6066 组 128D 响应独立核对，Recall=1；sanitizer 跳过项详见报告。
- 官方协议、完整题包和计分环境仍待核实。CREATE INDEX 主要保存声明，查询仍为
  精确扫描/缓存，尚未实现真正 ANN。旧 9.679× 不属于当前版本。
- 根目录已删除空的 conversation.json；当前真实材料在 agent/conversation.json。
  正式材料路径待官方协议核定，不能擅自补造学生理解或历史交互。

必读文件（按顺序）：

1. `validation/cardinality-20261109/REPORT.md`
2. `validation/cardinality-20261109/paired-candidate-v2/TABLES.md`
3. `validation/cardinality-20261109/run-manifest.json`
4. `validation/audit-20261109-42affed2e283/AUDIT.md`
5. `agent/conversation.json`

V2 生产树 SHA-256：`df56a37dcbae572b6283dfd4ee67cccc1e7e15f2117b59760cf7628936ae18f3`。
历史 Release 二进制 SHA-256：`78996ec9a6d15c5357b5111a4fd78ed28bf1cde174538dee81ae5de1b2daf26c`。
这些不是 Git commit SHA。本交接新增文档及字节校验工具，不改变 V2 的 13 项生产输入。
不同编译器、工具链或环境重建的二进制可能不同，应记录新哈希并重新验证。

本次交接提交前另从 Git 暂存区导出干净副本，在 WSL Ubuntu 24.04 重新构建：
382 个清单条目（13+49+320）逐字节校验通过，Release 二进制与上述 V2 完全一致。
CTest 5/5 通过；普通黑盒 19 项中 18 通过、1 压力项跳过；额外普通回归 8 项中
7 通过、1 大输出项跳过。本次没有重跑完整性能、sanitizer 或 cgroup 压力测试，
这些结论仍属于各自历史报告的被测对象与环境。

## 复现注意事项

完整历史证据随 Git 保存，原 build 目录、大型临时数据库和专用 Docker daemon 不随仓库迁移。
要比较旧基线，在新 `build-*` 目录解压 `baseline-source-snapshot.zip` 和
`baseline-tests-snapshot.zip`，然后自行构建。V2 的源码及测试快照也在同一证据目录。
快照内容须先检查再解压，保持生产文件相对路径；不要覆盖项目当前源码。

历史脚本可能引用原机器绝对路径、固定 Docker socket、镜像 ID 和 CPU 编号，
某些 validate 脚本直接覆盖历史日志。不要原样执行历史一键脚本。
先复制/参数化需要的驱动，在新输出目录运行；保留旧证据字节不变。
新机器需重新构建/确认镜像，核对 socket、CPU 可用集合、memory.max、swap 和 quota；
不要启动或关闭别人的 Docker 服务，也不要执行全局 drop_caches。
原容器测试挂载了精确 V2 二进制，不代表 V2 Dockerfile 重新构建已核验。
性能数字仅作历史背景，新机器需对两版本同机配对测量。

## 给队友执行 Agent 的提示词

你接手的是 OceanBase 加赛 MiniVectorDB V2，任务是在保留内存收益与事务正确性的前提下，
定位并尽可能修复单行 UPDATE 延迟退化。先读本 HANDOFF.md 和上面列出的五项材料。

先核对交接 commit、工作树、13 项生产输入和历史证据哈希，完成本机 Release 构建及
基本回归。记录工具链与新二进制哈希；不把历史测试通过当成本机验证通过。
当前阶段先做 UPDATE 调查，不同时引入 ANN 或重写磁盘索引。

以审计基线 B 和当前 V2 为诊断比较对象，从已保存的原始配对 SQL 恢复完整写入历史、
批大小、扫描/查询及事务前置顺序。单独加载最终 WAL 的实验只能作补充，不能代替
原写入历史的复现。原采样开关实验未解释退化，请保留该负结果。

在同机、同资源、独立数据库目录下交替运行，先用适当重复次数确认可复现性；
分别观察 UPDATE、后续主键 SELECT、数据库处理、提交同步等待、响应序列化及
客户端消费耗时。通过代码路径和 profiling 验证假设，不预设树操作、fsync 或采样器
一定是原因。诊断插桩和生产默认构建分开，不能用插桩耗时充当最终成绩。
若复现不了，报告原负载匹配程度、差异、波动和仍需排除因素，不虚构根因。

完成证据充分的最小修复，按 B/V2/新候选区分比较结果。保留精确查询、过滤后 TopK、
稳定排序、语句原子性、提交同步及崩溃恢复语义。禁止靠省略持久化或少返回数据提速。
修复后做相关事务、缓存失效、恢复及独立参考核验，并检查百万短记录内存优势是否保留。
最终候选完成完整本地 Release 回归与适用的 sanitizer、cgroup 资源回归；明确跳过项。

所有新证据放在新的 validation 子目录，不覆盖两轮旧清单或日志。记录源码/二进制/
脚本哈希、配对各轮耗时与波动、内存分项和负结果。RSS 不代替 cgroup 峰值，文件大小
不代替物理 I/O；官方未明确部分继续标为等待题包，不承诺正式通过或满分。

交付根因证据或未解决原因、改动取舍、测试与性能对照、剩余问题。更新真实学习材料，
在我的个人工作分支提交并推送到团队仓库，返回分支名和完整 commit SHA。
不得强推、覆盖其他人的分支或提交正式评测。普通实现选择自行完成，无需反复确认。
