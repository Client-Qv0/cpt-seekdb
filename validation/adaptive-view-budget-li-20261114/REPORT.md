# 视图预算按 cgroup 内存上限自适应（2026-11-14）

## 结论

`exact::budget` 固定 12 MiB。50k 行 × 128 维的紧凑视图需要约 33 MB
（fp32 向量 25.6 MB + 量化码 6.4 MB + keys/文本），因此**永远**装不下，
每条查询都走 `exact_bypass`：全表扫 + 全列解码。

改成按进程可用内存推导预算后，同一张表进入视图路径：

| 50k 行 × 128 维，TOPK 10，200 查询 | 每查询 | 峰值 RSS |
|---|---:|---:|
| 改动前（bypass） | 79.2 ms | 6.5 MB |
| 改动后（紧凑视图） | **1.84 ms（43×）** | 39.2 MB |

内存与性能是明确的权衡：用容器里**已经分配**的内存换 43 倍查询速度。

## 改动

`src/cpu_budget.hpp` 新增 `mvdb::cpu::memory_limit_bytes()`：与既有 CPU 配额探测走同一条
祖先链（cgroup v2 `memory.max`，回退 v1 `memory/latest_in_bytes`），`max` 与 v1 的
超大哨兵都视为"无限"。**无限制时返回 0。**

`src/exact_cache.hpp` 把 `constexpr size_t budget` 改成 `inline size_t budget()`：

```cpp
floor   = 12 MiB                      // 原值，保持不变（无 cgroup 或限额很小时行为完全不变）
share   = memory_limit / 3
ceiling = 48 MiB
budget  = clamp(share, floor, ceiling)
```

在 128 MiB 的 cgroup 下得到 42 MiB，视图可容纳 50k 行；在无限制或 64 MiB 的 cgroup 下退回 12 MiB。

`tests/test_exact_cache.cpp` 随 API 改为 `exact::budget()`，并新增边界断言
（不得低于 12 MiB、不得高于 48 MiB）。

## 正确性

- **跨路径一致性**：同一张 50k 表、同一批 12 条查询（半数为过滤查询），
  分别在"无 cgroup 限制 → 12 MiB → bypass 路径"和"128 MiB → 42 MiB → 视图路径"下跑，
  输出 JSON 逐字节相同（`equivalence/`）。
- CTest 9/9（含新增预算边界断言）、stress 21/21、optimization/large 16/16。
- 标准基准（10k/128D/TOPK 10，视图本来就装得下）8 对：查询 +0.14%、4/8，无回归。

## 内存风险的边界

- 只在**探测到** cgroup 内存上限时增长；探测不到就保持 12 MiB，与改动前完全一致。
- 上限 48 MiB 硬封顶，不会随容器变大而无界增长。
- 50k 表实测峰值 39.2 MB，占 128 MiB 限额的 31%。

**需要人工确认的一点**：如果正式评测对"峰值内存"本身计分或另有限制，
这条改动是拿内存换性能，方向可能不受欢迎。它不改变任何结果，只改变驻留策略。
在 64 MiB 的 cgroup 下 50k 表对**两个版本都** OOM（`oom-check/`，rc=137），
因此该配置不是本改动引入的退化。

## 残留

- 视图仍然装不下更大的表（例如 100k × 128 = 66 MB > 48 MiB 上限），这类表继续 bypass。
- 更深一层的做法是"只留 keys + int8 码的瘦视图，幸存者回盘读 fp32"，
  可以把上限之外的表也拉进快路径，但需要新的磁盘读路径与保守性证明。

## 身份

改动前/后二进制见 `binary.sha256`。分支 `perf/declared-width-budget-li-20261114`。
