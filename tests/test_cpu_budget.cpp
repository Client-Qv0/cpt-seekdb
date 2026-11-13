#include "cpu_budget.hpp"
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
void require(bool ok, const std::string &what) {
  if (!ok) throw std::runtime_error("cpu budget check failed: " + what);
}
void require_near(double got, double want, const std::string &what) {
  if (got < want - 1e-9 || got > want + 1e-9)
    throw std::runtime_error("cpu budget value " + what + ": got " +
                             std::to_string(got) + " want " +
                             std::to_string(want));
}
} // namespace

int main() {
  using namespace mvdb::cpu;
  require_near(parse_cpu_max("200000 100000"), 2.0, "two-cpu quota");
  require_near(parse_cpu_max("50000 100000"), 0.5, "half-cpu quota");
  require_near(parse_cpu_max("1500000 100000"), 15.0, "large quota");
  require_near(parse_cpu_max("max 100000"), 0.0, "unlimited quota");
  require_near(parse_cpu_max(""), 0.0, "empty cpu.max");
  require_near(parse_cpu_max("garbage"), 0.0, "malformed cpu.max");
  require_near(parse_cpu_max("200000\n"), 2.0, "trailing newline");
  require_near(parse_v1_quota(200000, 100000), 2.0, "v1 two cpu");
  require_near(parse_v1_quota(0, 100000), 0.0, "v1 unlimited");
  require_near(parse_v1_quota(-1, 100000), 0.0, "v1 unset");
  require_near(parse_v1_quota(200000, 0), 2.0, "v1 default period");

  require(effective_width(4, 2.0, 64) == 2, "quota below affinity");
  require(effective_width(4, 0.0, 64) == 4, "unknown quota keeps affinity");
  require(effective_width(1, 8.0, 64) == 1, "affinity below quota");
  require(effective_width(16, 0.0, 4) == 4, "cap applies");
  require(effective_width(4, 0.5, 64) == 1, "fractional quota rounds up");
  require(effective_width(4, 2.5, 64) == 3, "ceiling of 2.5 cpus");
  require(effective_width(0, 0.0, 64) == 1, "unknown affinity stays 1");
  require(effective_width(8, 1000.0, 64) == 8, "cap 64 does not trim 8");

  const size_t budget = budget_cpus();
  require(budget >= 1, "budget is at least one CPU");
  require(budget <= affinity_cpus(), "budget never exceeds the affinity mask");
  std::cout << "cpu budget parsing and width selection passed (budget="
            << budget << ", affinity=" << affinity_cpus() << ")\n";
  return 0;
}
