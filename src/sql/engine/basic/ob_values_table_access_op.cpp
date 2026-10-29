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

#define USING_LOG_PREFIX SQL_ENG

#include "sql/engine/basic/ob_values_table_access_op.h"
#include "sql/engine/ob_exec_context.h"
#include "sql/engine/ob_physical_plan.h"
#include "sql/engine/expr/ob_obj_cast_runtime.h"
#include "sql/engine/basic/file/ob_file_csv_reader.h"
#include "sql/engine/basic/file/file_json_reader.h"
#include "sql/engine/basic/file/file_glob_reader.h"
#include "sql/engine/basic/file/file_parquet_reader.h"

namespace oceanbase
{
using namespace common;
namespace sql
{
OB_SERIALIZE_MEMBER_INHERIT(ObValuesTableAccessSpec,
                            ObOpSpec,
                            access_type_,
                            column_exprs_,
                            value_exprs_,
                            start_param_idx_,
                            end_param_idx_,
                            obj_params_);

namespace {
bool file_scan_uses_column(const ObExpr *expression, const ObExpr *column, int depth = 0)
{
  if (expression == column) { return true; }
  if (expression == nullptr || depth >= 1024) { return depth >= 1024; }
  for (int64_t i = 0; i < expression->arg_cnt_; ++i) {
    if (file_scan_uses_column(expression->args_[i], column, depth + 1)) { return true; }
  }
  return false;
}
}

ObValuesTableAccessOp::ObValuesTableAccessOp(ObExecContext &exec_ctx,
                                             const ObOpSpec &spec,
                                             ObOpInput *input)
  : ObOperator(exec_ctx, spec, input), datum_caster_(), cm_(CM_NONE),
    row_idx_(0), row_cnt_(0), file_reader_(nullptr), file_batch_rows_(0),
    file_batch_idx_(0), file_cast_allocator_("FileScanCast") {}

int ObValuesTableAccessOp::open_file_scan()
{
  int ret = OB_SUCCESS;
  ObSQLSessionInfo *session = GET_MY_SESSION(ctx_);
  bool enabled = false;
  ObString secure_root;
  file_batch_rows_ = file_batch_idx_ = 0;
  if (OB_ISNULL(session) || MY_SPEC.obj_params_.count() != 8 + MY_SPEC.column_exprs_.count()) {
    ret = OB_ERR_UNEXPECTED;
  } else if (OB_FAIL(session->get_sys_variable(share::SYS_VAR_ENABLE_FILE_SQL, enabled))) {
  } else if (!enabled) {
    ret = OB_NOT_SUPPORTED;
  } else if (OB_FAIL(session->get_secure_file_priv(secure_root))) {
  } else if (MY_SPEC.obj_params_.at(2).get_int() != 2
             && OB_FAIL(ObFileCsvReader::check_secure_path(MY_SPEC.obj_params_.at(0).get_string(), secure_root))) {
  } else {
    const bool json_lines = MY_SPEC.obj_params_.at(2).get_int() == 1;
    const bool discovery = MY_SPEC.obj_params_.at(2).get_int() == 2;
    if (MY_SPEC.obj_params_.at(2).get_int() == 3) {
      FileParquetReader *reader = OB_NEWx(FileParquetReader, &ctx_.get_allocator());
      file_reader_ = reader;
      if (OB_ISNULL(reader)) { ret = OB_ALLOCATE_MEMORY_FAILED; }
      else if (OB_FAIL(reader->open(MY_SPEC.obj_params_.at(0).get_string()))) {
      } else {
        ObArray<int64_t> selected;
        for (int64_t i = 0; OB_SUCC(ret) && i < MY_SPEC.column_exprs_.count(); ++i) {
          bool used = false;
          const ExprFixedArray *sets[] = {&MY_SPEC.output_, &MY_SPEC.filters_, &MY_SPEC.startup_filters_};
          for (const auto *set : sets) {
            for (int64_t j = 0; !used && j < set->count(); ++j) {
              used = file_scan_uses_column(set->at(j), MY_SPEC.column_exprs_.at(i));
            }
          }
          if (used) { ret = selected.push_back(i); }
        }
        // COUNT(*) still needs one scalar column to advance the row iterator.
        if (OB_SUCC(ret) && selected.empty()) { ret = selected.push_back(0); }
        if (OB_SUCC(ret)) { ret = reader->project(selected); }
      }
    } else if (discovery) {
      FileGlobReader *reader = OB_NEWx(FileGlobReader, &ctx_.get_allocator());
      file_reader_ = reader;
      if (OB_ISNULL(reader)) { ret = OB_ALLOCATE_MEMORY_FAILED; }
      else { ret = reader->open(MY_SPEC.obj_params_.at(0).get_string(), secure_root); }
    } else if (json_lines) {
      FileJsonReader *reader = OB_NEWx(FileJsonReader, &ctx_.get_allocator());
      file_reader_ = reader;
      ObArray<ObFileColumnSchema> columns;
      if (OB_ISNULL(reader)) {
        ret = OB_ALLOCATE_MEMORY_FAILED;
      } else if (OB_FAIL(reader->open(MY_SPEC.obj_params_.at(0).get_string()))) {
      } else if (OB_FAIL(reader->infer_schema(file_cast_allocator_, columns))) {
      }
    } else {
      ObFileCsvReader *reader = OB_NEWx(ObFileCsvReader, &ctx_.get_allocator());
      file_reader_ = reader;
      ObCsvOptions options;
      options.header_ = MY_SPEC.obj_params_.at(1).get_bool();
      options.delimiter_ = MY_SPEC.obj_params_.at(4).get_int();
      options.quote_ = MY_SPEC.obj_params_.at(5).get_int();
      options.escape_ = MY_SPEC.obj_params_.at(6).get_int();
      options.null_str_ = MY_SPEC.obj_params_.at(7).get_string();
      if (OB_ISNULL(reader)) {
        ret = OB_ALLOCATE_MEMORY_FAILED;
      } else if (OB_FAIL(reader->open(MY_SPEC.obj_params_.at(0).get_string(), options))) {
      }
    }
    if (OB_FAIL(ret)) {
    } else if (!discovery
               && OB_FAIL(ObFileCsvReader::check_secure_path(MY_SPEC.obj_params_.at(0).get_string(), secure_root))) {
    } else if (file_reader_->column_count() != MY_SPEC.column_exprs_.count()) {
      ret = OB_INVALID_DATA;
    } else {
      ObString signature;
      if (OB_FAIL(file_reader_->signature(file_cast_allocator_, signature))) {
      } else if (signature != MY_SPEC.obj_params_.at(3).get_string()) {
        ret = OB_INVALID_DATA;
      }
      for (int64_t i = 0; OB_SUCC(ret) && i < file_reader_->column_count(); ++i) {
        if (file_reader_->column_name(i) != MY_SPEC.obj_params_.at(8 + i).get_string()) {
          ret = OB_INVALID_DATA;
        }
      }
      if (OB_SUCC(ret) && OB_FAIL(file_reader_->begin_scan())) {
      }
    }
  }
  return ret;
}

int ObValuesTableAccessOp::calc_next_file_row()
{
  int ret = OB_SUCCESS;
  const int64_t columns = MY_SPEC.column_exprs_.count();
  if (OB_ISNULL(file_reader_)) {
    ret = OB_NOT_INIT;
  } else if (file_batch_idx_ == file_batch_rows_) {
    file_cast_allocator_.reuse();
    file_batch_idx_ = 0;
    if (OB_FAIL(file_reader_->next_batch(256, file_cells_, file_nulls_, file_batch_rows_))) {
    } else if (file_batch_rows_ == 0) {
      ret = OB_ITER_END;
    }
  }
  for (int64_t i = 0; OB_SUCC(ret) && i < columns; ++i) {
    ObExpr *expr = MY_SPEC.column_exprs_.at(i);
    const int64_t index = file_batch_idx_ * columns + i;
    ObObj source;
    ObObj converted;
    if (file_nulls_.at(index)) {
      source.set_null();
    } else {
      ObString cell = file_cells_.at(index);
      source.set_varchar(cell);
      source.set_collation_type(CS_TYPE_UTF8MB4_BIN);
      // BOOLEAN widens to BIGINT/DOUBLE in mixed numeric columns.
      if ((expr->datum_meta_.type_ == ObTinyIntType || expr->datum_meta_.type_ == ObIntType
           || expr->datum_meta_.type_ == ObDoubleType)
          && (0 == cell.case_compare("true") || 0 == cell.case_compare("false"))) {
        source.set_int(0 == cell.case_compare("true") ? 1 : 0);
      }
    }
    const ObDataTypeCastParams params = ObBasicSessionInfo::create_dtc_params(GET_MY_SESSION(ctx_));
    ObAccuracy accuracy = ObAccuracy::DDL_DEFAULT_ACCURACY2[0][expr->datum_meta_.type_];
    accuracy.set_scale(expr->datum_meta_.scale_);
    ObCastCtx cast(&file_cast_allocator_, &params, cm_, expr->obj_meta_.get_collation_type(), &accuracy);
    if (source.is_null()) {
      expr->locate_datum_for_write(eval_ctx_).set_null();
      expr->set_evaluated_projected(eval_ctx_);
    } else if (OB_FAIL(ObObjCaster::to_type(expr->datum_meta_.type_,
                    expr->obj_meta_.get_collation_type(), cast, source, converted))) {
    } else if (OB_FAIL(calc_datum_from_param(converted, expr))) {
    }
  }
  for (int64_t i = 0; OB_SUCC(ret) && i < MY_SPEC.output_.count(); ++i) {
    ObDatum *datum = nullptr;
    if (OB_FAIL(MY_SPEC.output_.at(i)->eval(eval_ctx_, datum))) {
    }
  }
  if (OB_SUCC(ret)) {
    ++file_batch_idx_;
    ++row_idx_;
  }
  return ret;
}

int ObValuesTableAccessOp::inner_open()
{
  int ret = OB_SUCCESS;
  row_idx_ = 0;
  const int32_t result_flag = 0;
  ObPhysicalPlanCtx *plan_ctx = GET_PHY_PLAN_CTX(ctx_);
  if (OB_ISNULL(plan_ctx) || OB_ISNULL(ctx_.get_sql_ctx())) {
    ret = OB_ERR_UNEXPECTED;
  } else if (OB_UNLIKELY(MY_SPEC.column_exprs_.empty())) {
    ret = OB_ERR_UNEXPECTED;
  } else if (OB_FAIL(datum_caster_.init(eval_ctx_.exec_ctx_))) {
  } else if (OB_FAIL(ObSQLUtils::get_default_cast_mode(false, 0, GET_MY_SESSION(ctx_), cm_))) {
  } else {
    cm_ = cm_ | CM_COLUMN_CONVERT;
    if (OB_SUCC(ret)) {
      if (ObValuesTableDef::ACCESS_FILE == MY_SPEC.access_type_) {
        ret = open_file_scan();
      } else if (ObValuesTableDef::FOLD_ACCESS_EXPR == MY_SPEC.access_type_) {
        if (OB_UNLIKELY(MY_SPEC.start_param_idx_ < 0 ||
                        MY_SPEC.start_param_idx_ > MY_SPEC.end_param_idx_ ||
                        MY_SPEC.end_param_idx_ >= plan_ctx->get_param_store().count())) {
          ret = OB_ERR_UNEXPECTED;
        } else {
          const ObObj &first_column_node = plan_ctx->get_param_store().at(MY_SPEC.start_param_idx_);
          if (OB_FAIL(first_column_node.get_real_param_count(row_cnt_))) {
          }
        }
      } else if (ObValuesTableDef::ACCESS_PARAM == MY_SPEC.access_type_) {
        int64_t column_cnt = MY_SPEC.column_exprs_.count();
        row_cnt_ = (MY_SPEC.end_param_idx_ - MY_SPEC.start_param_idx_ + 1) / column_cnt;
      } else if (ObValuesTableDef::ACCESS_OBJ == MY_SPEC.access_type_) {
        int64_t column_cnt = MY_SPEC.column_exprs_.count();
        row_cnt_ = MY_SPEC.obj_params_.count() / column_cnt;
      } else {
        int64_t column_cnt = MY_SPEC.column_exprs_.count();
        row_cnt_ = MY_SPEC.value_exprs_.count() / column_cnt;
      }
    }
  }
  return ret;
}

int ObValuesTableAccessOp::inner_rescan()
{
  int ret = OB_SUCCESS;
  if (OB_FAIL(ObOperator::inner_rescan())) {
  } else {
    row_idx_ = 0;
    if (OB_NOT_NULL(file_reader_)) {
      file_batch_rows_ = file_batch_idx_ = 0;
      ret = file_reader_->rescan();
    }
  }
  return ret;
}

int ObValuesTableAccessOp::switch_iterator()
{
  int ret = OB_SUCCESS;
  if (OB_FAIL(ObOperator::inner_switch_iterator())) {
  } else {
    row_idx_ = 0;
    if (OB_NOT_NULL(file_reader_)) {
      file_batch_rows_ = file_batch_idx_ = 0;
      ret = file_reader_->rescan();
    }
  }
  return ret;
}

int ObValuesTableAccessOp::inner_get_next_row()
{
  int ret = OB_SUCCESS;
  if (OB_FAIL(try_check_status())) {
  } else {
    do {
      clear_evaluated_flag();
      if (OB_FAIL(calc_next_row())) {
        if(OB_ITER_END != ret) {
        }
      } else {
        LOG_DEBUG("output row", "row", ROWEXPR2STR(eval_ctx_, MY_SPEC.output_));
      }
      break;
    } while (OB_SUCC(ret));
  }
  return ret;
}

void ObValuesTableAccessOp::update_src_meta(const ObObjMeta &src_obj_meta,
                                            const ObAccuracy &src_obj_acc,
                                            ObDatumMeta &src_meta)
{
  src_meta.type_ = src_obj_meta.get_type();
  src_meta.cs_type_ = src_obj_meta.get_collation_type();
  src_meta.scale_ = src_obj_acc.get_scale();
  src_meta.precision_ = src_obj_acc.get_precision();
}

int ObValuesTableAccessOp::get_real_src_obj_type(const int64_t row_idx,
                                                 ObExpr &src_expr,
                                                 ObDatumMeta &src_meta,
                                                 ObObjMeta &src_obj_meta)
{
  int ret = OB_SUCCESS;
  if (T_QUESTIONMARK == src_expr.type_) {
    int64_t param_idx = src_expr.extra_;
    ObPhysicalPlanCtx *plan_ctx = GET_PHY_PLAN_CTX(ctx_);
    const ObSqlArrayObj *array_obj = NULL;
    if (OB_UNLIKELY(param_idx < 0 || param_idx >= plan_ctx->get_param_store().count())) {
      ret = OB_INVALID_ARGUMENT;
    } else if (plan_ctx->get_param_store().at(param_idx).is_ext_sql_array()) {
      // If the parameter is is_ext_sql_array
      if (OB_ISNULL(array_obj = reinterpret_cast<const ObSqlArrayObj*>(
                                            plan_ctx->get_param_store().at(param_idx).get_ext()))) {
        ret = OB_ERR_UNEXPECTED;
      } else if (array_obj->count_ <= row_idx) {
        ret = OB_ERR_UNEXPECTED;
      } else {
        src_obj_meta = array_obj->data_[row_idx].meta_;
        const ObAccuracy &src_obj_acc = array_obj->data_[row_idx].get_accuracy();
        update_src_meta(src_obj_meta, src_obj_acc, src_meta);
      }
    } else if (src_expr.frame_idx_ < spec_.plan_->get_expr_frame_info().const_frame_.count() +
                                     spec_.plan_->get_expr_frame_info().param_frame_.count()) {
      src_obj_meta = plan_ctx->get_param_store().at(param_idx).meta_;
      const ObAccuracy &src_obj_acc = plan_ctx->get_param_store().at(param_idx).get_accuracy();
      update_src_meta(src_obj_meta, src_obj_acc, src_meta);
    }
  }
  return ret;
}

int ObValuesTableAccessOp::calc_datum_from_expr(const int64_t col_idx,
                                                const int64_t row_idx,
                                                ObExpr *src_expr,
                                                ObExpr *dst_expr)
{
  int ret = OB_SUCCESS;
  ObDatumMeta src_meta = src_expr->datum_meta_;
  ObObjMeta src_obj_meta = src_expr->obj_meta_;
  ObDatum *datum = NULL;
  bool need_adjust_decimal_int = false;
  if (src_expr == dst_expr) {
    /* actually should not happened */
  } else if (T_QUESTIONMARK == src_expr->type_ &&
             OB_FAIL(get_real_src_obj_type(row_idx, *src_expr, src_meta, src_obj_meta))) {
    LOG_WARN("failed to get real obj type");
  } else {
    need_adjust_decimal_int = src_meta.type_ == ObDecimalIntType &&
                              dst_expr->datum_meta_.type_ == ObDecimalIntType &&
                              ObDatumCast::need_scale_decimalint(src_meta.scale_,
                                                                 src_meta.precision_,
                                                                 dst_expr->datum_meta_.scale_,
                                                                 dst_expr->datum_meta_.precision_);
  }
  if (OB_FAIL(ret)) {
  } else if (src_meta.type_ == dst_expr->datum_meta_.type_ &&
             src_meta.cs_type_ == dst_expr->datum_meta_.cs_type_ &&
             !need_adjust_decimal_int) {
    // when type and collation_type is same. src has the same type to dst;
    if (OB_FAIL(src_expr->eval(eval_ctx_, datum))) {
    } else {
      dst_expr->locate_datum_for_write(eval_ctx_) = *datum;
      dst_expr->set_evaluated_projected(eval_ctx_);
    }
  } else {
    if (OB_FAIL(ObCharset::check_valid_implicit_convert(src_meta.cs_type_,
                                                        dst_expr->datum_meta_.cs_type_))) {
    } else {
      ObExpr real_src_expr = *src_expr;
      real_src_expr.datum_meta_ = src_meta;
      real_src_expr.obj_meta_ = src_obj_meta;
      real_src_expr.obj_datum_map_ = ObDatum::get_obj_datum_map_type(src_meta.type_);
      if (OB_FAIL(datum_caster_.to_type(dst_expr->datum_meta_, real_src_expr, cm_, datum))) {
      } else {
        ObDatum &dst_datum = dst_expr->locate_datum_for_write(eval_ctx_);
        if (ObObjDatumMapType::OBJ_DATUM_STRING == dst_expr->obj_datum_map_) {
          ObExprStrResAlloc res_alloc(*dst_expr, eval_ctx_);
          if (OB_FAIL(dst_datum.deep_copy(*datum, res_alloc))) {
          }
        } else {
          ObDataBuffer res_alloc(const_cast<char*>(dst_datum.ptr_), dst_expr->res_buf_len_);
          if (OB_FAIL(dst_datum.deep_copy(*datum, res_alloc))) {
          }
        }
        dst_expr->set_evaluated_projected(eval_ctx_);
      }
    }
  }
  return ret;
}

int ObValuesTableAccessOp::calc_datum_from_param(const ObObj &src_obj, ObExpr *dst_expr)
{
  int ret = OB_SUCCESS;
  ObDatum &dst_datum = dst_expr->locate_datum_for_write(eval_ctx_);
  const ObObjType &src_type = src_obj.get_type();
  const ObObjType &dst_type =  dst_expr->obj_meta_.get_type();
  const ObObjParam src_obj_param = static_cast<const ObObjParam>(src_obj);
  bool need_adjust_decimal_int = ob_is_decimal_int_tc(src_type)
                                 && ob_is_decimal_int_tc(dst_expr->datum_meta_.type_)
                                 && ObDatumCast::need_scale_decimalint(src_obj_param.get_scale(),
                                                                       src_obj_param.get_precision(),
                                                                       dst_expr->datum_meta_.scale_,
                                                                       dst_expr->datum_meta_.precision_);
  if (ob_is_decimal_int_tc(src_type) && (ob_is_number_tc(dst_type) || need_adjust_decimal_int)) {
    ObObj dst_obj;
    const ObDataTypeCastParams dtc_params = ObBasicSessionInfo::create_dtc_params(GET_MY_SESSION(ctx_));
    ObAccuracy dst_accuracy = ObAccuracy::DDL_DEFAULT_ACCURACY2[0][dst_type];
    if (ob_is_decimal_int_tc(dst_type)) {
      dst_accuracy.set_scale(dst_expr->datum_meta_.scale_);
      dst_accuracy.set_precision(dst_expr->datum_meta_.precision_);
    }
    ObCastCtx cast_ctx(&eval_ctx_.exec_ctx_.get_allocator(), &dtc_params, cm_, dst_expr->obj_meta_.get_collation_type(), &dst_accuracy);
    ObSqlObjCastRuntime cast_runtime(&eval_ctx_.exec_ctx_);
    cast_ctx.runtime_ = &cast_runtime;
    if (OB_FAIL(ObObjCaster::to_type(dst_type, dst_expr->obj_meta_.get_collation_type(), cast_ctx,
                                     src_obj, dst_obj))) {
    } else if (OB_FAIL(dst_datum.from_obj(dst_obj))) {
    } else {
      dst_expr->set_evaluated_projected(eval_ctx_);
    }
  } else if (OB_FAIL(dst_datum.from_obj(src_obj))) {
  } else {
    dst_expr->set_evaluated_projected(eval_ctx_);
  }
  return ret;
}

OB_INLINE int ObValuesTableAccessOp::calc_next_row()
{
  int ret = OB_SUCCESS;
  int64_t col_num = MY_SPEC.column_exprs_.count();
  int64_t col_idx = 0;
  ObPhysicalPlanCtx *plan_ctx = GET_PHY_PLAN_CTX(ctx_);
  if (ObValuesTableDef::ACCESS_FILE == MY_SPEC.access_type_) {
    return calc_next_file_row();
  } else if (row_idx_ == row_cnt_) {
    ret = OB_ITER_END;
  } else if (ObValuesTableDef::FOLD_ACCESS_EXPR == MY_SPEC.access_type_ &&
             OB_FAIL(plan_ctx->replace_batch_param_datum(row_idx_,
                                          MY_SPEC.start_param_idx_,
                                          MY_SPEC.end_param_idx_ - MY_SPEC.start_param_idx_ + 1))) {
  } else {
    while (OB_SUCC(ret) && col_idx < col_num) {
      ObExpr *col_expr = MY_SPEC.column_exprs_.at(col_idx);
      switch (MY_SPEC.access_type_)
      {
        case ObValuesTableDef::ACCESS_FILE: {
          ret = OB_ERR_UNEXPECTED;
          break;
        }
        case ObValuesTableDef::ACCESS_EXPR : {
          int64_t idx = row_idx_ * col_num + col_idx;
          ObExpr *src_expr = MY_SPEC.value_exprs_.at(idx);
          if (OB_FAIL(calc_datum_from_expr(col_idx, row_idx_, src_expr, col_expr))) {
          }
          break;
        }
        case ObValuesTableDef::FOLD_ACCESS_EXPR : {
          ObExpr *src_expr = MY_SPEC.value_exprs_.at(col_idx);
          if (OB_FAIL(calc_datum_from_expr(col_idx, row_idx_, src_expr, col_expr))) {
          }
          break;
        }
        case ObValuesTableDef::ACCESS_PARAM: {
          int64_t param_idx = MY_SPEC.start_param_idx_ + col_idx + row_idx_ * col_num;
          const ObObjParam &param = plan_ctx->get_param_store().at(param_idx);
          if (OB_FAIL(calc_datum_from_param(param, col_expr))) {
          }
          break;
        }
        case ObValuesTableDef::ACCESS_OBJ: {
          int64_t idx = row_idx_ * col_num + col_idx;
          const ObObj &param = MY_SPEC.obj_params_.at(idx);
          if (OB_FAIL(calc_datum_from_param(param, col_expr))) {
          }
          break;
        }
      };
      col_idx++;
    } // while end

    for (int64_t i = 0; OB_SUCC(ret) && i < MY_SPEC.output_.count(); i++) {
      ObExpr *output = MY_SPEC.output_.at(i);
      if (i < col_num && output == MY_SPEC.column_exprs_.at(i)) {
        /* need do nothing */
      } else {
        ObDatum *dst_datum = NULL;
        MY_SPEC.output_.at(i)->eval(eval_ctx_, dst_datum);
      }
    }
    if (OB_SUCC(ret)) {
      ++row_idx_;
    }
  }
  return ret;
}

int ObValuesTableAccessOp::inner_close()
{
  int ret = OB_SUCCESS;
  row_idx_ = 0;
  if (OB_NOT_NULL(file_reader_)) {
    file_reader_->~IFileRowReader();
    file_reader_ = nullptr;
  }
  file_cells_.reset();
  file_nulls_.reset();
  file_cast_allocator_.reset();
  if (OB_FAIL(datum_caster_.destroy())) {
  }
  return ret;
}

void ObValuesTableAccessOp::destroy()
{
  if (OB_NOT_NULL(file_reader_)) {
    file_reader_->~IFileRowReader();
    file_reader_ = nullptr;
  }
  file_cells_.reset();
  file_nulls_.reset();
  file_cast_allocator_.reset();
  ObOperator::destroy();
}
} // end namespace sql
} // end namespace oceanbase
