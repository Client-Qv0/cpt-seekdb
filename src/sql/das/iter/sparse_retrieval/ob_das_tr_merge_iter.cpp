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

// Row level replay for the top-n shape.  When the optimizer pushes a top-n over
// the relevance score into the retrieval scan, the scan produces at most
// result_limit rows and nothing above it can change how many rows come out.
// Those rows carry the document ids the lookup above the scan needs, so the
// whole result is replayed instead of only its row count.
const int64_t FTS_SCAN_ROW_CACHE_SLOTS = 256;
const int64_t FTS_SCAN_ROW_CACHE_BUF = 8192;
const int64_t FTS_SCAN_ROW_MAX_ROWS = 32;
const int64_t FTS_SCAN_ROW_MAX_COLS = 4;

// One byte tag followed by a payload whose shape is fixed by the column type.
const uint8_t FTS_SCAN_CELL_NULL = 0;
const uint8_t FTS_SCAN_CELL_VALUE = 1;

bool is_row_cache_supported_type(const ObObjType type)
{
  const ObObjTypeClass tc = ob_obj_type_class(type);
  return ObIntTC == tc || ObUIntTC == tc || ObFloatTC == tc
      || ObDoubleTC == tc || ObStringTC == tc;
}

struct ObFTSScanRowEntry
{
  ObFTSScanRowEntry() : key_(0), epoch_(0), tablet_id_(0), row_cnt_(0), col_cnt_(0), buf_len_(0) {}
  uint64_t key_;
  uint64_t epoch_;
  int64_t tablet_id_;
  int32_t row_cnt_;
  int32_t col_cnt_;
  int32_t buf_len_;
  char buf_[FTS_SCAN_ROW_CACHE_BUF];
};

class ObFTSScanRowCache
{
public:
  ObFTSScanRowCache() : lock_() {}

  int get(const uint64_t key,
          const int64_t tablet_id,
          const uint64_t epoch,
          char *buf,
          const int64_t buf_cap,
          int64_t &buf_len,
          int64_t &row_cnt,
          int64_t &col_cnt)
  {
    int ret = OB_ENTRY_NOT_EXIST;
    common::ObSpinLockGuard guard(lock_);
    const ObFTSScanRowEntry &entry = entries_[key % FTS_SCAN_ROW_CACHE_SLOTS];
    if (entry.key_ == key
        && entry.tablet_id_ == tablet_id
        && entry.epoch_ == epoch
        && entry.buf_len_ <= buf_cap) {
      MEMCPY(buf, entry.buf_, entry.buf_len_);
      buf_len = entry.buf_len_;
      row_cnt = entry.row_cnt_;
      col_cnt = entry.col_cnt_;
      ret = OB_SUCCESS;
    }
    return ret;
  }

  void put(const uint64_t key,
           const int64_t tablet_id,
           const uint64_t epoch,
           const int64_t row_cnt,
           const int64_t col_cnt,
           const char *buf,
           const int64_t buf_len)
  {
    common::ObSpinLockGuard guard(lock_);
    ObFTSScanRowEntry &entry = entries_[key % FTS_SCAN_ROW_CACHE_SLOTS];
    entry.key_ = key;
    entry.tablet_id_ = tablet_id;
    entry.epoch_ = epoch;
    entry.row_cnt_ = static_cast<int32_t>(row_cnt);
    entry.col_cnt_ = static_cast<int32_t>(col_cnt);
    entry.buf_len_ = static_cast<int32_t>(buf_len);
    MEMCPY(entry.buf_, buf, buf_len);
  }

private:
  common::ObSpinLock lock_;
  ObFTSScanRowEntry entries_[FTS_SCAN_ROW_CACHE_SLOTS];
};

ObFTSScanRowCache &scan_row_cache()
{
  static ObFTSScanRowCache cache;
  return cache;
}

// Number of payload bytes a non null value of this column type takes.
int64_t row_cell_payload_size(const ObObjType type, const uint32_t string_len)
{
  const ObObjTypeClass tc = ob_obj_type_class(type);
  int64_t size = -1;
  if (ObIntTC == tc || ObUIntTC == tc || ObDoubleTC == tc) {
    size = 8;
  } else if (ObFloatTC == tc) {
    size = 4;
  } else if (ObStringTC == tc) {
    size = 4 + static_cast<int64_t>(string_len);
  }
  return size;
}

