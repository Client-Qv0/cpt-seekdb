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

#define USING_LOG_PREFIX STORAGE

#include "ob_text_daat_iter.h"

namespace oceanbase
{
namespace storage
{
int ObTextDaaTIter::init(const ObTextDaaTParam &param)
{
  int ret = OB_SUCCESS;
  if (OB_ISNULL(param.base_param_) || OB_ISNULL(param.dim_iters_) || OB_ISNULL(param.allocator_)
      || OB_ISNULL(param.relevance_collector_)) {
    ret = OB_INVALID_ARGUMENT;
  } else if (OB_FAIL(ObSRDaaTIterImpl::init(*param.base_param_, *param.dim_iters_,
                                            *param.allocator_, *param.relevance_collector_))) {
  } else if (nullptr != param.base_param_->relevance_expr_
             && OB_FAIL(bm25_param_estimator_.init(param.bm25_param_est_ctx_))) {
  } else {
    mode_flag_ = param.mode_flag_;
    function_lookup_mode_ = param.function_lookup_mode_;
  }
  return ret;
}

void ObTextDaaTIter::reset()
{
  MEMSET(filter_batch_ids_, 0, sizeof(filter_batch_ids_));
  MEMSET(filter_batch_counts_, 0, sizeof(filter_batch_counts_));
  filter_ended_mask_ = 0;
  bm25_param_estimator_.reset();
  // this class can know the type of dim_iters_, but ObSRDaaTIterImpl maybe not
  if (OB_NOT_NULL(dim_iters_)) {
    for (int64_t i = 0; i < dim_iters_->count(); ++i) {
      static_cast<ObTextRetrievalDaaTTokenIter *>(dim_iters_->at(i))->reset();
    }
  }
  ObSRDaaTIterImpl::reset();
}

void ObTextDaaTIter::reuse(const bool switch_tablet)
{
  MEMSET(filter_batch_ids_, 0, sizeof(filter_batch_ids_));
  MEMSET(filter_batch_counts_, 0, sizeof(filter_batch_counts_));
  filter_ended_mask_ = 0;
  if ((OB_NOT_NULL(dim_iters_) && 0 == dim_iters_->count())) {
    // do nothing
  } else {
    bm25_param_estimator_.reuse(switch_tablet);
  }
  if (OB_NOT_NULL(dim_iters_)) {
    for (int64_t i = 0; i < dim_iters_->count(); ++i) {
      static_cast<ObTextRetrievalDaaTTokenIter *>(dim_iters_->at(i))->reuse();
    }
  }
  ObSRDaaTIterImpl::reuse(switch_tablet);
}

int ObTextDaaTIter::pre_process()
{
  int ret = OB_SUCCESS;
  if (dim_iters_->count() == 0) {
    ret = OB_ITER_END;
  } else if (nullptr != iter_param_->relevance_expr_) {
    if (OB_FAIL(bm25_param_estimator_.do_estimation(*iter_param_->eval_ctx_))) {
    }
  }
  return ret;
}

int ObTextDaaTIter::get_next_rows(const int64_t capacity, int64_t &count)
{
  if (!is_inited_ || function_lookup_mode_ || sql::NATURAL_LANGUAGE_MODE != mode_flag_
      || nullptr != iter_param_->relevance_expr_ || nullptr != iter_param_->dim_weights_
      || !is_relevance_bool_filter_ || !iter_param_->eval_ctx_->is_vectorized()
      || dim_iters_->count() == 0 || dim_iters_->count() > FILTER_BATCH_MAX_DIMS) {
    return ObSRDaaTIterImpl::get_next_rows(capacity, count);
  }
  int ret = OB_SUCCESS;
  count = 0;
  const int64_t dims = dim_iters_->count();
  const int64_t batch_size = MIN(capacity, iter_param_->max_batch_size_);
  const int64_t should_match = static_cast<ObSRDaaTInnerProductRelevanceCollector *>(
      relevance_collector_)->get_should_match();
  const auto &meta = iter_param_->id_proj_expr_->datum_meta_;
  const auto cmp = ObDatumFuncs::get_basic_func(meta.type_, meta.cs_type_)->null_first_cmp_;
  if (iter_param_->limit_param_->is_valid()
      && output_row_cnt_ >= iter_param_->limit_param_->limit_) {
    ret = OB_ITER_END;
  }
  // Merge buffered postings directly. The generic heap dispatches several
  // virtual calls per posting, even though filter-only retrieval needs only
  // a sorted union and the number of matching dimensions.
  while (OB_SUCC(ret) && count < batch_size) {
    const ObDatum *min_id = nullptr;
    uint64_t matched_mask = 0;
    int64_t matched_count = 0;
    for (int64_t i = 0; OB_SUCC(ret) && i < dims; ++i) {
      if (filter_batch_counts_[i] == 0 && !(filter_ended_mask_ & (1ULL << i))) {
        auto *token_iter = static_cast<ObTextRetrievalDaaTTokenIter *>(dim_iters_->at(i));
        if (OB_FAIL(token_iter->get_next_doc_ids(filter_batch_ids_[i], filter_batch_counts_[i]))) {
          if (OB_ITER_END == ret) {
            filter_ended_mask_ |= 1ULL << i;
            ret = OB_SUCCESS;
          }
        }
      }
      if (OB_SUCC(ret) && filter_batch_counts_[i] > 0) {
        const ObDatum &id = filter_batch_ids_[i]->get_datum();
        int cmp_ret = -1;
        if (nullptr != min_id && OB_FAIL(cmp(id, *min_id, cmp_ret, nullptr))) {
        } else if (cmp_ret < 0) {
          min_id = &id;
          matched_mask = 1ULL << i;
          matched_count = 1;
        } else if (cmp_ret == 0) {
          matched_mask |= 1ULL << i;
          ++matched_count;
        }
      }
    }
    if (OB_FAIL(ret)) {
    } else if (nullptr == min_id) {
      ret = OB_ITER_END;
    } else {
      // Copy the selected ID before a following refill can replace its buffer.
      if (matched_count >= should_match && OB_FAIL(cache_result(count, *min_id, 1.0))) {
      }
      for (int64_t i = 0; i < dims; ++i) {
        if (matched_mask & (1ULL << i)) {
          ++filter_batch_ids_[i];
          --filter_batch_counts_[i];
        }
      }
    }
  }
  if ((OB_SUCC(ret) || OB_ITER_END == ret) && count > 0) {
    const int project_ret = project_results(count);
    if (OB_SUCCESS != project_ret) {
      ret = project_ret;
    }
  }
  return ret;
}

ObTextBMWIter::ObTextBMWIter()
  : ObSRBMWIterImpl(),
    bm25_param_estimator_() {}

void ObTextBMWIter::reuse(const bool switch_tablet)
{
  bm25_param_estimator_.reuse(switch_tablet);
  if (OB_NOT_NULL(dim_iters_)) {
    for (int64_t i = 0; i < dim_iters_->count(); ++i) {
      static_cast<ObTextRetrievalBlockMaxIter *>(dim_iters_->at(i))->reuse();
    }
  }
  ObSRBMWIterImpl::reuse(switch_tablet);
}

void ObTextBMWIter::reset()
{
  bm25_param_estimator_.reset();
  if (OB_NOT_NULL(dim_iters_)) {
    for (int64_t i = 0; i < dim_iters_->count(); ++i) {
      static_cast<ObTextRetrievalBlockMaxIter *>(dim_iters_->at(i))->reset();
    }
  }
  ObSRBMWIterImpl::reset();
}

int ObTextBMWIter::init(const ObTextDaaTParam &param)
{
  int ret = OB_SUCCESS;
  if (OB_ISNULL(param.base_param_) || OB_ISNULL(param.dim_iters_) || OB_ISNULL(param.allocator_)
      || OB_ISNULL(param.relevance_collector_)) {
    ret = OB_INVALID_ARGUMENT;
  } else if (OB_FAIL(ObSRBMWIterImpl::init(*param.base_param_, *param.dim_iters_,
                                           *param.allocator_, *param.relevance_collector_))) {
  } else if (OB_FAIL(bm25_param_estimator_.init(param.bm25_param_est_ctx_))) {
  }
  return ret;
}

int ObTextBMWIter::get_next_rows(const int64_t capacity, int64_t &count)
{
  int ret = OB_SUCCESS;
  if (IS_NOT_INIT) {
    ret = OB_NOT_INIT;
  } else if (dim_iters_->count() == 0) {
    ret = OB_ITER_END;
  } else if (OB_FAIL(bm25_param_estimator_.do_estimation(*iter_param_->eval_ctx_))) {
  }

  if (FAILEDx(ObSRBMWIterImpl::get_next_rows(capacity, count))) {
    if (OB_UNLIKELY(OB_ITER_END != ret)) {
    }
  }
  return ret;
}

int ObTextBMWIter::init_before_wand_process()
{
  int ret = OB_SUCCESS;
  if (OB_UNLIKELY(!bm25_param_estimator_.is_estimated())) {
    ret = OB_ERR_UNEXPECTED;
  }

  for (int64_t i = 0; OB_SUCC(ret) && i < dim_iters_->count(); ++i) {
    ObTextRetrievalBlockMaxIter *block_max_iter = static_cast<ObTextRetrievalBlockMaxIter *>(dim_iters_->at(i));
    if (OB_FAIL(block_max_iter->init_block_max_iter(
        bm25_param_estimator_.get_total_doc_cnt(), bm25_param_estimator_.get_avg_doc_token_cnt()))) {
    }
  }
  return ret;
}

} // namespace storage
} // namespace oceanbase
