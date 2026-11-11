#pragma once
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
 for (const auto &r:records) std::cerr << "C3DIAG {\"sequence\":" << r.sequence << ",\"hot\":" << (r.hot?"true":"false") << ",\"winner_ns\":" << r.total << ",\"get_ns\":" << r.get << ",\"unpack_ns\":" << r.unpack << ",\"project_ns\":" << r.project << ",\"construct_ns\":" << r.construct << "}\n";
}
}
