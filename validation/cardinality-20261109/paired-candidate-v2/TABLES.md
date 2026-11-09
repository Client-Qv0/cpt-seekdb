# V2 完整配对结果

来源为完整 summary.json；不筛选轮次，不更改原始记录。每个负载顺序为第1组 B→C、第2组 C→B、第3组 B→C。B/C 为基线耗时除以候选耗时，小于1表示候选更慢。

耗时单位为秒；CV 为总体标准差/均值。仅有三次重复，小毫秒阶段可能有较大相对波动。恢复指标包含 Docker 启动、数据库初始化/恢复、首条探针及响应消费；不是单独 WAL 重放时间。首次读不是 OS 冷缓存实验，没有全局 drop_caches。

资源数字单位为字节，来自真实 cgroup。memory.peak 是内核全生命周期峰值；anon/file 是连续采样及阶段快照的最大值。分项峰值并不同时发生，memory.stat 也可能短时滞后，不能将不同分项峰值相加或以短时下降声称释放。

summary SHA256: `90f0f5884d5b73134e8c295da3ea3dee062aace32fbec004c13f699fd66a655e`

本生成脚本 SHA256: `160983959a51d62fd6f91a2f01b06b1af94d61db79805efae891f10365faf25b`

## vector128

全部6轮通过：True；有效配对数：3

### 全部耗时指标

| 指标 | B三轮 | B中位数 | B范围 | B CV | C三轮 | C中位数 | C范围 | C CV | 配对B/C三值 | 配对B/C中位数 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fixed_warmup_seconds_not_in_warm_query_time | 0.008623476, 0.008008861, 0.007972289 | 0.008008861 | 0.007972289–0.008623476 | 0.036423119 | 0.008038836, 0.008483452, 0.007744092 | 0.008038836 | 0.007744092–0.008483452 | 0.037570809 | 1.0727269, 0.94405685, 1.0294672 | 1.0294672 |
| process_first_query_seconds | 0.009013916, 0.008116311, 0.008791051 | 0.008791051 | 0.008116311–0.009013916 | 0.044165678 | 0.007908482, 0.007767091, 0.007194851 | 0.007767091 | 0.007194851–0.007908482 | 0.040471103 | 1.1397783, 1.0449615, 1.2218531 | 1.1397783 |
| restart_startup_to_first_response_seconds | 0.5062234, 0.51492917, 0.48876748 | 0.5062234 | 0.48876748–0.51492917 | 0.021612614 | 0.52527394, 0.44726055, 0.5242078 | 0.5242078 | 0.44726055–0.52527394 | 0.07321334 | 0.96373219, 1.1512958, 0.93239261 | 0.96373219 |
| warm_queries_seconds | 0.76771492, 0.76259829, 0.75317384 | 0.76259829 | 0.75317384–0.76771492 | 0.0079123474 | 0.75480749, 0.75439168, 0.75254257 | 0.75439168 | 0.75254257–0.75480749 | 0.0013057646 | 1.0171003, 1.0108785, 1.0008388 | 1.0108785 |
| write_batches_seconds | 0.70932159, 0.70934612, 0.69283433 | 0.70932159 | 0.69283433–0.70934612 | 0.011050841 | 0.70865393, 0.70830568, 0.69325842 | 0.70830568 | 0.69325842–0.70865393 | 0.01020298 | 1.0009422, 1.0014689, 0.99938827 | 1.0009422 |

负收益指标（配对B/C中位数 < 1，全部列出）：

- `restart_startup_to_first_response_seconds`：0.96373219

### 资源原始三轮值与汇总

