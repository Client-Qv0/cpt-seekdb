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

#include "sql/engine/expr/ob_expr_tokenize.h"

#include "lib/alloc/alloc_struct.h"
#include "lib/allocator/page_arena.h"
#include "lib/charset/ob_charset.h"
#include "lib/hash_func/murmur_hash.h"
#include "lib/lock/ob_spin_lock.h"
#include "common/json_type/ob_json_base.h"
#include "common/json_type/ob_json_bin.h"
#include "common/json_type/ob_json_tree.h"
#include "lib/ob_errno.h"
#include "lib/oblog/ob_log_module.h"
#include "lib/string/ob_string.h"
#include "lib/utility/ob_macro_utils.h"
#include "object/ob_object.h"
#include "sql/resolver/ddl/ob_fts_index_builder_util.h"
#include "share/ob_json_access_utils.h"
#include "data_plane/fts/ob_fts_parser_helper.h"
#include "data_plane/fts/dict/ob_gen_dic_loader.h"
#include "data_plane/fts/ob_fts_parser_property.h"

#define USING_LOG_PREFIX SQL_ENG
#include "sql/engine/expr/ob_expr_json_func_helper.h" // file not self-contained, there're logs inside.

namespace oceanbase
{
namespace sql
{
namespace
{
// Only successful builtin-name normalization is cached. Each invocation owns
// its copy, including when argument evaluation invokes TOKENIZE recursively.
class ObTokenizeParserNameCache
{
public:
  bool get(const ObString &raw, char *buffer, ObString &name) const
  {
    for (const Slot &slot : slots_) {
      if (slot.raw_len_ > 0 && slot.raw_len_ == raw.length()
          && 0 == MEMCMP(slot.raw_, raw.ptr(), slot.raw_len_)) {
        MEMCPY(buffer, slot.name_, slot.name_len_);
        buffer[slot.name_len_] = '\0';
        name.assign_ptr(buffer, slot.name_len_);
        return true;
      }
    }
    return false;
  }