int encode_row_cell(const ObExpr &expr,
                    const ObDatum &datum,
                    char *buf,
                    const int64_t cap,
                    int64_t &len)
{
  int ret = OB_SUCCESS;
  const ObObjType type = expr.datum_meta_.type_;
  if (datum.is_null()) {
    if (len + 1 > cap) {
      ret = OB_BUF_NOT_ENOUGH;
    } else {
      buf[len++] = static_cast<char>(FTS_SCAN_CELL_NULL);
    }
  } else {
    const ObObjTypeClass tc = ob_obj_type_class(type);
    int64_t payload = 8;
    if (ObFloatTC == tc) {
      payload = 4;
    } else if (ObStringTC == tc) {
      const ObString str = datum.get_string();
      payload = 4 + str.length();
    } else if (ObIntTC != tc && ObUIntTC != tc && ObDoubleTC != tc) {
      ret = OB_NOT_SUPPORTED;
    }
    if (OB_SUCC(ret) && len + 1 + payload > cap) {
      ret = OB_BUF_NOT_ENOUGH;
    }
    if (OB_SUCC(ret)) {
      buf[len++] = static_cast<char>(FTS_SCAN_CELL_VALUE);
      if (ObIntTC == tc) {
        const int64_t v = datum.get_int();
        MEMCPY(buf + len, &v, sizeof(v));
      } else if (ObUIntTC == tc) {
        const uint64_t v = datum.get_uint64();
        MEMCPY(buf + len, &v, sizeof(v));
      } else if (ObDoubleTC == tc) {
        const double v = datum.get_double();
        MEMCPY(buf + len, &v, sizeof(v));
      } else if (ObFloatTC == tc) {
        const float v = datum.get_float();
        MEMCPY(buf + len, &v, sizeof(v));
      } else {
        const ObString str = datum.get_string();
        const uint32_t str_len = str.length();
        MEMCPY(buf + len, &str_len, sizeof(str_len));
        MEMCPY(buf + len + sizeof(str_len), str.ptr(), str_len);
      }
      len += payload;
    }
  }
  return ret;
}

int decode_row_cell(const ObExpr &expr,
                    const char *&pos,
                    const char *end,
                    ObDatum &datum)
{
  int ret = OB_SUCCESS;
  const ObObjTypeClass tc = ob_obj_type_class(expr.datum_meta_.type_);
  if (pos + 1 > end) {
    ret = OB_ERR_UNEXPECTED;
  } else {
    const uint8_t tag = static_cast<uint8_t>(*pos++);
    if (FTS_SCAN_CELL_NULL == tag) {
      datum.set_null();
    } else if (FTS_SCAN_CELL_VALUE != tag) {
      ret = OB_ERR_UNEXPECTED;
    } else if (ObIntTC == tc || ObUIntTC == tc || ObDoubleTC == tc || ObFloatTC == tc) {
      const int64_t payload = ObFloatTC == tc ? 4 : 8;
      if (pos + payload > end) {
        ret = OB_ERR_UNEXPECTED;
      } else if (ObIntTC == tc) {
        int64_t v = 0;
        MEMCPY(&v, pos, sizeof(v));
        datum.set_int(v);
      } else if (ObUIntTC == tc) {
        uint64_t v = 0;
        MEMCPY(&v, pos, sizeof(v));
        datum.set_uint(v);
      } else if (ObDoubleTC == tc) {
        double v = 0;
        MEMCPY(&v, pos, sizeof(v));
        datum.set_double(v);
      } else {
        float v = 0;
        MEMCPY(&v, pos, sizeof(v));
        datum.set_float(v);
      }
      pos += payload;
    } else if (ObStringTC == tc) {
      uint32_t str_len = 0;
      if (pos + 4 > end) {
        ret = OB_ERR_UNEXPECTED;
      } else {
        MEMCPY(&str_len, pos, sizeof(str_len));
        pos += sizeof(str_len);
        if (pos + str_len > end || str_len > FTS_SCAN_ROW_CACHE_BUF) {
          ret = OB_ERR_UNEXPECTED;
        } else {
          datum.set_string(pos, str_len);
          pos += str_len;
        }
      }
    } else {
      ret = OB_ERR_UNEXPECTED;
    }
  }
  return ret;
}

