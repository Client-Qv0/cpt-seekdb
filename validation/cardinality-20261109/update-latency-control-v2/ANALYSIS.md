# 单行更新延迟调查

The cause of the original consistent UPDATE slowdown remains unknown. Sampler on/off controls show large outliers and do not establish Python GIL/sampling as a sufficient cause. Neither the earlier negative observation nor the complete paired evidence is overwritten.

## 原18轮中相关观测

| 运行 | 阶段 | 毫秒 | CPU计数存在 | io.stat阶段增量 | sampler起始时间戳落入窗口数 |
| --- | --- | ---: | --- | --- | ---: |
| cardinality-vector4-1000000-pair-1-1-baseline | process_first_pk_query | 1.0255 | False | `{"8:48": {"rbytes": 0, "wbytes": 0, "rios": 0, "wios": 0, "dbytes": 0, "dios": 0}}` | 0 |
| cardinality-vector4-1000000-pair-1-1-baseline | update_cache_invalidation | 6.0071 | False | `{"8:48": {"rbytes": 0, "wbytes": 4096, "rios": 0, "wios": 1, "dbytes": 0, "dios": 0}}` | 0 |
| cardinality-vector4-1000000-pair-1-1-baseline | transaction_rollback_commit_restore | 12.9411 | False | `{"8:48": {"rbytes": 0, "wbytes": 8192, "rios": 0, "wios": 2, "dbytes": 0, "dios": 0}}` | 0 |
| cardinality-vector4-1000000-pair-1-2-candidate | process_first_pk_query | 6.3014 | False | `{"8:48": {"rbytes": 0, "wbytes": 0, "rios": 0, "wios": 0, "dbytes": 0, "dios": 0}}` | 0 |
| cardinality-vector4-1000000-pair-1-2-candidate | update_cache_invalidation | 13.2983 | False | `{"8:48": {"rbytes": 0, "wbytes": 4096, "rios": 0, "wios": 1, "dbytes": 0, "dios": 0}}` | 0 |
| cardinality-vector4-1000000-pair-1-2-candidate | transaction_rollback_commit_restore | 12.3544 | False | `{"8:48": {"rbytes": 0, "wbytes": 8192, "rios": 0, "wios": 2, "dbytes": 0, "dios": 0}}` | 0 |
| cardinality-vector4-1000000-pair-2-1-candidate | process_first_pk_query | 1.6637 | False | `{"8:48": {"rbytes": 0, "wbytes": 0, "rios": 0, "wios": 0, "dbytes": 0, "dios": 0}}` | 0 |
| cardinality-vector4-1000000-pair-2-1-candidate | update_cache_invalidation | 13.1274 | False | `{"8:48": {"rbytes": 0, "wbytes": 4096, "rios": 0, "wios": 1, "dbytes": 0, "dios": 0}}` | 1 |
| cardinality-vector4-1000000-pair-2-1-candidate | transaction_rollback_commit_restore | 12.9843 | False | `{"8:48": {"rbytes": 0, "wbytes": 8192, "rios": 0, "wios": 2, "dbytes": 0, "dios": 0}}` | 0 |
| cardinality-vector4-1000000-pair-2-2-baseline | process_first_pk_query | 0.8545 | False | `{"8:48": {"rbytes": 0, "wbytes": 0, "rios": 0, "wios": 0, "dbytes": 0, "dios": 0}}` | 0 |
| cardinality-vector4-1000000-pair-2-2-baseline | update_cache_invalidation | 5.4233 | False | `{"8:48": {"rbytes": 0, "wbytes": 4096, "rios": 0, "wios": 1, "dbytes": 0, "dios": 0}}` | 0 |
| cardinality-vector4-1000000-pair-2-2-baseline | transaction_rollback_commit_restore | 11.7161 | False | `{"8:48": {"rbytes": 0, "wbytes": 8192, "rios": 0, "wios": 2, "dbytes": 0, "dios": 0}}` | 0 |
| cardinality-vector4-1000000-pair-3-1-baseline | process_first_pk_query | 0.7726 | False | `{"8:48": {"rbytes": 0, "wbytes": 0, "rios": 0, "wios": 0, "dbytes": 0, "dios": 0}}` | 0 |
| cardinality-vector4-1000000-pair-3-1-baseline | update_cache_invalidation | 6.7228 | False | `{"8:48": {"rbytes": 0, "wbytes": 4096, "rios": 0, "wios": 1, "dbytes": 0, "dios": 0}}` | 0 |
| cardinality-vector4-1000000-pair-3-1-baseline | transaction_rollback_commit_restore | 11.7312 | False | `{"8:48": {"rbytes": 0, "wbytes": 8192, "rios": 0, "wios": 2, "dbytes": 0, "dios": 0}}` | 0 |
| cardinality-vector4-1000000-pair-3-2-candidate | process_first_pk_query | 0.9149 | False | `{"8:48": {"rbytes": 0, "wbytes": 0, "rios": 0, "wios": 0, "dbytes": 0, "dios": 0}}` | 0 |
| cardinality-vector4-1000000-pair-3-2-candidate | update_cache_invalidation | 12.6980 | False | `{"8:48": {"rbytes": 0, "wbytes": 4096, "rios": 0, "wios": 1, "dbytes": 0, "dios": 0}}` | 0 |
| cardinality-vector4-1000000-pair-3-2-candidate | transaction_rollback_commit_restore | 19.1228 | False | `{"8:48": {"rbytes": 0, "wbytes": 8192, "rios": 0, "wios": 2, "dbytes": 0, "dios": 0}}` | 1 |