| 进程 | 版本 | 指标 | 三轮原值 | 中位数 | 范围 | CV |
| --- | --- | --- | --- | --- | --- | --- |
| main | baseline | memory_current_bytes | 16175104, 16154624, 16027648 | 16154624 | 16027648–16175104 | 0.0040462717 |
| main | baseline | memory_peak_bytes | 16175104, 16154624, 16027648 | 16154624 | 16027648–16175104 | 0.0040462717 |
| main | baseline | anon_bytes | 7958528, 7954432, 7954432 | 7954432 | 7954432–7958528 | 0.00024270011 |
| main | baseline | file_bytes | 5992448, 5980160, 5980160 | 5980160 | 5980160–5992448 | 0.00096797643 |
| main | candidate | memory_current_bytes | 15761408, 15749120, 15409152 | 15749120 | 15409152–15761408 | 0.010437147 |
| main | candidate | memory_peak_bytes | 15761408, 15749120, 15409152 | 15749120 | 15409152–15761408 | 0.010437147 |
| main | candidate | anon_bytes | 7630848, 7630848, 7630848 | 7630848 | 7630848–7630848 | 0 |
| main | candidate | file_bytes | 5988352, 5988352, 5988352 | 5988352 | 5988352–5988352 | 0 |
| restart | baseline | memory_current_bytes | 3543040, 3477504, 3235840 | 3477504 | 3235840–3543040 | 0.038641146 |
| restart | baseline | memory_peak_bytes | 5959680, 6262784, 6246400 | 6246400 | 5959680–6262784 | 0.022608374 |
| restart | baseline | anon_bytes | 536576, 540672, 528384 | 536576 | 528384–540672 | 0.0095450444 |
| restart | baseline | file_bytes | 233472, 233472, 233472 | 233472 | 233472–233472 | 0 |
| restart | candidate | memory_current_bytes | 3305472, 3252224, 2576384 | 3252224 | 2576384–3305472 | 0.10899536 |
| restart | candidate | memory_peak_bytes | 5984256, 6213632, 5738496 | 5984256 | 5738496–6213632 | 0.032450002 |
| restart | candidate | anon_bytes | 466944, 462848, 397312 | 462848 | 397312–466944 | 0.072119268 |
| restart | candidate | file_bytes | 241664, 241664, 241664 | 241664 | 241664–241664 | 0 |

| 进程 | 版本 | 轮次 | memory.events 原始最大计数 |
| --- | --- | --- | --- |
| main | baseline | 1 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| main | baseline | 2 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| main | baseline | 3 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| main | candidate | 1 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| main | candidate | 2 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| main | candidate | 3 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | baseline | 1 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | baseline | 2 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | baseline | 3 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | candidate | 1 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | candidate | 2 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | candidate | 3 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |

## cardinality-scalar-1000000

全部6轮通过：True；有效配对数：3

### 全部耗时指标