  void put(const ObString &raw, const ObString &name)
  {
    if (!raw.empty() && raw.length() < storage::OB_FT_PARSER_NAME_LENGTH
        && name.length() < storage::OB_FT_PARSER_NAME_LENGTH) {
      Slot &slot = slots_[next_++ % SLOT_COUNT];
      slot.raw_len_ = raw.length();
      slot.name_len_ = name.length();
      MEMCPY(slot.raw_, raw.ptr(), slot.raw_len_);
      MEMCPY(slot.name_, name.ptr(), slot.name_len_);
    }
  }

private:
  static constexpr uint64_t SLOT_COUNT = 8;
  struct Slot
  {
    int32_t raw_len_ = 0;
    int32_t name_len_ = 0;
    char raw_[storage::OB_FT_PARSER_NAME_LENGTH];
    char name_[storage::OB_FT_PARSER_NAME_LENGTH];
  };
  Slot slots_[SLOT_COUNT];
  uint64_t next_ = 0;
};

int serialize_token_array(const storage::ObFTWordMap &words,
                          ObIAllocator &allocator, ObString &result)
{
  int ret = OB_SUCCESS;
  uint64_t count = 0;
  uint64_t payload_size = 0;
  uint64_t last_size = 0;
  for (auto it = words.begin(); it != words.end(); ++it) {
    const int64_t len = it->first.get_word().get_string().length();
    last_size = 1 + serialization::encoded_length_vi64(len) + len;
    payload_size += last_size;
    ++count;
  }
  // Match ObJsonArray::update_serialize_size, including its conservative
  // offset width. This preserves JSON_STORAGE_SIZE as well as token order.
  const uint64_t count_size = ObJsonVar::get_var_size(ObJsonVar::get_var_type(count));
  const uint64_t estimated_size = OB_JSON_BIN_ARR_HEADER_LEN + count_size
      + sizeof(uint32_t) + (sizeof(uint32_t) + 1) * count + payload_size;
  const uint64_t offset_size = ObJsonVar::get_var_size(
      ObJsonVar::get_var_type(estimated_size - last_size));
  const uint64_t total_size = OB_JSON_BIN_ARR_HEADER_LEN + count_size
      + sizeof(uint32_t) + (offset_size + 1) * count + payload_size;
  uint64_t obj_size = OB_JSON_BIN_ARR_HEADER_LEN + count_size
      + ObJsonVar::get_var_size(ObJsonVar::get_var_type(total_size))
      + (offset_size + 1) * count + payload_size;
  ObJsonBinMeta meta;
  meta.set_type(J_ARRAY_V0, false);
  meta.set_element_count(count);
  meta.set_element_count_var_type(ObJsonVar::get_var_type(count));
  meta.set_is_continuous(true);
  // The generic serializer retries if the actual header needs a wider field.
  // Calculate that width before writing, avoiding an intermediate JSON tree.
  uint64_t real_size = 0;
  do {
    meta.set_obj_size_var_type(ObJsonVar::get_var_type(obj_size));
    meta.set_entry_var_type(meta.obj_size_var_type());
    real_size = OB_JSON_BIN_ARR_HEADER_LEN + count_size
        + ObJsonVar::get_var_size(meta.obj_size_var_type())
        + (meta.entry_var_size() + 1) * count + payload_size;
    if (ObJsonVar::get_var_type(real_size) <= meta.obj_size_var_type()) {
      break;
    }
    obj_size = real_size;
  } while (true);
  meta.set_obj_size(real_size);
  meta.calc_entry_array();
  ObJsonBuffer buffer(&allocator);
  if (OB_UNLIKELY(count > INT32_MAX || real_size > INT32_MAX - sizeof(ObJsonBinDocHeader))) {
    ret = OB_SIZE_OVERFLOW;
  } else if (OB_FAIL(buffer.reserve(real_size + sizeof(ObJsonBinDocHeader)))) {
  } else if (OB_FAIL(ObJsonBin::add_doc_header_v0(buffer))) {
  } else {
    const int64_t start = buffer.length();
    if (OB_FAIL(meta.to_header(buffer))) {
    } else {
      int index = 0;
      for (auto it = words.begin(); OB_SUCC(ret) && it != words.end(); ++it, ++index) {
        const ObString word = it->first.get_word().get_string();
        if (OB_FAIL(ObJsonBinSerializer::set_value_entry(meta, buffer.ptr() + start,
                      index, buffer.length() - start, J_STRING_V0))) {
        } else if (OB_FAIL(ObJsonBinSerializer::serialize_json_string(J_STRING_V0, word, buffer))) {
        }
      }
    }
    if (OB_FAIL(ret)) {
    } else if (OB_FAIL(ObJsonBin::set_doc_header_v0(buffer, buffer.length(), false))) {
    } else {
      buffer.get_result_string(result);
    }
  }
  return ret;
}

// Reforming the parser properties parses, rebuilds and prints a JSON document. Its result only
// depends on the parser name and the properties given to TOKENIZE(), which are the same for most
// of the calls. So the results of the latest calls are kept and reused.
class ObReformedPropsCache final
{
public:
  static ObReformedPropsCache &instance()
  {
    static ObReformedPropsCache cache;
    return cache;
  }

  // Return true and the reformed properties, allocated by the allocator, if they are cached.
  bool get(const ObString &parser_name,
           const ObString &properties,
           ObIAllocator &allocator,
           ObString &reformed)
  {
    bool is_hit = false;
    char buf[MAX_PROPS_LEN];
    int64_t reformed_len = 0;
    if (is_cacheable(parser_name, properties)) {
      const Slot &slot = slots_[slot_idx(parser_name, properties)];
      common::ObSpinLockGuard guard(lock_);
      if (slot.is_same(parser_name, properties)) {
        reformed_len = slot.reformed_len_;
        if (reformed_len > 0) {
          MEMCPY(buf, slot.reformed_, reformed_len);
        }
        is_hit = true;
      }
    }
    if (is_hit) {
      if (0 == reformed_len) {
        reformed.reset();
      } else if (OB_SUCCESS != ob_write_string(allocator, ObString(reformed_len, buf), reformed)) {
        is_hit = false;
      }
    }
    return is_hit;
  }

