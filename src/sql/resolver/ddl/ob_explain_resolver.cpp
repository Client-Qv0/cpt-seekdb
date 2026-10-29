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

#define USING_LOG_PREFIX SQL_RESV
#include "sql/resolver/ddl/ob_explain_resolver.h"
#include "sql/resolver/ob_resolver.h"
#include "sql/parser/ob_parser.h"
#include "sql/resolver/dml/ob_select_resolver.h"

using namespace oceanbase;
using namespace sql;
using namespace common;
const static int64_t EXPLAIN_FORMAT = 0;
const static int64_t EXPLAIN_DISPLAY_OPTION = 1;
const static int64_t EXPLAIN_INTO_TABLE = 2;
const static int64_t EXPLAIN_STMT_ID = 3;
const static int64_t EXPLAIN_CHILD_STMT = 4;
int ObExplainResolver::resolve(const ParseNode &parse_tree)
{
  int ret = OB_SUCCESS;
  ObExplainStmt *explain_stmt = NULL;
  if (!(T_EXPLAIN == parse_tree.type_  && 5 == parse_tree.num_child_)) {
    ret = OB_ERR_UNEXPECTED;
    LOG_WARN("invalid EXPLAIN syntax",
             "type", parse_tree.type_,
             "# of child", parse_tree.num_child_);
  } else if (NULL == (explain_stmt = create_stmt<ObExplainStmt>())) {
    ret = OB_SQL_RESOLVER_NO_MEMORY;
    LOG_WARN("failed to create explain stmt");
  } else {
    ParseNode *child_node = parse_tree.children_[EXPLAIN_CHILD_STMT];
    ObStmt *child_stmt = NULL;
    ObExplainDisplayOpt opt;
    opt.with_tree_line_ = true;
    if (OB_ISNULL(child_node)) {
      ret = OB_ERR_UNEXPECTED;
      LOG_WARN("empty parse tree for stmt");
    } else if (!(T_SELECT == child_node->type_
                 || T_DELETE == child_node->type_
                 || T_INSERT == child_node->type_
                 || T_UPDATE == child_node->type_
                 || T_REPLACE == child_node->type_)) {
      ret = OB_NOT_SUPPORTED;
      LOG_WARN("invalid stmt type for EXPLAIN", "type", child_node->type_);
      LOG_USER_ERROR(OB_NOT_SUPPORTED, "stmt type for EXPLAIN");
    } else {
      ObResolver resolver(params_);
      if (OB_FAIL(resolver.resolve(ObResolver::IS_NOT_PREPARED_STMT,
                                   *child_node,
                                   child_stmt))) {
      } else if (OB_ISNULL(child_stmt)) {
        ret = OB_ERR_UNEXPECTED;
        LOG_WARN("failed to generate stmt for child stmt");
      } else {
        explain_stmt->set_explain_query_stmt(static_cast<ObDMLStmt *>(child_stmt));
        ParseNode *format = parse_tree.children_[EXPLAIN_FORMAT];
        if (NULL != format) {
          switch (format->type_) {
          case T_SHOW_COLUMNS: break; // DESCRIBE SELECT metadata request
          case T_OUTLINE:
          {
            explain_stmt->set_explain_format(EXPLAIN_OUTLINE);
            opt.with_tree_line_ = true;
          } break;
          case T_EXTENDED:
          {
            explain_stmt->set_explain_format(EXPLAIN_EXTENDED);
            opt.with_tree_line_ = true;
          } break;
          case T_PARTITIONS:
          {
            explain_stmt->set_explain_format(EXPLAIN_PARTITIONS);
            opt.with_tree_line_ = true;
          } break;
          case T_TRADITIONAL:
          {
            explain_stmt->set_explain_format(EXPLAIN_TRADITIONAL);
            opt.with_tree_line_ = true;
          } break;
          case T_FORMAT_JSON:
          {
            explain_stmt->set_explain_format(EXPLAIN_FORMAT_JSON);
            opt.with_tree_line_ = false;
          } break;
          case T_BASIC: {
            explain_stmt->set_explain_format(EXPLAIN_BASIC);
            opt.with_tree_line_ = true;
            break;
          }
          case T_EXTENDED_NOADDR: {
            explain_stmt->set_explain_format(EXPLAIN_EXTENDED_NOADDR);
            opt.with_tree_line_ = true;
            break;
          }
          case T_PLANREGRESS: {
            explain_stmt->set_explain_format(EXPLAIN_PLANREGRESS);
            opt.with_tree_line_ = true;
            break;
          }
          default:
            ret = OB_ERROR;
            LOG_WARN("unknown explain format", "format", format->type_);
            break;
          }
        }
      }
    }
    ParseNode *opt_node = parse_tree.children_[EXPLAIN_DISPLAY_OPTION];
    if (OB_SUCC(ret) && NULL != opt_node) {
      switch (opt_node->type_) {
      case T_PRETTY_COLOR:
        opt.with_color_ = true;
        // pass
      case T_PRETTY:
        opt.with_tree_line_ = true;
        break;
      default:
        ret = OB_ERR_UNEXPECTED;
      }
    }
    if (OB_SUCC(ret)) {
      explain_stmt->set_display_opt(opt);
    }
    ParseNode *into_table_node = parse_tree.children_[EXPLAIN_INTO_TABLE];
    if (OB_SUCC(ret) && NULL != into_table_node) {
      ObString into_table(into_table_node->str_len_, into_table_node->str_value_);
      explain_stmt->set_into_table(into_table);
    }
    ParseNode *statement_id_node = parse_tree.children_[EXPLAIN_STMT_ID];
    if (OB_SUCC(ret) && NULL != statement_id_node) {
      ObString statement_id(statement_id_node->str_len_, statement_id_node->str_value_);
      explain_stmt->set_statement_id(statement_id);
    }
    if (OB_SUCC(ret) && parse_tree.children_[EXPLAIN_FORMAT] != nullptr
        && parse_tree.children_[EXPLAIN_FORMAT]->type_ == T_SHOW_COLUMNS
        && explain_stmt->is_select_explain()) {
      auto *query = static_cast<ObSelectStmt *>(explain_stmt->get_explain_query_stmt());
      bool has_file = false;
      for (int64_t i = 0; !has_file && i < query->get_table_size(); ++i) {
        const TableItem *table = query->get_table_item(i);
        has_file = table != nullptr && table->values_table_def_ != nullptr
                   && table->values_table_def_->access_type_ == ObValuesTableDef::ACCESS_FILE;
      }
      if (has_file) { ret = resolve_file_description(*query); }
    }
  }

  return ret;
}

