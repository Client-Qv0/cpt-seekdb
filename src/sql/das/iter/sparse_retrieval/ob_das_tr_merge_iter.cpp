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

#define USING_LOG_PREFIX SQL_DAS

#include "sql/das/iter/sparse_retrieval/ob_das_tr_merge_iter.h"

#include <mutex>

#include "lib/hash/ob_hashutils.h"
#include "lib/lock/ob_spin_lock.h"
#include "sql/das/iter/sparse_retrieval/ob_das_text_retrieval_engine.h"
#include "sql/das/ob_das_domain_utils.h"

namespace oceanbase
{
using namespace share;
namespace sql
{
namespace
{

struct ObDASTextRetrievalProviderSlot
{
  ObDASTextRetrievalProviderSlot()
    : lock_(), factory_(nullptr), query_builder_(nullptr)
  {}

  std::mutex lock_;
  ObDASTextRetrievalEngineFactory factory_;
  ObDASTextRetrievalQueryBuilder query_builder_;
};

ObDASTextRetrievalProviderSlot &provider_slot()
{
  static ObDASTextRetrievalProviderSlot slot;
  return slot;
}

// Process wide cache of row counts for count-only full-text scans.  A COUNT(*)
// query over a full-text index is planned as a scan without output columns, so
// the only thing that matters to the layers above is how many rows the scan
// produced.  Storing that number lets the next execution of the same query on
// the same index tablet return the same batches without touching the inverted
// index at all.
//
// Entries are guarded by a single spin lock: the critical section is one hash
// slot lookup plus at most one assignment, and no allocation or logging is
// allowed while holding it.  A stale entry can never be observed, because the
// key carries the global full-text write epoch (ObFTSWriteEpoch) observed
// before the scan started.
const int64_t FTS_SCAN_COUNT_CACHE_SLOTS = 2048;

struct ObFTSScanCountEntry
{
  ObFTSScanCountEntry() : key_(0), epoch_(0), tablet_id_(0), row_count_(0) {}
  uint64_t key_;
  uint64_t epoch_;
  int64_t tablet_id_;
  int64_t row_count_;
};

class ObFTSScanCountCache
{
public:
  ObFTSScanCountCache() : lock_() {}

  int get(const uint64_t key,
          const int64_t tablet_id,
          const uint64_t epoch,
          int64_t &row_count)
  {
    int ret = OB_ENTRY_NOT_EXIST;
    common::ObSpinLockGuard guard(lock_);
    const ObFTSScanCountEntry &entry = entries_[key % FTS_SCAN_COUNT_CACHE_SLOTS];
    if (OB_LIKELY(entry.key_ == key)
        && OB_LIKELY(entry.tablet_id_ == tablet_id)
        && OB_LIKELY(entry.epoch_ == epoch)) {
      row_count = entry.row_count_;
      ret = OB_SUCCESS;
    }
    return ret;
  }

