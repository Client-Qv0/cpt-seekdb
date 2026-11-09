#pragma once
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <iterator>
#include <limits>
#include <memory>
#include <stdexcept>
#include <utility>
#include <vector>

namespace mvdb::compact {
struct Ref {
  uint64_t offset = 0;
  uint32_t size = 0;
  bool deleted = false;
};

// A Store owns one arena shared by its committed and uncommitted indexes.
// Moving a node between those indexes never allocates after a durable commit.
// Capacity follows the high-water mark, not the live row count. Freed slots are
// reused; blocks are released when the owning Store is destroyed.
class Arena {
  friend class Rows;
  struct Node {
    int64_t key;
    uint64_t offset;
    uint32_t size;
    uint32_t left, right, parent_flags;
  };
  static_assert(sizeof(Node) == 32, "compact row node must occupy 32 bytes");
  static constexpr uint32_t parent_mask = 0x3fffffffu;
  static constexpr uint32_t red_flag = 0x40000000u;
  static constexpr uint32_t deleted_flag = 0x80000000u;
  static constexpr uint32_t block_size = 2048;
  std::vector<std::unique_ptr<Node[]>> blocks_;
  uint32_t used_ = 0, free_ = 0;
  size_t live_ = 0;

  Node &node(uint32_t id) noexcept {
    return blocks_[(id - 1) / block_size][(id - 1) % block_size];
  }
  const Node &node(uint32_t id) const noexcept {
    return blocks_[(id - 1) / block_size][(id - 1) % block_size];
  }
  uint32_t acquire(int64_t key, Ref value) {
    uint32_t id;
    if (free_) {
      id = free_;
      free_ = node(id).left;
    } else {
      if (used_ == parent_mask)
        throw std::length_error("compact row index capacity exceeded");
      if (used_ / block_size == blocks_.size()) {
        // Both allocations happen before used_ changes. A failed allocation
        // therefore leaves all existing indexes and the free list untouched.
        auto block = std::make_unique<Node[]>(block_size);
        blocks_.push_back(std::move(block));
      }
      id = ++used_;
    }
    node(id) = Node{
        key, value.offset, value.size, 0, 0, value.deleted ? deleted_flag : 0};
    ++live_;
    return id;
  }
  void release(uint32_t id) noexcept {
    node(id).left = free_;
    free_ = id;
    --live_;
  }

public:
  Arena() = default;
  Arena(const Arena &) = delete;
  Arena &operator=(const Arena &) = delete;
  size_t live_nodes() const noexcept { return live_; }
  size_t capacity_nodes() const noexcept { return blocks_.size() * block_size; }
  size_t capacity_bytes() const noexcept {
    return capacity_nodes() * sizeof(Node);
  }
};

class Rows {
  using Id = uint32_t;
  Arena *arena_ = nullptr;
  Id root_ = 0;
  size_t size_ = 0;
  Arena::Node &node(Id id) const noexcept { return arena_->node(id); }
  Id parent(Id id) const noexcept {
    return id ? node(id).parent_flags & Arena::parent_mask : 0;
  }
  void parent(Id id, Id value) noexcept {
    if (id)
      node(id).parent_flags =
          (node(id).parent_flags & ~Arena::parent_mask) | value;
  }
  bool red(Id id) const noexcept {
    return id && (node(id).parent_flags & Arena::red_flag);
  }
  void red(Id id, bool value) noexcept {
    if (id) {
      if (value)
        node(id).parent_flags |= Arena::red_flag;
      else
        node(id).parent_flags &= ~Arena::red_flag;
    }
  }
  Id left(Id id) const noexcept { return id ? node(id).left : 0; }
  Id right(Id id) const noexcept { return id ? node(id).right : 0; }
  Id minimum(Id id) const noexcept {
    while (left(id))
      id = left(id);
    return id;
  }
  Id next(Id id) const noexcept {
    if (right(id))
      return minimum(right(id));
    Id p = parent(id);
    while (p && id == right(p)) {
      id = p;
      p = parent(p);
    }
    return p;
  }
  Ref value(Id id) const noexcept {
    const auto &n = node(id);
    return {n.offset, n.size, (n.parent_flags & Arena::deleted_flag) != 0};
  }
  void value(Id id, Ref ref) noexcept {
    auto &n = node(id);
    n.offset = ref.offset;
    n.size = ref.size;
    n.parent_flags = (n.parent_flags & ~Arena::deleted_flag) |
                     (ref.deleted ? Arena::deleted_flag : 0);
  }
  Id find_id(int64_t key) const noexcept {
    Id id = root_;
    while (id && node(id).key != key)
      id = key < node(id).key ? left(id) : right(id);
    return id;
  }
  struct InsertPosition {
    Id existing = 0, parent = 0;
    bool left = false;
  };
  InsertPosition insertion_position(int64_t key) const noexcept {
    InsertPosition result;
    Id id = root_;
    while (id) {
      const auto &n = node(id);
      if (key == n.key) {
        result.existing = id;
        return result;
      }
      result.parent = id;
      result.left = key < n.key;
      id = result.left ? n.left : n.right;
    }
    return result;
  }
  void rotate_left(Id x) noexcept {
    Id y = right(x), p = parent(x);
    node(x).right = left(y);
    parent(left(y), x);
    parent(y, p);
    if (!p)
      root_ = y;
    else if (x == left(p))
      node(p).left = y;
    else
      node(p).right = y;
    node(y).left = x;
    parent(x, y);
  }
  void rotate_right(Id x) noexcept {
    Id y = left(x), p = parent(x);
    node(x).left = right(y);
    parent(right(y), x);
    parent(y, p);
    if (!p)
      root_ = y;
    else if (x == left(p))
      node(p).left = y;
    else
      node(p).right = y;
    node(y).right = x;
    parent(x, y);
  }
  void insert_node(Id id, InsertPosition position) noexcept {
    // The caller searched this tree before allocating or detaching a node.
    // Neither operation changes this tree, so its insertion slot remains valid.
    assert(!position.existing);
    Id p = position.parent;
    assert(p ? !(position.left ? left(p) : right(p)) : !root_);
    node(id).left = node(id).right = 0;
    parent(id, p);
    red(id, true);
    if (!p)
      root_ = id;
    else if (position.left)
      node(p).left = id;
    else
      node(p).right = id;
    ++size_;
    while (red(parent(id))) {
      p = parent(id);
      Id g = parent(p);
      if (p == left(g)) {
        Id uncle = right(g);
        if (red(uncle)) {
          red(p, false);
          red(uncle, false);
          red(g, true);
          id = g;
        } else {
          if (id == right(p)) {
            id = p;
            rotate_left(id);
            p = parent(id);
            g = parent(p);
          }
          red(p, false);
          red(g, true);
          rotate_right(g);
        }
      } else {
        Id uncle = left(g);
        if (red(uncle)) {
          red(p, false);
          red(uncle, false);
          red(g, true);
          id = g;
        } else {
          if (id == left(p)) {
            id = p;
            rotate_right(id);
            p = parent(id);
            g = parent(p);
          }
          red(p, false);
          red(g, true);
          rotate_left(g);
        }
      }
    }
    red(root_, false);
  }
  void transplant(Id old, Id replacement) noexcept {
    Id p = parent(old);
    if (!p)
      root_ = replacement;
    else if (old == left(p))
      node(p).left = replacement;
    else
      node(p).right = replacement;
    parent(replacement, p);
  }
  void erase_fix(Id x, Id p) noexcept {
    // NIL is represented by zero, without a shared mutable sentinel parent.
    while (x != root_ && !red(x)) {
      if (x == left(p)) {
        Id sibling = right(p);
        if (red(sibling)) {
          red(sibling, false);
          red(p, true);
          rotate_left(p);
          sibling = right(p);
        }
        if (!red(left(sibling)) && !red(right(sibling))) {
          red(sibling, true);
          x = p;
          p = parent(x);
        } else {
          if (!red(right(sibling))) {
            red(left(sibling), false);
            red(sibling, true);
            rotate_right(sibling);
            sibling = right(p);
          }
          red(sibling, red(p));
          red(p, false);
          red(right(sibling), false);
          rotate_left(p);
          x = root_;
          p = 0;
        }
      } else {
        Id sibling = left(p);
        if (red(sibling)) {
          red(sibling, false);
          red(p, true);
          rotate_right(p);
          sibling = left(p);
        }
        if (!red(left(sibling)) && !red(right(sibling))) {
          red(sibling, true);
          x = p;
          p = parent(x);
        } else {
          if (!red(left(sibling))) {
            red(right(sibling), false);
            red(sibling, true);
            rotate_left(sibling);
            sibling = left(p);
          }
          red(sibling, red(p));
          red(p, false);
          red(left(sibling), false);
          rotate_right(p);
          x = root_;
          p = 0;
        }
      }
    }
    red(x, false);
  }
  void detach(Id z) noexcept {
    Id y = z, x, xp;
    bool was_red = red(y);
    if (!left(z)) {
      x = right(z);
      xp = parent(z);
      transplant(z, x);
    } else if (!right(z)) {
      x = left(z);
      xp = parent(z);
      transplant(z, x);
    } else {
      y = minimum(right(z));
      was_red = red(y);
      x = right(y);
      if (parent(y) == z) {
        xp = y;
        parent(x, y);
      } else {
        xp = parent(y);
        transplant(y, x);
        node(y).right = right(z);
        parent(right(y), y);
      }
      transplant(z, y);
      node(y).left = left(z);
      parent(left(y), y);
      red(y, red(z));
    }
    --size_;
    if (!was_red)
      erase_fix(x, xp);
  }
  void clear_tree(Id id) noexcept {
    if (!id)
      return;
    clear_tree(left(id));
    clear_tree(right(id));
    arena_->release(id);
  }
  int validate_tree(Id id, Id p, const int64_t *low, const int64_t *high,
                    size_t &count) const noexcept {
    if (!id)
      return 1;
    const auto &n = node(id);
    if (parent(id) != p || (low && n.key <= *low) || (high && n.key >= *high) ||
        (red(id) && (red(left(id)) || red(right(id)))))
      return -1;
    ++count;
    int a = validate_tree(left(id), id, low, &n.key, count);
    int b = validate_tree(right(id), id, &n.key, high, count);
    return a < 0 || b < 0 || a != b ? -1 : a + !red(id);
  }

public:
  struct Entry {
    int64_t first;
    Ref second;
  };
  class Iterator {
    friend class Rows;
    const Rows *owner_ = nullptr;
    Id id_ = 0;
    Iterator(const Rows *owner, Id id) : owner_(owner), id_(id) {}

