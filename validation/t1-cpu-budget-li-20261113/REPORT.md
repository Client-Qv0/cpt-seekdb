# T1 — CPU 配额感知的扫描宽度

基线：`59d425b651a4ca53970338cff58d296edf8a8d7b`
改动：`src/cpu_budget.hpp`（新增）、`src/engine.cpp`、`tests/test_cpu_budget.cpp`（新增）、`CMakeLists.txt`

## 机制

- 新增 `mvdb::cpu::budget_cpus()`：`min(affinity 可见 CPU 数, cgroup CPU 配额)`，结果缓存一次，
  查询热路径不读文件。
- 配额解析覆盖 cgroup v2 `cpu.max`（含 `max` 表示不限）与 v1 `cpu.cfs_quota_us/period`。
  v2 从挂载根逐级向下匹配 `/proc/self/cgroup`，任一层祖先上的限制都生效
  （Docker 把限制放在容器根，systemd scope 放在 `system.slice/` 下一层）。
- 池容量与扫描宽度统一来自同一预算，先定宽度再切片。
- 修复：宽度大于池容量时旧实现只执行 `body(0)`，其余切片会被静默跳过（漏行）。
  现在切片前先 `width = min(width, pool.capacity())`。

## 实测（`CPUQuota=200%`，无 cpuset，affinity=4，即公开启动器 `--cpus=2` 的形态）

| 构建 | 生效宽度 | nr_periods | nr_throttled | throttled_usec |
| --- | ---: | ---: | ---: | ---: |
| 旧（按 affinity=4） | 4 | 27 | **17** | **197,191** |
| 新（按配额=2） | 2 | 21 | **0** | **0** |

端到端查询（10 对交替，3000 次查询）：

| 指标 | 配对中位 | 胜率 |
| --- | ---: | ---: |
| 查询耗时 | +0.14% | 5/10 |
| 写入耗时 | +3.14% | 7/10 |

## 结论

- 配额识别正确：`--cpus=2` 形态下宽度从 4 降到 2；`CPUQuota=50%` 降到 1；
  cpuset 形态（`AllowedCPUs=0-1`）仍为 2；1 CPU 时仍不创建线程。
- **限流被完全消除**（17 次 → 0 次），但本负载的端到端查询时间在噪声内（+0.14%，5/10）。
  因此 T1 的价值是确定性与避免超订，不是可测量的吞吐收益。
- 保留。

## 验证

- CTest 9/9（新增 `cpu_budget`：cpu.max 解析、v1 解析、`effective_width` 边界、
  预算不超过亲和性）。
- `parallel_search` 多宽度确定性仍通过。
