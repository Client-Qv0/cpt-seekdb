#pragma once
// Transient exact-search view. No disk/protocol representation depends on this.
#include "engine.hpp"
#include <cmath>
#include <cstring>
#include <limits>
#include <string_view>
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
#include <immintrin.h>
#endif

namespace mvdb::exact {
constexpr size_t budget = 12 * 1024 * 1024;
inline bool available() {
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
  return __builtin_cpu_supports("avx2");
#else
  return false;
#endif
}
inline size_t add(size_t a,size_t b) {
  return a>budget || b>budget-a ? budget+1 : a+b;
}
inline size_t mul(size_t a,size_t b) {
  return b && a>budget/b ? budget+1 : a*b;
}
struct ScalarColumn {
  Type type;
  std::vector<int64_t> integers;
  std::vector<size_t> offsets;
  std::vector<char> text;
};
struct Plan {
  std::vector<Type> types;
  std::vector<size_t> text_bytes;
  size_t vector_column,dim,count=0;
  Plan(std::vector<Type> t,size_t v,size_t d)
      :types(std::move(t)),text_bytes(types.size()),vector_column(v),dim(d) {}
  void observe(const std::vector<Cell>& row) {
    count=add(count,1);
    for(size_t c=0;c<types.size();++c)
      if(types[c]==Type::Varchar)
        text_bytes[c]=add(text_bytes[c],std::get<std::string>(row[c]).size());
  }
  size_t required_bytes() const {
    // Fixed reserve covers objects, table identity, allocator metadata and the
    // four-lane query scratch. Count all owned capacity again after allocation.
    size_t bytes=4096;
    if(!dim || vector_column>=types.size() || dim>budget || count>budget) return budget+1;
    bytes=add(bytes,mul(types.size(),sizeof(ScalarColumn)+sizeof(Type)+sizeof(size_t)+96));
    bytes=add(bytes,mul(count,sizeof(int64_t)));
    bytes=add(bytes,mul(mul((count+3)/4,dim),4*sizeof(float)));
    for(size_t c=0;c<types.size();++c) {
      if(types[c]==Type::BigInt) bytes=add(bytes,mul(count,sizeof(int64_t)));
      if(types[c]==Type::Varchar) {
        bytes=add(bytes,mul(count+1,sizeof(size_t)));
        bytes=add(bytes,text_bytes[c]);
      }
    }
    return bytes;
  }
  bool fits() const {return required_bytes()<=budget;}
};
struct Compact {
  size_t dim,count,vector_column;
  std::vector<int64_t> keys;
  std::vector<float> vectors;
  std::vector<ScalarColumn> columns;
  explicit Compact(const Plan& p):dim(p.dim),count(p.count),vector_column(p.vector_column) {
    if(!p.fits()) throw Error("RESOURCE","exact cache plan exceeds budget");
    keys.resize(count);
    vectors.resize(((count+3)/4)*dim*4);
    columns.resize(p.types.size());
    for(size_t c=0;c<columns.size();++c) {
      auto& col=columns[c];col.type=p.types[c];
      if(col.type==Type::BigInt) col.integers.resize(count);
      if(col.type==Type::Varchar) {col.offsets.resize(count+1);col.text.resize(p.text_bytes[c]);}
    }
    // Include the live sizing plan until it is destroyed after publication.
    if(allocated_bytes()>budget) throw Error("RESOURCE","exact cache allocation exceeds budget");
  }
  size_t allocated_bytes() const {
    size_t bytes=4096+columns.capacity()*(sizeof(ScalarColumn)+sizeof(Type)+sizeof(size_t)+96);
    bytes+=keys.capacity()*sizeof(int64_t)+vectors.capacity()*sizeof(float);
    for(const auto& c:columns) bytes+=c.integers.capacity()*sizeof(int64_t)+c.offsets.capacity()*sizeof(size_t)+c.text.capacity();
    return bytes;
  }
  size_t index(size_t row,size_t dimension=0) const {
    return (row/4)*dim*4+dimension*4+row%4;
  }
  void fill(size_t i,int64_t key,const std::vector<Cell>& row) {
    if(i>=count) throw Error("CORRUPTION","exact cache row count changed");
    keys[i]=key;
    const auto& v=std::get<std::vector<float>>(row[vector_column]);
    if(v.size()!=dim) throw Error("CORRUPTION","exact cache dimension changed");
    for(size_t d=0;d<dim;++d) vectors[index(i,d)]=v[d];
    for(size_t c=0;c<columns.size();++c) {
      auto& col=columns[c];
      if(col.type==Type::BigInt) col.integers[i]=std::get<int64_t>(row[c]);
      if(col.type==Type::Varchar) {
        const auto& s=std::get<std::string>(row[c]);size_t offset=col.offsets[i];
        if(offset>col.text.size() || s.size()>col.text.size()-offset) throw Error("CORRUPTION","exact cache text size changed");
        if(!s.empty()) std::memcpy(col.text.data()+offset,s.data(),s.size());
        col.offsets[i+1]=offset+s.size();
      }
    }
  }
  int compare_scalar(size_t c,size_t row,const Cell& value) const {
    const auto& col=columns[c];
    if(col.type==Type::BigInt) {auto a=col.integers[row],b=std::get<int64_t>(value);return (a>b)-(a<b);}
    const size_t begin=col.offsets[row],length=col.offsets[row+1]-begin;
    std::string_view a(length?col.text.data()+begin:"",length);
    std::string_view b=std::get<std::string>(value);
    int cmp=a.compare(b);return (cmp>0)-(cmp<0);
  }
  double distance(size_t row,const std::vector<float>& q) const {
    double sum=0;
    for(size_t d=0;d<dim;++d) {double x=double(vectors[index(row,d)])-double(q[d]);sum+=x*x;}
    return std::sqrt(sum);
  }
};
inline void distances4_scalar(const Compact& cache,const size_t* rows,
                              const std::vector<float>& q,double* out) {
  for(size_t lane=0;lane<4;++lane) out[lane]=cache.distance(rows[lane],q);
}
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
// Every lane is one independent record. Never horizontally reduce dimensions;
// no-fma prevents contraction even if a caller builds with FMA support enabled.
__attribute__((target("avx2,no-fma"),noinline))
inline void distances4_avx2(const Compact& cache,const size_t* rows,
                           const std::vector<float>& q,double* out) {
  const bool contiguous=rows[0]%4==0 && rows[1]==rows[0]+1 &&
      rows[2]==rows[0]+2 && rows[3]==rows[0]+3;
  const size_t start=cache.index(rows[0]);
  const __m128i indices=_mm_set_epi32(int(cache.index(rows[3])),
      int(cache.index(rows[2])),int(cache.index(rows[1])),int(start));
  __m256d sum=_mm256_setzero_pd();
  for(size_t d=0;d<cache.dim;++d) {
    __m128 values=contiguous ? _mm_loadu_ps(cache.vectors.data()+start+d*4) :
        _mm_i32gather_ps(cache.vectors.data()+d*4,indices,4);
    __m256d delta=_mm256_sub_pd(_mm256_cvtps_pd(values),
                              _mm256_set1_pd(double(q[d])));
    __m256d square=_mm256_mul_pd(delta,delta);
    sum=_mm256_add_pd(sum,square);
  }
  _mm256_storeu_pd(out,_mm256_sqrt_pd(sum));
}
// Two independent four-record accumulation chains share each query broadcast.
// A record still visits dimensions in exactly the scalar order, without FMA.
__attribute__((target("avx2,no-fma"),noinline))
inline void distances8_avx2(const Compact& cache,const size_t* rows,
                           const std::vector<float>& q,double* out) {
  const bool contiguous0=rows[0]%4==0 && rows[1]==rows[0]+1 &&
      rows[2]==rows[0]+2 && rows[3]==rows[0]+3;
  const bool contiguous1=rows[4]%4==0 && rows[5]==rows[4]+1 &&
      rows[6]==rows[4]+2 && rows[7]==rows[4]+3;
  const size_t start0=cache.index(rows[0]),start1=cache.index(rows[4]);
  const __m128i indices0=_mm_set_epi32(int(cache.index(rows[3])),
      int(cache.index(rows[2])),int(cache.index(rows[1])),int(start0));
  const __m128i indices1=_mm_set_epi32(int(cache.index(rows[7])),
      int(cache.index(rows[6])),int(cache.index(rows[5])),int(start1));
  __m256d sum0=_mm256_setzero_pd(),sum1=_mm256_setzero_pd();
  for(size_t d=0;d<cache.dim;++d) {
    const float* column=cache.vectors.data()+d*4;
    const __m256d query=_mm256_set1_pd(double(q[d]));
    const __m128 values0=contiguous0 ? _mm_loadu_ps(column+start0) :
        _mm_i32gather_ps(column,indices0,4);
    const __m128 values1=contiguous1 ? _mm_loadu_ps(column+start1) :
        _mm_i32gather_ps(column,indices1,4);
    const __m256d delta0=_mm256_sub_pd(_mm256_cvtps_pd(values0),query);
    const __m256d delta1=_mm256_sub_pd(_mm256_cvtps_pd(values1),query);
    const __m256d square0=_mm256_mul_pd(delta0,delta0);
    const __m256d square1=_mm256_mul_pd(delta1,delta1);
    sum0=_mm256_add_pd(sum0,square0);
    sum1=_mm256_add_pd(sum1,square1);
  }
  _mm256_storeu_pd(out,_mm256_sqrt_pd(sum0));
  _mm256_storeu_pd(out+4,_mm256_sqrt_pd(sum1));
}

// Unfiltered scan: row is aligned to four and eight consecutive rows exist.
// The caller has already checked AVX2 once for the whole query.
__attribute__((target("avx2,no-fma"),noinline))
inline void distances8_contiguous_avx2(const Compact& cache,size_t row,
                                      const std::vector<float>& q,double* out) {
  const float* block0=cache.vectors.data()+(row/4)*cache.dim*4;
  const float* block1=block0+cache.dim*4;
  __m256d sum0=_mm256_setzero_pd(),sum1=_mm256_setzero_pd();
  for(size_t d=0;d<cache.dim;++d) {
    const __m256d query=_mm256_set1_pd(double(q[d]));
    const __m256d delta0=_mm256_sub_pd(_mm256_cvtps_pd(_mm_loadu_ps(block0+d*4)),query);
    const __m256d delta1=_mm256_sub_pd(_mm256_cvtps_pd(_mm_loadu_ps(block1+d*4)),query);
    sum0=_mm256_add_pd(sum0,_mm256_mul_pd(delta0,delta0));
    sum1=_mm256_add_pd(sum1,_mm256_mul_pd(delta1,delta1));
  }
  _mm256_storeu_pd(out,_mm256_sqrt_pd(sum0));
  _mm256_storeu_pd(out+4,_mm256_sqrt_pd(sum1));
}

#endif
inline void distances4(const Compact& cache,const size_t* rows,
                       const std::vector<float>& q,double* out) {
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
  if(available()) {distances4_avx2(cache,rows,q,out);return;}
#endif
  distances4_scalar(cache,rows,q,out);
}
inline void distances8(const Compact& cache,const size_t* rows,
                       const std::vector<float>& q,double* out) {
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
  if(available()) {distances8_avx2(cache,rows,q,out);return;}
#endif
  for(size_t lane=0;lane<8;++lane) out[lane]=cache.distance(rows[lane],q);
}
// Precondition: available() has been checked by the query dispatcher.
inline void distances8_contiguous(const Compact& cache,size_t row,
                                 const std::vector<float>& q,double* out) {
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
  distances8_contiguous_avx2(cache,row,q,out);
#else
  for(size_t lane=0;lane<8;++lane) out[lane]=cache.distance(row+lane,q);
#endif
}
} // namespace mvdb::exact
