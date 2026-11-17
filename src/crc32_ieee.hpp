#pragma once
#include <array>
#include <cstddef>
#include <cstdint>

namespace mvdb::storage_detail {
// Reflected IEEE CRC-32, identical polynomial/state convention to the WAL.
// Do not substitute SSE4.2 CRC32: those instructions use CRC-32C instead.
constexpr auto make_crc_tables() {
  std::array<std::array<uint32_t,256>,8> tables{};
  for(uint32_t i=0;i<256;++i) {
    uint32_t c=i;
    for(unsigned j=0;j<8;++j)c=(c>>1)^(0xedb88320u&(0u-(c&1u)));
    tables[0][i]=c;
  }
  for(size_t n=1;n<8;++n)for(size_t i=0;i<256;++i) {
    const uint32_t c=tables[n-1][i];tables[n][i]=tables[0][c&255]^(c>>8);
  }
  return tables;
}
inline constexpr auto crc_tables=make_crc_tables();
inline uint32_t crc_update(uint32_t crc,const void* data,size_t length) {
  const auto* p=static_cast<const unsigned char*>(data);
  while(length>=8) {
    const uint32_t low=crc^uint32_t(p[0])^(uint32_t(p[1])<<8)^
        (uint32_t(p[2])<<16)^(uint32_t(p[3])<<24);
    crc=crc_tables[7][low&255]^crc_tables[6][(low>>8)&255]^
        crc_tables[5][(low>>16)&255]^crc_tables[4][low>>24]^
        crc_tables[3][p[4]]^crc_tables[2][p[5]]^
        crc_tables[1][p[6]]^crc_tables[0][p[7]];
    p+=8;length-=8;
  }
  while(length--){crc=crc_tables[0][(crc^*p++)&255]^(crc>>8);}
  return crc;
}
}
