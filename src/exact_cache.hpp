#pragma once
// Transient exact-search view. No disk/protocol representation depends on this.
#include "engine.hpp"
#include "cpu_budget.hpp"
#include <cmath>
#include <cfenv>
#include <algorithm>
#include <cstdint>
#include <memory>
#include <cstring>
#include <limits>
#include <string_view>
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
#include <immintrin.h>
#endif

namespace mvdb::exact {
// The view budget follows the memory this process may actually use. A fixed
// 12 MiB left every table that needs more (50k rows x 128D is about 33 MiB with
// its screening codes) on the per-row path permanently. The old value stays the
// floor, so a run with no cgroup limit behaves exactly as before.
inline size_t budget() {
  static const size_t value = [] {
    constexpr size_t floor_bytes = 12 * 1024 * 1024;
    constexpr size_t ceiling_bytes = 48 * 1024 * 1024;
    const size_t limit = cpu::memory_limit_bytes();
    if (!limit) return floor_bytes;
    const size_t share = limit / 3;
    if (share < floor_bytes) return floor_bytes;
    return share > ceiling_bytes ? ceiling_bytes : share;
  }();
  return value;
}
inline bool available() {
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
  return __builtin_cpu_supports("avx2");
#else
  return false;
#endif
}
// Scan width: 0 keeps the automatic width derived from the CPU affinity mask.
// Tests set an explicit width to prove every width returns identical rows.
inline size_t &thread_limit() {
  static size_t value = 0;
  return value;
}
inline void set_thread_limit(size_t width) { thread_limit() = width; }
// Queries answered by the scan workers instead of the serial loop.
inline size_t &parallel_runs() {
  static size_t value = 0;
  return value;
}
// The screening bound assumes IEEE binary32/binary64 round-to-nearest with
// gradual underflow. Check once per query, never change the caller's FP mode.
constexpr size_t fp32_screen_max_dim = 8192;
inline bool fp32_screen_available(size_t dim) {
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
  if(!dim || dim>fp32_screen_max_dim || !available()) return false;
  const unsigned control=_mm_getcsr();
  constexpr unsigned rounding_ftz_daz=0x6000u|0x8000u|0x0040u;
  constexpr unsigned exception_masks=0x1f80u;
  return (control&rounding_ftz_daz)==0 &&
         (control&exception_masks)==exception_masks;
#else
  (void)dim;
  return false;
#endif
}
// For D<=8192, a finite FP32 sequential square sum a and the original double
// sum S obey a <= 1.01*S + 2*D*2^-149. With n=D+3, the relative factor is at
// most 1/((1-n*2^-24)*(1-n*2^-53)) < 1.00049; 2*D*2^-149 covers FP32 square
// underflow. A subnormal difference of two FP32 inputs is exactly representable.
// Use nextup(d)^2, not d^2: distinct sums can round to the same sqrt distance.
// Every operation forming the rejection threshold is expanded upward.
inline double fp32_screen_threshold(double worst_distance,size_t dim) {
  const double infinity=std::numeric_limits<double>::infinity();
  if(!dim || dim>fp32_screen_max_dim ||
     !std::isfinite(worst_distance) || worst_distance<0) return infinity;
  const double next=std::nextafter(worst_distance,infinity);
  const double squared_upper=std::nextafter(next*next,infinity);
  const double scaled_upper=std::nextafter(1.01*squared_upper,infinity);
  return std::nextafter(scaled_upper+double(dim)*0x1p-148,infinity);
}
inline bool fp32_screen_reject(float approximate_sum,double threshold) {
  // Overflow/NaN must be refined, never interpreted as a distant record.
  return std::isfinite(approximate_sum) && double(approximate_sum)>threshold;
}
inline size_t add(size_t a,size_t b) {
  return a>budget() || b>budget()-a ? budget()+1 : a+b;
}
inline size_t mul(size_t a,size_t b) {
  return b && a>budget()/b ? budget()+1 : a*b;
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
  // Widest stored text per column. The declared VARCHAR width is only an upper
  // bound on that and is usually far larger, so callers that budget memory per
  // projected row need the width the rows actually carry.
  std::vector<size_t> text_max;
  size_t vector_column,dim,count=0;
  Plan(std::vector<Type> t,size_t v,size_t d)
      :types(std::move(t)),text_bytes(types.size()),text_max(types.size()),
       vector_column(v),dim(d) {}
  void observe(const std::vector<Cell>& row) {
    count=add(count,1);
    for(size_t c=0;c<types.size();++c)
      if(types[c]==Type::Varchar) {
        const size_t width=std::get<std::string>(row[c]).size();
        text_bytes[c]=add(text_bytes[c],width);
        text_max[c]=std::max(text_max[c],width);
      }
  }
  size_t required_bytes() const {
    // Fixed reserve covers objects, table identity, allocator metadata and the
    // four-lane query scratch. Count all owned capacity again after allocation.
    size_t bytes=4096;
    if(!dim || vector_column>=types.size() || dim>budget() || count>budget()) return budget()+1;
    bytes=add(bytes,mul(types.size(),sizeof(ScalarColumn)+sizeof(Type)+sizeof(size_t)+96));
    bytes=add(bytes,mul(text_max.size(),sizeof(size_t)));
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
  bool fits() const {return required_bytes()<=budget();}
};
struct Compact {
  size_t dim,count,vector_column;
  std::vector<int64_t> keys;
  std::vector<float> vectors;
  std::vector<ScalarColumn> columns;
  // Widest stored text per column, carried over from the plan that sized it.
  std::vector<size_t> text_max;
  // Optional row-major screening codes; exact vectors are always retained.
  std::unique_ptr<int8_t[]> quantized_codes;
  double quantized_step=1,quantized_inverse=1;
  // One optional posting index per view. New object/allocator bookkeeping fits
  // in the existing 4096-byte fixed reserve; payload is accounted separately.
  std::unique_ptr<uint32_t[]> equality_rows;
  size_t equality_column = std::numeric_limits<size_t>::max();
  bool equality_attempted = false;
  struct EqualityRange {
    const uint32_t* rows = nullptr;
    size_t size = 0;
    bool indexed = false;
  };
  static constexpr size_t equality_sort_scratch = 4096;
  explicit Compact(const Plan& p):dim(p.dim),count(p.count),vector_column(p.vector_column),
                                 text_max(p.text_max) {
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
    if(allocated_bytes()>budget()) throw Error("RESOURCE","exact cache allocation exceeds budget");
  }
  size_t allocated_bytes() const {
    size_t bytes=4096+columns.capacity()*(sizeof(ScalarColumn)+sizeof(Type)+sizeof(size_t)+96);
    bytes+=keys.capacity()*sizeof(int64_t)+vectors.capacity()*sizeof(float);
    for(const auto& c:columns) bytes+=c.integers.capacity()*sizeof(int64_t)+c.offsets.capacity()*sizeof(size_t)+c.text.capacity();
    bytes+=text_max.capacity()*sizeof(size_t);
    if(equality_rows) bytes+=count*sizeof(uint32_t);
    // Reserve the prepared query as well, including during posting-index build.
    if(quantized_codes) bytes+=count*dim+dim*sizeof(int16_t)+64;
    return bytes;
  }
  size_t index(size_t row,size_t dimension=0) const {
    return (row/4)*dim*4+dimension*4+row%4;
  }
  int64_t integer_cell(size_t row,size_t column) const {
    return columns[column].integers[row];
  }
  std::string text_cell(size_t row,size_t column) const {
    const auto& col=columns[column];
    const size_t begin=col.offsets[row],end=col.offsets[row+1];
    return begin==end ? std::string() : std::string(col.text.data()+begin,end-begin);
  }
  // Widest text stored in this column, in bytes.
  size_t text_width(size_t column) const {return text_max[column];}
  std::vector<float> vector_cell(size_t row,size_t column) const {
    if(column!=vector_column) throw Error("CORRUPTION","invalid exact vector column");
    std::vector<float> result(dim);
    for(size_t d=0;d<dim;++d)result[d]=vectors[index(row,d)];
    return result;
  }
  double distance_cell(size_t row,size_t column,
                       const std::vector<float>& q) const {
    if(column!=vector_column || q.size()!=dim)
      throw Error("CORRUPTION","invalid exact distance projection");
    double sum=0;
    for(size_t d=0;d<dim;++d) {
      const double x=double(vectors[index(row,d)])-double(q[d]);
      sum+=x*x;
    }
    return std::sqrt(sum);
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
  // Call once after every exact row has been filled, before publishing the view.
  // Bypassed views never pay this scan; an optional-budget failure returns before
  // reading vectors. Only a complete code array is published.
  void prepare_quantized_codes() {
    if(quantized_codes || !count || !fp32_screen_available(dim) ||
       std::fegetround()!=FE_TONEAREST) return;
    const size_t payload=mul(count,dim);
    const size_t scratch=add(mul(dim,sizeof(int16_t)),64);
    if(add(add(allocated_bytes(),payload),scratch)>budget()) return;
    double max_abs=0;
    for(float value:vectors) {
      if(!std::isfinite(value)) return;
      max_abs=std::max(max_abs,std::abs(double(value)));
    }
    double step=1,inverse=1;
    if(max_abs>0) {
      int exponent=0;
      std::frexp(max_abs,&exponent);exponent-=7;
      step=std::ldexp(1.0,exponent);
      if(max_abs>127*step) {++exponent;step*=2;}
      inverse=std::ldexp(1.0,-exponent);
    }
    try {
      std::unique_ptr<int8_t[]> codes(new int8_t[payload]);
      for(size_t row=0;row<count;++row)for(size_t d=0;d<dim;++d) {
        // This binary64 power-of-two scaling is exact even for FP32 subnormals.
        const double rounded=std::nearbyint(double(vectors[index(row,d)])*inverse);
        if(!std::isfinite(rounded) || rounded < -127 || rounded > 127) return;
        codes[row*dim+d]=static_cast<int8_t>(rounded); // Never clamp a code.
      }
      quantized_step=step;quantized_inverse=inverse;
      quantized_codes=std::move(codes);
    } catch(const std::bad_alloc&) {} // Keep the complete original exact view.
  }
  int compare_scalar(size_t c,size_t row,const Cell& value) const {
    const auto& col=columns[c];
    if(col.type==Type::BigInt) {auto a=col.integers[row],b=std::get<int64_t>(value);return (a>b)-(a<b);}
    const size_t begin=col.offsets[row],length=col.offsets[row+1]-begin;
    std::string_view a(length?col.text.data()+begin:"",length);
    std::string_view b=std::get<std::string>(value);
    int cmp=a.compare(b);return (cmp>0)-(cmp<0);
  }
  EqualityRange equality_range(size_t c,const Cell& value) {
    if(columns[c].type!=Type::BigInt && columns[c].type!=Type::Varchar) return {};
    if(!count) return {nullptr,0,true};
    if(!equality_attempted) {
      equality_attempted=true;
      // count is already bounded by the 12MiB view plan. Keep the final array
      // itself as construction storage; sorting needs no second array. Reserve
      // scratch for the fixed toolchain's in-place introsort stack as well.
      const size_t needed=mul(count,sizeof(uint32_t));
      if(add(add(allocated_bytes(),needed),equality_sort_scratch)>budget()) return {};
      try {
        std::unique_ptr<uint32_t[]> rows(new uint32_t[count]);
        for(size_t i=0;i<count;++i) rows[i]=static_cast<uint32_t>(i);
        const auto& col=columns[c];
        if(col.type==Type::BigInt) {
          std::sort(rows.get(),rows.get()+count,[&](uint32_t a,uint32_t b) {
            const auto x=col.integers[a],y=col.integers[b];
            return x<y || (x==y && a<b);
          });
        } else {
          auto text=[&](uint32_t row) {
            const size_t begin=col.offsets[row],length=col.offsets[row+1]-begin;
            return std::string_view(length?col.text.data()+begin:"",length);
          };
          std::sort(rows.get(),rows.get()+count,[&](uint32_t a,uint32_t b) {
            const int cmp=text(a).compare(text(b));
            return cmp<0 || (cmp==0 && a<b);
          });
        }
        equality_column=c;
        equality_rows=std::move(rows); // publish only a complete sorted index
      } catch(const std::bad_alloc&) {
        // This optional index never invalidates or bypasses the existing view.
        return {};
      }
    }
    if(!equality_rows || equality_column!=c) return {};
    const uint32_t* first=equality_rows.get();
    const uint32_t* last=first+count;
    const uint32_t* begin=std::lower_bound(first,last,value,
      [&](uint32_t row,const Cell& v){return compare_scalar(c,row,v)<0;});
    const uint32_t* end=std::upper_bound(begin,last,value,
      [&](const Cell& v,uint32_t row){return compare_scalar(c,row,v)>0;});
    // The secondary sort key is row number, so equal-value candidates retain
    // the original ascending scan order without an additional sort or buffer.
    return {begin,static_cast<size_t>(end-begin),true};
  }
  double distance(size_t row,const std::vector<float>& q) const {
    return distance_cell(row,vector_column,q);
  }
};
static_assert(sizeof(Compact)<512,"exact view object exceeds fixed reserve");
struct QuantizedQuery {
  std::unique_ptr<int16_t[]> codes;
  double root_dim_upper=0;
};
inline QuantizedQuery prepare_quantized_query(const Compact& cache,
                                             const std::vector<float>& query,
                                             bool fp_mode_ok) {
  QuantizedQuery prepared;
  if(!fp_mode_ok || !cache.quantized_codes || query.size()!=cache.dim ||
     std::fegetround()!=FE_TONEAREST) return prepared;
  try {prepared.codes.reset(new int16_t[cache.dim]);}
  catch(const std::bad_alloc&) {return prepared;}
  for(size_t d=0;d<cache.dim;++d) {
    const double rounded=std::nearbyint(double(query[d])*cache.quantized_inverse);
    if(!std::isfinite(rounded) || rounded < -127 || rounded > 127) {
      prepared.codes.reset();return prepared;
    }
    prepared.codes[d]=static_cast<int16_t>(rounded);
  }
  prepared.root_dim_upper=std::nextafter(std::sqrt(double(cache.dim)),
                                       std::numeric_limits<double>::infinity());
  return prepared;
}
// If r is the real distance and I the exact integer square sum, quantization
// gives step*sqrt(I) <= r+step*sqrt(D). Original double accumulation differs
// from the real square sum by relative error <1e-12 for D<=8192. The factor 1.000001 and
// nextup(d) cover that error and every sqrt rounding tie. Expand each operation
// upward; only an integer sum strictly above this bound may be discarded.
inline double quantized_threshold(double worst_distance,double step,
                                  double root_dim_upper) {
  const double inf=std::numeric_limits<double>::infinity();
  if(!std::isfinite(worst_distance) || worst_distance<0 ||
     !std::isfinite(step) || step<=0) return inf;
  const double next=std::nextafter(worst_distance,inf);
  const double distance_upper=std::nextafter(next*1.000001,inf);
  const double units_upper=std::nextafter(distance_upper/step,inf);
  const double radius_upper=std::nextafter(units_upper+root_dim_upper,inf);
  return std::nextafter(radius_upper*radius_upper,inf);
}
inline void distances4_scalar(const Compact& cache,const size_t* rows,
                              const std::vector<float>& q,double* out) {
  for(size_t lane=0;lane<4;++lane) out[lane]=cache.distance(rows[lane],q);
}
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
// Difference codes are at most 254. D<=8192 bounds the whole integer sum by
// 528515072, so packed products, partial sums and horizontal reduction are exact.
__attribute__((target("avx2,no-fma"),noinline))
inline uint32_t quantized_squared_distance_avx2(const int8_t* row,
                                              const int16_t* query,size_t dim) {
  __m256i sum=_mm256_setzero_si256();
  size_t d=0;
  for(;d+16<=dim;d+=16) {
    const __m128i bytes=_mm_loadu_si128(reinterpret_cast<const __m128i*>(row+d));
    const __m256i values=_mm256_cvtepi8_epi16(bytes);
    const __m256i q=_mm256_loadu_si256(reinterpret_cast<const __m256i*>(query+d));
    const __m256i delta=_mm256_sub_epi16(values,q);
    sum=_mm256_add_epi32(sum,_mm256_madd_epi16(delta,delta));
  }
  __m128i halves=_mm_add_epi32(_mm256_castsi256_si128(sum),_mm256_extracti128_si256(sum,1));
  halves=_mm_hadd_epi32(halves,halves);
  halves=_mm_hadd_epi32(halves,halves);
  uint32_t result=static_cast<uint32_t>(_mm_cvtsi128_si32(halves));
  for(;d<dim;++d) {const int delta=int(row[d])-int(query[d]);result+=uint32_t(delta*delta);}
  return result;
}
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

// Screening only: no returned distance or heap entry is taken from this sum.
// Preconditions: eight consecutive rows, row%4==0, fp32_screen_available().
__attribute__((target("avx2,no-fma"),noinline))
inline void squared_distances8_fp32_contiguous_avx2(
    const Compact& cache,size_t row,const std::vector<float>& q,float* out) {
  const float* block0=cache.vectors.data()+(row/4)*cache.dim*4;
  const float* block1=block0+cache.dim*4;
  __m256 sum=_mm256_setzero_ps();
  for(size_t d=0;d<cache.dim;++d) {
    const __m128 low=_mm_loadu_ps(block0+d*4);
    const __m128 high=_mm_loadu_ps(block1+d*4);
    const __m256 values=_mm256_insertf128_ps(_mm256_castps128_ps256(low),high,1);
    const __m256 delta=_mm256_sub_ps(values,_mm256_set1_ps(q[d]));
    sum=_mm256_add_ps(sum,_mm256_mul_ps(delta,delta));
  }
  _mm256_storeu_ps(out,sum);
}

// Four independent chains hide addition latency without regrouping dimensions
// within any record. The same query broadcast serves all 32 records.
__attribute__((target("avx2,no-fma"),noinline))
inline void squared_distances32_fp32_contiguous_avx2(
    const Compact& cache,size_t row,const std::vector<float>& q,float* out) {
  const size_t stride=cache.dim*4;
  const float* p0=cache.vectors.data()+(row/4)*stride;
  const float* p1=p0+stride;const float* p2=p1+stride;const float* p3=p2+stride;
  const float* p4=p3+stride;const float* p5=p4+stride;const float* p6=p5+stride;
  const float* p7=p6+stride;
  __m256 sum0=_mm256_setzero_ps(),sum1=_mm256_setzero_ps();
  __m256 sum2=_mm256_setzero_ps(),sum3=_mm256_setzero_ps();
  for(size_t d=0;d<cache.dim;++d) {
    const __m256 query=_mm256_set1_ps(q[d]);
    const __m256 v0=_mm256_insertf128_ps(_mm256_castps128_ps256(_mm_loadu_ps(p0+d*4)),_mm_loadu_ps(p1+d*4),1);
    const __m256 v1=_mm256_insertf128_ps(_mm256_castps128_ps256(_mm_loadu_ps(p2+d*4)),_mm_loadu_ps(p3+d*4),1);
    const __m256 v2=_mm256_insertf128_ps(_mm256_castps128_ps256(_mm_loadu_ps(p4+d*4)),_mm_loadu_ps(p5+d*4),1);
    const __m256 v3=_mm256_insertf128_ps(_mm256_castps128_ps256(_mm_loadu_ps(p6+d*4)),_mm_loadu_ps(p7+d*4),1);
    const __m256 delta0=_mm256_sub_ps(v0,query),delta1=_mm256_sub_ps(v1,query);
    const __m256 delta2=_mm256_sub_ps(v2,query),delta3=_mm256_sub_ps(v3,query);
    sum0=_mm256_add_ps(sum0,_mm256_mul_ps(delta0,delta0));
    sum1=_mm256_add_ps(sum1,_mm256_mul_ps(delta1,delta1));
    sum2=_mm256_add_ps(sum2,_mm256_mul_ps(delta2,delta2));
    sum3=_mm256_add_ps(sum3,_mm256_mul_ps(delta3,delta3));
  }
  _mm256_storeu_ps(out,sum0);_mm256_storeu_ps(out+8,sum1);
  _mm256_storeu_ps(out+16,sum2);_mm256_storeu_ps(out+24,sum3);
}

// Filtered candidates may cross arbitrary AoSoA blocks. The 12 MiB view
// budget keeps every float-element offset safely inside signed 32-bit range.
__attribute__((target("avx2,no-fma"),noinline))
inline void squared_distances32_fp32_avx2(
    const Compact& cache,const size_t* rows,const std::vector<float>& q,float* out) {
  int32_t offsets[32];
  for(size_t lane=0;lane<32;++lane)offsets[lane]=int32_t(cache.index(rows[lane]));
  const __m256i indices0=_mm256_loadu_si256(reinterpret_cast<const __m256i*>(offsets));
  const __m256i indices1=_mm256_loadu_si256(reinterpret_cast<const __m256i*>(offsets+8));
  const __m256i indices2=_mm256_loadu_si256(reinterpret_cast<const __m256i*>(offsets+16));
  const __m256i indices3=_mm256_loadu_si256(reinterpret_cast<const __m256i*>(offsets+24));
  __m256 sum0=_mm256_setzero_ps(),sum1=_mm256_setzero_ps();
  __m256 sum2=_mm256_setzero_ps(),sum3=_mm256_setzero_ps();
  for(size_t d=0;d<cache.dim;++d) {
    const float* column=cache.vectors.data()+d*4;
    const __m256 query=_mm256_set1_ps(q[d]);
    const __m256 delta0=_mm256_sub_ps(_mm256_i32gather_ps(column,indices0,4),query);
    sum0=_mm256_add_ps(sum0,_mm256_mul_ps(delta0,delta0));
    const __m256 delta1=_mm256_sub_ps(_mm256_i32gather_ps(column,indices1,4),query);
    sum1=_mm256_add_ps(sum1,_mm256_mul_ps(delta1,delta1));
    const __m256 delta2=_mm256_sub_ps(_mm256_i32gather_ps(column,indices2,4),query);
    sum2=_mm256_add_ps(sum2,_mm256_mul_ps(delta2,delta2));
    const __m256 delta3=_mm256_sub_ps(_mm256_i32gather_ps(column,indices3,4),query);
    sum3=_mm256_add_ps(sum3,_mm256_mul_ps(delta3,delta3));
  }
  _mm256_storeu_ps(out,sum0);_mm256_storeu_ps(out+8,sum1);
  _mm256_storeu_ps(out+16,sum2);_mm256_storeu_ps(out+24,sum3);
}

// Four rows per call: one query load feeds four independent integer
// accumulators. Per-row arithmetic is unchanged, so the results are identical
// to four quantized_squared_distance_avx2 calls.
__attribute__((target("avx2,no-fma"),noinline))
inline void quantized_squared_distance4_avx2(const int8_t* r0,const int8_t* r1,
                                             const int8_t* r2,const int8_t* r3,
                                             const int16_t* query,size_t dim,
                                             uint32_t* out) {
  __m256i s0=_mm256_setzero_si256(),s1=_mm256_setzero_si256();
  __m256i s2=_mm256_setzero_si256(),s3=_mm256_setzero_si256();
  size_t d=0;
  for(;d+16<=dim;d+=16) {
    const __m256i q=_mm256_loadu_si256(reinterpret_cast<const __m256i*>(query+d));
    const int8_t* rows[4]={r0,r1,r2,r3};
    __m256i* sums[4]={&s0,&s1,&s2,&s3};
    for(int lane=0;lane<4;++lane) {
      const __m128i bytes=_mm_loadu_si128(reinterpret_cast<const __m128i*>(rows[lane]+d));
      const __m256i values=_mm256_cvtepi8_epi16(bytes);
      const __m256i delta=_mm256_sub_epi16(values,q);
      *sums[lane]=_mm256_add_epi32(*sums[lane],_mm256_madd_epi16(delta,delta));
    }
  }
  const uint32_t partial[4]={
      static_cast<uint32_t>(_mm256_extract_epi32(s0,0)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s0,1)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s0,2)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s0,3)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s0,4)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s0,5)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s0,6)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s0,7)),
      static_cast<uint32_t>(_mm256_extract_epi32(s1,0)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s1,1)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s1,2)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s1,3)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s1,4)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s1,5)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s1,6)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s1,7)),
      static_cast<uint32_t>(_mm256_extract_epi32(s2,0)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s2,1)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s2,2)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s2,3)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s2,4)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s2,5)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s2,6)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s2,7)),
      static_cast<uint32_t>(_mm256_extract_epi32(s3,0)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s3,1)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s3,2)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s3,3)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s3,4)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s3,5)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s3,6)) +
          static_cast<uint32_t>(_mm256_extract_epi32(s3,7))};
  const int8_t* rows[4]={r0,r1,r2,r3};
  for(int lane=0;lane<4;++lane) {
    uint32_t extra=partial[lane];
    for(size_t t=d;t<dim;++t) {
      const int delta=int(rows[lane][t])-int(query[t]);extra+=uint32_t(delta*delta);
    }
    out[lane]=extra;
  }
}

