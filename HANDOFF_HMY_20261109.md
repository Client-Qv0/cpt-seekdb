# MiniVectorDB 接手说明：SQL 注释安全修复与当前缺口

更新日期：2026-11-09。本文是 `HANDOFF_NEXT_GPT.md` 之后的增量交接；历史报告记录的是各自当时的版本和环境，请勿把其中“未提交”“生产代码未改”等历史表述套用到本次提交。

## 先看结论

- 比赛分支为 `2026-competition-round2`。本次修改之前的完整提交为 `7d58539e73d9cafebbc529312789678f1fad759b`；本文件所在提交的完整 SHA 请运行 `git rev-parse HEAD` 获取。三个历史交接分支已在此前纳入本分支的历史，不需要再次合并。
- 本次修复了 SQL 解析器对 `--` 注释判断过宽而导致错误修改数据的问题，增加了解析、事务、自动提交和重启回归；没有引入 ANN、列式缓存或修改 WAL。
- 本机 Release、ASan/UBSan 和 Docker 公开样例已按下文范围验证。**公开 20 例 / 95 条 SQL 不等于正式 29 例全部通过**；没有提交正式评测，无法推算赛事得分或名次。
- Docker 依赖固定仅做了隔离探针，默认 `Dockerfile` 未修改；列式缓存仍未接入 Engine；UPDATE 慢例的根因仍不确定。

## 本次修改了什么

原来的词法分析把任意 `--` 都视作注释开始。例如 `DELETE FROM comment_guard WHERE id=1--2;` 被错误截断成 `DELETE ... WHERE id=1`，自动提交后真实删除了 ID 1，重启后删除仍存在。本地 V2 对照复现和每条响应见 [`validation/parser-safety-hmy-20261109/baseline-reproduction.json`](validation/parser-safety-hmy-20261109/baseline-reproduction.json)，修复前失败测试见同目录 `baseline-test.txt`。

