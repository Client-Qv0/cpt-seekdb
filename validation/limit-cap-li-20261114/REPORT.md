# 退役 `limit <= 4096` 常数上限（2026-11-14）

## 结论

TopK 快路径有一个与内存无关的硬上限 `*st.limit <= 4096`。结果大小本来就由
结果预算（4 MiB）和实测宽度判定，这个常数只是让 `LIMIT` 超过 4096 的查询
全部掉进"逐行物化投影"的通用路径。

`LIMIT 5000`（10k 行、200 条查询）从 **5.332 s 降到 2.559 s（2.09×，4/4 胜）**，
标准基准无回归。

## 测量条件

2 CPU cgroup、`MemoryMax=128 MiB`、零 swap。改动前二进制 = `36a8092` 的构建。

| 形状 | 改动前 | 改动后 | 中位 | 胜 |
|---|---:|---:|---:|---:|
| LIMIT 5000，200 查询 | 5.332 s | 2.559 s | **+52.2%** | 4/4 |
| 标准基准（10k/128D/TOPK 10），8 对 | — | — | 查询 +1.46% | 5/8 |

每对数值 51.4–53.2%，几乎无离散，远超本机 ±3% 的零效应带（见
`validation/declared-width-budget-li-20261114/noise/`）。

## 改动

`src/engine.cpp`：

```cpp
const bool heap_fits = limit <= result_budget / 64;
const bool wide_ok = declared_fits && heap_fits;
const bool narrow_ok = limit <= 4096 && measure_actual;
if (limit && (wide_ok || narrow_ok) && ...) {
```

- `heap_fits`：每个 winner 在堆里先占一个 `Neighbor`（24 B），用 64 B 计上限，
  65536 封顶，避免堆本身无界。
- **宽上限只在声明口径已经放得下时启用**（`wide_ok`）。这是被验收测试逼出来的：
  只放宽常数时，`LIMIT 8000` + 大 payload 表的冷查询会逐行物化 8000 个大行，
  `optimization_acceptance` 直接报 `std::bad_alloc`。没有视图时没有实测宽度可用，
  所以宽上限必须同时满足声明口径。
- 窄上限区间（`<= 4096`）保持上一提交的"声明口径或实测口径"逻辑不变。

## 正确性

- 新增用例：5000 行构造表上 `LIMIT 5000` 必须返回 5000 行、按 `(distance, id)` 有序，
  且 `LIMIT 4100` 的结果必须是 `LIMIT 5000` 的前缀。
- Release CTest 9/9、stress 21/21、optimization/large 16/16。
- 说明：本候选**没有"改动前失败"的测试**——两条路径结果本就相同，差异只有性能。
  验收门槛是"构造形状上跨数量级 + 结果等价 + 无回归"，不是红绿翻转。

## 残留

- `declared_fits` 为假且 `LIMIT > 4096` 的查询仍走通用路径（与改动前一致，安全但不快）。
  要消除得给快路径加落盘排序（`SpillSorter`），风险高于本轮时间预算。
- 官方隐藏负载是否使用 `LIMIT > 4096` 未知；本改动在最坏形状上是 2.09×，不踩中时无影响。

## 身份

```
改动前（36a8092） 见 binary.sha256
改动后            见 binary.sha256
分支              perf/declared-width-budget-li-20261114
```
