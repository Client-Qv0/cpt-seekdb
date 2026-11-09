"""Create a separate diagnostic source tree; never patch production files."""
from pathlib import Path
import shutil

root = Path('/mnt/e/MiniVectorDB/work')
dest = Path('/mnt/e/MiniVectorDB/profile-source')
dest.mkdir(exist_ok=True)
shutil.copytree(root / 'src', dest / 'src', dirs_exist_ok=True)
shutil.copy2(root / 'CMakeLists.txt', dest)
p = dest / 'src/engine.cpp'
s = p.read_text()
def replace_once(old, new):
    global s
    if s.count(old) != 1:
        raise RuntimeError(f'expected one occurrence: {old!r}')
    s = s.replace(old, new)

replace_once('#include <algorithm>', '''#include <algorithm>
#include <chrono>
#include <iostream>
namespace diagnostic {
using Clock = std::chrono::steady_clock;
struct Totals {
  long long ns[4]{};
  unsigned long long count[4]{};
  ~Totals() {
    const char *names[] = {"parse", "filter", "distance", "heap"};
    for (int i = 0; i < 4; ++i)
      std::cerr << "profile " << names[i] << " calls=" << count[i] << " ns=" << ns[i] << "\\n";
  }
} totals;
struct Timer {
  int index; Clock::time_point start = Clock::now();
  explicit Timer(int i) : index(i) {}
  ~Timer() { totals.ns[index] += std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - start).count(); ++totals.count[index]; }
};
} // namespace diagnostic''')
replace_once('  auto st = parse_sql(sql);', '  Statement st;\n  { diagnostic::Timer timer(0); st = parse_sql(sql); }')
replace_once('bool matches(const std::vector<Cell> &row, const std::vector<Filter> &f) {', 'bool matches(const std::vector<Cell> &row, const std::vector<Filter> &f) {\n  diagnostic::Timer timer(1);')
replace_once('  const auto &a = std::get<std::vector<float>>(row[p.col]);', '  diagnostic::Timer timer(2);\n  const auto &a = std::get<std::vector<float>>(row[p.col]);')
replace_once('      if (nearest.size() < *st.limit)\n        nearest.push(n);', '      diagnostic::Timer timer(3);\n      if (nearest.size() < *st.limit)\n        nearest.push(n);')
p.write_text(s)
print('instrumented source:', p)
