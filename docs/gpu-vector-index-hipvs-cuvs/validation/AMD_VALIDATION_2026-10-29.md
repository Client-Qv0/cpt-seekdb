# AMD hipVS 实测与 CPU 对照（2026-10-29）

在真实 AMD Radeon `gfx1100` 服务器上，从 `amd-cagra-submit` 的
`e6d5f688c46bd0c987d28075c8bc7969f44255cc` 构建 seekdb，保留原有三个提交，
修复搜索模式限制，并完成三种规模、每种 CPU/GPU 各两次的 SQL 离线建索引测试。
百万向量的 GPU Recall@10 中位数从旧桥接库的 91.20% 提升到 98.55%。

## 对题目要求的结论

- 已实测 AMD Radeon + hipVS，且计时覆盖 seekdb 的 `CREATE VECTOR INDEX`、持久化和首条查询，
  不只是一个脱离数据库的 GPU 内核或 `batch_knn` 测试。
- 本实现通过 `type=hnsw,lib=cuvs` SQL 接入，但实际存储和搜索的是 **CAGRA 图**，
  **没有将 GPU 图转换为原生 VSAG HNSW 格式**。若评测要求必须保留 HNSW 图结构/CPU 搜索，
  仍需增加相应转换与验证；现有证据不能替代这一要求。
- 用户提供的题目原文没有指定数据集、召回率门槛或加速倍数。下表是实测结果，
  不是官方评分或“必过”承诺。0.90 仅作为本次探索时使用的参考线。
- 测量支持当前配置在这些合成数据上的实际构建加速。CPU/GPU 的图算法与参数不同，
  **这不是匹配召回率后的最优速度比较**，也不能推广到所有真实语料。

## 实测结果

百万组原计划三轮；收到提前交付要求后，在已完成的两组 CPU/GPU 配对结果保存后停止第三轮，
未完成的第三轮不纳入统计。其余规模预先按两轮执行。

构建、就绪、查询耗时均取两次运行的中位数；Recall@10 列出两次的最小值到最大值。
“就绪” = DDL 返回耗时 + 第一条查询耗时。查询 P95 是各次 P95 的中位数。
加速比 = CPU 构建中位数 / GPU 构建中位数；不含导入和数据集生成时间。

| 数据规模 | 后端 | 构建秒 | 就绪秒 | 构建加速 | Recall@10 范围 | 查询中位数 ms | 查询 P95 ms |
|---|---|---:|---:|---:|---:|---:|---:|
| 100,000 × 128 | CPU VSAG HNSW | 47.759 | 47.828 | 1.00× | 90.50%–90.50% | 2.016 | 2.089 |
| 100,000 × 128 | GPU hipVS CAGRA | 12.858 | 12.870 | 3.71× | 100.00%–100.00% | 4.275 | 5.085 |
| 100,000 × 256 | CPU VSAG HNSW | 71.295 | 71.389 | 1.00× | 70.10%–70.10% | 3.365 | 3.448 |
| 100,000 × 256 | GPU hipVS CAGRA | 14.410 | 14.434 | 4.95× | 99.90%–99.90% | 4.380 | 5.128 |
| 1,000,000 × 128 | CPU VSAG HNSW | 804.625 | 805.251 | 1.00× | 43.20%–43.20% | 2.751 | 3.173 |
| 1,000,000 × 128 | GPU hipVS CAGRA | 61.244 | 61.268 | 13.14× | 98.45%–98.65% | 4.774 | 5.964 |

CPU 在百万行、128 维这组数据上的低召回如实保留，没有丢弃失败查询或替换数据。
该数据是独立的高维单位随机向量，对 `m=16,ef_construction=200` 的 HNSW 较难。
提高 CPU 图构建预算、调优搜索预算并做等召回比较，是后续评估方向；本次未做这组额外调优。

### 修复前后

旧库（同一 observer、同一百万向量数据）的单次 GPU 结果：构建 61.273 秒，
Recall@10 91.20%，查询中位数 7.391 ms。
修复后上述两次 GPU 的 Recall@10 中位数为 98.55%，查询中位数为 4.774 ms。
旧库只有一次运行，因此前后延迟差不能解读为经过重复验证的稳定提速承诺。
本次保留原先 NN-Descent 构建参数，主要改进搜索正确性与召回率。