// DESCRIBE file SELECT exposes resolved metadata as a native constant SELECT.
// No file rows or AI expressions are evaluated to obtain the description.
int ObExplainResolver::resolve_file_description(ObSelectStmt &query)
{
  int ret = OB_SUCCESS;
  ObSqlString text;
  for (int64_t i = 0; OB_SUCC(ret) && i < query.get_select_item_size(); ++i) {
    const SelectItem &item = query.get_select_item(i);
    const ObString &name = item.alias_name_.empty() ? item.expr_name_ : item.alias_name_;
    const ObObjType type = item.expr_->get_result_type().get_type();
    const char *type_name = "VARCHAR";
    if (type == ObTinyIntType) { type_name = "BOOLEAN"; }
    else if (ob_is_integer_type(type)) { type_name = "BIGINT"; }
    else if (type == ObDoubleType || type == ObFloatType || ob_is_number_tc(type)) { type_name = "DOUBLE"; }
    else if (type == ObDateType) { type_name = "DATE"; }
    else if (type == ObDateTimeType || type == ObTimestampType) { type_name = "DATETIME"; }
    bool nullable = true;
    if (item.expr_->is_column_ref_expr()) {
      const auto *column = static_cast<const ObColumnRefRawExpr *>(item.expr_);
      const TableItem *table = query.get_table_item_by_id(column->get_table_id());
      const int64_t index = column->get_column_id() - OB_APP_MIN_COLUMN_ID;
      if (table != nullptr && table->values_table_def_ != nullptr && index >= 0
          && index < table->values_table_def_->column_nnvs_.count()) {
        nullable = table->values_table_def_->column_nnvs_.at(index) > 0;
      }
    }
    if (i > 0) { ret = text.append(" UNION ALL "); }
    if (OB_SUCC(ret)) { ret = text.append("SELECT CONVERT(X'"); }
    for (int64_t j = 0; OB_SUCC(ret) && j < name.length(); ++j) {
      ret = text.append_fmt("%02x", static_cast<unsigned char>(name.ptr()[j]));
    }
    if (OB_SUCC(ret)) {
      ret = text.append_fmt("' USING utf8mb4) AS column_name, '%s' AS column_type, "
            "'%s' AS `null`, NULL AS `key`, NULL AS `default`, NULL AS extra",
            type_name, nullable ? "YES" : "NO");
    }
  }
  if (OB_SUCC(ret)) {
    ParseResult result;
    ObParser parser(*allocator_, session_info_->get_sql_mode());
    if (OB_FAIL(parser.parse(text.string(), result))) {
    } else if (OB_ISNULL(result.result_tree_) || result.result_tree_->num_child_ != 1) {
      ret = OB_ERR_UNEXPECTED;
    } else {
      ObSelectResolver resolver(params_);
      if (OB_FAIL(resolver.resolve(*result.result_tree_->children_[0]))) {
      } else { set_basic_stmt(resolver.get_basic_stmt()); }
    }
  }
  return ret;
}
