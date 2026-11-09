#ifdef NDEBUG
#undef NDEBUG
#endif
#include "compact_rows.hpp"
#include "storage.hpp"
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <limits>
#include <map>
#include <new>
#include <random>
#include <string>
#include <vector>

// Fault injection is confined to this executable. Production has no hooks.
static long allocation_budget = -1;
void *operator new(std::size_t size) {
  if (allocation_budget == 0)
    throw std::bad_alloc();
  if (allocation_budget > 0)
    --allocation_budget;
  if (void *p = std::malloc(size ? size : 1))
    return p;
  throw std::bad_alloc();
}
void *operator new[](std::size_t size) { return ::operator new(size); }
void operator delete(void *p) noexcept { std::free(p); }
void operator delete[](void *p) noexcept { std::free(p); }
void operator delete(void *p, std::size_t) noexcept { std::free(p); }
void operator delete[](void *p, std::size_t) noexcept { std::free(p); }

using mvdb::compact::Arena;
using mvdb::compact::Ref;
using mvdb::compact::Rows;
using Model = std::map<int64_t, Ref>;
bool equal(Ref a, Ref b) {
  return a.offset == b.offset && a.size == b.size && a.deleted == b.deleted;
}
void check(const Rows &rows, const Model &model) {
  assert(rows.valid());
  assert(rows.size() == model.size());
  auto expected = model.begin();
  for (auto row : rows) {
    assert(expected != model.end());
    assert(row.first == expected->first && equal(row.second, expected->second));
    auto found = rows.find(row.first);
    assert(found != rows.end() && equal(found.ref(), row.second));
    ++expected;
  }
  assert(expected == model.end());
}
int64_t signed_bits(uint64_t bits) {
  int64_t result;
  std::memcpy(&result, &bits, sizeof result);
  return result;
}
void randomized_layers() {
  Arena arena;
  std::array<Rows, 3> layers{Rows(arena), Rows(arena), Rows(arena)};
  std::array<Model, 3> model;
  std::mt19937_64 rng(0x9f27e92);
  const std::array<int64_t, 5> special{INT64_MIN, INT64_MAX, -1, 0, 1};
  for (size_t step = 0; step < 60000; ++step) {
    size_t layer = rng() % layers.size();
    auto &rows = layers[layer];
    auto &expected = model[layer];
    int64_t key = step % 17 == 0  ? special[rng() % special.size()]
                  : step % 7 == 0 ? signed_bits(rng())
                                  : int64_t(rng() % 1401) - 700;
    switch (rng() % 10) {
    case 0:
    case 1: {
      assert(rows.erase(key) == expected.erase(key));
      break;
    }
    case 2: {
      auto found = rows.find(key);
      auto truth = expected.find(key);
      assert((found == rows.end()) == (truth == expected.end()));
      if (found != rows.end())
        assert(equal(found.ref(), truth->second));
      break;
    }
    case 3: {
      size_t destination = rng() % layers.size();
      auto found = rows.find(key);
      if (found != rows.end()) {
        Ref value = found.ref();
        layers[destination].transfer(rows, found);
        if (destination != layer) {
          model[destination][key] = value;
          expected.erase(key);
        }
      }
      break;
    }
    case 4:
      if (step % 101 == 0) {
        Rows copied(rows);
        check(copied, expected);
        Rows moved(std::move(copied));
        assert(copied.empty() && copied.valid());
        check(moved, expected);
        copied = moved;
        check(copied, expected);
        Rows assigned(arena);
        assigned.set(37, Ref{});
        assigned = std::move(copied);
        check(assigned, expected);
        assert(copied.empty());
        assigned = assigned;
        assigned = std::move(assigned);
        check(assigned, expected);
      }
      break;
    default: {
      Ref value{rng(), uint32_t(rng()), bool(rng() & 1)};
      rows.set(key, value);
      expected[key] = value;
      break;
    }
    }
    if (step % 109 == 0)
      for (size_t i = 0; i < layers.size(); ++i)
        check(layers[i], model[i]);
  }
  for (size_t i = 0; i < layers.size(); ++i)
    check(layers[i], model[i]);
}
void deletion_and_transfer_shapes() {
  Arena arena;
  std::mt19937 rng(1027);
  std::vector<int64_t> keys(4096);
  for (int round = 0; round != 6; ++round) {
    for (size_t i = 0; i < keys.size(); ++i)
      keys[i] = int64_t(i) - 2048;
    if (round % 3 == 1)
      std::reverse(keys.begin(), keys.end());
    if (round % 3 == 2)
      std::shuffle(keys.begin(), keys.end(), rng);
    Rows source(arena), destination(arena);
    Model model;
    for (auto key : keys) {
      Ref ref{uint64_t(key), uint32_t(key), bool(key & 1)};
      source.set(key, ref);
      model[key] = ref;
    }
    check(source, model);
    std::shuffle(keys.begin(), keys.end(), rng);
    for (size_t i = 0; i < keys.size(); ++i) {
      auto found = source.find(keys[i]);
      if (round & 1)
        destination.transfer(source, found);
      else
        source.erase(found);
      if (i % 41 == 0)
        assert(source.valid() && destination.valid());
    }
    assert(source.empty());
    if (round & 1)
      check(destination, model);
    for (auto it = destination.begin(); it != destination.end();)
      it = destination.erase(it);
    assert(destination.empty() && destination.valid());
  }
}
void failed_allocation_and_reuse() {
  Arena arena;
  Rows rows(arena);
  Model model;
  for (int i = 0; i < 2048; ++i) {
    Ref ref{uint64_t(i), uint32_t(i), false};
    rows.set(i, ref);
    model[i] = ref;
  }
  const auto capacity = arena.capacity_bytes();
  // Fail both the new block allocation and the block-directory growth.
  for (long available : {0L, 1L}) {
    allocation_budget = available;
    bool failed = false;
    try {
      rows.set(2048, Ref{});
    } catch (const std::bad_alloc &) {
      failed = true;
    }
    allocation_budget = -1;
    assert(failed && arena.live_nodes() == rows.size());
    assert(arena.capacity_bytes() == capacity);
    check(rows, model);
  }
  {
    Rows destination(arena);
    destination.set(-9, Ref{17, 23, true});
    allocation_budget = 0;
    bool failed = false;
    try {
      destination = rows;
    } catch (const std::bad_alloc &) {
      failed = true;
    }
    allocation_budget = -1;
    assert(failed && destination.size() == 1 && destination.valid());
    assert(equal(destination.find(-9).ref(), Ref{17, 23, true}));
    check(rows, model);
  }
  // Copy failure returns any already-copied slots and preserves its source.
  {
    Rows extra(arena);
    for (int i = 0; i < 2048; ++i)
      extra.set(i, Ref{});
    for (int i = 0; i < 1024; ++i)
      extra.erase(i);
    const auto live = arena.live_nodes();
    allocation_budget = 0;
    bool failed = false;
    try {
      Rows copy(rows);
    } catch (const std::bad_alloc &) {
      failed = true;
    }
    allocation_budget = -1;
    assert(failed && arena.live_nodes() == live && extra.valid());
    check(rows, model);
  }
  const auto high_water = arena.capacity_bytes();
  rows.clear();
  assert(arena.live_nodes() == 0);
  // High-water capacity is intentionally retained, not claimed as reclaimed.
  assert(arena.capacity_bytes() == high_water);
  allocation_budget = 0;
  for (int i = 0; i < 4096; ++i)
    rows.set(i, Ref{uint64_t(i), 0, bool(i & 1)});
  Rows transferred(arena);
  while (!rows.empty())
    transferred.transfer(rows, rows.begin());
  assert(transferred.valid());
  // Overwriting an existing destination key also releases its source slot.
  transferred.erase(0);
  rows.set(1, Ref{7, 9, true});
  transferred.transfer(rows, rows.begin());
  assert(rows.empty() && transferred.valid());
  assert(equal(transferred.find(1).ref(), Ref{7, 9, true}));
  allocation_budget = -1;
}