hipVS C API 的默认搜索算法为 `SINGLE_CTA`，其候选数上限为 512。
原桥接库在 Top-200 时要求至少 800 个候选，实测返回 `rc=15`。
现在显式设置 `AUTO`，最低候选数提高至 1024，保留 `search_width=4`；
同时在清理资源之前记录错误，避免错误信息被清理 API 覆盖。

## 测试方法与环境

- 同一服务器、同一 seekdb observer，CPU/GPU 轮流顺序运行，无并发基准。
  每种规模每个后端两次，各次新建独立表，保存结果后删除该表。
- CPU：AMD EPYC 9334，容器可见 128 个逻辑 CPU，但 cgroup 配额为 16 核；
  seekdb `cpu_count=16`。该配置不表示 HNSW 构建能并行用满 16 核。
- GPU：ROCm 报告 `AMD Radeon Graphics`、`gfx1100`，VRAM 约 48 GiB。
  不根据此前其他机器的记录推定本机的商品型号。
- ROCm 7.2.4；本机 `/opt/hipvs` C API 版本头为 1.0.0；Linux 6.8.0-79-generic。
- 容器内存上限 59,055,800,320 字节。实际 SQL 读回 `memory_budget=0M`、`memory_limit=0M`
  （自动），`ob_vector_memory_limit_percentage=50`，向量内存限额 23,622,320,128 字节。
  初始启动脚本的 `_memory_budget=20G` 没有设置生效，不能将其描述为实际 20 GiB 配额；
  所有基准期间设置保持一致。
- 构建开关 `OB_BUILD_CUVS=ON, OB_BUILD_CUVS_TRACE=ON`。性能测试没有设置 `OB_VSAG_TRACE`，
  功能回归单独开启 trace，不与性能测试并行。
- CPU：`lib=vsag,type=hnsw,m=16,ef_construction=200`。
  SQL 会话明确设置并读回 `ob_hnsw_ef_search=1000`；仅写 DDL 的 `ef_search` 不足以覆盖会话默认值。
- GPU：`lib=cuvs`，CAGRA NN-Descent，graph degree 128，intermediate degree 128，65 iterations；
  search `AUTO`，`itopk_size>=1024`，`search_width=4`。
- 数据与查询是分别生成的单位化 float32 正态随机向量，种子 20261029，每组 200 条独立查询。
  查询不是直接复制数据行；每条返回 10 个不重复、范围正确的 ID。
- 精确真值使用 float64 L2 分块穷举，SQL 输入以 9 位有效数字保留 float32 值；
  无索引时先将三条查询与 SQL 精确搜索交叉核对。输入文件有 SHA-256，复用时校验。
- 记录 SQL EXPLAIN，并要求使用向量算子。计时包含 SQL 客户端往返，不是纯内核时延。
- 首次探索中未设置会话 ef_search 的运行不纳入对照表；原始服务器留存该探索日志，
  本目录只收录可用于本报告的正式基准。

## 功能回归

- 原桥接库：同一扩展回归在单查询 Top-200 失败（退出码 5），成功复现问题。
- 修复桥接库：写入与重新加载各 4 个组合（nq=1/3，Top-10/200）全部成功，
  共 8 组；检查 ID 唯一性、距离有限性和已知自身邻居；两次错误形状加载被预期拒绝。
- Python 数据集测试 2 项通过：末尾不足 100 行分块的精确真值/SQL float32 往返，
  以及缓存内容损坏检测。
- 独立 SQL 生命周期测试 6 项通过：离线 DDL、重启后 GPU 搜索且不重建、
  CPU 索引隔离、过滤回退、删除可见性、新插入可见性。
  trace 保留在证据中；测试仅停止自己启动的 observer。

## 逐次结果