| 指标 | B三轮 | B中位数 | B范围 | B CV | C三轮 | C中位数 | C范围 | C CV | 配对B/C三值 | 配对B/C中位数 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| create_seconds | 0.005273651, 0.005120874, 0.005458631 | 0.005273651 | 0.005120874–0.005458631 | 0.026133119 | 0.004637645, 0.005394778, 0.005059574 | 0.005059574 | 0.004637645–0.005394778 | 0.061577025 | 1.1371399, 0.94922794, 1.0788717 | 1.0788717 |
| delete_restore_seconds | 0.43724926, 0.43268278, 0.43348974 | 0.43348974 | 0.43268278–0.43724926 | 0.0045800597 | 0.4433921, 0.43934789, 0.43234949 | 0.43934789 | 0.43234949–0.4433921 | 0.010405954 | 0.98614579, 0.98482952, 1.0026373 | 0.98614579 |
| pk_lookup_remaining_seconds | 0.008771717, 0.007883427, 0.00854733 | 0.00854733 | 0.007883427–0.008771717 | 0.044894345 | 0.007428888, 0.008267864, 0.008379316 | 0.008267864 | 0.007428888–0.008379316 | 0.05285918 | 1.1807577, 0.95350226, 1.020051 | 1.020051 |
| process_first_pk_query_seconds | 0.000606364, 0.00175761, 0.000772038 | 0.000772038 | 0.000606364–0.00175761 | 0.48613399 | 0.000593734, 0.000740835, 0.000790719 | 0.000740835 | 0.000593734–0.000790719 | 0.11803527 | 1.0212722, 2.3724716, 0.97637467 | 1.0212722 |
| restart_remaining_checks_seconds | 0.29648539, 0.29743217, 0.2931857 | 0.29648539 | 0.2931857–0.29743217 | 0.006155395 | 0.29869532, 0.29863249, 0.30356852 | 0.29869532 | 0.29863249–0.30356852 | 0.0076996688 | 0.99260139, 0.9959806, 0.96579746 | 0.99260139 |
| restart_startup_to_first_response_seconds | 1.4301945, 1.4928674, 1.4301234 | 1.4301945 | 1.4301234–1.4928674 | 0.020372025 | 1.3467389, 1.350823, 1.3665908 | 1.350823 | 1.3467389–1.3665908 | 0.0063183658 | 1.0619687, 1.105154, 1.0464899 | 1.0619687 |
| restore_update_seconds | 0.005768996, 0.00431365, 0.004208465 | 0.00431365 | 0.004208465–0.005768996 | 0.14949395 | 0.004483957, 0.005151788, 0.004028584 | 0.004483957 | 0.004028584–0.005151788 | 0.10127224 | 1.2865859, 0.83731124, 1.0446512 | 1.0446512 |
| scan_after_invalidation_seconds | 0.2909181, 0.28325784, 0.28303558 | 0.28325784 | 0.28303558–0.2909181 | 0.012825043 | 0.28678215, 0.28471294, 0.29058069 | 0.28678215 | 0.28471294–0.29058069 | 0.0084560916 | 1.0144219, 0.99488924, 0.97403436 | 0.99488924 |
| scan_first_after_pk_seconds | 0.2927723, 0.28701371, 0.2893953 | 0.2893953 | 0.28701371–0.2927723 | 0.0081546051 | 0.28970451, 0.29228112, 0.28971746 | 0.28971746 | 0.28970451–0.29228112 | 0.0041697095 | 1.0105893, 0.9819783, 0.99888803 | 0.99888803 |
| scan_warm_three_seconds | 0.86431164, 0.8547639, 0.84805243 | 0.8547639 | 0.84805243–0.86431164 | 0.0077963098 | 0.85701481, 0.85562195, 0.86276726 | 0.85701481 | 0.85562195–0.86276726 | 0.0036026447 | 1.0085142, 0.99899717, 0.98294461 | 0.99899717 |
| transaction_pending_seconds | 0.23174548, 0.22952598, 0.22558914 | 0.22952598 | 0.22558914–0.23174548 | 0.011118869 | 0.22998564, 0.22965614, 0.23138108 | 0.22998564 | 0.22965614–0.23138108 | 0.0032459741 | 1.0076519, 0.99943324, 0.97496795 | 0.99943324 |
| transaction_rollback_commit_restore_seconds | 0.012609885, 0.018574287, 0.018645728 | 0.018574287 | 0.012609885–0.018645728 | 0.17029747 | 0.018688634, 0.018340881, 0.011928944 | 0.018340881 | 0.011928944–0.018688634 | 0.19043655 | 0.67473551, 1.012726, 1.5630661 | 1.012726 |
| update_cache_invalidation_seconds | 0.006061661, 0.005972887, 0.012755675 | 0.006061661 | 0.005972887–0.012755675 | 0.38443213 | 0.005438451, 0.013203697, 0.012990136 | 0.012990136 | 0.005438451–0.013203697 | 0.34249388 | 1.1145933, 0.45236474, 0.98195084 | 0.98195084 |
| write_batches_seconds | 6.4148073, 6.3729172, 6.3665353 | 6.3729172 | 6.3665353–6.4148073 | 0.0033533795 | 6.6076966, 6.4758409, 6.4934868 | 6.4934868 | 6.4758409–6.6076966 | 0.0089559918 | 0.97080839, 0.98410653, 0.98044941 | 0.98044941 |

