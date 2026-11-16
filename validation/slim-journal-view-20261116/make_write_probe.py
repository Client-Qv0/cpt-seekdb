"""Apply only to a scratch copy of f9a61047 for write-path attribution."""
from pathlib import Path

def edit(file,pairs):
    p=Path("src")/file
    s=p.read_text()
    for a,b in pairs:
        assert s.count(a)==1,(a,s.count(a))
        s=s.replace(a,b)
    p.write_text(s)

Path("src/write_probe.hpp").write_text("""#pragma once
#include <chrono>
#include <cstdio>
namespace mvdb::write_probe {
using Clock = std::chrono::steady_clock;
enum Stage {Parse, Prepare, Duplicate, Append, CRC, Account, Overlay, Sync, N};
inline const char *const names[]={"sql_parse","prepare","duplicate_lookup","append_including_crc","crc","account_live","overlay","journal_flush_durable"};
inline long long elapsed[N]{}, count[N]{};
struct Timer {
  Stage stage;
  Clock::time_point start = Clock::now();
  explicit Timer(Stage s): stage(s) {}
  ~Timer() {
    elapsed[stage]+=std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-start).count();
    ++count[stage];
  }
};
inline void print() {
  for(int i=0;i<N;++i) std::fprintf(stderr,"WRITE_PROBE %s %lld %lld\\n",names[i],elapsed[i],count[i]);
}
}
""")
edit("engine.cpp",[
('#include "spill.hpp"', '#include "spill.hpp"\n#include "write_probe.hpp"'),
('  auto st = parse_sql(sql);', '''  auto st = [&] {
    write_probe::Timer phase(write_probe::Parse);
    return parse_sql(sql);
  }();'''),
('  store_.close();\n  *cache_ = Cache{};', '  store_.close();\n  *cache_ = Cache{};\n  write_probe::print();'),
('''      if (width > 1)
        WorkerPool::instance().run(width, prepare);
      else
        prepare(0);''', '''      {
        write_probe::Timer phase(write_probe::Prepare);
        if (width > 1)
          WorkerPool::instance().run(width, prepare);
        else
          prepare(0);
      }'''),
('''        if (store_.get(st.table, entry.first))
          throw Error("DUPLICATE_KEY", "duplicate primary key");''','''        {
          write_probe::Timer phase(write_probe::Duplicate);
          if (store_.get(st.table, entry.first))
            throw Error("DUPLICATE_KEY", "duplicate primary key");
        }''')
])
edit("storage.cpp",[
('#include "compact_rows.hpp"', '#include "compact_rows.hpp"\n#include "write_probe.hpp"'),
('  static void overlay(Layer &target, Layer &source, bool remove_deleted) {','  static void overlay(Layer &target, Layer &source, bool remove_deleted) {\n    write_probe::Timer phase(write_probe::Overlay);'),
('  void account_live(const Layer &incoming) {','  void account_live(const Layer &incoming) {\n    write_probe::Timer phase(write_probe::Account);'),
('''    const bool combined_sync = durable && !statement_previously_flushed;
    if (combined_sync)''','''    const bool combined_sync = durable && !statement_previously_flushed;
    write_probe::Timer phase(write_probe::Sync);
    if (combined_sync)'''),
('''  Ref append_staged(uint32_t kind, const std::string &table, int64_t key,
                    const std::string &value) {
    if (table.size() > 1024 * 1024''','''  Ref append_staged(uint32_t kind, const std::string &table, int64_t key,
                    const std::string &value) {
    write_probe::Timer append_time(write_probe::Append);
    if (table.size() > 1024 * 1024'''),
('''    uint32_t crc = crc_update(0xffffffffu, h.data(), h.size());
    crc = crc_update(crc, table.data(), table.size());
    crc = crc_update(crc, value.data(), value.size()) ^ 0xffffffffu;
    set32(h.data() + 24, crc);
    const Ref ref{end''','''    uint32_t crc;
    {
      write_probe::Timer phase(write_probe::CRC);
      crc = crc_update(0xffffffffu, h.data(), h.size());
      crc = crc_update(crc, table.data(), table.size());
      crc = crc_update(crc, value.data(), value.size()) ^ 0xffffffffu;
    }
    set32(h.data() + 24, crc);
    const Ref ref{end''')
])

