#include "../../src/oblib/lib/vector/ob_cuvs_search_worker.h"
#include <atomic>
#include <cassert>
#include <stdexcept>
#include <thread>
#include <vector>

using oceanbase::common::obvsag::CuvsSearchWorker;
struct Job { int input; int output = 0; pthread_t worker{}; size_t stack = 0; };
static void *calculate(void *raw)
{
  Job &job = *static_cast<Job *>(raw);
  job.worker = pthread_self();
  pthread_attr_t attr;
  assert(pthread_getattr_np(pthread_self(), &attr) == 0);
  assert(pthread_attr_getstacksize(&attr, &job.stack) == 0);
  pthread_attr_destroy(&attr);
  job.output = job.input * 3;
  return nullptr;
}
static void *fail(void *) { throw std::runtime_error("test failure"); }
int main()
{
  CuvsSearchWorker worker;
  assert(!worker.run(nullptr, nullptr));
  Job first{7};
  assert(worker.run(calculate, &first));
  assert(first.output == 21 && first.stack >= 32UL * 1024 * 1024);
  assert(!worker.run(fail, nullptr));
  std::atomic<int> completed{0};
  std::vector<std::thread> callers;
  for (int caller = 0; caller < 8; ++caller) {
    callers.emplace_back([&, caller] {
      for (int i = 0; i < 100; ++i) {
        Job job{caller * 100 + i};
        assert(worker.run(calculate, &job));
        assert(job.output == job.input * 3);
        assert(pthread_equal(job.worker, first.worker));
        ++completed;
      }
    });
  }
  for (auto &caller : callers) { caller.join(); }
  assert(completed == 800);
}