负收益指标（配对B/C中位数 < 1，全部列出）：

- `delete_restore_seconds`：0.98614579
- `restart_remaining_checks_seconds`：0.99260139
- `scan_after_invalidation_seconds`：0.99488924
- `scan_first_after_pk_seconds`：0.99888803
- `scan_warm_three_seconds`：0.99899717
- `transaction_pending_seconds`：0.99943324
- `update_cache_invalidation_seconds`：0.98195084
- `write_batches_seconds`：0.98044941

### 资源原始三轮值与汇总

| 进程 | 版本 | 指标 | 三轮原值 | 中位数 | 范围 | CV |
| --- | --- | --- | --- | --- | --- | --- |
| main | baseline | memory_current_bytes | 1.3012173e+08, 1.3043302e+08, 1.3037978e+08 | 1.3037978e+08 | 1.3012173e+08–1.3043302e+08 | 0.0010432307 |
| main | baseline | memory_peak_bytes | 1.3012173e+08, 1.3043302e+08, 1.3037978e+08 | 1.3037978e+08 | 1.3012173e+08–1.3043302e+08 | 0.0010432307 |
| main | baseline | anon_bytes | 72232960, 72237056, 72228864 | 72232960 | 72228864–72237056 | 4.6299778e-05 |
| main | baseline | file_bytes | 54714368, 53387264, 53387264 | 53387264 | 53387264–54714368 | 0.011621904 |
| main | candidate | memory_current_bytes | 97931264, 98148352, 98127872 | 98127872 | 97931264–98148352 | 0.00099793735 |
| main | candidate | memory_peak_bytes | 97931264, 98148352, 98127872 | 98127872 | 97931264–98148352 | 0.00099793735 |
| main | candidate | anon_bytes | 40267776, 40267776, 40271872 | 40267776 | 40267776–40271872 | 4.7949195e-05 |
| main | candidate | file_bytes | 53395456, 53395456, 53395456 | 53395456 | 53395456–53395456 | 0 |
| restart | baseline | memory_current_bytes | 72757248, 72245248, 72970240 | 72757248 | 72245248–72970240 | 0.0041874765 |
| restart | baseline | memory_peak_bytes | 74674176, 74162176, 74887168 | 74674176 | 74162176–74887168 | 0.004079838 |
| restart | baseline | anon_bytes | 70098944, 70094848, 70094848 | 70094848 | 70094848–70098944 | 2.7546037e-05 |
| restart | baseline | file_bytes | 344064, 344064, 344064 | 344064 | 344064–344064 | 0 |
| restart | candidate | memory_current_bytes | 39886848, 40017920, 40308736 | 40017920 | 39886848–40308736 | 0.0043997357 |
| restart | candidate | memory_peak_bytes | 41816064, 41934848, 42225664 | 41934848 | 41816064–42225664 | 0.0040975357 |
| restart | candidate | anon_bytes | 38154240, 38154240, 38158336 | 38154240 | 38154240–38158336 | 5.0605223e-05 |
| restart | candidate | file_bytes | 352256, 352256, 352256 | 352256 | 352256–352256 | 0 |

| 进程 | 版本 | 轮次 | memory.events 原始最大计数 |
| --- | --- | --- | --- |
| main | baseline | 1 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| main | baseline | 2 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| main | baseline | 3 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| main | candidate | 1 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| main | candidate | 2 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| main | candidate | 3 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | baseline | 1 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | baseline | 2 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | baseline | 3 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | candidate | 1 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | candidate | 2 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | candidate | 3 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |

## cardinality-vector4-1000000

全部6轮通过：True；有效配对数：3

### 全部耗时指标