int skip_row_cell(const ObExpr &expr, const char *&pos, const char *end)
{
  int ret = OB_SUCCESS;
  if (pos + 1 > end) {
    ret = OB_ERR_UNEXPECTED;
  } else {
    const uint8_t tag = static_cast<uint8_t>(*pos++);
    if (FTS_SCAN_CELL_NULL == tag) {
      // nothing to skip
    } else if (FTS_SCAN_CELL_VALUE != tag) {
      ret = OB_ERR_UNEXPECTED;
    } else if (ObStringTC == ob_obj_type_class(expr.datum_meta_.type_)) {
      uint32_t str_len = 0;
      if (pos + 4 > end) {
        ret = OB_ERR_UNEXPECTED;
      } else {
        MEMCPY(&str_len, pos, sizeof(str_len));
        if (pos + 4 + str_len > end) {
          ret = OB_ERR_UNEXPECTED;
        } else {
          pos += 4 + str_len;
        }
      }
    } else {
      const int64_t payload = row_cell_payload_size(expr.datum_meta_.type_, 0);
      if (payload < 0 || pos + payload > end) {
        ret = OB_ERR_UNEXPECTED;
      } else {
        pos += payload;
      }
    }
  }
  return ret;
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
    result_cache_mode_(RC_NONE),
    result_cache_eval_ctx_(nullptr),
    result_cache_output_(nullptr),
    result_cache_buf_(nullptr),
    result_cache_buf_len_(0),
    result_cache_row_cnt_(0),
    result_cache_col_cnt_(0),
    result_cache_replayed_(0),
    result_cache_topn_limit_(-1),
    result_cache_topn_offset_(-1),
    result_cache_engine_opened_(false),
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
  // The caller decides whether this scan may be replayed.  On top of that, a
  // boolean query tree or a functional lookup carries state that a replay would
  // not reproduce, and replaying rows requires output columns whose values can
  // be copied out and written back.
  if (OB_ISNULL(ir_ctdef)) {
    ret = OB_ERR_UNEXPECTED;
  } else if (param.result_cache_allowed_
      && nullptr == param.boolean_compute_node_
      && 0 == param.function_lookup_mode_
      && param.query_tokens_.count() > 0) {
    bool type_supported = true;
    const int64_t col_cnt = ir_ctdef->result_output_.count();
    for (int64_t i = 0; type_supported && i < col_cnt; ++i) {
      const ObExpr *expr = ir_ctdef->result_output_.at(i);
      if (OB_ISNULL(expr) || !is_row_cache_supported_type(expr->datum_meta_.type_)) {
        type_supported = false;
      }
    }
    if (!ir_ctdef->has_pushdown_topk()) {
      // Only the row count matters, and the caller guaranteed that nothing
      // above the scan reads the rows.
      result_cache_mode_ = RC_COUNT;
    } else if (col_cnt > 0 && col_cnt <= FTS_SCAN_ROW_MAX_COLS && type_supported) {
      // The top-n bound is what makes the produced row set finite, so it has to
      // be part of the identity of the result.  Both expressions may be missing,
      // which is itself part of the identity and is encoded as -1.
      int64_t topn_limit = -1;
      int64_t topn_offset = -1;
      if (OB_UNLIKELY(nullptr == param.ir_rtdef_->eval_ctx_)) {
        result_cache_mode_ = RC_NONE;
      } else {
        if (nullptr != ir_ctdef->topk_limit_expr_) {
          ObDatum *datum = nullptr;
          if (OB_FAIL(ir_ctdef->topk_limit_expr_->eval(*param.ir_rtdef_->eval_ctx_, datum))
              || OB_ISNULL(datum) || datum->is_null()) {
            result_cache_mode_ = RC_NONE;
            ret = OB_SUCCESS;
          } else {
            topn_limit = datum->get_int();
          }
        }
        if (RC_ROWS == result_cache_mode_) {
          if (nullptr != ir_ctdef->topk_offset_expr_) {
            ObDatum *datum = nullptr;
            if (OB_FAIL(ir_ctdef->topk_offset_expr_->eval(*param.ir_rtdef_->eval_ctx_, datum))
                || OB_ISNULL(datum) || datum->is_null()) {
              result_cache_mode_ = RC_NONE;
              ret = OB_SUCCESS;
            } else {
              topn_offset = datum->get_int();
            }
          }
        }
        if (RC_ROWS == result_cache_mode_) {
          result_cache_topn_limit_ = topn_limit;
          result_cache_topn_offset_ = topn_offset;
        }
      }
    }
    if (RC_NONE != result_cache_mode_) {
      for (int64_t i = 0; i < param.query_tokens_.count(); ++i) {
        const ObString &token = param.query_tokens_.at(i);
        hash = common::murmurhash(token.ptr(), token.length(), hash);
      }
      for (int64_t i = 0; i < param.dim_weights_.count(); ++i) {
        const double weight = param.dim_weights_.at(i);
        hash = common::murmurhash(&weight, sizeof(weight), hash);
      }
      hash = common::murmurhash(&ir_ctdef->mode_flag_, sizeof(ir_ctdef->mode_flag_), hash);
      if (RC_ROWS == result_cache_mode_) {
        hash = common::murmurhash(&result_cache_topn_limit_,
                                  sizeof(result_cache_topn_limit_), hash);
        hash = common::murmurhash(&result_cache_topn_offset_,
                                  sizeof(result_cache_topn_offset_), hash);
      }
      result_cache_token_hash_ = hash;
      result_cache_eval_ctx_ = param.ir_rtdef_->eval_ctx_;
      result_cache_output_ = &ir_ctdef->result_output_;
      result_cache_usable_ = true;
    }
  }
  return ret;
}

