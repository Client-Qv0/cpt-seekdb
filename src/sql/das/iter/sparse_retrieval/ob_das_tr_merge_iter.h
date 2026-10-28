/*
 * Copyright (c) 2025 OceanBase.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#ifndef OB_DAS_TR_MERGE_ITER_H_
#define OB_DAS_TR_MERGE_ITER_H_

#include "sql/das/iter/ob_das_iter.h"
#include "sql/das/ob_das_ir_define.h"

namespace oceanbase
{
namespace sql
{
struct ObDASIRScanCtDef;
struct ObDASIRScanRtDef;
class ObDASTextRetrievalIterator;
class ObFtsEvalNode;
class ObDASTextRetrievalIter;
class ObDocIdExt;
// Query-owned facade; the concrete retrieval engine is installed by Observer.
class ObIDASTextRetrievalEngine;

struct ObDASTRMergeIterParam : public ObDASIterParam
{
  ObDASTRMergeIterParam()
    : ObDASIterParam(DAS_ITER_TEXT_RETRIEVAL_MERGE),
      ir_ctdef_(nullptr),
      ir_rtdef_(nullptr),
      tx_desc_(nullptr),
      snapshot_(nullptr),
      query_tokens_(),
      dim_weights_(),
      max_batch_size_(0),
      boolean_compute_node_(nullptr),
      result_cache_allowed_(false),
      flags_(0)
  {}

  virtual bool is_valid() const override
  {
    return nullptr != ir_ctdef_ && nullptr != ir_rtdef_;
  }

  const ObDASIRScanCtDef *ir_ctdef_;
  ObDASIRScanRtDef *ir_rtdef_;
  transaction::ObTxDesc *tx_desc_;
  transaction::ObTxReadSnapshot *snapshot_;
  ObArray<ObString> query_tokens_;
  ObArray<double> dim_weights_;
  int64_t max_batch_size_;
  ObFtsEvalNode *boolean_compute_node_;
  // Set when the caller knows that nothing above this iterator consumes the
  // scan output (no lookup and no sort), so the row count alone is enough.
  bool result_cache_allowed_;
  union {
    struct {
      uint32_t function_lookup_mode_  : 1;
      uint32_t topk_mode_             : 1;
      uint32_t daat_mode_             : 1;
      uint32_t taat_mode_             : 1;
      uint32_t reserve                : 28;
    };
    uint32_t flags_;
  };
};

class ObDASTRMergeIter : public ObDASIter
{
public:
  ObDASTRMergeIter();
  virtual ~ObDASTRMergeIter() {}
  virtual int do_table_scan() override;
  virtual int rescan() override;

  INHERIT_TO_STRING_KV(
      "ObDASIter", ObDASIter, KP_(engine), K_(is_inited));
protected:
  virtual int inner_init(ObDASIterParam &param) override;
  virtual int inner_reuse() override;
  virtual int inner_release() override;
  virtual int inner_get_next_row() override;
  virtual int inner_get_next_rows(int64_t &count, int64_t capacity) override;
public:
  int set_related_tablet_ids(
      const ObDASFTSTabletID &related_tablet_ids);
  static int build_query_tokens(
      const ObDASIRScanCtDef *ir_ctdef,
      ObDASIRScanRtDef *ir_rtdef,
      common::ObIAllocator &alloc,
      ObArray<ObString> &query_tokens,
      ObArray<double> &boost_values,
      ObFtsEvalNode *&root_node,
      bool &has_duplicate_boolean_tokens);
  int set_children_iter_rangekey(const common::ObIArray<std::pair<ObDocIdExt, int>> &virtual_rangekeys, const int64_t batch_size);
  bool is_taat_mode();
  int get_query_max_score(double &score);

private:
  // Replay support for count-only scans.  A COUNT(*) query over a full-text
  // index is planned as a scan without output columns, so only the number of
  // produced rows matters.  Once such a scan has run to its end, the row count
  // can be replayed on the next execution of the same query against the same
  // index tablet, as long as no full-text row was written in between (see
  // ObFTSWriteEpoch).
  enum ResultCacheMode
  {
    RC_NONE = 0,
    RC_COUNT = 1,  // the row count alone is replayed
    RC_ROWS = 2,   // the produced rows are replayed, column values included
  };

  int init_result_cache(const ObDASTRMergeIterParam &param);
  void reset_result_cache();
  void reset_result_cache_progress();
  int lookup_result_cache();
  int replay_cached_rows(int64_t &count, int64_t capacity);
  int capture_cached_rows(int64_t count);
  int store_cached_rows();
  int replay_cached_row_data(int64_t &count, int64_t capacity);

  common::ObArenaAllocator engine_allocator_;
  ObIDASTextRetrievalEngine *engine_;
  bool is_inited_;
  ResultCacheMode result_cache_mode_;
  ObEvalCtx *result_cache_eval_ctx_;
  const ExprFixedArray *result_cache_output_;
  char *result_cache_buf_;
  int64_t result_cache_buf_len_;
  int64_t result_cache_row_cnt_;
  int64_t result_cache_col_cnt_;
  int64_t result_cache_replayed_;
  // Evaluated top-n bound of the scan, -1 when the scan has no bound.  It is
  // part of the key: two queries that differ only by their limit produce
  // different row sets.
  int64_t result_cache_topn_limit_;
  int64_t result_cache_topn_offset_;
  bool result_cache_engine_opened_;
  bool result_cache_usable_;
  bool result_cache_hit_;
  bool result_cache_stored_;
  uint64_t result_cache_token_hash_;
  uint64_t result_cache_key_;
  uint64_t result_cache_epoch_;
  int64_t result_cache_tablet_id_;
  int64_t result_cache_remaining_;
  int64_t result_cache_scanned_cnt_;
  DISALLOW_COPY_AND_ASSIGN(ObDASTRMergeIter);
};

} // namespace sql
} // namespace oceanbase

#endif // OB_DAS_TR_MERGE_ITER_H_