| 指标 | B三轮 | B中位数 | B范围 | B CV | C三轮 | C中位数 | C范围 | C CV | 配对B/C三值 | 配对B/C中位数 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| create_seconds | 0.004690322, 0.011996785, 0.005258584 | 0.005258584 | 0.004690322–0.011996785 | 0.4536396 | 0.005524397, 0.005341693, 0.005105714 | 0.005341693 | 0.005105714–0.005524397 | 0.032191839 | 0.84901972, 2.2458769, 1.029941 | 1.029941 |
| delete_restore_seconds | 0.47616406, 0.47958145, 0.48009787 | 0.47958145 | 0.47616406–0.48009787 | 0.0036469274 | 0.4583185, 0.47211349, 0.45107725 | 0.4583185 | 0.45107725–0.47211349 | 0.018948466 | 1.038937, 1.0158181, 1.0643362 | 1.038937 |
| pk_lookup_remaining_seconds | 0.007702175, 0.007733234, 0.008071774 | 0.007733234 | 0.007702175–0.008071774 | 0.021362521 | 0.007871187, 0.008406499, 0.008242473 | 0.008242473 | 0.007871187–0.008406499 | 0.027397911 | 0.97852776, 0.91991137, 0.97929032 | 0.97852776 |
| process_first_pk_query_seconds | 0.001025543, 0.00085453, 0.000772604 | 0.00085453 | 0.000772604–0.001025543 | 0.11917233 | 0.006301388, 0.001663741, 0.000914869 | 0.001663741 | 0.000914869–0.006301388 | 0.80487055 | 0.16274875, 0.51361961, 0.84449686 | 0.51361961 |
| restart_remaining_checks_seconds | 0.30728869, 0.31050219, 0.31209233 | 0.31050219 | 0.30728869–0.31209233 | 0.0064461549 | 0.30957539, 0.31132358, 0.31312977 | 0.31132358 | 0.30957539–0.31312977 | 0.0046608889 | 0.99261343, 0.99736159, 0.99668687 | 0.99668687 |
| restart_startup_to_first_response_seconds | 1.4648126, 1.4433553, 1.465075 | 1.4648126 | 1.4433553–1.465075 | 0.0069816322 | 1.3965629, 1.3680789, 1.3961703 | 1.3961703 | 1.3680789–1.3965629 | 0.0096153847 | 1.0488698, 1.0550235, 1.0493526 | 1.0493526 |
| restore_update_seconds | 0.006547098, 0.005215334, 0.005170995 | 0.005215334 | 0.005170995–0.006547098 | 0.11312069 | 0.004761726, 0.004981136, 0.005096018 | 0.004981136 | 0.004761726–0.005096018 | 0.028037195 | 1.3749422, 1.047017, 1.0147129 | 1.047017 |
| scan_after_invalidation_seconds | 0.3090197, 0.30569876, 0.31294459 | 0.3090197 | 0.30569876–0.31294459 | 0.0095773625 | 0.29845505, 0.30285497, 0.29969546 | 0.29969546 | 0.29845505–0.30285497 | 0.0061675696 | 1.0353978, 1.0093899, 1.0442086 | 1.0353978 |
| scan_first_after_pk_seconds | 0.32865299, 0.33193116, 0.33282884 | 0.33193116 | 0.32865299–0.33282884 | 0.0054199315 | 0.299697, 0.31276739, 0.30297245 | 0.30297245 | 0.299697–0.31276739 | 0.018197283 | 1.0966176, 1.0612716, 1.0985449 | 1.0966176 |
| scan_warm_three_seconds | 0.92827399, 0.92648381, 0.9260305 | 0.92648381 | 0.9260305–0.92827399 | 0.0010449436 | 0.89150778, 0.91193338, 0.90815961 | 0.90815961 | 0.89150778–0.91193338 | 0.0098178114 | 1.0412405, 1.0159556, 1.0196781 | 1.0196781 |
| transaction_pending_seconds | 0.26007611, 0.25431514, 0.2639666 | 0.26007611 | 0.25431514–0.2639666 | 0.015281328 | 0.24272717, 0.24357687, 0.24334684 | 0.24334684 | 0.24272717–0.24357687 | 0.0014753743 | 1.071475, 1.0440858, 1.0847341 | 1.071475 |
| transaction_rollback_commit_restore_seconds | 0.012941075, 0.011716137, 0.011731204 | 0.011731204 | 0.011716137–0.012941075 | 0.0473164 | 0.012354432, 0.012984283, 0.019122811 | 0.012984283 | 0.012354432–0.019122811 | 0.20600067 | 1.0474844, 0.90233223, 0.6134665 | 0.90233223 |
| update_cache_invalidation_seconds | 0.006007119, 0.005423259, 0.006722838 | 0.006007119 | 0.005423259–0.006722838 | 0.087829138 | 0.01329834, 0.013127428, 0.012697992 | 0.013127428 | 0.012697992–0.01329834 | 0.019365645 | 0.45171946, 0.41312426, 0.52944103 | 0.45171946 |
| vector_topk_first_seconds | 0.27756731, 0.27556515, 0.27481141 | 0.27556515 | 0.27481141–0.27756731 | 0.0042138246 | 0.26471759, 0.26563463, 0.27010255 | 0.26563463 | 0.26471759–0.27010255 | 0.0088162179 | 1.0485412, 1.0373841, 1.0174336 | 1.0373841 |
| vector_topk_warm_three_seconds | 0.82363782, 0.82204824, 0.83395362 | 0.82363782 | 0.82204824–0.83395362 | 0.0063851613 | 0.78928778, 0.79671955, 0.79942421 | 0.79671955 | 0.78928778–0.79942421 | 0.0053896535 | 1.0435203, 1.0317912, 1.0431929 | 1.0431929 |
| write_batches_seconds | 6.9333344, 6.8239598, 6.8655716 | 6.8655716 | 6.8239598–6.9333344 | 0.0065571039 | 6.8972359, 6.9792119, 6.930374 | 6.930374 | 6.8972359–6.9792119 | 0.0048547304 | 1.0052338, 0.97775507, 0.99064951 | 0.99064951 |

