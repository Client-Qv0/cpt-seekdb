# 声明宽度 vs 结果预算：陡崖修复（2026-11-14）

## 结论

`engine.cpp` 的 TopK 快路径门限用 **声明 VARCHAR 宽度 × 4** 估算 winner 物化后的内存占用。
声明宽度只是"能存多少文本"的上界，与实际存储的文本无关，于是"宽声明 + 短文本"的表被误判为
会超出 4 MiB 结果预算，每条查询都掉进"逐行物化投影"的通用路径。

实测代价：**13 倍**。修复后该表回到快路径，标准基准无回归。

## 缺陷位置

`src/engine.cpp`（修改前）：

```cpp
projection_bound += sizeof(Cell) + 32 +
                    (p.distance                ? 0
                     : c.type == Type::Vector  ? size_t(c.size) * 4
                     : c.type == Type::Varchar ? size_t(c.size) * 4   // 声明宽度
                                               : 0);
...
if (... && projection_bound <= result_budget / *st.limit) { ... }
```

`c.size` 是 `VARCHAR(n)` 里的 n。对比 `exact_cache.hpp` 的 `required_bytes()` 用的是
**实际字节数**，两处口径不一致——即性能优化交接第 7 节第 3 条。

## 触发条件（改动前，实测计算）

`projection_bound` 累加 SELECT 里的**全部投影列**，因此需要声明宽度 × LIMIT 足够大：

| LIMIT | 单个 VARCHAR 需要声明超过 |
|---:|---:|
| 10 | 104842 字符（超过 MySQL VARCHAR 上限 65535，**不可触发**） |
| 20 | 52413 字符 |
| 100 | 10470 字符 |
| 1000 | 1032 字符 |

或者 LIMIT 10 时投影 2 个 `VARCHAR(65535)` 列。

注意：本地与官方基准的查询是 `SELECT id, L2_DISTANCE(v,..) AS d`，`grp` 未被投影，
所以在**默认 benchmark 里无法触发**。这条只在"宽声明列被投影 + LIMIT 较大"时生效。

## 测量条件

2 CPU cgroup（`CPUQuota=200%`、`AllowedCPUs=0-1`）、`MemoryMax=128 MiB`、零 swap。
10k 行 × 128 维，数据与 SQL 形状固定，只改 DDL 声明宽度。

**噪声底（同一二进制自比，8 对，3000 查询）**：

```
query_seconds: median +3.03%  wins 7/8   min -7.07%  max +4.83%
write_seconds: median -2.69%  wins 3/8   min -9.71%  max +26.73%
```

上一轮同一实验得到 −2.96%。即**零效应在单次会话内就能造出中位 ±3%、胜率 7/8**。
因此本报告所有 A/B 只看是否跨过数量级，不把 ±3% 读成收益。

## 改动前后对照

同一份数据、同一 SQL，仅 DDL 不同（`VARCHAR(8)` vs `VARCHAR(65535)`，实际都存 `'gN'`）：

| LIMIT | 改动前 narrow / wide | 改动后 narrow / wide |
|---:|---|---|
| 10（两者都在快路径） | 0.329s / 0.329s（+1.20%，3/6） | 0.323s / 0.333s（−3.28%，2/6） |
| 20（wide 跨门限 → 掉出快路径） | **0.390s / 5.063s（13×）** | 0.382s / 0.374s（+2.34%，4/6） |

改动后 LIMIT 20 的 wide 从 5.063s 降到 0.374s，与 narrow 的差异回到噪声带内。

## 改动内容

**`src/exact_cache.hpp`**

- `Plan` 新增 `text_max`：观察行时记录每列**实际存储文本的最大字节数**，计入
  `required_bytes()`（每列一个 `size_t`）。
- `Compact` 新增 `text_max`（从 plan 传入）与 `text_width(column)` 访问器，
  并计入 `allocated_bytes()`。

**`src/engine.cpp`**

- 门限拆成 `declared_fits`（原有声明宽度口径）与 `measure_actual`
  （`exact::available() && !point_lookup && 表名 ≤1024 && !cache_->exact_bypass`）。
  条件改为 `(declared_fits || measure_actual)`：声明口径放不下时也允许进入，
  以便建立/使用视图取得真实宽度。
- 视图可用的分支里，用 `view.text_width()` 算出 `actual_bound`；
  只有 `!declared_fits && actual_bound > budget/limit` 才清空 `winner_view` 并走
  `scan_rows(original_visit)`（即通用路径，逐行记账并落盘）。
- `point_lookup` 提到门限之前以便参与判定；`limit` 提为局部量，避免空 `st.limit` 解引用。

净改动 2 文件、+51/−10 行。

## 正确性证据

1. **三路等价**：同一批 40 条查询（半数带过滤），
   `窄表快路径 == 宽表快路径 == 通用路径前 20 行`，逐字节相同。
   通用路径由 `LIMIT 5000`（>4096 上限）强制触发，作为独立 oracle。
2. **回退分支等价**：真实存 5000 字节文本、`LIMIT 1000` 时
   `actual_bound=5192 > 4194` 触发回退，8 条查询结果仍与通用路径前 1000 行相同。
3. **Release CTest 9/9**、**stress acceptance 21/21**、**optimization/large 16/16**。

## 标准基准回归

未改动的 `HEAD` 二进制（`97956a87…`，与交接文档一致）vs 改动后二进制，8 对交替：

```
query_seconds: median -0.46%  wins 3/8  min -16.80%  max +6.84%
write_seconds: median +1.37%  wins 7/8  min -8.00%   max +7.67%
```

查询无回归。写路径的 +1.37%/7-8 胜与本改动无关（改动不触及写路径），
其形态与上面的零效应自比（+3.03%/7-8）一致，再次说明 7/8 胜率本身不构成证据。

## 残留与未做

- **冷查询的一次性问题**：`declared_fits` 为假时，第一条查询会先建视图（两次扫描）
  并只物化 K 个 winner，这次物化仍可能短暂超过 4 MiB 结果预算；
  视图建立后由实测宽度接管。已知且未消除。
- `exact_bypass`（视图装不下）的表保持改动前的行为，仍用声明宽度判定。
- 未测：官方隐藏负载是否会出现"宽声明列被投影 + 大 LIMIT"的形状。
- 该改动是"踩中时从 13 倍回到 1 倍"，不踩中时无影响。
- 已提交到 `perf/declared-width-budget-li-20261114`，**未推送、未创建 PR**。

## 身份

```
未改动基线 97956a87ca4c964a0c69469b0f4cca7e93eb657fd65b349c6ee292ed9e565cbf
改动后     78d8c99c536621f00118538be55d30f4ae05d7ec8943f384a6554d43b375f3d1
分支       perf/declared-width-budget-li-20261114（自 e5e33de，即 perf/agent-v17.1-citations-li-20261113）
```

## 未入库文件

仓库 `.gitignore` 忽略 `*.log`，因此本目录下的 `logs/ctest.log`、
`logs/acceptance-stress.log`、`logs/optimization-large.log`、`noise/summary.log`、
`main-regression/summary.log`、`equivalence/run.log` 只留在本地，未强加 `-f`。
原始配对 JSON（真正的测量数据）与复现脚本均已入库，日志可由 `scripts/` 重新生成。