`src/sql.cpp` 现在仅在 `--` 后跟空白或控制字符时按注释处理；不支持的 `1--2` 等表达式返回错误，避免静默执行被截断的语句。`#` 和合法 `--` 注释遇到 CR 或 LF 均结束，避免把换行后的语句吞入注释。注释规则参考 [MySQL 官方文档](https://dev.mysql.com/doc/refman/8.4/en/comments.html)。本修复没有实现算术表达式，不能把拒绝 `1--2` 理解为实现了 MySQL 全部表达式语义。

新增测试位于 `tests/test_parser.cpp` 和 `tests/acceptance.py`：覆盖合法注释、非法双横线、CR 后额外语句、失败语句不影响事务中先前的有效写入，以及自动提交失败后重启仍不发生误删。

## 本机验证结果

以下是本机运行记录，不代表队友机器或正式平台结果。证据均在 [`validation/parser-safety-hmy-20261109/`](validation/parser-safety-hmy-20261109/)；先读 `*-updated.txt` 获取加入最后一条自动提交回归后的完整结果。历史文件不覆盖。

| 范围 | 本机结果 | 对应记录 |
|---|---|---|
| Release CTest | 5/5 通过 | `release-ctest.txt` |
| Release 黑盒含压力项 | 21/21 通过 | `release-acceptance-updated.txt` |
| Release 额外回归含大输出 | 14/14 通过 | `release-optimization.txt` |
| 公开桥单测；原生公开样例 | 4/4；20 例 / 95 SQL 通过 | `release-public-bridge.txt`、`release-public-samples.*` |
| Agent 材料结构检查 | 5/5 通过 | `release-agent-material.txt` |
| ASan/UBSan CTest | 5/5 通过 | `sanitize-ctest.txt` |
| ASan/UBSan 黑盒 | 21 项中 20 通过、1 个压力项跳过 | `sanitize-acceptance-updated.txt` |
| ASan/UBSan 额外回归 | 11 个测试通过，另有 1 个大输出测试类跳过 | `sanitize-optimization.txt` |
| 原 Dockerfile 实际构建及容器入口公开样例 | 构建成功；20 例 / 95 SQL 通过 | `docker-build.txt`、`docker-public-samples.*` |

本次 Release 可执行文件 SHA-256 为 `ffe90b07f75fbb8b38ddf225b5e04176318d3f46614e5a195c646b18314aae4d`；该次镜像中二进制与本机 Release 文件逐字节相同，见 `docker-binary-comparison.txt`。Docker 构建使用了缓存，不是锁定依赖的无缓存重建证明。旧性能报告使用的二进制 SHA 为 `78996ec9a6d15c5357b5111a4fd78ed28bf1cde174538dee81ae5de1b2daf26c`，性能数字属于旧版本，不能直接归于这次解析器修改后的二进制。

在新的 Linux/WSL 构建目录执行以下命令重新验证；路径、编译器及依赖由接手人根据本机配置，记录新日志，**不要覆盖已有证据**。公开桥仍是开发协议适配，不是正式驱动。

```bash
cmake -S . -B build-teammate -DCMAKE_BUILD_TYPE=Release
cmake --build build-teammate --parallel 2
ctest --test-dir build-teammate --output-on-failure
python3 tests/acceptance.py --binary "$PWD/build-teammate/minivectordb" --stress -v
python3 tests/optimization_acceptance.py --binary "$PWD/build-teammate/minivectordb" --large -v
python3 tests/test_public_bridge.py
python3 tests/public_samples.py --binary "$PWD/build-teammate/minivectordb" \
  --package validation/exact-query-li-20261109/public-package/mysqltest \
  --output /tmp/minivectordb-teammate-public-results.json
python3 tests/test_agent_material.py -v
```

上述 `/tmp` 路径只是示例，运行前请换成自己新建的输出文件并确认不会覆盖已有文件。WSL 的 Windows 挂载目录在本机有临时文件行为限制，必要时为测试设置本机可用的 `TMPDIR`。仓库内 `run_*.sh` 是本轮证据生成脚本，会拒绝覆盖部分已有文件，不能直接当作无需调整的重复运行命令；具体环境和限制以脚本为准。

## Docker 固定依赖探针：尚未合入

[`validation/docker-lock-hmy-20261109/`](validation/docker-lock-hmy-20261109/) 保存了独立实验。第一次因基础镜像缺 CA 导致 HTTPS 校验失败（`snapshot-probe.txt`）；第二次因固定旧版 OpenSSL 需要显式处理降级而失败（`ca-probe.txt`）；第三次在隔离的证书阶段构造 CA bundle 后，成功访问固定时间的 Ubuntu 快照并查询包版本（`ca-probe2.txt`）。这只是 apt 元数据/证书可行性探针，不是完整数据库镜像的无缓存、可复现构建；探针中的旧 OpenSSL 包不应直接复制进运行时镜像。

默认 `Dockerfile` 的 Ubuntu 标签和 apt 包仍未完全锁定。后续若继续，应验证基础镜像摘要、所有依赖来源和 TLS/包签名，至少独立无缓存重建并比较可执行文件，再通过实际入口重跑公开样例；保留失败证据，不要关闭 TLS 验证。参考 [Ubuntu Snapshot Service](https://snapshot.ubuntu.com/)。

## 队友接下来需要做的事

1. **先核对正式准入接口。** 当前程序使用显式 `--dev-protocol` 的逐行 SQL / JSON 开发协议，公开题包没有完整正式通信驱动；确认官方驱动、错误码和最终输入输出约定，并在拿到正式用例后验证 29 例。公开 ANN 指令目前明确回退精确检索，并非真正 ANN。
2. **复测性能并补齐平台口径。** 已有旧版本本地 10,000×128、1,000 查询实验和重启校验见 [`validation/benchmark-public-hmy-20261109/REPORT.md`](validation/benchmark-public-hmy-20261109/REPORT.md)。修复后版本尚未按同一负载复跑性能；正式生成器、固定基线、资源上限、独立数据设备物理 I/O 和统一冷热缓存流程仍需确认。没有这些数据不要计算官方综合指标或宣称 40 分。
3. **谨慎推进列式缓存。** 现有列式代码只是独立探针，未接入 Engine。若继续，应先细分 profile，再写参考模型和回归，验证单预算、超预算和复杂谓词回退、过滤后精确 TopK、稳定顺序、事务可见性与失败语句/事务边界失效；同机同资源交替测试并保留负结果。
4. **继续排查 UPDATE 慢例。** 历史慢例尚未找到根因，不要预设原因或删掉提交同步。先复现原始写入和查询历史，结合事务和恢复回归决定是否修复。
5. **检查学习材料和提交要求。** `agent/conversation.json` 必须真实记录用户与 Agent 的实际交互；不能把 Agent 的分析伪装成学生理解。核对正式要求的文件位置和限制，并确保源码、Dockerfile 和材料最终来自同一个提交；是否正式提测由队伍决定。

提交前应重新核对当前分支、远端更新和本地改动，避免覆盖他人工作；不要强推。可先读 `HANDOFF_NEXT_GPT.md`、`validation/local-hmy-20261109/REPORT.md`、`validation/benchmark-public-hmy-20261109/REPORT.md` 以及本文件链接的证据，注意这些旧报告中的分支和状态可能已经过时。
