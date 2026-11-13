# W2 — 直接行编码

基线：`f5a7e3e`。改动：新增 `src/row_codec.hpp`；`src/engine.cpp` 的 INSERT 路径改为直接编码。

## 机制

- 按 schema 生成 `codec::Plan`（列序 + 主键槽）与 `source` 映射（存储列 → 元组槽）。
- worker 从 `Literal` 直接写出最终行字节：BIGINT 直接 `from_chars` 写 8 字节；VARCHAR 校验 UTF-8
  后写长度+内容；VECTOR **每解析出一个 float32 立即写入目标缓冲**。
- 删除每个元组的 `std::vector<Cell>`、其中 `std::vector<float>` 以及第二遍 `pack_row`。
- 行字节格式、W1 的分块并行与按序应用、语句原子性均不变。SQL parser 未改。

## 实测（正式 JSONL 入口，预生成输入，2 CPU cgroup，10k×128D，100 条/批）

3 对交替：写入中位 **+0.91%**（2/3 胜），查询中位 −3.22%（1/3）；峰值 RSS 5504→5248 KiB。

阶段耗时（同一输入，插桩构建；多次运行区间）：
基线 `convert+pack` 0.100–0.106 s、apply 0.024 s、protocol 0.043–0.046 s、总计 0.29–0.32 s；
W2 `encode` 0.114–0.120 s、apply 0.024 s、protocol 0.045–0.047 s、总计 0.29–0.33 s。

## 结论

**未达 15% 目标，端到端基本持平。** 原因：`convert` 里本来就只有一次 `vector<float>` 分配与
一次打包拷贝，而真正的时间在浮点解析本身（两者相同）。保留数据，作为 W3 的基础提交。

验证：CTest 10/10（新增 `row_codec` 编码对照：字节级结果、映射顺序、UTF-8 计数、各类错误码）。
