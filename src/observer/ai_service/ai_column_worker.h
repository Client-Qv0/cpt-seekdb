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
#include <atomic>
#include <charconv>
#include "share/ob_thread_pool.h"
#include "share/ai_column/ob_ai_column_schema.h"
#include "share/ai_column/ai_column_execution.h"
#include "common/mysqlclient/ob_mysql_transaction.h"
#include "common/mysqlclient/ob_mysql_result.h"
#include "share/ob_server_struct.h"
#include "share/rc/ob_server_runtime.h"
#include "config_bridge.h"
#include "share/schema/ob_multi_version_schema_service.h"
#include "sql/engine/expr/ob_expr_uuid.h"
#include "lib/time/ob_time_utility.h"

namespace oceanbase { namespace omt {
class AiColumnWorker : public share::ObThreadPool
{
  // One seekdb process exclusively owns this runtime's persistent store.
  // Recover once before either worker can claim work after a restart.
  std::atomic<int> recovery_state_{0};
  struct Task {
    int64_t column_id = 0;
    int64_t state = 0;
    int64_t retries = 0;
    common::ObString spec, predicate, result;
  };
  static int read_string(common::sqlclient::ObMySQLResult &row, const char *name,
                         common::ObIAllocator &alloc, common::ObString &value)
  {
    common::ObString tmp;
    int ret = row.get_varchar(name, tmp);
    if (OB_SUCC(ret)) { ret = ob_write_string(alloc, tmp, value); }
    return ret;
  }
  static int one_string(common::ObISQLClient &client, const common::ObSqlString &sql,
                        common::ObIAllocator &alloc, common::ObString &value)
  {
    int ret = OB_SUCCESS;
    common::ObMySQLProxy::MySQLResult res;
    if (OB_FAIL(client.read(res, sql.ptr()))) {}
    else if (OB_ISNULL(res.get_result())) { ret = OB_ERR_UNEXPECTED; }
    else if (OB_FAIL(res.get_result()->next())) {}
    else { ret = read_string(*res.get_result(), "value", alloc, value); }
    return ret;
  }
  static int scalar_bool(common::ObISQLClient &client, const common::ObSqlString &sql, bool &value)
  {
    int ret = OB_SUCCESS;
    int64_t v = 0;
    common::ObMySQLProxy::MySQLResult res;
    if (OB_FAIL(client.read(res, sql.ptr()))) {}
    else if (OB_ISNULL(res.get_result())) { ret = OB_ERR_UNEXPECTED; }
    else if (OB_FAIL(res.get_result()->next())) {}
    else if (OB_FAIL(res.get_result()->get_int("value", v))) {}
    else { value = v != 0; }
    return ret;
  }
  static int write(common::ObISQLClient &client, const common::ObSqlString &sql)
  {
    int64_t affected = 0;
    return client.write(sql.ptr(), affected);
  }
  static int load(common::ObISQLClient &client, const common::ObSqlString &filter,
                  common::ObIAllocator &alloc, common::ObIArray<Task> &tasks, bool &leased)
  {
    int ret = OB_SUCCESS;
    common::ObSqlString sql;
    common::ObMySQLProxy::MySQLResult res;
    leased = false;
    if (OB_FAIL(sql.append("SELECT column_id,state,retry_count,spec_text,rowkey_predicate,IFNULL(result_value,'') result_value,"
        "(owner IS NOT NULL AND lease_until > NOW(6)) leased FROM oceanbase.__all_ai_column_task WHERE "))) {}
    else if (OB_FAIL(sql.append(filter.string()))) {}
    else if (OB_FAIL(sql.append(" ORDER BY column_id FOR UPDATE"))) {}
    else if (OB_FAIL(client.read(res, sql.ptr()))) {}
    else if (OB_ISNULL(res.get_result())) { ret = OB_ERR_UNEXPECTED; }
    else {
      auto &row = *res.get_result();
      while (OB_SUCC(ret) && OB_SUCC(ret = row.next())) {
        Task task;
        int64_t active = 0;
        if (OB_FAIL(row.get_int("column_id", task.column_id))) {}
        else if (OB_FAIL(row.get_int("state", task.state))) {}
        else if (OB_FAIL(row.get_int("retry_count", task.retries))) {}
        else if (OB_FAIL(row.get_int("leased", active))) {}
        else if (OB_FAIL(read_string(row,"spec_text",alloc,task.spec))) {}
        else if (OB_FAIL(read_string(row,"rowkey_predicate",alloc,task.predicate))) {}
        else if (OB_FAIL(read_string(row,"result_value",alloc,task.result))) {}
        else if (OB_FAIL(tasks.push_back(task))) {}
        leased = leased || active != 0;
      }
      if (ret == OB_ITER_END) { ret = OB_SUCCESS; }
    }
    return ret;
  }
  static int build_table(common::ObISQLClient &client, int64_t table_id,
                         common::ObIAllocator &alloc, common::ObSqlString &table)
  {
    int ret = OB_SUCCESS;
    common::ObSqlString sql;
    common::ObString database, name;
    common::ObMySQLProxy::MySQLResult res;
    if (OB_FAIL(sql.append_fmt("SELECT d.database_name,t.table_name FROM oceanbase.__all_table t JOIN oceanbase.__all_database d "
                              "ON d.database_id=t.database_id WHERE t.table_id=%ld", table_id))) {}
    else if (OB_FAIL(client.read(res,sql.ptr()))) {}
    else if (OB_ISNULL(res.get_result())) { ret = OB_ERR_UNEXPECTED; }
    else if (OB_FAIL(res.get_result()->next())) {}
    else if (OB_FAIL(read_string(*res.get_result(),"database_name",alloc,database))) {}
    else if (OB_FAIL(read_string(*res.get_result(),"table_name",alloc,name))) {}
    else if (OB_FAIL(share::ai_column_quote_identifier(table,database))) {}
    else if (OB_FAIL(table.append("."))) {}
    else { ret = share::ai_column_quote_identifier(table,name); }
    return ret;
  }
  // Preserve native argument types (notably NULL and AI_PROMPT objects) and
  // evaluate under the SQL mode captured when the definition was created.
  static int split_arguments(const common::ObString &expression, uint64_t mode,
                              common::ObIArray<common::ObString> &arguments)
  {
    int ret=OB_SUCCESS;
    int64_t pos=0, start=0, depth=0;
    char quote=0;
    bool line_comment=false, block_comment=false, closed=false;
    while (pos<expression.length() && expression.ptr()[pos]!='(') { ++pos; }
    start=++pos;
    for (; OB_SUCC(ret) && pos<expression.length(); ++pos) {
      const char c=expression.ptr()[pos];
      const char next=pos+1<expression.length()?expression.ptr()[pos+1]:0;
      if (line_comment) { if (c=='\n' || c=='\r') { line_comment=false; } }
      else if (block_comment) { if (c=='*' && next=='/') { block_comment=false; ++pos; } }
      else if (quote!=0) {
        if (c=='\\' && quote!='`' && !(mode & SMO_NO_BACKSLASH_ESCAPES)) { ++pos; }
        else if (c==quote) { if (next==quote) { ++pos; } else { quote=0; } }
      } else if (c=='\'' || c=='"' || c=='`') { quote=c; }
      else if (c=='#') { line_comment=true; }
      else if (c=='-' && next=='-' && pos+2<expression.length()
               && static_cast<unsigned char>(expression.ptr()[pos+2])<=32) { line_comment=true; ++pos; }
      else if (c=='/' && next=='*') { block_comment=true; ++pos; }
      else if (c=='(') { ++depth; }
      else if ((c==',' || c==')') && depth==0) {
        ret=arguments.push_back(common::ObString(pos-start,expression.ptr()+start));
        start=pos+1;
        if (c==')') { closed=true; break; }
      } else if (c==')') { --depth; }
    }
    if (OB_SUCC(ret) && (!closed || arguments.count()<2 || arguments.count()>3)) { ret=OB_INVALID_ARGUMENT; }
    return ret;
  }
  static int calculate(common::ObISQLClient &client, const common::ObSqlString &table,
                       const common::ObString &request, const Task &task,
                       const share::ObAiColumnSpec &spec, common::ObIAllocator &alloc,
                       common::ObString &value)
  {
    int ret = OB_SUCCESS;
    common::ObSqlString sql;
    const common::ObString expression = share::ai_column_expression(spec);
    if (spec.result_type_ == share::AI_COLUMN_RESULT_VECTOR) {
      ret = sql.append("SELECT /*+ PARALLEL(1) */ ");
      if (OB_SUCC(ret)) { ret = sql.append(expression); }
    } else {
      common::ObSEArray<common::ObString,3> args;
      if (OB_FAIL(split_arguments(expression,spec.sql_mode_,args))) { return ret; }
      if (OB_FAIL(sql.append("SELECT /*+ PARALLEL(1) */ AI_COMPLETE("))) {}
      else if (OB_FAIL(sql.append(args.at(0)))) {}
      else if (OB_FAIL(sql.append(","))) {}
      else if (OB_FAIL(sql.append(args.at(1)))) {}
      else if (OB_FAIL(sql.append(",JSON_MERGE_PATCH(IFNULL(CAST("))) {}
      else if (OB_FAIL(sql.append(args.count()==3?args.at(2):common::ObString::make_string("JSON_OBJECT()")))) {}
      else if (OB_FAIL(sql.append(" AS JSON),JSON_OBJECT()),JSON_OBJECT('__ai_column_instruction',CONVERT("))) {}
      else if (OB_FAIL(share::ai_column_sql_literal(sql,common::ObString::make_string(
          share::ai_column_result_type_instruction(spec.result_type_))))) {}
      else if (OB_FAIL(sql.append(" USING utf8mb4)))) value"))) {}
    }
    if (OB_FAIL(ret)) {}
    else if (spec.result_type_ == share::AI_COLUMN_RESULT_VECTOR && OB_FAIL(sql.append(" value"))) {}
    else if (OB_FAIL(sql.append(" FROM "))) {}
    else if (OB_FAIL(sql.append(table.string()))) {}
    else if (OB_FAIL(sql.append(" WHERE "))) {}
    else if (OB_FAIL(sql.append(task.predicate))) {}
    else if (OB_FAIL(sql.append(" AND "))) {}
    else {
      common::ObString request_name;
      if (OB_FAIL(share::build_ai_hidden_column_name(alloc,share::AI_COLUMN_REQUEST_PREFIX,spec.result_column_name_,request_name))) {}
      else if (OB_FAIL(share::ai_column_quote_identifier(sql,request_name))) {}
      else if (OB_FAIL(sql.append("="))) {}
      else if (OB_FAIL(share::ai_column_sql_literal(sql,request))) {}
      else {
        common::ObMySQLTransaction computation;
        common::ObSqlString mode_sql;
        common::ObString old_mode;
        bool saved_mode=false;
        if (OB_FAIL(computation.start(&client))) { return ret; }
        if (OB_FAIL(mode_sql.append("SELECT @@session.sql_mode value"))) {}
        else if (OB_FAIL(one_string(computation,mode_sql,alloc,old_mode))) {}
        else {
          saved_mode=true;
          mode_sql.reset(); mode_sql.append_fmt("SET SESSION sql_mode=%lu",spec.sql_mode_);
          if (OB_SUCC(ret=write(computation,mode_sql))) {
            share::AiColumnExecutionGuard execution_guard;
            ret=one_string(computation,sql,alloc,value);
          }
        }
        if (saved_mode) {
          computation.reset_last_error();
          mode_sql.reset(); mode_sql.append("SET SESSION sql_mode=CONVERT(");
          share::ai_column_sql_literal(mode_sql,old_mode);
          mode_sql.append(" USING utf8mb4)");
          const int restore_ret=write(computation,mode_sql);
          if (OB_SUCC(ret)) { ret=restore_ret; }
        }
        const int end_ret=computation.end(OB_SUCC(ret));
        if (OB_SUCC(ret)) { ret=end_ret; }
        if (ret != OB_SUCCESS && ret != OB_ITER_END) {
          LOG_WARN("AI column calculation failed", K(ret), K(task.column_id));
        }
      }
    }
    if (OB_SUCC(ret) && spec.result_type_ == share::AI_COLUMN_RESULT_JSON) {
      common::ObSqlString validate;
      bool valid = false;
      if (OB_FAIL(validate.append("SELECT JSON_VALID(CONVERT("))) {}
      else if (OB_FAIL(share::ai_column_sql_literal(validate,value))) {}
      else if (OB_FAIL(validate.append(" USING utf8mb4)) value"))) {}
      else if (OB_FAIL(scalar_bool(client,validate,valid))) {}
      else if (!valid) { ret = OB_INVALID_DATA; }
    }
    return ret;
  }
  static int validate_value(common::ObISQLClient &client, int64_t table_id, const Task &task,
                            const share::ObAiColumnSpec &spec, common::ObIAllocator &alloc)
  {
    using namespace common;
    using namespace share::schema;
    int ret=OB_SUCCESS;
    ObSchemaGetterGuard schema;
    const ObTableSchema *table=nullptr;
    const ObColumnSchemaV2 *column=nullptr;
    if (GCTX.schema_service_==nullptr) { return OB_NOT_INIT; }
    if (OB_FAIL(GCTX.schema_service_->get_runtime_schema_guard(schema))) {}
    else if (OB_FAIL(schema.get_table_schema(table_id,table))) {}
    else if (table==nullptr || (column=table->get_column_schema(task.column_id))==nullptr) { ret=OB_SCHEMA_EAGAIN; }
    if (OB_FAIL(ret)) { return ret; }
    if (spec.result_type_==share::AI_COLUMN_RESULT_INTEGER) {
      const char *begin=task.result.ptr(), *end=begin+task.result.length();
      auto space=[](char c) { return c==' ' || c=='\t' || c=='\r' || c=='\n'; };
      while (begin<end && space(*begin)) { ++begin; }
      while (begin<end && space(end[-1])) { --end; }
      if (begin<end && *begin=='+') { ++begin; }
      int bits=64;
      switch (column->get_data_type()) {
        case ObTinyIntType: case ObUTinyIntType: bits=8; break;
        case ObSmallIntType: case ObUSmallIntType: bits=16; break;
        case ObMediumIntType: case ObUMediumIntType: bits=24; break;
        case ObInt32Type: case ObUInt32Type: bits=32; break;
        default: break;
      }
      if (ob_is_unsigned_type(column->get_data_type())) {
        uint64_t number=0;
        auto parsed=std::from_chars(begin,end,number);
        const uint64_t maximum=bits==64 ? UINT64_MAX : (uint64_t(1)<<bits)-1;
        if (parsed.ec!=std::errc() || parsed.ptr!=end || number>maximum) { ret=OB_INVALID_DATA; }
      } else {
        int64_t number=0;
        auto parsed=std::from_chars(begin,end,number);
        const int64_t minimum=bits==64 ? INT64_MIN : -(int64_t(1)<<(bits-1));
        const int64_t maximum=bits==64 ? INT64_MAX : (int64_t(1)<<(bits-1))-1;
        if (parsed.ec!=std::errc() || parsed.ptr!=end || number<minimum || number>maximum) { ret=OB_INVALID_DATA; }
      }
    } else if (spec.result_type_==share::AI_COLUMN_RESULT_STRING) {
      ObString converted;
      if (OB_FAIL(ObCharset::charset_convert(alloc,task.result,CS_TYPE_UTF8MB4_BIN,column->get_collation_type(),converted))) {}
      else if (column->get_data_length()>0 && ObCharset::strlen_char(column->get_collation_type(),converted.ptr(),converted.length())
               > static_cast<uint64_t>(column->get_data_length())) { ret=OB_INVALID_DATA; }
    } else if (spec.result_type_==share::AI_COLUMN_RESULT_VECTOR) {
      const auto &types=column->get_extended_type_info();
      int64_t dimension=0;
      if (types.empty()) { return OB_SCHEMA_ERROR; }
      const ObString &type=types.at(0);
      if (type.length()<9 || type.ptr()[type.length()-1]!=')'
          || OB_SUCCESS!=share::parse_ai_spec_integer(ObString(type.length()-8,type.ptr()+7),dimension)
          || dimension<=0) { return OB_SCHEMA_ERROR; }
      ObSqlString validate;
      bool valid=false;
      validate.append("SELECT JSON_TYPE(CONVERT("); share::ai_column_sql_literal(validate,task.result);
      validate.append(" USING utf8mb4))='ARRAY' AND JSON_LENGTH(CONVERT("); share::ai_column_sql_literal(validate,task.result);
      validate.append_fmt(" USING utf8mb4))=%ld value",dimension);
      if (OB_FAIL(scalar_bool(client,validate,valid))) {}
      else if (!valid) { ret=OB_INVALID_DATA; }
    }
    return ret;
  }
  static int run_group()
  {
    int ret = OB_SUCCESS;
    if (GCTX.sql_proxy_ == nullptr) { return OB_NOT_INIT; }
    auto &client = *GCTX.sql_proxy_;
    common::ObArenaAllocator alloc("AiColumnWorker");
    common::ObSqlString pick;
    common::ObString request;
    // A request UUID identifies exactly one row change. A live lease excludes
    // the whole group; retry delay is committed and visible to SQL readers.
    if (OB_FAIL(pick.append("SELECT request_id value FROM oceanbase.__all_ai_column_task GROUP BY request_id "
        "HAVING MAX(owner IS NOT NULL AND lease_until>NOW(6))=0 AND MAX(state=3 AND eligible_ts>NOW(6))=0 LIMIT 1"))) {}
    else if (OB_FAIL(one_string(client,pick,alloc,request))) { return ret; }
    common::ObSqlString filter, table, sql;
    common::ObString owner;
    char uuid[37] = {};
    if (OB_FAIL(ret)) { return ret; }
    else if (OB_FAIL(sql::ObExprUuid::gen_server_uuid(uuid,sql::UuidCommon::LENGTH_UUID))) { return ret; }
    else if (OB_FAIL(ob_write_string(alloc,common::ObString::make_string(uuid),owner))) { return ret; }
    else if (OB_FAIL(filter.append("request_id="))) { return ret; }
    else if (OB_FAIL(share::ai_column_sql_literal(filter,request))) { return ret; }
    common::ObMySQLTransaction tx;
    common::ObSEArray<Task,4> tasks;
    bool leased = false;
    int64_t table_id = 0;
    {
      common::ObMySQLProxy::MySQLResult res;
      sql.append("SELECT table_id FROM oceanbase.__all_ai_column_task WHERE "); sql.append(filter.string()); sql.append(" LIMIT 1");
      if (OB_FAIL(client.read(res,sql.ptr()))) { return ret; }
      if (OB_ISNULL(res.get_result())) { return OB_ERR_UNEXPECTED; }
      if (OB_FAIL(res.get_result()->next())) { return ret; }
      if (OB_FAIL(res.get_result()->get_int("table_id",table_id))) { return ret; }
    }
    if (OB_FAIL(tx.start(&client))) { return ret; }
    if (OB_FAIL(load(tx,filter,alloc,tasks,leased))) {}
    else if (leased || tasks.empty()) { ret = OB_EAGAIN; }
    else {
      sql.reset(); sql.append("UPDATE oceanbase.__all_ai_column_task SET owner=");
      share::ai_column_sql_literal(sql,owner);
      sql.append(",lease_until=DATE_ADD(NOW(6),INTERVAL 300 SECOND),state=IF(state<4,2,state) WHERE "); sql.append(filter.string());
      ret = write(tx,sql);
    }
    int end_ret = tx.end(OB_SUCC(ret));
    if (OB_SUCC(ret)) { ret = end_ret; }
    if (OB_FAIL(ret)) { return ret; }
    common::ObSqlString owned;
    owned.append(filter.string()); owned.append(" AND owner="); share::ai_column_sql_literal(owned,owner);
    owned.append(" AND lease_until>NOW(6)");
    struct LeaseGuard {
      common::ObISQLClient &client_;
      const common::ObSqlString &owned_;
      ~LeaseGuard() {
        common::ObSqlString release;
        if (OB_SUCCESS==release.append("UPDATE oceanbase.__all_ai_column_task SET owner=NULL,lease_until=NOW(6) WHERE ")
            && OB_SUCCESS==release.append(owned_.string())) {
          const int ret=write(client_,release);
          if (ret!=OB_SUCCESS) { LOG_WARN("AI column lease release failed", K(ret)); }
        }
      }
    } lease_guard{client,owned};
    ret = build_table(client,table_id,alloc,table);
    if (ret == OB_ITER_END) {
      sql.reset(); sql.append("DELETE FROM oceanbase.__all_ai_column_task WHERE "); sql.append(owned.string()); return write(client,sql);
    }
    if (OB_FAIL(ret)) { return ret; }
    bool retry = false;
    for (int64_t i=0; OB_SUCC(ret) && i<tasks.count(); ++i) {
      auto &task = tasks.at(i);
      if (task.state >= 4) { continue; }
      share::ObAiColumnSpec spec;
      if (OB_FAIL(share::deserialize_ai_column_spec(task.spec,alloc,spec))) { break; }
      // Renew the whole group's lease between external calls. A deleted or
      // superseded group must not dispatch the next request from this snapshot.
      sql.reset();
      // Internal SQL reports changed rows. Two renewals can observe the same
      // NOW(6), so an unchanged deadline must not look like lost ownership.
      // Advance by at least one microsecond while retaining the owner/expiry
      // predicate: zero changed rows then really means the lease is gone.
      sql.append("UPDATE oceanbase.__all_ai_column_task SET lease_until="
                 "GREATEST(DATE_ADD(NOW(6),INTERVAL 300 SECOND),"
                 "DATE_ADD(lease_until,INTERVAL 1 MICROSECOND)) WHERE ");
      sql.append(owned.string());
      int64_t renewed_rows=0;
      if (OB_FAIL(client.write(sql.ptr(),renewed_rows))) { break; }
      if (renewed_rows==0) { return OB_EAGAIN; }
      int result_ret = calculate(client,table,request,task,spec,alloc,task.result);
      if (result_ret==OB_SUCCESS) { result_ret=validate_value(client,table_id,task,spec,alloc); }
      if (result_ret == OB_SUCCESS) { task.state = 4; }
      else if (task.retries < spec.max_retries_) { task.state = 3; ++task.retries; retry = true; }
      else { task.state = 5; task.result.reset(); }
      sql.reset(); sql.append_fmt("UPDATE oceanbase.__all_ai_column_task SET state=%ld,retry_count=%ld,result_value=",task.state,task.retries);
      share::ai_column_sql_literal(sql,task.result);
      sql.append(",eligible_ts=DATE_ADD(NOW(6),INTERVAL 1 SECOND) WHERE "); sql.append(owned.string()); sql.append_fmt(" AND column_id=%ld",task.column_id);
      ret = write(client,sql);
    }
    if (OB_FAIL(ret)) { return ret; }
    if (retry) {
      sql.reset(); sql.append("UPDATE oceanbase.__all_ai_column_task SET owner=NULL,lease_until=NOW(6) WHERE "); sql.append(owned.string()); return write(client,sql);
    }
    // Lock the group, then update the business row once and remove its tasks
    // in the same transaction. Every result is guarded by its request UUID.
    common::ObMySQLTransaction publish;
    common::ObSEArray<Task,4> locked;
    if (OB_FAIL(publish.start(&client))) { return ret; }
    if (OB_FAIL(load(publish,owned,alloc,locked,leased))) {}
    else if (locked.count()!=tasks.count()) { ret = OB_EAGAIN; }
    else {
      common::ObSqlString update, guard;
      update.append("UPDATE "); update.append(table.string()); update.append(" SET ");
      guard.append(tasks.at(0).predicate);
      for (int64_t i=0; OB_SUCC(ret) && i<tasks.count(); ++i) {
        share::ObAiColumnSpec spec;
        auto &task = tasks.at(i);
        if (OB_FAIL(share::deserialize_ai_column_spec(task.spec,alloc,spec))) { break; }
        if (i>0) { update.append(","); }
        share::ai_column_quote_identifier(update,spec.result_column_name_); update.append("=");
        if (task.state==4) {
          update.append("CONVERT("); share::ai_column_sql_literal(update,task.result); update.append(" USING utf8mb4)");
        } else { update.append("NULL"); }
        common::ObString state_name,request_name;
        share::build_ai_hidden_column_name(alloc,share::AI_COLUMN_STATE_PREFIX,spec.result_column_name_,state_name);
        share::build_ai_hidden_column_name(alloc,share::AI_COLUMN_REQUEST_PREFIX,spec.result_column_name_,request_name);
        update.append(","); share::ai_column_quote_identifier(update,state_name); update.append_fmt("=%ld",task.state==4?2L:3L);
        guard.append(" AND "); share::ai_column_quote_identifier(guard,request_name); guard.append("="); share::ai_column_sql_literal(guard,request);
        guard.append_fmt(" AND EXISTS (SELECT 1 FROM oceanbase.__all_column c JOIN oceanbase.__all_ai_column a ON a.table_id=c.table_id AND a.result_spec_column_id=c.column_id WHERE a.table_id=%ld AND a.column_id=%ld AND c.comment=",table_id,task.column_id);
        share::ai_column_sql_literal(guard,task.spec); guard.append(")");
      }
      if (OB_SUCC(ret)) {
        update.append(" WHERE "); update.append(guard.string());
        ret = write(publish,update);
        if (ret==OB_ERR_CHECK_CONSTRAINT_VIOLATED || ret==OB_ERR_DATA_TOO_LONG
            || ret==OB_DATA_OUT_OF_RANGE || ret==OB_ERR_INVALID_JSON_TEXT) {
          // A schema constraint can reject an otherwise well-typed answer.
          // Publish a terminal failure rather than retrying the cached answer
          // indefinitely. The failed UPDATE has statement-level rollback.
          publish.reset_last_error();
          update.reset(); update.append("UPDATE "); update.append(table.string()); update.append(" SET ");
          for (int64_t i=0; i<tasks.count(); ++i) {
            share::ObAiColumnSpec failed_spec;
            common::ObString state_name;
            if (OB_SUCCESS!=share::deserialize_ai_column_spec(tasks.at(i).spec,alloc,failed_spec)) { break; }
            if (i>0) { update.append(","); }
            share::ai_column_quote_identifier(update,failed_spec.result_column_name_); update.append("=NULL,");
            share::build_ai_hidden_column_name(alloc,share::AI_COLUMN_STATE_PREFIX,failed_spec.result_column_name_,state_name);
            share::ai_column_quote_identifier(update,state_name); update.append("=3");
          }
          update.append(" WHERE "); update.append(guard.string());
          ret=write(publish,update);
        }
      }
      if (OB_SUCC(ret)) {
        sql.reset(); sql.append("DELETE FROM oceanbase.__all_ai_column_task WHERE "); sql.append(owned.string()); ret = write(publish,sql);
      }
    }
    end_ret=publish.end(OB_SUCC(ret));
    return OB_SUCC(ret)?end_ret:ret;
  }
public:
  void run1() override
  {
    while (!has_set_stop()) {
      // Bootstrap and system-package loading own startup resources. Do not
      // contend with the first user CALL or write into a read-only runtime.
      if (!share::server_is_write_enabled()
          || (config::_enable_async_load_sys_package() && !GCTX.sys_package_ready_)) {
        ob_usleep(100*1000);
        continue;
      }
      if (recovery_state_.load()!=2) {
        int expected=0;
        if (recovery_state_.compare_exchange_strong(expected,1)) {
          int recover_ret=OB_NOT_INIT;
          if (GCTX.sql_proxy_!=nullptr) {
            common::ObSqlString recover;
            recover.append("UPDATE oceanbase.__all_ai_column_task SET owner=NULL,lease_until=NOW(6),"
                           "state=IF(state=2,1,state) WHERE owner IS NOT NULL");
            recover_ret=write(*GCTX.sql_proxy_,recover);
          }
          // The pool starts before full schema loading. A temporarily absent
          // task schema must not skip recovery of leases persisted on disk.
          recovery_state_.store(recover_ret==OB_SUCCESS ? 2 : 0);
        }
        ob_usleep(100*1000);
        continue;
      }
      const int ret = run_group();
      if (ret != OB_SUCCESS && ret != OB_ITER_END && ret != OB_EAGAIN
          && ret != OB_TABLE_NOT_EXIST && REACH_TIME_INTERVAL(10*1000*1000)) {
        LOG_WARN("AI column worker iteration failed", K(ret));
      }
      ob_usleep(100*1000);
    }
  }
};
} }