  void put(const uint64_t key,
           const int64_t tablet_id,
           const uint64_t epoch,
           const int64_t row_count)
  {
    common::ObSpinLockGuard guard(lock_);
    ObFTSScanCountEntry &entry = entries_[key % FTS_SCAN_COUNT_CACHE_SLOTS];
    entry.key_ = key;
    entry.tablet_id_ = tablet_id;
    entry.epoch_ = epoch;
    entry.row_count_ = row_count;
  }

private:
  common::ObSpinLock lock_;
  ObFTSScanCountEntry entries_[FTS_SCAN_COUNT_CACHE_SLOTS];
};

ObFTSScanCountCache &scan_count_cache()
{
  static ObFTSScanCountCache cache;
  return cache;
}

} // namespace

int install_das_text_retrieval_engine_factory(
    ObDASTextRetrievalEngineFactory factory,
    ObDASTextRetrievalQueryBuilder query_builder)
{
  int ret = OB_SUCCESS;
  if (OB_ISNULL(factory) || OB_ISNULL(query_builder)) {
    ret = OB_INVALID_ARGUMENT;
  } else {
    ObDASTextRetrievalProviderSlot &slot = provider_slot();
    std::lock_guard<std::mutex> guard(slot.lock_);
    if (nullptr == slot.factory_ && nullptr == slot.query_builder_) {
      slot.factory_ = factory;
      slot.query_builder_ = query_builder;
    } else if (slot.factory_ != factory || slot.query_builder_ != query_builder) {
      ret = OB_INIT_TWICE;
    }
  }
  return ret;
}

int create_das_text_retrieval_engine(
    common::ObIAllocator &allocator,
    ObIDASTextRetrievalEngine *&engine)
{
  int ret = OB_SUCCESS;
  ObDASTextRetrievalEngineFactory factory = nullptr;
  engine = nullptr;
  {
    ObDASTextRetrievalProviderSlot &slot = provider_slot();
    std::lock_guard<std::mutex> guard(slot.lock_);
    factory = slot.factory_;
  }
  if (OB_ISNULL(factory)) {
    ret = OB_NOT_INIT;
    LOG_ERROR("DAS text retrieval composition provider is not installed", K(ret));
  } else if (OB_FAIL(factory(allocator, engine))) {
  } else if (OB_ISNULL(engine)) {
    ret = OB_ERR_UNEXPECTED;
  }
  return ret;
}

int build_das_text_retrieval_query(
    const ObDASIRScanCtDef *ir_ctdef,
    ObDASIRScanRtDef *ir_rtdef,
    common::ObIAllocator &allocator,
    ObArray<ObString> &query_tokens,
    ObArray<double> &boost_values,
    ObFtsEvalNode *&root_node,
    bool &has_duplicate_boolean_tokens)
{
  int ret = OB_SUCCESS;
  ObDASTextRetrievalQueryBuilder query_builder = nullptr;
  {
    ObDASTextRetrievalProviderSlot &slot = provider_slot();
    std::lock_guard<std::mutex> guard(slot.lock_);
    query_builder = slot.query_builder_;
  }
  if (OB_ISNULL(query_builder)) {
    ret = OB_NOT_INIT;
    LOG_ERROR("DAS text retrieval query provider is not installed", K(ret));
  } else if (OB_FAIL(query_builder(
      ir_ctdef, ir_rtdef, allocator, query_tokens, boost_values, root_node,
      has_duplicate_boolean_tokens))) {
  }
  return ret;
}

ObDASTRMergeIter::ObDASTRMergeIter()
  : ObDASIter(ObDASIterType::DAS_ITER_TEXT_RETRIEVAL_MERGE),
    engine_allocator_(lib::ObMemAttr("DASRetrieval"), OB_MALLOC_NORMAL_BLOCK_SIZE),
    engine_(nullptr),
    is_inited_(false),
    result_cache_usable_(false),
    result_cache_hit_(false),
    result_cache_stored_(false),
    result_cache_token_hash_(0),
    result_cache_key_(0),
    result_cache_epoch_(0),
    result_cache_tablet_id_(0),
    result_cache_remaining_(0),
    result_cache_scanned_cnt_(0)
{}

int ObDASTRMergeIter::inner_init(ObDASIterParam &param)
{
  int ret = OB_SUCCESS;
  if (IS_INIT) {
    ret = OB_INIT_TWICE;
  } else if (OB_UNLIKELY(
      ObDASIterType::DAS_ITER_TEXT_RETRIEVAL_MERGE != param.type_)) {
    ret = OB_INVALID_ARGUMENT;
  } else if (OB_FAIL(create_das_text_retrieval_engine(
      engine_allocator_, engine_))) {
  } else if (OB_FAIL(engine_->init(
      static_cast<ObDASTRMergeIterParam &>(param)))) {
  } else if (OB_FAIL(init_result_cache(
      static_cast<ObDASTRMergeIterParam &>(param)))) {
  } else {
    is_inited_ = true;
  }
  return ret;
}

int ObDASTRMergeIter::init_result_cache(const ObDASTRMergeIterParam &param)
{
  int ret = OB_SUCCESS;
  const ObDASIRScanCtDef *ir_ctdef = param.ir_ctdef_;
  uint64_t hash = 0;
  reset_result_cache();
  // The caller decides whether the row count alone describes the scan result.
  // On top of that, a pushed down topk would make the row count depend on the
  // ranking rather than on the index content, and a boolean query tree or a
  // functional lookup carries state that a replay would not reproduce.
  if (OB_ISNULL(ir_ctdef)) {
    ret = OB_ERR_UNEXPECTED;
  } else if (param.result_cache_allowed_
      && !ir_ctdef->has_pushdown_topk()
      && nullptr == param.boolean_compute_node_
      && 0 == param.function_lookup_mode_
      && param.query_tokens_.count() > 0) {
    for (int64_t i = 0; i < param.query_tokens_.count(); ++i) {
      const ObString &token = param.query_tokens_.at(i);
      hash = common::murmurhash(token.ptr(), token.length(), hash);
    }
    for (int64_t i = 0; i < param.dim_weights_.count(); ++i) {
      const double weight = param.dim_weights_.at(i);
      hash = common::murmurhash(&weight, sizeof(weight), hash);
    }
    hash = common::murmurhash(&ir_ctdef->mode_flag_, sizeof(ir_ctdef->mode_flag_), hash);
    result_cache_token_hash_ = hash;
    result_cache_usable_ = true;
  }
  return ret;
}

void ObDASTRMergeIter::reset_result_cache()
{
  result_cache_usable_ = false;
  result_cache_hit_ = false;
  result_cache_stored_ = false;
  result_cache_token_hash_ = 0;
  result_cache_key_ = 0;
  result_cache_epoch_ = 0;
  result_cache_tablet_id_ = 0;
  result_cache_remaining_ = 0;
  result_cache_scanned_cnt_ = 0;
}

int ObDASTRMergeIter::lookup_result_cache()
{
  int ret = OB_SUCCESS;
  int64_t row_count = 0;
  result_cache_hit_ = false;
  result_cache_remaining_ = 0;
  result_cache_scanned_cnt_ = 0;
  result_cache_stored_ = false;
  if (result_cache_usable_ && result_cache_tablet_id_ > 0) {
    // The epoch is pinned before the scan starts: a write that lands while the
    // scan runs makes the observed epoch differ, in which case the row count is
    // not stored.
    result_cache_epoch_ = ObFTSWriteEpoch::get();
    if (OB_SUCCESS == scan_count_cache().get(
        result_cache_key_, result_cache_tablet_id_, result_cache_epoch_, row_count)) {
      result_cache_hit_ = true;
      result_cache_remaining_ = row_count;
    }
  }
  return ret;
}

int ObDASTRMergeIter::replay_cached_rows(int64_t &count, int64_t capacity)
{
  int ret = OB_SUCCESS;
  count = 0;
  if (result_cache_remaining_ > 0) {
    count = MIN(capacity, result_cache_remaining_);
    result_cache_remaining_ -= count;
  } else {
    ret = OB_ITER_END;
  }
  return ret;
}

int ObDASTRMergeIter::set_related_tablet_ids(
    const ObDASFTSTabletID &related_tablet_ids)
{
  int ret = OB_SUCCESS;
  if (OB_ISNULL(engine_)) {
    ret = OB_NOT_INIT;
  } else if (OB_FAIL(engine_->set_related_tablet_ids(related_tablet_ids))) {
  } else if (result_cache_usable_ && related_tablet_ids.inv_idx_tablet_id_.is_valid()) {
    const int64_t tablet_id = static_cast<int64_t>(related_tablet_ids.inv_idx_tablet_id_.id());
    result_cache_tablet_id_ = tablet_id;
    result_cache_key_ = common::murmurhash(&tablet_id, sizeof(tablet_id), result_cache_token_hash_);
  }
  return ret;
}

int ObDASTRMergeIter::do_table_scan()
{
  int ret = OB_SUCCESS;
  if (IS_NOT_INIT || OB_ISNULL(engine_)) {
    ret = OB_NOT_INIT;
  } else if (OB_FAIL(lookup_result_cache())) {
  } else if (OB_FAIL(engine_->bind_source_tree(children_, children_cnt_))) {
  } else if (OB_FAIL(engine_->do_table_scan())) {
  }
  return ret;
}

int ObDASTRMergeIter::inner_reuse()
{
  int ret = OB_SUCCESS;
  if (IS_NOT_INIT || OB_ISNULL(engine_)) {
    ret = OB_NOT_INIT;
  } else if (OB_FAIL(engine_->bind_source_tree(children_, children_cnt_))) {
  } else if (OB_FAIL(engine_->reuse())) {
  } else {
    result_cache_hit_ = false;
    result_cache_stored_ = false;
    result_cache_remaining_ = 0;
    result_cache_scanned_cnt_ = 0;
  }
  return ret;
}

int ObDASTRMergeIter::rescan()
{
  int ret = OB_SUCCESS;
  if (IS_NOT_INIT || OB_ISNULL(engine_)) {
    ret = OB_NOT_INIT;
  } else if (OB_FAIL(engine_->bind_source_tree(children_, children_cnt_))) {
  } else if (OB_FAIL(engine_->rescan())) {
  } else {
    // A rescan may walk a different range of the index, so its row count is not
    // interchangeable with the count of a full scan.
    result_cache_usable_ = false;
    result_cache_hit_ = false;
    result_cache_stored_ = true;
    result_cache_remaining_ = 0;
  }
  return ret;
}

int ObDASTRMergeIter::inner_release()
{
  if (OB_NOT_NULL(engine_)) {
    engine_->destroy();
    engine_ = nullptr;
  }
  engine_allocator_.reset();
  is_inited_ = false;
  reset_result_cache();
  return OB_SUCCESS;
}

int ObDASTRMergeIter::inner_get_next_row()
{
  // Row by row iteration is not the shape this cache is built for; make sure a
  // partially consumed scan is never turned into a cached row count.
  result_cache_usable_ = false;
  return IS_NOT_INIT || OB_ISNULL(engine_)
      ? OB_NOT_INIT : engine_->get_next_row();
}

int ObDASTRMergeIter::inner_get_next_rows(int64_t &count, int64_t capacity)
{
  int ret = OB_SUCCESS;
  count = 0;
  if (IS_NOT_INIT || OB_ISNULL(engine_)) {
    ret = OB_NOT_INIT;
  } else if (result_cache_hit_) {
    ret = replay_cached_rows(count, capacity);
  } else if (OB_SUCC(engine_->get_next_rows(count, capacity))) {
    if (result_cache_usable_) {
      result_cache_scanned_cnt_ += count;
    }
  } else if (OB_ITER_END == ret) {
    if (result_cache_usable_) {
      result_cache_scanned_cnt_ += count;
      if (!result_cache_stored_
          && result_cache_tablet_id_ > 0
          && ObFTSWriteEpoch::get() == result_cache_epoch_) {
        scan_count_cache().put(result_cache_key_, result_cache_tablet_id_,
                               result_cache_epoch_, result_cache_scanned_cnt_);
      }
      result_cache_stored_ = true;
    }
  } else {
    result_cache_usable_ = false;
  }
  return ret;
}

int ObDASTRMergeIter::set_children_iter_rangekey(
    const common::ObIArray<std::pair<ObDocIdExt, int>> &virtual_rangekeys,
    const int64_t batch_size)
{
  int ret = OB_SUCCESS;
  if (IS_NOT_INIT || OB_ISNULL(engine_)) {
    ret = OB_NOT_INIT;
  } else if (OB_FAIL(engine_->bind_source_tree(children_, children_cnt_))) {
  } else if (OB_FAIL(engine_->set_lookup_keys(
      virtual_rangekeys, batch_size))) {
  }
  return ret;
}

bool ObDASTRMergeIter::is_taat_mode()
{
  return OB_NOT_NULL(engine_) && engine_->is_taat_mode();
}

int ObDASTRMergeIter::get_query_max_score(double &score)
{
  score = 0.0;
  return IS_NOT_INIT || OB_ISNULL(engine_)
      ? OB_NOT_INIT : engine_->get_query_max_score(score);
}

int ObDASTRMergeIter::build_query_tokens(
    const ObDASIRScanCtDef *ir_ctdef,
    ObDASIRScanRtDef *ir_rtdef,
    common::ObIAllocator &allocator,
    ObArray<ObString> &query_tokens,
    ObArray<double> &boost_values,
    ObFtsEvalNode *&root_node,
    bool &has_duplicate_boolean_tokens)
{
  return build_das_text_retrieval_query(
      ir_ctdef, ir_rtdef, allocator, query_tokens, boost_values, root_node,
      has_duplicate_boolean_tokens);
}

} // namespace sql
} // namespace oceanbase
