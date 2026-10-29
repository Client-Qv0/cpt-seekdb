/*
 * Copyright (c) 2025 OceanBase.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 * http://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
#pragma once

namespace oceanbase { namespace share {
// The task worker executes one local, serial SQL evaluation synchronously on
// its own thread. Its persisted retry budget owns all transport attempts.
inline thread_local bool ai_column_task_execution = false;
class AiColumnExecutionGuard
{
public:
  AiColumnExecutionGuard() : previous_(ai_column_task_execution) { ai_column_task_execution=true; }
  ~AiColumnExecutionGuard() { ai_column_task_execution=previous_; }
  AiColumnExecutionGuard(const AiColumnExecutionGuard &) = delete;
  AiColumnExecutionGuard &operator=(const AiColumnExecutionGuard &) = delete;
private:
  bool previous_;
};
} }