  void put(const ObString &parser_name, const ObString &properties, const ObString &reformed)
  {
    if (is_cacheable(parser_name, properties) && reformed.length() <= MAX_PROPS_LEN
        && (reformed.empty() || OB_NOT_NULL(reformed.ptr()))) {
      Slot &slot = slots_[slot_idx(parser_name, properties)];
      common::ObSpinLockGuard guard(lock_);
      slot.name_len_ = parser_name.length();
      MEMCPY(slot.name_, parser_name.ptr(), slot.name_len_);
      slot.props_len_ = properties.length();
      if (slot.props_len_ > 0) {
        MEMCPY(slot.props_, properties.ptr(), slot.props_len_);
      }
      slot.reformed_len_ = reformed.length();
      if (slot.reformed_len_ > 0) {
        MEMCPY(slot.reformed_, reformed.ptr(), slot.reformed_len_);
      }
      slot.is_used_ = true;
    }
  }

private:
  static const int64_t SLOT_CNT = 8;
  static const int64_t MAX_PROPS_LEN = 256;

  struct Slot
  {
    Slot() : is_used_(false), name_len_(0), props_len_(0), reformed_len_(0) {}
    bool is_same(const ObString &parser_name, const ObString &properties) const
    {
      return is_used_ && name_len_ == parser_name.length() && props_len_ == properties.length()
             && 0 == MEMCMP(name_, parser_name.ptr(), name_len_)
             && (0 == props_len_ || 0 == MEMCMP(props_, properties.ptr(), props_len_));
    }
    bool is_used_;
    int64_t name_len_;
    int64_t props_len_;
    int64_t reformed_len_;
    char name_[storage::OB_FT_PARSER_NAME_LENGTH];
    char props_[MAX_PROPS_LEN];
    char reformed_[MAX_PROPS_LEN];
  };

  ObReformedPropsCache() = default;

  static bool is_cacheable(const ObString &parser_name, const ObString &properties)
  {
    return !parser_name.empty() && OB_NOT_NULL(parser_name.ptr())
           && parser_name.length() < storage::OB_FT_PARSER_NAME_LENGTH
           && properties.length() <= MAX_PROPS_LEN
           && (properties.empty() || OB_NOT_NULL(properties.ptr()));
  }

  static int64_t slot_idx(const ObString &parser_name, const ObString &properties)
  {
    uint64_t hash_val = murmurhash(parser_name.ptr(), static_cast<int32_t>(parser_name.length()), 0);
    if (!properties.empty()) {
      hash_val = murmurhash(properties.ptr(), static_cast<int32_t>(properties.length()), hash_val);
    }
    return hash_val % SLOT_CNT;
  }

  common::ObSpinLock lock_;
  Slot slots_[SLOT_CNT];
};
// A bounded per-thread cache for the serialized result of TOKENIZE().
//
// TOKENIZE() is a pure function of its arguments and the same text is analyzed
// repeatedly: a document column is re-analyzed for every row of an index build,
// and applications routinely analyze the same literal on every execution of the
// same statement. The cache keeps the serialized JSON result of recent calls,
// keyed by a hash over every input that can change the output.
//
// It is per thread (no synchronization) and bounded in both entry count and
// bytes; when it fills up it is dropped as a whole.
class ObExprTokenizeResultCache
{
public:
  static const int64_t MAX_ENTRIES = 64;
  static const int64_t MAX_BYTES = 256 * 1024;

public:
  ObExprTokenizeResultCache() : buf_(NULL), used_(0)
  {
    MEMSET(entries_, 0, sizeof(entries_));
  }

  static ObExprTokenizeResultCache &instance()
  {
    static thread_local ObExprTokenizeResultCache cache;
    return cache;
  }

