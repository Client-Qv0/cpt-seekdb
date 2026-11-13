# REPORT：并行精确扫描（Parallel exact scan）

日期：2026-11-13　基线：`10a8762faa16b2a547b6596edc4173152e380bb6`（未提交改动）
本目录记录本轮全部实测数据；原始 JSON 见同目录 `ab/`、`abq/` 等子目录。

---

## 1. 改动摘要

| 文件 | 变更 | 行数 |
| --- | --- | ---: |
| `src/engine.cpp` | 进程级 worker 池、按 CPU 亲和性选宽度、扫描切片化（连续路径与候选列表路径）、局部堆合并、异常回传 | +~210 |
| `src/exact_cache.hpp` | 测试用 `thread_limit()` / `parallel_runs()` 访问点（默认 0 = 自动） | +12 |
| `tests/test_parallel_search.cpp` | 新增：多宽度结果逐字节一致、合并顺序、worker 确实启用 | +138 |
| `CMakeLists.txt` | 注册 `parallel_search` 测试 | 1 行 |

语义不变量：结果逐字节不变、距离并列仍按主键升序、过滤/投影/事务/持久化/恢复不变、
单 CPU 自动退化串行、候选行 < 1024 走串行。

## 2. 环境

```
Ubuntu 24.04.1 LTS, g++ 13.3.0, CMake 3.28.3, Python 3.12
Intel Xeon Gold 5218, nproc=4（测量时固定 AllowedCPUs=0-1）
cgroup: MemoryMax=134217728, MemorySwapMax=0, CPUQuota=200%
```

二进制身份：

| 变体 | SHA-256 |
| --- | --- |
| 基线（`build-verify`，与冻结值一致） | `9aa8283238a2e9e513b8f25d621becb2680d7a5e8bdebfa78dff014f9614e84a` |
| 候选（线程开启） | `2b8032ac209c2c838e0912f52b50b534b841a45bfa49f40a94f5592439d33792` |
| 对照（同源码，阈值调到 1G 使线程永不启用） | `b9b49ad8b8e17717985990419a529bd4c8648c4c36cff9c42957cf683fc9b324` |

## 3. 正确性验证（本机实测）

| 项目 | 结果 |
| --- | --- |
| Release CTest | **8/8**（新增 `parallel_search`） |
| ASan+UBSan CTest | **8/8** |
| ThreadSanitizer（`parallel_search`，`setarch -R`） | **无数据竞争报告** |
| `acceptance.py --stress` | **21/21** |
| `optimization_acceptance.py --large` | **16/16** |
| `test_public_bridge.py` | **4/4** |
| `test_agent_material.py` | **8/8** |
| 官方公开题包（f4d4e266） | **20 用例 / 95 SQL 全过** |
| 多宽度确定性 | width ∈ {1,2,3,4,2} × 48 条查询，12000 行含大量等距记录，逐字节一致 |

## 4. 性能（配对交替，2 CPU cgroup，3000 次查询）

### A. 候选 vs 冻结基线（20 对）

| 指标 | 配对中位数 | 胜率 | 区间 |
| --- | ---: | ---: | --- |
| 查询耗时 | **+22.37%** | **20/20** | +10.74% … +28.66% |
| 写入耗时 | −5.67% | 3/20 | −11.04% … +6.21% |
| 峰值 RSS | 0% | — | 11648 KiB → 11648 KiB |

查询中位数绝对时间：1.1667 s → 0.9021 s（**1.29×**）。

### B. 候选 vs 同源码关闭线程（20 对，用于归因）

| 指标 | 配对中位数 | 胜率 |
| --- | ---: | ---: |
| 查询耗时 | **+24.06%** | **20/20** |
| 写入耗时 | +5.21% | 16/20 |

### 结论与解读

- 查询侧 **20/20 胜、+22~24%**，两种对照方向一致，是本轮唯一主效应。
- 写入侧两次对照下方向相反（A：−5.7%，B：+5.2%），且写入代码路径完全未改动、
  线程在写阶段尚未创建。**判定为 fsync 主导的测量噪声（±10%），不是回归**。
  若要给出写入结论，需要写专用负载与更多重复，不在本轮范围。
- 噪声控制：同二进制 base-vs-base 对照（8 对）显示查询中位 −2.96%、单对波动 ±14%，
  因此本报告只采用「多配对 + 胜率」，不采用单次数字。

## 5. 未验证/限制

- 正式判题环境 CPU 配额未实测；设计按 `sched_getaffinity` 自适应，1 CPU 时退化为串行。
- 未跑真实 cgroup `memory.peak`（只有进程 RSS）；线程栈按需触页，RSS 实测无变化。
- 未测 4 CPU 配置下的收益（官方记录为 2 CPU）。
- 未测超大表（百万行）时的表现：超过 12 MiB 视图预算会走 `exact_bypass` 串行路径。
- 本地 A/B 不是官方分数。

## 6. 复现命令

```bash
cd /home/li/minivectordb-self-iterate-20261113
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release -j4
ctest --test-dir build-release --output-on-failure

/home/li/verify-out-20261113/abq.sh <输出目录> \
  /home/li/build-verify-20261113/minivectordb \
  /home/li/build-parallel-20261113/minivectordb 20 3000
```
