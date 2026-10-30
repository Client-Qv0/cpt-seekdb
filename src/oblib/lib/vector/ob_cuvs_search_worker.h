/* Copyright (c) 2026 OceanBase. Licensed under the Apache License, Version 2.0. */
#ifndef OCEANBASE_LIB_VECTOR_CUVS_SEARCH_WORKER_H_
#define OCEANBASE_LIB_VECTOR_CUVS_SEARCH_WORKER_H_

#include <condition_variable>
#include <mutex>
#include <pthread.h>

namespace oceanbase {
namespace common {
namespace obvsag {

// Keep the large stack required by hipVS without creating a thread (and its
// runtime thread-local state) for every SQL query. This executes each submitted
// job synchronously; it does not retain queries, results, or index graphs.
class CuvsSearchWorker {
public:
  CuvsSearchWorker() = default;
  CuvsSearchWorker(const CuvsSearchWorker &) = delete;
  CuvsSearchWorker &operator=(const CuvsSearchWorker &) = delete;

  ~CuvsSearchWorker()
  {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      stopping_ = true;
      changed_.notify_all();
    }
    if (started_) { pthread_join(thread_, nullptr); }
  }

  bool run(void *(*function)(void *), void *argument)
  {
    if (function == nullptr) { return false; }
    std::unique_lock<std::mutex> lock(mutex_);
    changed_.wait(lock, [this] { return !busy_ || stopping_; });
    if (stopping_) { return false; }
    if (!started_) {
      pthread_attr_t attr;
      if (pthread_attr_init(&attr) != 0) { return false; }
      int rc = pthread_attr_setstacksize(&attr, 32UL * 1024 * 1024);
      if (rc == 0) { rc = pthread_create(&thread_, &attr, entry, this); }
      pthread_attr_destroy(&attr);
      if (rc != 0) { return false; }
      started_ = true;
    }
    busy_ = true;
    done_ = false;
    function_ = function;
    argument_ = argument;
    changed_.notify_all();
    changed_.wait(lock, [this] { return done_; });
    const bool success = success_;
    argument_ = nullptr;
    busy_ = false;
    changed_.notify_all();
    return success;
  }

private:
  static void *entry(void *argument)
  {
    static_cast<CuvsSearchWorker *>(argument)->loop();
    return nullptr;
  }

  void loop()
  {
    std::unique_lock<std::mutex> lock(mutex_);
    while (true) {
      changed_.wait(lock, [this] { return function_ != nullptr || stopping_; });
      if (stopping_) { return; }
      auto function = function_;
      void *argument = argument_;
      lock.unlock();
      bool success = true;
      try { function(argument); } catch (...) { success = false; }
      lock.lock();
      function_ = nullptr;
      success_ = success;
      done_ = true;
      changed_.notify_all();
    }
  }

  std::mutex mutex_;
  std::condition_variable changed_;
  pthread_t thread_{};
  void *(*function_)(void *) = nullptr;
  void *argument_ = nullptr;
  bool started_ = false;
  bool busy_ = false;
  bool done_ = false;
  bool success_ = false;
  bool stopping_ = false;
};

} // namespace obvsag
} // namespace common
} // namespace oceanbase
#endif