负收益指标（配对B/C中位数 < 1，全部列出）：

- `pk_lookup_remaining_seconds`：0.97852776
- `process_first_pk_query_seconds`：0.51361961
- `restart_remaining_checks_seconds`：0.99668687
- `transaction_rollback_commit_restore_seconds`：0.90233223
- `update_cache_invalidation_seconds`：0.45171946
- `write_batches_seconds`：0.99064951

### 资源原始三轮值与汇总

| 进程 | 版本 | 指标 | 三轮原值 | 中位数 | 范围 | CV |
| --- | --- | --- | --- | --- | --- | --- |
| main | baseline | memory_current_bytes | 1.341399e+08, 1.3420954e+08, 1.3396378e+08 | 1.341399e+08 | 1.3396378e+08–1.3420954e+08 | 0.0007712158 |
| main | baseline | memory_peak_bytes | 1.3421773e+08, 1.3421773e+08, 1.3421773e+08 | 1.3421773e+08 | 1.3421773e+08–1.3421773e+08 | 0 |
| main | baseline | anon_bytes | 73261056, 73256960, 73261056 | 73261056 | 73256960–73261056 | 2.6356553e-05 |
| main | baseline | file_bytes | 67198976, 67022848, 66854912 | 67022848 | 66854912–67198976 | 0.0020958687 |
| main | candidate | memory_current_bytes | 1.1599872e+08, 1.1627725e+08, 1.1627725e+08 | 1.1627725e+08 | 1.1599872e+08–1.1627725e+08 | 0.0011300945 |
| main | candidate | memory_peak_bytes | 1.1599872e+08, 1.1627725e+08, 1.1627725e+08 | 1.1627725e+08 | 1.1599872e+08–1.1627725e+08 | 0.0011300945 |
| main | candidate | anon_bytes | 41275392, 41279488, 41279488 | 41279488 | 41275392–41279488 | 4.677715e-05 |
| main | candidate | file_bytes | 71122944, 71122944, 71122944 | 71122944 | 71122944–71122944 | 0 |
| restart | baseline | memory_current_bytes | 86130688, 85409792, 85815296 | 85815296 | 85409792–86130688 | 0.003439635 |
| restart | baseline | memory_peak_bytes | 87494656, 86773760, 87179264 | 87179264 | 86773760–87494656 | 0.0033858015 |
| restart | baseline | anon_bytes | 71090176, 71090176, 71086080 | 71090176 | 71086080–71090176 | 2.7161418e-05 |
| restart | baseline | file_bytes | 12918784, 12918784, 12918784 | 12918784 | 12918784–12918784 | 0 |
| restart | candidate | memory_current_bytes | 41615360, 41267200, 41365504 | 41365504 | 41267200–41615360 | 0.0035386227 |
| restart | candidate | memory_peak_bytes | 42958848, 42610688, 42708992 | 42708992 | 42610688–42958848 | 0.0034274404 |
| restart | candidate | anon_bytes | 39149568, 39149568, 39145472 | 39149568 | 39145472–39149568 | 4.9322134e-05 |
| restart | candidate | file_bytes | 352256, 352256, 352256 | 352256 | 352256–352256 | 0 |

