import pathlib,shutil,hashlib,json,subprocess,os
R=pathlib.Path(__file__).resolve().parent
T=pathlib.Path('/var/tmp/minivectordb-c3-20261111')
S=T/'diagnostic-source';assert not S.exists()
shutil.copytree(T/'baseline-source',S)
header='''#pragma once
#include <chrono>
#include <cstdint>
#include <iostream>
#include <vector>
namespace c3diag {
inline uint64_t now() { return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
struct Record { uint64_t sequence=0, total=0, get=0, unpack=0, project=0, construct=0; bool hot=false; };
inline Record current;
inline std::vector<Record> records;
inline void begin() { auto seq=current.sequence+1; current=Record{};current.sequence=seq; }
inline void finish() { if (current.total) records.push_back(current); }
inline void emit() {
 for (const auto &r:records) std::cerr << "C3DIAG {\\\"sequence\\\":" << r.sequence << ",\\\"hot\\\":" << (r.hot?"true":"false") << ",\\\"winner_ns\\\":" << r.total << ",\\\"get_ns\\\":" << r.get << ",\\\"unpack_ns\\\":" << r.unpack << ",\\\"project_ns\\\":" << r.project << ",\\\"construct_ns\\\":" << r.construct << "}\\n";
}
}
'''
# Correct generated C++ quotes (Python triple-quoted layer).
(S/'src/c3diag.hpp').write_text(header)
engine=(S/'src/engine.cpp').read_text()
engine=engine.replace('#include "engine.hpp"','#include "engine.hpp"\n#include "c3diag.hpp"',1)
old='''      if (cache_->exact_view) {
        const auto &view = *cache_->exact_view;'''
assert engine.count(old)==1
engine=engine.replace(old,old.replace('        const auto','        c3diag::current.hot = true;\n        const auto'))
old='''    for (const auto &n : winners) {
      auto data = store_.get(st.table, n.key);
      if (!data)
        throw Error("CORRUPTION", "missing visible search result");
      auto row = unpack_row(*data, schema);
      std::vector<Cell> output;
      for (auto &p : ps)
        output.push_back(project(p, row));
      result.rows.push_back(std::move(output));
    }'''
assert engine.count(old)==1
new='''    const auto diagnostic_winners_start = c3diag::now();
    for (const auto &n : winners) {
      auto before = c3diag::now();
      auto data = store_.get(st.table, n.key);
      c3diag::current.get += c3diag::now()-before;
      if (!data)
        throw Error("CORRUPTION", "missing visible search result");
      before = c3diag::now();
      auto row = unpack_row(*data, schema);
      c3diag::current.unpack += c3diag::now()-before;
      before = c3diag::now();
      std::vector<Cell> output;
      c3diag::current.construct += c3diag::now()-before;
      for (auto &p : ps) {
        before = c3diag::now();
        auto value = project(p,row);
        c3diag::current.project += c3diag::now()-before;
        before = c3diag::now();
        output.push_back(std::move(value));
        c3diag::current.construct += c3diag::now()-before;
      }
      before = c3diag::now();
      result.rows.push_back(std::move(output));
      c3diag::current.construct += c3diag::now()-before;
    }
    c3diag::current.total += c3diag::now()-diagnostic_winners_start;'''
engine=engine.replace(old,new)
(S/'src/engine.cpp').write_text(engine)
main=(S/'src/main.cpp').read_text().replace('#include "engine.hpp"','#include "engine.hpp"\n#include "c3diag.hpp"',1)
main=main.replace('      mvdb::Request request;','      c3diag::begin();\n      mvdb::Request request;')
main=main.replace('            return 0;','            c3diag::emit();\n            return 0;',1)
main=main.replace("        std::cout << '\\n' << std::flush;","        std::cout << '\\n' << std::flush;\n        c3diag::finish();")
main=main.replace('    engine->prepare_shutdown();','    c3diag::emit();\n    engine->prepare_shutdown();') if False else main
(S/'src/main.cpp').write_text(main)
dest=R/'diagnostic-source';assert not dest.exists();shutil.copytree(S,dest)
manifest=[{'path':str(p.relative_to(S)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in S.rglob('*') if p.is_file()]
(R/'inputs/diagnostic-source-manifest.json').write_text(json.dumps(manifest,indent=2))
env=dict(os.environ,DOCKER_HOST='unix://'+str(T/'docker.sock'))
with (R/'runtime/diagnostic-build.log').open('wb') as log:
 p=subprocess.run(['docker','build','--network','host','-t','minivectordb:c3-instrumented-87c2',str(S)],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1200)
assert p.returncode==0
print('DIAGNOSTIC_BUILT',flush=True)