  public:
    using iterator_category = std::forward_iterator_tag;
    using value_type = Entry;
    using difference_type = std::ptrdiff_t;
    using reference = Entry;
    using pointer = void;
    Iterator() = default;
    Entry operator*() const noexcept { return {key(), ref()}; }
    int64_t key() const noexcept { return owner_->node(id_).key; }
    Ref ref() const noexcept { return owner_->value(id_); }
    Iterator &operator++() noexcept {
      id_ = owner_->next(id_);
      return *this;
    }
    Iterator operator++(int) noexcept {
      auto old = *this;
      ++*this;
      return old;
    }
    bool operator==(Iterator other) const noexcept {
      return owner_ == other.owner_ && id_ == other.id_;
    }
    bool operator!=(Iterator other) const noexcept { return !(*this == other); }
  };
  Rows() = default; // An allocation-free empty view used by scan().
  explicit Rows(Arena &arena) noexcept : arena_(&arena) {}
  ~Rows() { clear(); }
  Rows(const Rows &other) : arena_(other.arena_) {
    try {
      for (auto entry : other)
        set(entry.first, entry.second);
    } catch (...) {
      clear();
      throw;
    }
  }
  Rows(Rows &&other) noexcept
      : arena_(other.arena_), root_(other.root_), size_(other.size_) {
    other.root_ = 0;
    other.size_ = 0;
  }
  Rows &operator=(const Rows &other) {
    if (this != &other) {
      Rows copy(other);
      swap(copy);
    }
    return *this;
  }
  Rows &operator=(Rows &&other) noexcept {
    if (this != &other) {
      clear();
      arena_ = other.arena_;
      root_ = other.root_;
      size_ = other.size_;
      other.root_ = 0;
      other.size_ = 0;
    }
    return *this;
  }
  void swap(Rows &other) noexcept {
    std::swap(arena_, other.arena_);
    std::swap(root_, other.root_);
    std::swap(size_, other.size_);
  }
  bool empty() const noexcept { return !root_; }
  size_t size() const noexcept { return size_; }
  Iterator begin() const noexcept { return Iterator(this, minimum(root_)); }
  Iterator end() const noexcept { return Iterator(this, 0); }
  Iterator find(int64_t key) const noexcept {
    return Iterator(this, find_id(key));
  }
  void set(int64_t key, Ref ref) {
    const auto position = insertion_position(key);
    if (position.existing)
      value(position.existing, ref);
    else {
      if (!arena_)
        throw std::logic_error("cannot write an unbound compact row index");
      insert_node(arena_->acquire(key, ref), position);
    }
  }
  void update(Iterator position, Ref ref) noexcept {
    assert(position.owner_ == this && position.id_);
    value(position.id_, ref);
  }
  Iterator erase(Iterator position) noexcept {
    assert(position.owner_ == this && position.id_);
    Id id = position.id_;
    auto successor = position;
    ++successor;
    detach(id);
    arena_->release(id);
    return successor;
  }
  size_t erase(int64_t key) noexcept {
    auto position = find(key);
    if (position == end())
      return 0;
    erase(position);
    return 1;
  }
  // Preconditions: both indexes use this Store's arena; position belongs to
  // source and is not end(). This is deliberately allocation-free.
  void transfer(Rows &source, Iterator position) noexcept {
    assert(arena_ == source.arena_ && position.owner_ == &source &&
           position.id_);
    if (this == &source)
      return;
    Id id = position.id_;
    const auto destination = insertion_position(source.node(id).key);
    source.detach(id);
    if (destination.existing) {
      value(destination.existing, source.value(id));
      arena_->release(id);
    } else {
      insert_node(id, destination);
    }
  }
  void clear() noexcept {
    clear_tree(root_);
    root_ = 0;
    size_ = 0;
  }
  bool valid() const noexcept {
    size_t count = 0;
    return !red(root_) &&
           validate_tree(root_, 0, nullptr, nullptr, count) > 0 &&
           count == size_;
  }
};
} // namespace mvdb::compact