void ObDASTRMergeIter::reset_result_cache()
{
  result_cache_mode_ = RC_NONE;
  result_cache_usable_ = false;
  result_cache_hit_ = false;
  result_cache_stored_ = false;
  result_cache_token_hash_ = 0;
  result_cache_key_ = 0;
  result_cache_epoch_ = 0;
  result_cache_tablet_id_ = 0;
  result_cache_remaining_ = 0;
  result_cache_scanned_cnt_ = 0;
  result_cache_eval_ctx_ = nullptr;
  result_cache_output_ = nullptr;
  result_cache_buf_ = nullptr;
  result_cache_buf_len_ = 0;
  result_cache_row_cnt_ = 0;
  result_cache_col_cnt_ = 0;
  result_cache_replayed_ = 0;
  result_cache_topn_limit_ = -1;
  result_cache_topn_offset_ = -1;
}

void ObDASTRMergeIter::reset_result_cache_progress()
{
  result_cache_hit_ = false;
  result_cache_stored_ = false;
  result_cache_remaining_ = 0;
  result_cache_scanned_cnt_ = 0;
  result_cache_buf_len_ = 0;
  result_cache_row_cnt_ = 0;
  result_cache_col_cnt_ = 0;
  result_cache_replayed_ = 0;
}

int ObDASTRMergeIter::lookup_result_cache()
{
  int ret = OB_SUCCESS;
  int64_t cached_value = 0;
  reset_result_cache_progress();
  if (result_cache_usable_ && result_cache_tablet_id_ > 0) {
    // The epoch is pinned before the scan starts: a write that lands while the
    // scan runs makes the observed epoch differ, in which case the result is
    // not stored.
    result_cache_epoch_ = ObFTSWriteEpoch::get();
    if (RC_COUNT == result_cache_mode_) {
      if (OB_SUCCESS == scan_count_cache().get(
          result_cache_key_, result_cache_tablet_id_, result_cache_epoch_, cached_value)) {
        result_cache_hit_ = true;
        result_cache_remaining_ = cached_value;
      }
    } else if (RC_ROWS == result_cache_mode_) {
      if (OB_NOT_NULL(result_cache_output_)) {
        result_cache_col_cnt_ = result_cache_output_->count();
      }
      if (OB_ISNULL(result_cache_buf_)) {
        if (OB_ISNULL(result_cache_buf_ = static_cast<char *>(
            engine_allocator_.alloc(FTS_SCAN_ROW_CACHE_BUF)))) {
          result_cache_usable_ = false;
        }
      }
      if (OB_SUCC(ret) && result_cache_usable_) {
        int64_t row_cnt = 0;
        int64_t col_cnt = 0;
        if (OB_SUCCESS == scan_row_cache().get(
            result_cache_key_, result_cache_tablet_id_, result_cache_epoch_,
            result_cache_buf_, FTS_SCAN_ROW_CACHE_BUF, result_cache_buf_len_,
            row_cnt, col_cnt)) {
          result_cache_hit_ = true;
          result_cache_row_cnt_ = row_cnt;
          result_cache_col_cnt_ = col_cnt;
        }
      }
    }
  }
  return ret;
}