## 12次固定对照：每次5个UPDATE+SELECT

两个SQL耗时求和，排除中间同步采样；不是原来连续分组计时的替代值。

| 运行 | 五次合计耗时（毫秒） | 中位数（毫秒） | UPDATE CPU usage_usec阶段增量 | UPDATE nr_throttled阶段增量 |
| --- | --- | ---: | --- | --- |
| pair-1-sampler-off-baseline | 14.2070, 8.0818, 12.6864, 13.2819, 13.3092 | 13.2819 | [77, 108, 163, 115, 238] | [0, 0, 0, 0, 0] |
| pair-1-sampler-off-candidate | 6.0951, 13.3629, 5.8415, 6.6773, 12.4687 | 6.6773 | [118, 202, 105, 119, 114] | [0, 0, 0, 0, 0] |
| pair-1-sampler-on-baseline | 12.6022, 6.5428, 12.3845, 7.1684, 5.9764 | 7.1684 | [103, 88, 128, 119, 172] | [0, 0, 0, 0, 0] |
| pair-1-sampler-on-candidate | 12.3535, 12.9798, 12.7899, 12.5107, 6.2791 | 12.5107 | [86, 130, 120, 111, 104] | [0, 0, 0, 0, 0] |
| pair-2-sampler-off-baseline | 12.9861, 12.5763, 12.8994, 4.9730, 14.3820 | 12.8994 | [88, 124, 108, 116, 111] | [0, 0, 0, 0, 0] |
| pair-2-sampler-off-candidate | 5.7545, 6.5927, 13.7499, 13.0448, 13.7434 | 13.0448 | [103, 106, 124, 118, 113] | [0, 0, 0, 0, 0] |
| pair-2-sampler-on-baseline | 5.6658, 13.7304, 24.6744, 15.2143, 18.1290 | 15.2143 | [90, 122, 123, 355, 109] | [0, 0, 0, 0, 0] |
| pair-2-sampler-on-candidate | 12.9471, 12.2816, 6.1176, 12.4798, 13.1133 | 12.4798 | [82, 129, 95, 98, 95] | [0, 0, 0, 0, 0] |
| pair-3-sampler-off-baseline | 13.0603, 14.4510, 12.2749, 4.5540, 13.2085 | 13.0603 | [83, 143, 101, 98, 181] | [0, 0, 0, 0, 0] |
| pair-3-sampler-off-candidate | 12.8224, 12.3919, 13.2639, 5.8373, 12.7142 | 12.7142 | [81, 130, 244, 123, 112] | [0, 0, 0, 0, 0] |
| pair-3-sampler-on-baseline | 5.3724, 12.4317, 12.6346, 13.1302, 15.3812 | 12.6346 | [83, 95, 118, 125, 115] | [0, 0, 0, 0, 0] |
| pair-3-sampler-on-candidate | 7.9681, 13.4866, 13.1341, 13.2237, 23.1526 | 13.2237 | [130, 127, 111, 104, 108] | [0, 0, 0, 0, 0] |

## 证据边界

- Original adapter did not record cpu.stat; a sampler timestamp marks snapshot start, not the full thread execution interval.
- Counter deltas are observations, not syscall service times. Small intervals can expose accounting granularity or lag.
- Controls copy/recover frozen WAL rather than rebuild the original write-then-read allocator and page-cache history.
- Controls add synchronous before/after captures outside individual SQL timers. Transaction sums exclude those gaps and are not identical to the original grouped timer.
- Only three pairs per control; no post hoc selection or further runs were used.