#endif
inline uint32_t quantized_squared_distance(const Compact& cache,size_t row,
                                          const QuantizedQuery& query) {
  const int8_t* codes=cache.quantized_codes.get()+row*cache.dim;
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
  return quantized_squared_distance_avx2(codes,query.codes.get(),cache.dim);
#else
  uint32_t sum=0;
  for(size_t d=0;d<cache.dim;++d) {
    const int delta=int(codes[d])-int(query.codes[d]);sum+=uint32_t(delta*delta);
  }
  return sum;
#endif
}
inline void quantized_squared_distance4(const Compact& cache,const size_t* rows,
                                        const QuantizedQuery& query,
                                        uint32_t* out) {
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
  const int8_t* base=cache.quantized_codes.get();
  const size_t stride=cache.dim;
  quantized_squared_distance4_avx2(base+rows[0]*stride,base+rows[1]*stride,
                                   base+rows[2]*stride,base+rows[3]*stride,
                                   query.codes.get(),cache.dim,out);
#else
  for(int lane=0;lane<4;++lane)
    out[lane]=quantized_squared_distance(cache,rows[lane],query);
#endif
}
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
inline void squared_distances8_fp32_contiguous(
    const Compact& cache,size_t row,const std::vector<float>& q,float* out) {
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
  squared_distances8_fp32_contiguous_avx2(cache,row,q,out);
#else
  (void)cache;(void)row;(void)q;
  for(size_t lane=0;lane<8;++lane) out[lane]=std::numeric_limits<float>::infinity();
#endif
}
inline void squared_distances32_fp32_contiguous(
    const Compact& cache,size_t row,const std::vector<float>& q,float* out) {
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
  squared_distances32_fp32_contiguous_avx2(cache,row,q,out);
#else
  (void)cache;(void)row;(void)q;
  for(size_t lane=0;lane<32;++lane) out[lane]=std::numeric_limits<float>::infinity();
#endif
}
inline void squared_distances32_fp32(
    const Compact& cache,const size_t* rows,const std::vector<float>& q,float* out) {
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
  squared_distances32_fp32_avx2(cache,rows,q,out);
#else
  (void)cache;(void)rows;(void)q;
  for(size_t lane=0;lane<32;++lane) out[lane]=std::numeric_limits<float>::infinity();
#endif
}
} // namespace mvdb::exact