int ObDASTRMergeIter::capture_cached_rows(int64_t count)
{
  int ret = OB_SUCCESS;
  if (!result_cache_usable_ || count <= 0) {
    // nothing to capture
  } else if (RC_COUNT == result_cache_mode_) {
    result_cache_scanned_cnt_ += count;
  } else if (RC_ROWS != result_cache_mode_) {
    result_cache_usable_ = false;
  } else if (OB_ISNULL(result_cache_buf_) || OB_ISNULL(result_cache_eval_ctx_)
      || OB_ISNULL(result_cache_output_)) {
    result_cache_usable_ = false;
  } else if (result_cache_row_cnt_ + count > FTS_SCAN_ROW_MAX_ROWS
      || (result_cache_topn_limit_ >= 0
          && result_cache_row_cnt_ + count > result_cache_topn_limit_
              + (result_cache_topn_offset_ > 0 ? result_cache_topn_offset_ : 0))) {
    // More rows than the cache holds, or more rows than the top-n bound the
    // scan is supposed to produce: leave this scan alone, a miss is always
    // better than a wrong hit.
    result_cache_usable_ = false;
  } else {
    int64_t len = result_cache_buf_len_;
    for (int64_t r = 0; OB_SUCC(ret) && r < count; ++r) {
      for (int64_t c = 0; OB_SUCC(ret) && c < result_cache_col_cnt_; ++c) {
        const ObExpr *expr = result_cache_output_->at(c);
        ObDatum *datums = nullptr;
        if (OB_ISNULL(expr)) {
          ret = OB_ERR_UNEXPECTED;
        } else if (OB_ISNULL(datums = expr->locate_batch_datums(*result_cache_eval_ctx_))) {
          ret = OB_ERR_UNEXPECTED;
        } else if (OB_FAIL(encode_row_cell(*expr, datums[r], result_cache_buf_,
                                           FTS_SCAN_ROW_CACHE_BUF, len))) {
        }
      }
    }
    if (OB_FAIL(ret)) {
      // A buffer that does not fit the rows is not an error for the query, it
      // only means this scan cannot be cached.
      ret = OB_SUCCESS;
      result_cache_usable_ = false;
    } else {
      result_cache_buf_len_ = len;
      result_cache_row_cnt_ += count;
    }
  }
  return ret;
}

int ObDASTRMergeIter::store_cached_rows()
{
  int ret = OB_SUCCESS;
  if (result_cache_usable_ && !result_cache_stored_ && result_cache_tablet_id_ > 0
      && ObFTSWriteEpoch::get() == result_cache_epoch_) {
    if (RC_COUNT == result_cache_mode_) {
      if (result_cache_scanned_cnt_ > 0) {
        scan_count_cache().put(result_cache_key_, result_cache_tablet_id_,
                               result_cache_epoch_, result_cache_scanned_cnt_);
      }
    } else if (RC_ROWS == result_cache_mode_ && 0 == result_cache_buf_len_) {
      // A scan that returned no rows at all still has a useful entry: replaying
      // it means answering with OB_ITER_END straight away.
      scan_row_cache().put(result_cache_key_, result_cache_tablet_id_,
                           result_cache_epoch_, 0, result_cache_col_cnt_,
                           result_cache_buf_, 0);
    } else if (RC_ROWS == result_cache_mode_) {
      scan_row_cache().put(result_cache_key_, result_cache_tablet_id_,
                           result_cache_epoch_, result_cache_row_cnt_,
                           result_cache_col_cnt_, result_cache_buf_,
                           result_cache_buf_len_);
    }
    result_cache_stored_ = true;
  }
  return ret;
}

