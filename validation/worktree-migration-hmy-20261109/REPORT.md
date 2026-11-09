# F 盘工作区迁移验证

2026-11-09 将本轮 MiniVectorDB 工作从 `E:/MiniVectorDB/work` 复制到 `F:/OceanBase/seekdb/cpt-seekdb`。F 盘现处于个人分支 `codex/minivectordb-hmy-20261109`，HEAD 为 `944c08ee3549a625706801565fe570d804e58928`；原 `2026-competition` 分支仍保留。E 盘工作区切为同一 HEAD 的 detached 状态，保留未提交文件作为备份；后续以 F 盘为工作目录。

迁移前为 212 个文件记录了字节数和 SHA-256，复制后两边全部匹配。旧生产及证据清单 13、49、320 项重新核验为零失败；本轮性能证据清单 103 个文件及 6 项源码/学习材料哈希均匹配。旧报告和清单未修改；其中 E 盘路径是历史运行时的真实路径，不代表本次测试从 E 盘源码构建。

在 WSL 中从 F 盘源码重新执行 Release 构建，生成的二进制 SHA-256 为 `78996ec9a6d15c5357b5111a4fd78ed28bf1cde174538dee81ae5de1b2daf26c`，与此前本机构建相同。CTest 5/5、公开桥单元测试 4/4、benchmark 辅助测试 2/2、常规优化测试 11 项通过（大输出类 1 项跳过）、公开样例 20 例/95 条 SQL 通过。日志及结果在本目录；CTest 临时目录使用 Linux `/dev/shm`，不代表本轮重新执行了完整性能、sanitizer 或 cgroup 压力测试。

切换分支后，F 盘原先存在且被原分支忽略的 `rust/Cargo.lock` 现在显示为未跟踪文件。它不是本轮改动，已保留；不要用未审阅的 `git add -A` 将其一并提交。

源代码、测试和证据现在都可从 F 盘查看。编译工具及 Python 依赖仍位于 E 盘，以遵循环境尽量不下载到 C 盘的要求。旧 `validation/local-hmy-20261109/` 和 `validation/benchmark-public-hmy-20261109/` 中部分脚本写有原机器/原 E 盘路径，应视为历史复现记录；通用 benchmark 用法见 `tests/README.txt`。迁移没有创建正式分支、提交、推送或提交评测。