| 进程 | 版本 | 轮次 | memory.events 原始最大计数 |
| --- | --- | --- | --- |
| main | baseline | 1 | `{"high": 0, "low": 0, "max": 416, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| main | baseline | 2 | `{"high": 0, "low": 0, "max": 416, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| main | baseline | 3 | `{"high": 0, "low": 0, "max": 416, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| main | candidate | 1 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| main | candidate | 2 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| main | candidate | 3 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | baseline | 1 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | baseline | 2 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | baseline | 3 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | candidate | 1 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | candidate | 2 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |
| restart | candidate | 3 | `{"high": 0, "low": 0, "max": 0, "oom": 0, "oom_group_kill": 0, "oom_kill": 0}` |

## io.stat 最后存活样本

These are each database cgroup last-live io.stat raw cumulative device counters, not database file sizes, not finalized lifetime writeback accounting, and not official physical IO. No sync or dedicated-device attribution calibration is performed. Devices are retained separately without summing possibly stacked-device counters. Missing/empty counters are preserved rather than fabricated.

以下 rbytes/wbytes 为对应 cgroup 最后存活样本的设备累计计数。没有执行结束后全程写回清算，也未做专用设备归因校准；不是数据库文件字节数，不是官方物理 I/O 评分值。不同设备分别保留，不做可能重复计数的堆叠设备求和。

IO JSON SHA256: `d237765f027785419538d52449e8df0e31c08fcb2b9c17b110b0edda06a952fa`

| 运行 | 进程 | 最后采样阶段 | 设备 major:minor | rbytes | wbytes |
| --- | --- | --- | --- | --- | --- |
| cardinality-scalar-1000000-pair-1-1-baseline | main | before_cleanup | 8:48 | 0 | 57167872 |
| cardinality-scalar-1000000-pair-1-1-baseline | restart | before_cleanup | 未报告 | 未报告 | 未报告 |
| cardinality-scalar-1000000-pair-1-2-candidate | main | before_cleanup | 8:48 | 0 | 57167872 |
| cardinality-scalar-1000000-pair-1-2-candidate | restart | before_cleanup | 未报告 | 未报告 | 未报告 |
| cardinality-scalar-1000000-pair-2-1-candidate | main | before_cleanup | 8:48 | 0 | 57167872 |
| cardinality-scalar-1000000-pair-2-1-candidate | restart | before_cleanup | 未报告 | 未报告 | 未报告 |
| cardinality-scalar-1000000-pair-2-2-baseline | main | before_cleanup | 8:48 | 0 | 57167872 |
| cardinality-scalar-1000000-pair-2-2-baseline | restart | before_cleanup | 未报告 | 未报告 | 未报告 |
| cardinality-scalar-1000000-pair-3-1-baseline | main | before_cleanup | 8:48 | 0 | 57167872 |
| cardinality-scalar-1000000-pair-3-1-baseline | restart | before_cleanup | 未报告 | 未报告 | 未报告 |
| cardinality-scalar-1000000-pair-3-2-candidate | main | before_cleanup | 8:48 | 0 | 57167872 |
| cardinality-scalar-1000000-pair-3-2-candidate | restart | before_cleanup | 未报告 | 未报告 | 未报告 |
| cardinality-vector4-1000000-pair-1-1-baseline | main | before_cleanup | 8:48 | 829984768 | 74899456 |
| cardinality-vector4-1000000-pair-1-1-baseline | restart | before_cleanup | 8:48 | 12574720 | 0 |
| cardinality-vector4-1000000-pair-1-2-candidate | main | before_cleanup | 8:48 | 0 | 73170944 |
| cardinality-vector4-1000000-pair-1-2-candidate | restart | before_cleanup | 未报告 | 未报告 | 未报告 |
| cardinality-vector4-1000000-pair-2-1-candidate | main | before_cleanup | 8:48 | 0 | 73170944 |
| cardinality-vector4-1000000-pair-2-1-candidate | restart | before_cleanup | 未报告 | 未报告 | 未报告 |
| cardinality-vector4-1000000-pair-2-2-baseline | main | before_cleanup | 8:48 | 829984768 | 74899456 |
| cardinality-vector4-1000000-pair-2-2-baseline | restart | before_cleanup | 8:48 | 12574720 | 0 |
| cardinality-vector4-1000000-pair-3-1-baseline | main | before_cleanup | 8:48 | 829980672 | 74899456 |
| cardinality-vector4-1000000-pair-3-1-baseline | restart | before_cleanup | 8:48 | 12574720 | 0 |
| cardinality-vector4-1000000-pair-3-2-candidate | main | before_cleanup | 8:48 | 0 | 73170944 |
| cardinality-vector4-1000000-pair-3-2-candidate | restart | before_cleanup | 未报告 | 未报告 | 未报告 |
| vector128-pair-1-1-baseline | main | before_cleanup | 8:48 | 0 | 6049792 |
| vector128-pair-1-1-baseline | restart | before_cleanup | 未报告 | 未报告 | 未报告 |
| vector128-pair-1-2-candidate | main | before_cleanup | 8:48 | 0 | 6049792 |
| vector128-pair-1-2-candidate | restart | before_cleanup | 未报告 | 未报告 | 未报告 |
| vector128-pair-2-1-candidate | main | before_cleanup | 8:48 | 0 | 6049792 |
| vector128-pair-2-1-candidate | restart | before_cleanup | 未报告 | 未报告 | 未报告 |
| vector128-pair-2-2-baseline | main | before_cleanup | 8:48 | 0 | 6049792 |
| vector128-pair-2-2-baseline | restart | before_cleanup | 未报告 | 未报告 | 未报告 |
| vector128-pair-3-1-baseline | main | before_cleanup | 8:48 | 0 | 6049792 |
| vector128-pair-3-1-baseline | restart | before_cleanup | 未报告 | 未报告 | 未报告 |
| vector128-pair-3-2-candidate | main | before_cleanup | 8:48 | 0 | 6049792 |
| vector128-pair-3-2-candidate | restart | before_cleanup | 未报告 | 未报告 | 未报告 |

初始容器创建耗时仅保存在各 run.json 的 initial_container_launch_seconds 元数据中，不在冻结工具的 summary 对比指标内。上表包含 summary 中全部计时指标；未将进程就绪或单独重放时间从容器创建时间中猜测扣除。