int ObDASTRMergeIter::replay_cached_row_data(int64_t &count, int64_t capacity)
{
  int ret = OB_SUCCESS;
  count = 0;
  if (result_cache_replayed_ >= result_cache_row_cnt_) {
    ret = OB_ITER_END;
  } else if (OB_ISNULL(result_cache_buf_) || OB_ISNULL(result_cache_eval_ctx_)
      || OB_ISNULL(result_cache_output_)) {
    ret = OB_ERR_UNEXPECTED;
  } else {
    const char *pos = result_cache_buf_;
    const char *end = result_cache_buf_ + result_cache_buf_len_;
    const int64_t replay_cnt = MIN(capacity, result_cache_row_cnt_ - result_cache_replayed_);
    for (int64_t r = 0; OB_SUCC(ret) && r < result_cache_replayed_; ++r) {
      for (int64_t c = 0; OB_SUCC(ret) && c < result_cache_col_cnt_; ++c) {
        ret = skip_row_cell(*result_cache_output_->at(c), pos, end);
      }
    }
    for (int64_t r = 0; OB_SUCC(ret) && r < replay_cnt; ++r) {
      for (int64_t c = 0; OB_SUCC(ret) && c < result_cache_col_cnt_; ++c) {
        const ObExpr *expr = result_cache_output_->at(c);
        ObDatum *datums = nullptr;
        if (OB_ISNULL(datums = expr->locate_batch_datums(*result_cache_eval_ctx_))) {
          ret = OB_ERR_UNEXPECTED;
        } else {
          ret = decode_row_cell(*expr, pos, end, datums[r]);
        }
      }
    }
    if (OB_SUCC(ret)) {
      result_cache_replayed_ += replay_cnt;
      count = replay_cnt;
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
  } else if (result_cache_hit_) {
    // The whole batch stream is replayed, so the physical scan is not opened:
    // opening it is the dominating cost of a top-n scan.
  } else if (OB_FAIL(engine_->do_table_scan())) {
  } else {
    result_cache_engine_opened_ = true;
  }
  return ret;
}

int ObDASTRMergeIter::inner_reuse()
{
  int ret = OB_SUCCESS;
  if (IS_NOT_INIT || OB_ISNULL(engine_)) {
    ret = OB_NOT_INIT;
  } else if (OB_FAIL(engine_->bind_source_tree(children_, children_cnt_))) {
  } else if (result_cache_engine_opened_ && OB_FAIL(engine_->reuse())) {
  } else {
    reset_result_cache_progress();
  }
  return ret;
}

int ObDASTRMergeIter::rescan()
{
  int ret = OB_SUCCESS;
  if (IS_NOT_INIT || OB_ISNULL(engine_)) {
    ret = OB_NOT_INIT;
  } else if (OB_FAIL(engine_->bind_source_tree(children_, children_cnt_))) {
  } else if (!result_cache_engine_opened_ && OB_FAIL(engine_->do_table_scan())) {
  } else if (OB_FALSE_IT(result_cache_engine_opened_ = true)) {
  } else if (OB_FAIL(engine_->rescan())) {
  } else {
    // A rescan may walk a different range of the index, so its result is not
    // interchangeable with the result of a full scan.  Any capture in progress
    // is dropped with it.
    reset_result_cache_progress();
    result_cache_usable_ = false;
    result_cache_stored_ = true;
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
  result_cache_engine_opened_ = false;
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
    if (RC_ROWS == result_cache_mode_) {
      ret = replay_cached_row_data(count, capacity);
    } else {
      ret = replay_cached_rows(count, capacity);
    }
    if (OB_FAIL(ret) && OB_ITER_END != ret) {
      // A cached row that cannot be decoded is treated as a corrupt entry: drop
      // it and answer from the real scan, which is already opened.
      result_cache_hit_ = false;
      result_cache_usable_ = false;
      count = 0;
      ret = OB_SUCCESS;
      if (!result_cache_engine_opened_) {
        if (OB_FAIL(engine_->do_table_scan())) {
        } else {
          result_cache_engine_opened_ = true;
        }
      }
    }
  }
  // Only a real scan may fill the cache.  Keeping this in a separate statement
  // guarded by !result_cache_hit_ is what stops a finished replay from falling
  // through to the store path with an empty capture buffer.
  if (OB_SUCC(ret) && !result_cache_hit_) {
    if (OB_SUCC(engine_->get_next_rows(count, capacity))) {
      // Caching is best effort: it must not change what the scan returns, so
      // the helpers report into a local code instead of overwriting ret.
      int cache_ret = capture_cached_rows(count);
      UNUSED(cache_ret);
    } else if (OB_ITER_END == ret) {
      int cache_ret = capture_cached_rows(count);
      if (OB_SUCCESS == cache_ret) {
        cache_ret = store_cached_rows();
      }
      UNUSED(cache_ret);
      result_cache_stored_ = true;
    } else {
      result_cache_usable_ = false;
    }
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
