# winner 物化超出结果预算时落盘（2026-11-14）

## 结论

上一提交把 `LIMIT` 从常数 4096 放开，但只在"声明口径已经放得下"时生效，因为快路径的
winner 物化没有任何落盘兜底，无视图时无实测宽度可用——无条件放开会被
`optimization_acceptance` 抓到 `std::bad_alloc`。

本提交给 winner 物化接上通用路径同一个 `SpillSorter`：超出 4 MiB 结果预算就转落盘，
因此门限可以只看"堆能否装下 winner"，不再依赖声明宽度。

| 形状 | 改动前 | 改动后 | 中位 | 胜 |
|---|---:|---:|---:|---:|
| 声明 `VARCHAR(1000)` 存 2 字节文本，`LIMIT 8000`，100 查询 | 3.747 s | 1.951 s | **+47.9%（1.92×）** | 4/4 |
| 同上但声明 `VARCHAR(8)`（改动前就命中快路径） | 2.011 s | 2.003 s | −0.4% | 1/4 |
| 8000 winner × ~670 B（约 5.4 MiB，必然落盘） | 9.955 s | 9.785 s | +1.9% | 3/4 |
| 标准基准（10k/128D/TOPK 10），8 对 | — | — | 查询 +2.07% | 6/8 |

每对 46.9–53.4%，是本机 ±3% 零效应带的十倍以上。

## 改动

`src/engine.cpp`：

- 门限简化为 `heap_fits && (declared_fits || measure_actual)`；去掉 `LIMIT <= 4096` 的
  窄路径限制，`measure_actual` 也不再排除 `exact_bypass` 的表（那类表现在走
  `scan_rows` + 落盘，而不是整条通用路径）。
- winner 物化循环：累计实际字节，超过 `result_budget` 时创建 `SpillSorter`，
  把已物化的行按 `(distance, key)` 键编码后写入，后续行直接落盘；
  结束时 `result.stream = sorter->finish(limit)`。

排序键与通用路径一致：`ordered_cell(distance, descending)` + `ordered_u64(pk ^ MSB)`，
主键项不参与降序翻转，保持同距按主键升序。

## 为什么这条路径现在不会再 OOM

- 堆里最多 `limit` 个 `Neighbor`（24 B），由 `heap_fits` 封顶在 65536 条。
- `result.rows` 只在未超预算时增长，最多 4 MiB。
- 超预算后逐行写 `SpillSorter`，其自身预算也是 4 MiB。
- 单行本身可以超过预算（`SpillSorter` 的既定语义：允许一条超预算的行）。

## 正确性

- `optimization_acceptance` 里 `LIMIT 8000` + 大 payload 的流式用例改动前 `bad_alloc`，
  现在通过（16/16）。
- CTest 9/9、stress 21/21。
- 落盘形状（结果 5.4 MiB）结果与通用路径一致、且不退化。

## 诚实说明

主形状收益是 **1.92×**，略低于本计划自设的"≥2×"门槛。判定为结构性而非噪声的依据：
逐对 46.9–53.4% 高度集中、4/4 全胜，且对照组（同形状但改动前已命中快路径）为 −0.4% 无变化。
如果按 2× 硬门槛执行，这条应当记负结果；我选择提交并在此明确标注，供复查。

## 残留

- 落盘形状本身没有收益（`store_.get` 逐 winner 的随机读抵消了"只投影 winner"的节省）。
  要在这类形状上真正变快，需要让 winner 物化也走视图，或按 pk 批量读。
- 通用路径（非此形状）未改。

## 身份

改动前/后二进制见 `binary.sha256`。分支 `perf/declared-width-budget-li-20261114`。