void allocation_free_transfers() {
  Arena arena;
  Rows source(arena), target(arena);
  Model model;
  for (int i = 0; i < 1000; ++i) {
    source.set(i, Ref{uint64_t(i), uint32_t(i), bool(i & 1)});
    target.set(i + 500, Ref{});
    model[i + 500] = Ref{};
  }
  for (auto entry : source)
    model[entry.first] = entry.second;
  allocation_budget = 0;
  while (!source.empty())
    target.transfer(source, source.begin());
  assert(target.valid());
  allocation_budget = -1;
  check(target, model);
  assert(arena.live_nodes() == model.size());
}

void saved_successors_during_transfer() {
  Arena arena;
  std::vector<int64_t> keys{INT64_MIN, INT64_MAX};
  for (int64_t key = -2048; key < 2048; ++key)
    keys.push_back(key);
  std::mt19937 rng(913);
  for (int round = 0; round != 3; ++round) {
    std::shuffle(keys.begin(), keys.end(), rng);
    Rows source(arena), target(arena);
    Model source_model, target_model;
    for (auto key : keys) {
      Ref incoming{uint64_t(key), uint32_t(key), bool(key & 1)};
      source.set(key, incoming);
      source_model[key] = incoming;
      if (round != 0 && (uint64_t(key) & 1) == 0) {
        target.set(key, Ref{42, 17, false});
        target_model[key] = Ref{42, 17, false};
      }
    }
    const auto action = [round](int64_t key) {
      // Include both full draining (overlay) and retained predecessors, which
      // exercise removing a node with two children while its successor is held.
      return round == 2 ? uint64_t(key) % 3 : uint64_t(2);
    };
    for (auto key : keys) {
      const auto op = action(key);
      if (op == 2)
        target_model[key] = source_model.at(key);
      if (op != 0)
        source_model.erase(key);
    }
    const auto high_water = arena.capacity_bytes();
    allocation_budget = 0;
    size_t visited = 0;
    int64_t previous = 0;
    for (auto next = source.begin(); next != source.end();) {
      auto current = next++;
      const auto key = current.key();
      assert(visited == 0 || previous < key);
      previous = key;
      ++visited;
      const auto op = action(key);
      if (op == 1)
        source.erase(current);
      else if (op == 2)
        target.transfer(source, current);
      if (visited % 71 == 0)
        assert(source.valid() && target.valid());
    }
    allocation_budget = -1;
    assert(visited == keys.size() && arena.capacity_bytes() == high_water);
    check(source, source_model);
    check(target, target_model);
    assert(arena.live_nodes() == source.size() + target.size());
  }
  assert(arena.live_nodes() == 0);
}