  // On a hit the value is copied into @param allocator; cached bytes are never
  // handed out directly because they can be evicted by a later insertion.
  int get(const uint64_t key, common::ObIAllocator &allocator, common::ObString &value)
  {
    int ret = OB_ENTRY_NOT_EXIST;
    for (int64_t i = 0; i < MAX_ENTRIES && OB_ENTRY_NOT_EXIST == ret; ++i) {
      const Entry &entry = entries_[i];
      if (0 != entry.len_ && entry.key_ == key) {
        char *buf = static_cast<char *>(allocator.alloc(entry.len_));
        if (OB_ISNULL(buf)) {
          ret = OB_ALLOCATE_MEMORY_FAILED;
        } else {
          MEMCPY(buf, buf_ + entry.offset_, entry.len_);
          value.assign_ptr(buf, static_cast<common::ObString::obstr_size_t>(entry.len_));
          ret = OB_SUCCESS;
        }
      }
    }
    return ret;
  }

  // Best effort: a failure to cache must never fail the statement.
  int put(const uint64_t key, const common::ObString &value)
  {
    int ret = OB_SUCCESS;
    if (value.empty() || value.length() > MAX_BYTES) {
      // not worth caching
    } else if (OB_ISNULL(buf_)
               && OB_ISNULL(buf_ = static_cast<char *>(
                                 ob_malloc(MAX_BYTES, common::ObMemAttr("FTSTokCache"))))) {
      ret = OB_ALLOCATE_MEMORY_FAILED;
    } else {
      Entry *slot = NULL;
      if (used_ + value.length() > MAX_BYTES) {
        reset();
      }
      for (int64_t i = 0; i < MAX_ENTRIES && NULL == slot; ++i) {
        if (0 == entries_[i].len_ || entries_[i].key_ == key) {
          slot = &entries_[i];
        }
      }
      if (NULL != slot) {
        MEMCPY(buf_ + used_, value.ptr(), value.length());
        slot->key_ = key;
        slot->offset_ = used_;
        slot->len_ = value.length();
        used_ += value.length();
      }
    }
    return ret;
  }

private:
  struct Entry
  {
    uint64_t key_;
    int64_t offset_;
    int64_t len_;
  };

