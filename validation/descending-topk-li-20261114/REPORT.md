# 降序 TopK 进入 winner-only 快路径（2026-11-14）

## 结论

TopK 快路径要求 `!keys[0].desc`，因此 `ORDER BY d DESC` 永远走"逐行物化投影"的通用路径。
降序只是在 `(distance, key)` 全序上翻转距离项、同距仍按主键升序，快路径完全可以覆盖。

10k 行、`LIMIT 500`、200 条查询：**1.585 s → 0.582 s（2.72×，4/4 胜）**，标准基准无回归。

## 测量条件

2 CPU cgroup、128 MiB、零 swap。改动前二进制 = `8c94125` 的构建。

| 形状 | 改动前 | 改动后 | 中位 | 胜 |
|---|---:|---:|---:|---:|
| DESC LIMIT 500，200 查询 | 1.585 s | 0.582 s | **+63.0%** | 4/4 |
| 标准基准，8 对 | — | — | 查询 +1.05% | 5/8 |

每对 61.5–64.7%，远超本机 ±3% 零效应带。

## 改动

`src/engine.cpp`：

- 门限去掉 `!keys[0].desc`。
- `better_neighbor` 捕获 `descending`：距离用 `>` 或 `<` 比较，同距仍 `key` 升序。
- `screen = !descending && exact::fp32_screen_available(view.dim)`：
  `fp32_screen_threshold` 与 `quantized_threshold` 都假定"越小越好"（以堆顶为最差），
  降序时堆顶是最小距离，筛选会反向误拒，因此降序只做精确 8/4 路精算、不做近似筛选。

## 正确性

- 新增用例：5 行等距递增表上，`ORDER BY d DESC LIMIT 3` 必须给出 5,4,3；
  ASC 必须给出 1,2,3；同距按主键升序。
- CTest 9/9、stress 21/21、optimization/large 16/16。

## 残留

- 降序没有近似筛选，因此比同规模升序慢（0.582 s vs 升序 LIMIT 20 的 0.39 ms/1000 量级不可直接比，
  但同 LIMIT 下降序仍明显慢于升序）。要补需要一套"越大越好"的筛选阈值，风险高于收益。
- 官方隐藏负载是否使用降序 TopK 未知；本改动在最坏形状上 2.72×，不踩中时无影响。

## 身份

改动前/后二进制见 `binary.sha256`。分支 `perf/declared-width-budget-li-20261114`。