void stable_iteration_and_snapshot() {
  Arena arena;
  {
    Rows base(arena), pending(arena), current(arena);
    Model original;
    for (int i = 0; i < 3000; ++i) {
      Ref value{uint64_t(i), uint32_t(i + 1), false};
      base.set(i, value);
      current.set(i, value);
      original[i] = value;
    }
    Rows snapshot(current);
    size_t visited = 0;
    // Growth and rotations in other indexes must not invalidate base iterators.
    for (auto it = base.begin(); it != base.end(); ++it) {
      assert(it.key() == int64_t(visited));
      assert(equal(it.ref(), original.at(it.key())));
      current.set(it.key(), Ref{999, 2, true});
      current.set(it.key() + 10000, Ref{});
      pending.set(-it.key() - 1, Ref{});
      ++visited;
    }
    assert(visited == original.size());
    check(base, original);
    check(snapshot, original);
    assert(current.valid() && pending.valid());
  }
  assert(arena.live_nodes() == 0 && arena.capacity_nodes() >= 12000);
}

void storage_commit_without_allocations() {
  char pattern[] = "/tmp/mvdb-compact-seal-XXXXXX";
  char *directory = ::mkdtemp(pattern);
  assert(directory);
  {
    mvdb::Store store(directory);
    store.begin_statement();
    store.set_metadata("t", "old");
    store.set_metadata("u", "other");
    for (int i = 0; i < 4000; ++i)
      store.put(i & 1 ? "t" : "u", i, "old");
    allocation_budget = 0;
    store.finish_statement(); // Includes commit append, fdatasync and overlay.
    allocation_budget = -1;
    store.begin();
    store.begin_statement();
    store.set_metadata("t", "new");
    store.set_metadata("new_table", "schema");
    for (int i = 0; i < 6000; ++i) {
      if (i < 1000)
        store.erase(i & 1 ? "t" : "u", i);
      else
        store.put(i & 1 ? "t" : "new_table", i, "new");
    }
    allocation_budget = 0;
    store.finish_statement(); // Current -> pending, including new tables.
    allocation_budget = -1;
    store.begin_statement();
    store.put("t", 1001, "last");
    store.erase("t", 5001);
    allocation_budget = 0;
    store.finish_statement(); // Existing-key replacements and tombstones.
    store.commit(); // Pending -> committed after durable commit, no allocation.
    allocation_budget = -1;
    assert(!store.get("t", 1));
    assert(store.get("t", 1001) == "last");
    assert(!store.get("t", 5001));
    assert(store.get("new_table", 4000) == "new");
    store.begin();
    store.begin_statement();
    store.put("t", 1001, "rolled_back");
    store.finish_statement();
    allocation_budget = 0;
    store.rollback();
    allocation_budget = -1;
    assert(store.get("t", 1001) == "last");
  }
  {
    mvdb::Store recovered(directory);
    assert(recovered.metadata("t") == "new");
    assert(recovered.get("t", 1001) == "last");
    assert(!recovered.get("t", 5001));
    assert(recovered.get("new_table", 4000) == "new");
    recovered.checkpoint();
  }
  {
    mvdb::Store recovered(directory);
    assert(recovered.get("t", 1001) == "last");
    assert(!recovered.get("t", 5001));
  }
  std::filesystem::remove_all(directory);
}

int main() {
  randomized_layers();
  deletion_and_transfer_shapes();
  failed_allocation_and_reuse();
  allocation_free_transfers();
  saved_successors_during_transfer();
  stable_iteration_and_snapshot();
  storage_commit_without_allocations();
  std::cout
      << "compact_rows: 7 suites passed; allocation faults, no-allocation "
         "seal, high-water retention and slot reuse checked\n";
}
