/*
 * Copyright (c) 2026 OceanBase.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include <gtest/gtest.h>
#include "sql/engine/expr/ob_expr_ai/ob_ai_func_utils.h"

using namespace oceanbase::common;
using namespace oceanbase;

namespace {

class AIProviderResultTest : public ::testing::Test
{
protected:
  ObArenaAllocator allocator_;

  ObJsonObject *object(const char *json)
  {
    ObJsonObject *result = nullptr;
    ObString text = ObString::make_string(json);
    EXPECT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_object_form_str(allocator_, text, result));
    return result;
  }

  ObJsonNode *array(const char *json)
  {
    ObJsonObject *root = object(json);
    return root == nullptr ? nullptr : root->get_value("items");
  }
};

TEST_F(AIProviderResultTest, restores_embedding_request_order)
{
  auto *response = object(R"({"data":[{"index":1,"embedding":[20,21]},
                                     {"index":0,"embedding":[10,11]}]})");
  ObOpenAIUtils::ObOpenAIEmbed provider;
  ObIJsonBase *result = nullptr;
  ASSERT_EQ(OB_SUCCESS, provider.parse_output(allocator_, response, result));
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::validate_embedding_result(result, 2, 2));
  auto *vectors = static_cast<ObJsonArray *>(result);
  EXPECT_EQ(10, vectors->get_value(0)->get_value(0)->get_int());
  EXPECT_EQ(20, vectors->get_value(1)->get_value(0)->get_int());
}

TEST_F(AIProviderResultTest, rejects_malformed_embedding_envelopes)
{
  const char *cases[] = {
    R"({"data":{}})", R"({"data":[null]})",
    R"({"data":[{"embedding":[1]}]})",
    R"({"data":[{"index":-1,"embedding":[1]}]})",
    R"({"data":[{"index":1,"embedding":[1]}]})",
    R"({"data":[{"index":0.5,"embedding":[1]}]})",
    R"({"data":[{"index":0,"embedding":[1]},{"index":0,"embedding":[2]}]})"
  };
  for (const char *json : cases) {
    SCOPED_TRACE(json);
    ObOpenAIUtils::ObOpenAIEmbed provider;
    ObIJsonBase *result = nullptr;
    EXPECT_EQ(OB_INVALID_DATA, provider.parse_output(allocator_, object(json), result));
    EXPECT_EQ(nullptr, result);
  }
}

TEST_F(AIProviderResultTest, validates_vector_shape_elements_and_dimensions)
{
  const char *cases[] = {
    R"({"items":{}})", R"({"items":[null]})", R"({"items":[1]})",
    R"({"items":[[]]})", R"({"items":[[true]]})", R"({"items":[["1"]]})",
    R"({"items":[[null]]})", R"({"items":[[{}]]})"
  };
  for (const char *json : cases) {
    SCOPED_TRACE(json);
    EXPECT_EQ(OB_INVALID_DATA, ObAIFuncJsonUtils::validate_embedding_result(array(json), 1, 0));
  }
  auto *valid = array(R"({"items":[[1,2.5],[-3,4]]})");
  EXPECT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::validate_embedding_result(valid, 2, 0));
  EXPECT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::validate_embedding_result(valid, 2, 2));
  EXPECT_EQ(OB_INVALID_DATA, ObAIFuncJsonUtils::validate_embedding_result(valid, 1, 0));
  EXPECT_EQ(OB_INVALID_DATA, ObAIFuncJsonUtils::validate_embedding_result(valid, 2, 3));
  EXPECT_EQ(OB_INVALID_DATA, ObAIFuncJsonUtils::validate_embedding_result(
      array(R"({"items":[[1],[2,3]]})"), 2, 0));
}

TEST_F(AIProviderResultTest, sorts_rerank_scores_with_stable_original_index_ties)
{
  auto *input = array(R"({"items":[{"index":2,"relevance_score":0.5},
                                   {"index":1,"relevance_score":1},
                                   {"index":0,"relevance_score":0.5}]})");
  ObJsonArray *result = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::normalize_rerank_result(allocator_, input, 3, result));
  const int64_t expected[] = {1, 0, 2};
  for (int64_t i = 0; i < 3; ++i) {
    EXPECT_EQ(expected[i], static_cast<ObJsonObject *>(result->get_value(i))->get_value("index")->get_int());
  }
}

TEST_F(AIProviderResultTest, rejects_invalid_rerank_indexes_counts_and_scores)
{
  const char *cases[] = {
    R"({"items":[]})", R"({"items":[null]})",
    R"({"items":[{"index":-1,"relevance_score":1}]})",
    R"({"items":[{"index":1,"relevance_score":1}]})",
    R"({"items":[{"index":0,"relevance_score":"1"}]})",
    R"({"items":[{"index":0,"relevance_score":true}]})",
    R"({"items":[{"index":0}]})"
  };
  for (const char *json : cases) {
    SCOPED_TRACE(json);
    ObJsonArray *result = nullptr;
    EXPECT_EQ(OB_INVALID_DATA, ObAIFuncJsonUtils::normalize_rerank_result(allocator_, array(json), 1, result));
    EXPECT_EQ(nullptr, result);
  }
  ObJsonArray *result = nullptr;
  EXPECT_EQ(OB_INVALID_DATA, ObAIFuncJsonUtils::normalize_rerank_result(allocator_,
      array(R"({"items":[{"index":0,"relevance_score":1},{"index":0,"relevance_score":2}]})"), 2, result));
}

TEST_F(AIProviderResultTest, ollama_completion_forces_non_streaming)
{
  ObOllamaUtils::ObOllamaComplete provider;
  ObString model("test-model");
  ObString prompt;
  ObString content("hello");
  ObJsonObject *body = nullptr;
  ASSERT_EQ(OB_SUCCESS, provider.get_body(allocator_, model, prompt, content,
      object(R"({"stream":true,"temperature":0.2})"), body));
  ASSERT_NE(nullptr, body->get_value("stream"));
  EXPECT_FALSE(body->get_value("stream")->get_boolean());
  EXPECT_EQ(ObJsonNodeType::J_STRING, body->get_value("prompt")->json_type());
}

TEST_F(AIProviderResultTest, rejects_non_object_configuration)
{
  const char *cases[] = {"[]", "null", "1", "true", "\"config\""};
  for (const char *json : cases) {
    ObJsonObject *config = nullptr;
    ObString text = ObString::make_string(json);
    EXPECT_EQ(OB_INVALID_ARGUMENT,
              ObAIFuncJsonUtils::get_json_object_form_str(allocator_, text, config));
    EXPECT_EQ(nullptr, config);
  }
}

TEST_F(AIProviderResultTest, renders_repeated_unicode_and_json_prompt_arguments)
{
  ObString text("{0}/{0}/{1}");
  auto *args = static_cast<ObJsonArray *>(array(R"({"items":["你好\n世界",{"a":[1,true]}]})"));
  ObJsonObject *prompt = nullptr;
  ObString rendered;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncPromptObjectUtils::construct_prompt_object(allocator_, text, args, prompt));
  ASSERT_EQ(OB_SUCCESS, ObAIFuncPromptObjectUtils::replace_all_str_args_in_template(allocator_, prompt, rendered));
  EXPECT_EQ(0, rendered.compare("你好\n世界/你好\n世界/{\"a\": [1, true]}"));
}

TEST_F(AIProviderResultTest, rejects_invalid_prompt_shape_and_placeholder_index)
{
  ObString rendered;
  EXPECT_EQ(OB_INVALID_ARGUMENT, ObAIFuncPromptObjectUtils::replace_all_str_args_in_template(
      allocator_, object(R"({"template":1,"args":[]})"), rendered));
  auto *args = static_cast<ObJsonArray *>(array(R"({"items":["value"]})"));
  const char *cases[] = {"{1}", "{99999999999999999999999999999999999}"};
  for (const char *value : cases) {
    ObString text = ObString::make_string(value);
    ObJsonObject *prompt = nullptr;
    ASSERT_EQ(OB_SUCCESS, ObAIFuncPromptObjectUtils::construct_prompt_object(allocator_, text, args, prompt));
    EXPECT_EQ(OB_INVALID_ARGUMENT,
              ObAIFuncPromptObjectUtils::replace_all_str_args_in_template(allocator_, prompt, rendered));
  }
}

} // namespace