  void reset()
  {
    MEMSET(entries_, 0, sizeof(entries_));
    used_ = 0;
  }

private:
  Entry entries_[MAX_ENTRIES];
  char *buf_;
  int64_t used_;
};
} // end anonymous namespace

ObExprTokenize::ObExprTokenize(common::ObIAllocator &alloc)
    : ObStringExprOperator(alloc,
                           T_FUN_TOKENIZE,
                           N_TOKENIZE,
                           MORE_THAN_ZERO,
                           VALID_FOR_GENERATED_COL)
{
}

ObExprTokenize::~ObExprTokenize() {}

int ObExprTokenize::eval_tokenize(const ObExpr &expr, ObEvalCtx &ctx, ObDatum &expr_datum)
{
  int ret = OB_SUCCESS;

  ObEvalCtx::TempAllocGuard tmp_alloc_g(ctx);
  common::ObArenaAllocator &temp_allocator = tmp_alloc_g.get_allocator();

  ObIJsonBase *json_result = nullptr;
  ObString binary_result;
  TokenizeParam param(temp_allocator);

  // check param num, which is checked in ObExprOperator::calc_resultType.
  if (OB_UNLIKELY(expr.arg_cnt_ < 1 || expr.arg_cnt_ > 3)) {
    ret = OB_INVALID_ARGUMENT;
  } else if (OB_FAIL(parse_param(expr, ctx, temp_allocator, param))) {
  } else {
    // The key covers every input that can change the output, and the session, so
    // that a result can never be handed to a statement that could not have
    // produced it. Only the serialized default form is cached.
    uint64_t cache_key = 0;
    cache_key = common::murmurhash(param.fulltext_.ptr(), param.fulltext_.length(), cache_key);
    cache_key = common::murmurhash(param.parser_name_.ptr(), param.parser_name_.length(), cache_key);
    cache_key = common::murmurhash(param.properties_.ptr(), param.properties_.length(), cache_key);
    const int64_t cache_coll_type = static_cast<int64_t>(param.meta_.get_collation_type());
    cache_key = common::murmurhash(&cache_coll_type, sizeof(cache_coll_type), cache_key);
    const int64_t cache_mode = static_cast<int64_t>(param.output_mode_);
    cache_key = common::murmurhash(&cache_mode, sizeof(cache_mode), cache_key);
    const ObBasicSessionInfo *cache_session = ctx.exec_ctx_.get_my_session();
    const uint64_t cache_scope = reinterpret_cast<uint64_t>(cache_session);
    cache_key = common::murmurhash(&cache_scope, sizeof(cache_scope), cache_key);
    bool cache_hit = false;
    ObString cached_value;
    if (OB_SUCCESS == ObExprTokenizeResultCache::instance().get(cache_key, temp_allocator, cached_value)) {
      cache_hit = true;
      if (OB_FAIL(ObJsonExprHelper::pack_json_str_res(expr, ctx, expr_datum, cached_value))) {
      }
    }
    if (OB_SUCC(ret) && !cache_hit) {
      if (OB_FAIL(tokenize_fulltext(param, param.output_mode_, temp_allocator, json_result, binary_result))) {
      } else if (TokenizeParam::DEFAULT == param.output_mode_) {
        if (OB_FAIL(ObJsonExprHelper::pack_json_str_res(expr, ctx, expr_datum, binary_result))) {
        } else {
          // Best effort: a failure to cache must never fail the statement.
          int cache_ret = ObExprTokenizeResultCache::instance().put(cache_key, binary_result);
          UNUSED(cache_ret);
        }
      } else if (OB_FAIL(ObJsonExprHelper::pack_json_res(expr,
                                                         ctx,
                                                         temp_allocator,
                                                         json_result,
                                                         expr_datum))) {
      }
    }
  }

  return ret;
}

int ObExprTokenize::tokenize_fulltext(const TokenizeParam &param,
                                      TokenizeParam::OUTPUT_MODE mode,
                                      ObIAllocator &allocator,
                                      ObIJsonBase *&result,
                                      ObString &binary_result)
{
  int ret = OB_SUCCESS;
  storage::ObFTParseHelper tokenize_helper;
  const int64_t ft_word_bkt_cnt = MIN(MAX(param.fulltext_.length() / 2, 2), 997);
  int64_t doc_len = 0;
  storage::ObFTWordMap token_map;

  if (TokenizeParam::OUTPUT_MODE::DEFAULT != mode && TokenizeParam::OUTPUT_MODE::ALL != mode) {
    ret = OB_INVALID_ARGUMENT;
  } else if (OB_FAIL(tokenize_helper.init(&allocator, param.parser_name_, param.properties_))) {
  } else if (OB_FAIL(token_map.create(ft_word_bkt_cnt, common::ObMemAttr("FTWordMap")))) {
  } else if (
      (0 != param.fulltext_.length())
      && OB_FAIL(tokenize_helper.segment(
                     param.meta_,
                     param.fulltext_.ptr(),
                     param.fulltext_.length(),
                     doc_len,
                     token_map))) {
  } else {
    switch (param.output_mode_) {
    case TokenizeParam::OUTPUT_MODE::DEFAULT: {
      if (OB_FAIL(serialize_token_array(token_map, allocator, binary_result))) {
      } else {
        // pass
      }
      break;
    }
    case TokenizeParam::OUTPUT_MODE::ALL: {
      if (OB_FAIL(tokenize_helper.make_detail_json(token_map, doc_len, result))) {
      } else {
        // pass
      }
      break;
    }
    default:
      ret = OB_INVALID_ARGUMENT;
    }
  }
  return ret;
}

ObExprTokenize::TokenizeParam::TokenizeParam(ObIAllocator &allocator)
  : allocator_(allocator),
    parser_name_(ObString(OB_DEFAULT_FULLTEXT_PARSER_NAME)),
    meta_(),
    fulltext_(),
    output_mode_(OUTPUT_MODE::DEFAULT)
{
}

int ObExprTokenize::TokenizeParam::parse_json_param(const ObIJsonBase *obj)
{
  int ret = OB_SUCCESS;
  ObString str;
  ObIJsonBase *val;

  if (OB_UNLIKELY(nullptr == obj)) {
    ret = OB_INVALID_ARGUMENT;
  } else if (ObJsonNodeType::J_OBJECT != obj->json_type()) {
    ret = OB_INVALID_ARGUMENT;
  } else if (obj->element_count() == 0) {
    // no data
  } else if (OB_FAIL(obj->get_object_value(0, str, val))) {
  } else if (0 == str.case_compare(CASE_INDICATOR_STR)) {
    if (ObJsonNodeType::J_STRING != val->json_type()) {
      ret = OB_INVALID_ARGUMENT;
    } else if (0 == ObString(val->get_data_length(), val->get_data()).case_compare("UPPER")) {
    } else if (0 == ObString(val->get_data_length(), val->get_data()).case_compare("LOWER")) {
    } else {
      ret = OB_INVALID_ARGUMENT;
    }
    ret = OB_NOT_SUPPORTED;
    LOG_USER_ERROR(OB_NOT_SUPPORTED, "case indentifier");
  } else if (0 == str.case_compare(OUTPUT_MODE_STR)) {
    if (ObJsonNodeType::J_STRING != val->json_type()) {
      ret = OB_INVALID_ARGUMENT;
      LOG_USER_ERROR(OB_INVALID_ARGUMENT, "output mode should be string default or all");
    } else if (0 == ObString(val->get_data_length(), val->get_data()).case_compare("DEFAULT")) {
      output_mode_ = DEFAULT;
    } else if (0 == ObString(val->get_data_length(), val->get_data()).case_compare("ALL")) {
      output_mode_ = ALL;
    } else {
      ret = OB_INVALID_ARGUMENT;
      LOG_USER_ERROR(OB_INVALID_ARGUMENT, "output mode should be string default or all");
    }
  } else if (0 == str.case_compare(STOPWORDS_LIST_STR)) {
    ret = OB_NOT_SUPPORTED;
    LOG_USER_ERROR(OB_NOT_SUPPORTED, "stopwords");
  } else if (0 == str.case_compare(ADDITIONAL_ARGS_STR)) {
    if (ObJsonNodeType::J_ARRAY != val->json_type()) {
      ret = OB_INVALID_ARGUMENT;
      LOG_USER_ERROR(OB_INVALID_ARGUMENT, "parser arguments");
    } else {
      ObString json_str;
      if (OB_FAIL(storage::ObFTParserJsonProps::tokenize_array_to_props_json(allocator_, val, json_str))) {
        ObSqlString message;
        message.append_fmt("format in %s form", ADDITIONAL_ARGS_STR);
        LOG_USER_ERROR(OB_INVALID_ARGUMENT, message.ptr());
      } else {
        properties_ = json_str;
      }
    }
  } else {
    ret = OB_INVALID_ARGUMENT;
    ObSqlString message;
    message.append_fmt("config: %s", str.ptr());
    LOG_USER_ERROR(OB_INVALID_ARGUMENT, message.ptr());
  }
  return ret;
}

int ObExprTokenize::parse_param(const ObExpr &expr,
                                ObEvalCtx &ctx,
                                common::ObArenaAllocator &allocator,
                                TokenizeParam &param)
{
  int ret = OB_SUCCESS;

  // The caller keeps this arena alive through JSON serialization. Reusing it
  // avoids creating a separate arena for the name and parser properties.
  MultimodeAlloctor temp_allocator(allocator);

  if (OB_UNLIKELY(expr.arg_cnt_ < 1 || expr.arg_cnt_ > 3)) {
    ret = OB_INVALID_ARGUMENT;
  } else if (OB_FAIL(parse_fulltext(expr, ctx, param))) {
  } else if (OB_FAIL(parse_parser_name(expr, ctx, param))) {
  } else if (OB_FAIL(parse_parser_properties(expr, ctx, temp_allocator, param))) {
  } else if (OB_FAIL(param.reform_parser_properties(param.properties_))) {
  } else if (OB_FAIL(param.try_load_dictionary_for_ik())) {
  }
  return ret;
}

int ObExprTokenize::construct_ft_parser_inner_name(const ObString &input_str, TokenizeParam &param)
{
  int ret = OB_SUCCESS;
  storage::ObFTParser parser;
  static thread_local ObTokenizeParserNameCache cache;
  char *parser_name_buf = param.parser_name_buf_;
  if (cache.get(input_str, parser_name_buf, param.parser_name_)) {
  } else if (OB_FAIL(parser.init(input_str))) {
  } else if (OB_FAIL(parser.serialize_to_str(parser_name_buf, storage::OB_FT_PARSER_NAME_LENGTH))) {
  } else {
    param.parser_name_ = ObString::make_string(parser_name_buf);
    cache.put(input_str, param.parser_name_);
  }
  return ret;
}

int ObExprTokenize::calc_result_typeN(ObExprResType &type,
                                      ObExprResType *types,
                                      int64_t param_num,
                                      common::ObExprTypeCtx &type_ctx) const
{
  int ret = OB_SUCCESS;

  if (OB_UNLIKELY(param_num < 1 || param_num > 3)) {
    ret = OB_ERR_PARAM_SIZE;
    ObString expr_name(N_TOKENIZE);
    LOG_USER_ERROR(OB_ERR_PARAM_SIZE, expr_name.length(), expr_name.ptr());
  } else {
    // just okay
  }

  ObLength length = ObAccuracy::DDL_DEFAULT_ACCURACY[ObJsonType].get_length();

  if (OB_SUCC(ret)) {
    // set res type
    type.set_json();
    type.set_length(length); // keep consistent with other json expr, maybe calc it later.

    // param type set, skip charset after first param
    for (int64_t i = 1; OB_SUCC(ret) && i < param_num; ++i) {
      if (ob_is_string_type(types[i].get_type())) {
        if (types[i].get_charset_type() != CHARSET_UTF8MB4) {
          types[i].set_calc_collation_type(CS_TYPE_UTF8MB4_BIN);
        }
      }
    }

    // handle param
    if (param_num >= 2) {
      types[1].set_varchar();
    }

    if (param_num >= 3) {
      if (OB_FAIL(ObJsonExprHelper::is_valid_for_json(types, 2, N_TOKENIZE))) {
      }
    }
  }

  return ret;
}

int ObExprTokenize::cg_expr(ObExprCGCtx &op_cg_ctx,
                            const ObRawExpr &raw_expr,
                            ObExpr &rt_expr) const
{
  int ret = OB_SUCCESS;
  CK((rt_expr.arg_cnt_ >= 1 && rt_expr.arg_cnt_ <= 3));
  if (OB_SUCC(ret)) {
    // do register
    rt_expr.eval_func_ = eval_tokenize;
  }
  return ret;
}

int ObExprTokenize::parse_fulltext(const ObExpr &expr, ObEvalCtx &ctx, TokenizeParam &param)
{
  int ret = OB_SUCCESS;

  ObDatum *fulltext_datum;

  if (OB_FAIL(expr.args_[0]->eval(ctx, fulltext_datum))) {
  } else {
    if (fulltext_datum->is_null()) {
      // do nothing, return empty result
      param.fulltext_ = ObString::make_empty_string();
    } else {
      param.fulltext_ = fulltext_datum->get_string();
    }
    param.meta_.set_varchar(); // as we hardcoded in fts_index
    param.meta_.set_collation_type(expr.args_[0]->obj_meta_.get_collation_type());
  }
  return ret;
}

int ObExprTokenize::parse_parser_name(const ObExpr &expr, ObEvalCtx &ctx, TokenizeParam &param)
{
  int ret = OB_SUCCESS;
  ObDatum *parser_datum = nullptr;
  ObString raw_parser_name;

  if (expr.arg_cnt_ < 2) {
    raw_parser_name = ObString::make_string(OB_DEFAULT_FULLTEXT_PARSER_NAME);
  } else if (OB_FAIL(expr.args_[1]->eval(ctx, parser_datum))) {
  } else {
    if (parser_datum->is_null()) {
      raw_parser_name = ObString::make_string(OB_DEFAULT_FULLTEXT_PARSER_NAME);
    } else {
      ObString name = parser_datum->get_string();
      raw_parser_name = name.trim();
    }
  }

  if (OB_FAIL(ret)) {
    // already logged
  } else if (OB_FAIL(construct_ft_parser_inner_name(raw_parser_name, param))) {
  }

  return ret;
}

int ObExprTokenize::parse_parser_properties(const ObExpr &expr,
                                            ObEvalCtx &ctx,
                                            MultimodeAlloctor &mm_alloc,
                                            TokenizeParam &param)
{
  int ret = OB_SUCCESS;
  ObIJsonBase *base = nullptr;

  if (expr.arg_cnt_ < 3) {
    // do nothing
  } else {
    bool is_null = false;
    if (OB_FAIL(ObJsonExprHelper::get_json_doc(expr, ctx, mm_alloc, 2, base, is_null))) {
    } else {
      if (ObJsonNodeType::J_ARRAY != base->json_type()) {
        ret = OB_INVALID_ARGUMENT;
        LOG_USER_ERROR(OB_INVALID_ARGUMENT, "parser args should be in an array.");
      } else {
        for (uint64_t i = 0; OB_SUCC(ret) && i < base->element_count(); ++i) {
          ObIJsonBase *node = nullptr;
          if (OB_FAIL(base->get_array_element(i, node))) {
          } else if (ObJsonNodeType::J_OBJECT != (node->json_type())) {
            ret = OB_INVALID_ARGUMENT;
          } else if (OB_FAIL(param.parse_json_param(node))) {
          }
        } // for
      }
    }
  }

  return ret;
}

int ObExprTokenize::TokenizeParam::reform_parser_properties(const ObString &properties)
{
  int ret = OB_SUCCESS;
  // the properties may be properties_ itself, which is replaced by the reformed one below
  const ObString raw_properties = properties;
  ObString reformed;

  if (ObReformedPropsCache::instance().get(parser_name_, raw_properties, allocator_, reformed)) {
    properties_ = reformed;
  } else {
    storage::ObFTParserJsonProps parser_properties;
    if (OB_FAIL(parser_properties.init())) {
    } else if (OB_FAIL(parser_properties.parse_from_valid_str(raw_properties))) {
      LOG_USER_ERROR(OB_INVALID_ARGUMENT, "parser properties invalid.");
    } else if (OB_FAIL(parser_properties.rebuild_props_for_ddl(parser_name_,
                                                               ObCollationType::CS_TYPE_UTF8MB4_BIN,
                                                               true))) {
    } else if (OB_FAIL(parser_properties.to_format_json(allocator_, properties_))) {
    } else {
      ObReformedPropsCache::instance().put(parser_name_, raw_properties, properties_);
    }
  }

  return ret;
}

int ObExprTokenize::TokenizeParam::try_load_dictionary_for_ik()
{
  int ret = OB_SUCCESS;
  bool need_to_load_dic = false;
  storage::ObDicLoaderHandle dic_loader_handle;
  if (OB_FAIL(share::ObFtsIndexBuilderUtil::check_need_to_load_dic(
          parser_name_, need_to_load_dic))) {
  } else if (need_to_load_dic) {
    if (OB_FAIL(storage::ObGenDicLoader::get_instance().get_dic_loader(
                    ObString::make_string(storage::ObFTSLiteral::PARSER_NAME_IK), // currently only ik, use parser_name_ without version suffix
                    ObCharset::charset_type_by_coll(meta_.get_collation_type()),
                    dic_loader_handle))) {
    } else if (OB_UNLIKELY(!dic_loader_handle.is_valid())) {
      ret = OB_ERR_UNEXPECTED;
    } else if (OB_FAIL(dic_loader_handle.get_loader()->try_load_dictionary_in_trans())) {
    }
  }
  return ret;
}

} // namespace sql
} // namespace oceanbase