| 数据规模 | 后端 | 次数 | 导入秒 | DDL 秒 | 首查询秒 | Recall@10 |
|---|---|---:|---:|---:|---:|---:|
| 100,000 × 128 | vsag | 1 | 12.604 | 48.851 | 0.067 | 90.50% |
| 100,000 × 128 | vsag | 2 | 2.523 | 46.667 | 0.069 | 90.50% |
| 100,000 × 128 | cuvs | 1 | 2.649 | 12.996 | 0.015 | 100.00% |
| 100,000 × 128 | cuvs | 2 | 2.598 | 12.719 | 0.009 | 100.00% |
| 100,000 × 256 | vsag | 1 | 4.133 | 71.015 | 0.094 | 70.10% |
| 100,000 × 256 | vsag | 2 | 3.981 | 71.575 | 0.094 | 70.10% |
| 100,000 × 256 | cuvs | 1 | 3.920 | 16.106 | 0.038 | 99.90% |
| 100,000 × 256 | cuvs | 2 | 4.017 | 12.713 | 0.009 | 99.90% |
| 1,000,000 × 128 | vsag | 1 | 29.194 | 808.537 | 0.632 | 43.20% |
| 1,000,000 × 128 | vsag | 2 | 26.343 | 800.713 | 0.620 | 43.20% |
| 1,000,000 × 128 | cuvs | 1 | 27.961 | 63.324 | 0.032 | 98.65% |
| 1,000,000 × 128 | cuvs | 2 | 26.686 | 59.165 | 0.016 | 98.45% |

## 复现与证据

构建与运行命令参见 [README](../README.md#offline-build-benchmark)，
基准入口为 [benchmark_offline_ddl.py](benchmark_offline_ddl.py)。
在同一服务顺序执行三个规模，每次使用新的数据库名和输出路径，例如：

```bash
OPENBLAS_NUM_THREADS=1 python3 benchmark_offline_ddl.py \
  --data-dir /work/data/n1m_d128 --output /work/results/n1m_d128.json \
  --database amd_bench_new_1m128 --rows 1000000 --dim 128 \
  --queries 200 --repeats 2 --ef-search 1000 --backends cuvs vsag \
  --observer-bin /path/to/seekdb --bridge-lib /path/to/libseekdb_cuvs_bridge.so
```

另两组参数为 `--rows 100000 --dim 128` 和 `--rows 100000 --dim 256`。
先生成数据或运行一次后，后续同配置复用输入时会验证校验和。

原始文件包含每条查询耗时、返回 ID、召回率、查询计划与二进制/数据校验和：

- [100k × 128 正式结果](results/2026-10-29/candidate-100k128.json)
- [100k × 256 正式结果](results/2026-10-29/candidate-100k256.json)
- [1M × 128 正式结果](results/2026-10-29/candidate-1m128.json)
- [旧桥接库 1M GPU 对照](results/2026-10-29/baseline-1m128.json)
- [旧桥接库 100k CPU/GPU 对照](results/2026-10-29/baseline-100k128-ef1000.json)
- [环境记录](results/2026-10-29/environment.json)
- [SQL 生命周期结果](results/2026-10-29/sql-lifecycle-summary.json)
- [SQL trace（gzip 原始日志）](results/2026-10-29/sql-lifecycle-trace.log.gz)
- [修复前回归日志](results/2026-10-29/test-original.log)
- [修复后写入日志](results/2026-10-29/test-final-write.log)
- [修复后加载日志](results/2026-10-29/test-final-read.log)

Observer SHA-256：`549c032143d646b4cd7ed9e5445bc78e72e6665cc84d89e3ae7cda1c79214f92`。
修复桥接库 SHA-256：`e75ffa869689539384254e8471be1afd3b909428747a0d2ee5389675a99acf2c`。
旧桥接库 SHA-256：`fd82e1bec6bf3bcf24ad628d4d35948c080176a80e51ec4f8dd4abb40904d207`。

目前仍只支持 dense float32 L2；GPU snapshot 恢复依赖可用 GPU。
没有验证 GPU 故障后的快照 CPU 恢复、多 GPU、大规模真实语料或长时间并发压力。
这些限制不能由本次构建加速结果推断为已经解决。
