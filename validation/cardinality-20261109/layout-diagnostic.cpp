// Development-only object layout diagnostic; no database or cgroup workload.
// Original diagnostic was compiled from stdin using g++ -std=c++17 on WSL.
#include <cstdint>
#include <iostream>
#include <map>
#include <malloc.h>
#include <cstdlib>
struct Ref { uint64_t offset; uint32_t size; bool deleted; };
struct Entry { int64_t key; Ref value; };
struct Page128 { uint32_t count; uint32_t reserved; Entry rows[128]; };
int main(){
 std::cout << "Ref=" << sizeof(Ref) << " Entry=" << sizeof(Entry)
 << " MapNode=" << sizeof(std::_Rb_tree_node<std::pair<const int64_t,Ref>>)
 << " OffsetOnlyNode=" << sizeof(std::_Rb_tree_node<std::pair<const int64_t,uint64_t>>)
 << " Page128=" << sizeof(Page128) << '\n';
 for(size_t n : {size_t(48),size_t(56),sizeof(Page128)}) {void *p=malloc(n); std::cout<<"requested="<<n<<" usable="<<malloc_usable_size(p)<<'\n'; free(p);}
}
