#include "crc32_ieee.hpp"
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <random>
#include <vector>
static uint32_t independent(uint32_t c,const unsigned char*p,size_t n) {
 for(size_t i=0;i<n;++i){c^=p[i];for(unsigned j=0;j<8;++j)c=(c>>1)^(0xedb88320u&(0u-(c&1u)));}return c;
}
int main() {
 using mvdb::storage_detail::crc_update;
 if((crc_update(0xffffffffu,"123456789",9)^0xffffffffu)!=0xcbf43926u)return 1;
 std::mt19937 rng(1701123);size_t checks=0;std::vector<unsigned char> data(65536+16);
 for(auto&v:data)v=static_cast<unsigned char>(rng());
 for(size_t offset=0;offset<16;++offset)for(size_t n=0;n<1025;++n){
  const uint32_t initial=rng(),want=independent(initial,data.data()+offset,n);
  if(crc_update(initial,data.data()+offset,n)!=want)return 2;
  const size_t split=n?rng()%(n+1):0;
  if(crc_update(crc_update(initial,data.data()+offset,split),data.data()+offset+split,n-split)!=want)return 3;
  checks+=2;
 }
 for(size_t n:{size_t(4095),size_t(4096),size_t(4097),size_t(65535),size_t(65536)}) {
  if(crc_update(12345,data.data(),n)!=independent(12345,data.data(),n))return 4;++checks;
 }
 if(crc_update(12345,nullptr,0)!=12345)return 5;
 std::cout<<checks<<" IEEE CRC state/alignment/chunk comparisons passed\n";
}
