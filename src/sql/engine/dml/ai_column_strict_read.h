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

#pragma once
#include "share/ai_column/ob_ai_column_schema.h"
#include "query/session/ob_inner_sql_connection_access.h"
#include "sql/session/ob_inner_sql_connection.h"
#include "sql/engine/ob_physical_plan.h"
#include "common/mysqlclient/ob_mysql_result.h"

namespace oceanbase { namespace sql {
inline int check_ai_column_strict_read(ObExecContext &ctx, const ObPhysicalPlan &plan)
{
  using namespace common;
  using namespace share;
  using namespace share::schema;
  int ret = OB_SUCCESS;
  auto *session = ctx.get_my_session();
  bool strict = false;
  if (session == nullptr || !session->is_user_session() || plan.get_ai_column_reads().empty()) { return ret; }
  if (OB_FAIL(session->get_sys_variable(SYS_VAR_AI_COLUMN_STRICT_READ,strict)) || !strict) { return ret; }
  common::sqlclient::ObISQLConnectionGuard connection_guard;
  ObIInnerSQLConnection *conn = nullptr;
  if (OB_FAIL(query::ObInnerSQLConnectionAccess::create_spi_connection_with_external_session(session,connection_guard))) { return ret; }
  if (OB_ISNULL(conn=as_inner_sql_connection(connection_guard.get_ptr()))) { return OB_ERR_UNEXPECTED; }
  auto *old_conn=session->get_inner_conn();
  const bool old_hidden=session->is_table_name_hidden();
  session->set_inner_conn(connection_guard.get_ptr());
  session->set_table_name_hidden(true);
  ObSQLSessionInfo::StmtSavedValue saved_session;
  ObIInnerSQLConnection::SavedValue saved_connection;
  bool nested=false;
  if (OB_FAIL(conn->begin_nested_session(saved_session,saved_connection,true))) {}
  else { nested=true; }
  for (int64_t i=0; OB_SUCC(ret) && i<plan.get_ai_column_reads().count(); ++i) {
    const auto &check=plan.get_ai_column_reads().at(i);
    const ObTableSchema *table=nullptr;
    const ObDatabaseSchema *database=nullptr;
    const ObColumnSchemaV2 *state=nullptr;
    auto *schema=ctx.get_sql_ctx()->schema_guard_;
    ObSqlString sql;
    if (OB_FAIL(schema->get_table_schema(check.table_id_,table))) {}
    else if (table==nullptr) { ret=OB_TABLE_NOT_EXIST; }
    else if (OB_ISNULL(state=table->get_column_schema(check.state_column_id_))) { ret=OB_SCHEMA_EAGAIN; }
    else if (OB_FAIL(schema->get_database_schema(table->get_database_id(),database))) {}
    else if (database==nullptr) { ret=OB_SCHEMA_EAGAIN; }
    else if (OB_FAIL(sql.append("SELECT 1 value FROM "))) {}
    else if (OB_FAIL(ai_column_quote_identifier(sql,database->get_database_name_str()))) {}
    else if (OB_FAIL(sql.append("."))) {}
    else if (OB_FAIL(ai_column_quote_identifier(sql,table->get_table_name_str()))) {}
    else if (OB_FAIL(sql.append(" WHERE IFNULL("))) {}
    else if (OB_FAIL(ai_column_quote_identifier(sql,state->get_column_name_str()))) {}
    else if (OB_FAIL(sql.append(",1) <> 2 LIMIT 1"))) {}
    else {
      // Destroy the result before restoring the external statement context.
      ObMySQLProxy::MySQLResult result;
      if (OB_FAIL(conn->execute_read(sql.string(),result))) {}
      else if (result.get_result()==nullptr) { ret=OB_ERR_UNEXPECTED; }
      else {
        ret=result.get_result()->next();
        if (ret==OB_ITER_END) { ret=OB_SUCCESS; }
        else if (ret==OB_SUCCESS) {
          ret=OB_ERR_AI_COLUMN_UNFINISHED;
          LOG_USER_ERROR(OB_ERR_AI_COLUMN_UNFINISHED,check.table_id_,check.column_id_);
        }
      }
    }
  }
  if (nested) {
    const int end_ret=conn->end_nested_session(saved_session,saved_connection);
    if (OB_SUCC(ret)) { ret=end_ret; }
  }
  session->set_inner_conn(old_conn);
  session->set_table_name_hidden(old_hidden);
  return ret;
}
} }
