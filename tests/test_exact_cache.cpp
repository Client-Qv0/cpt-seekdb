#include "exact_cache.hpp"
#include <cmath>
#include <array>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <random>
using namespace mvdb;
void require(bool ok) { if(!ok) throw std::runtime_error("exact cache check failed"); }

void test_compact_accessors() {
  exact::Plan plan({Type::BigInt,Type::Varchar,Type::Vector},2,3);
  const std::vector<std::vector<Cell>> rows={
      {int64_t(-5),std::string(),std::vector<float>{1,2,3}},
      {int64_t(7),std::string("中🙂"),std::vector<float>{-1,0.5f,9}}};
  for(const auto& row:rows)plan.observe(row);
  exact::Compact view(plan);
  for(size_t i=0;i<rows.size();++i)view.fill(i,int64_t(i),rows[i]);
  require(view.integer_cell(0,0)==std::get<int64_t>(rows[0][0]) &&
          view.integer_cell(1,0)==7);
  require(view.text_cell(1,1)==std::get<std::string>(rows[1][1]) &&
          view.text_cell(0,1).empty());
  require(view.vector_cell(1,2)==std::get<std::vector<float>>(rows[1][2]));
  std::cout<<"compact direct-cell accessors passed\n";
}
void check_posting_range(exact::Compact& view,size_t col,const Cell& value,bool indexed=true) {
  auto range=view.equality_range(col,value);
  require(range.indexed==indexed);
  if(!indexed) return;
  size_t found=0;
  for(size_t i=0;i<view.count;++i) if(view.compare_scalar(col,i,value)==0) {
    require(found<range.size && range.rows[found]==i);++found;
  }
  require(found==range.size);
}
void test_equality_postings() {
  for(bool text_column: {false,true}) {
    exact::Plan plan({Type::BigInt,Type::BigInt,Type::Varchar,Type::Vector},3,3);
    std::vector<std::vector<Cell>> rows;
    const std::string text[]={"", "x", "a", "x", "中🙂", std::string("a\0z",3)};
    for(int64_t i=0;i<51;++i) {
      rows.push_back({i+9007199254740993LL, (i%7)-3, text[i%6],std::vector<float>{float(i),0,1}});
      plan.observe(rows.back());
    }
    exact::Compact view(plan);
    for(size_t i=0;i<rows.size();++i)view.fill(i,std::get<int64_t>(rows[i][0]),rows[i]);
    size_t before=view.allocated_bytes();
    if(text_column) {
      for(const auto& value:text)check_posting_range(view,2,Cell(value));
      check_posting_range(view,2,Cell(std::string("missing")));
      check_posting_range(view,1,Cell(int64_t(1)),false);
    } else {
      for(int64_t v=-4;v<=4;++v)check_posting_range(view,1,Cell(v));
      check_posting_range(view,1,Cell(std::numeric_limits<int64_t>::min()));
      check_posting_range(view,1,Cell(std::numeric_limits<int64_t>::max()));
      check_posting_range(view,2,Cell(std::string("x")),false);
    }
    require(view.equality_attempted && view.equality_rows);
    require(view.allocated_bytes()==before+view.count*sizeof(uint32_t));
    require(view.allocated_bytes()+view.equality_sort_scratch<=exact::budget());
  }
  exact::Plan empty({Type::BigInt,Type::Vector},1,1);
  exact::Compact zero(empty);check_posting_range(zero,0,Cell(int64_t(0)));
  require(!zero.equality_rows);
  exact::Plan boundary({Type::BigInt,Type::BigInt,Type::Vector},2,128);
  boundary.count=22000;
  while(boundary.required_bytes()+boundary.count*sizeof(uint32_t)+exact::Compact::equality_sort_scratch<=exact::budget())++boundary.count;
  require(boundary.fits());
  exact::Compact full(boundary);size_t before=full.allocated_bytes();
  check_posting_range(full,1,Cell(int64_t(0)),false);
  check_posting_range(full,1,Cell(int64_t(1)),false);
  require(full.equality_attempted && !full.equality_rows && full.allocated_bytes()==before);
  require(full.compare_scalar(1,0,Cell(int64_t(0)))==0);
  std::cout<<"equality posting ordering, strings, one-index policy and budget checks passed\n";
}

void test_fp32_screen() {
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
  if(!exact::available()) {
    require(!exact::fp32_screen_available(128));
    std::cout<<"FP32 screen AVX2 checks skipped: AVX2 unavailable\n";
    return;
  }
  struct RestoreMxcsr {
    unsigned value=_mm_getcsr();
    ~RestoreMxcsr() { _mm_setcsr(value); }
  } restore;
  const unsigned safe=(restore.value|0x1f80u)&~(0x6000u|0x8000u|0x0040u|0x003fu);
  _mm_setcsr(safe);
  require(exact::fp32_screen_available(1) && exact::fp32_screen_available(8192));
  require(!exact::fp32_screen_available(0) && !exact::fp32_screen_available(8193));
  for(unsigned mode: {0x8000u,0x0040u,0x2000u,0x4000u,0x6000u}) {
    _mm_setcsr(safe|mode);
    bool enabled=exact::fp32_screen_available(128);
    _mm_setcsr(safe);
    require(!enabled);
  }
  for(unsigned bit=7;bit<=12;++bit) {
    // Only inspect the control word while an exception is unmasked.
    _mm_setcsr(safe&~(1u<<bit));
    bool enabled=exact::fp32_screen_available(128);
    _mm_setcsr(safe);
    require(!enabled);
  }
  auto make_cache=[](const std::vector<std::vector<float>>& vectors) {
    exact::Plan plan({Type::BigInt,Type::Vector},1,vectors.front().size());
    std::vector<std::vector<Cell>> rows;
    for(size_t i=0;i<vectors.size();++i) {
      rows.push_back({int64_t(i),vectors[i]});plan.observe(rows.back());
    }
    require(plan.fits());
    exact::Compact cache(plan);
    for(size_t i=0;i<rows.size();++i)cache.fill(i,int64_t(i),rows[i]);
    return cache;
  };
  const float tiny=std::numeric_limits<float>::denorm_min();
  const float maximum=std::numeric_limits<float>::max();
  auto edge=make_cache({{1,0},{1,0x1p-26f},{0,0},{tiny,0},
                        {1e-23f,0},{maximum,0},{-maximum,0},{2,0}});
  std::vector<float> zero(2,0);
  float rough[8];
  exact::squared_distances8_fp32_contiguous(edge,0,zero,rough);
  const double tie=edge.distance(0,zero),near_tie=edge.distance(1,zero);
  require(tie==1 && std::memcmp(&tie,&near_tie,sizeof(double))==0);
  const double bound=exact::fp32_screen_threshold(tie,2);
  require(!exact::fp32_screen_reject(rough[0],bound));
  require(!exact::fp32_screen_reject(rough[1],bound));
  require(exact::fp32_screen_reject(rough[7],bound));
  require(rough[3]==0 && rough[4]==0);
  require(!exact::fp32_screen_reject(rough[3],exact::fp32_screen_threshold(0,2)));
  require(!exact::fp32_screen_reject(rough[4],exact::fp32_screen_threshold(0,2)));
  require(std::isinf(rough[5]) && std::isfinite(edge.distance(5,zero)));
  require(!exact::fp32_screen_reject(rough[5],bound));
  std::vector<float> opposite(2,maximum);
  exact::squared_distances8_fp32_contiguous(edge,0,opposite,rough);
  require(std::isinf(rough[6]) && std::isfinite(edge.distance(6,opposite)));
  require(!exact::fp32_screen_reject(rough[6],bound));
  require(!exact::fp32_screen_reject(std::numeric_limits<float>::quiet_NaN(),bound));
  require(std::isinf(exact::fp32_screen_threshold(1,8193)));

  std::mt19937 random(20261111);
  size_t rejected=0;
  for(size_t dim: {size_t(1),size_t(3),size_t(128),size_t(8192)}) {
    std::vector<std::vector<float>> vectors(40,std::vector<float>(dim));
    for(size_t i=0;i<vectors.size();++i)
      for(float& v:vectors[i])v=float(i)+float(int(random()%2001)-1000)/1024;
    auto cache=make_cache(vectors);
    for(unsigned attempt=0;attempt<3;++attempt) {
      std::vector<float> query(dim);
      for(float& v:query)v=float(int(random()%4001)-2000)/1024;
      std::array<double,40> exact_distances;
      for(size_t i=0;i<40;++i)exact_distances[i]=cache.distance(i,query);
      auto ordered=exact_distances;
      std::sort(ordered.begin(),ordered.end());
      const double worst=ordered[3];
      const double threshold=exact::fp32_screen_threshold(worst,dim);
      std::array<float,40> all_screen_sums;
      for(size_t row=0;row<40;) {
        const size_t count=row+32<=40 ? 32 : 8;
        double full[32];float screen_sums[32];
        for(size_t offset=0;offset<count;offset+=8)
          exact::distances8_contiguous(cache,row+offset,query,full+offset);
        if(count==32)
          exact::squared_distances32_fp32_contiguous(cache,row,query,screen_sums);
        else
          exact::squared_distances8_fp32_contiguous(cache,row,query,screen_sums);
        for(size_t lane=0;lane<count;++lane) {
          all_screen_sums[row+lane]=screen_sums[lane];
          // The old scalar and SIMD results remain the bitwise oracle. Every
          // rejected record must be strictly worse, including sqrt ties.
          require(std::memcmp(&full[lane],&exact_distances[row+lane],sizeof(double))==0);
          if(exact::fp32_screen_reject(screen_sums[lane],threshold)) {
            require(exact_distances[row+lane]>worst);++rejected;
          }
        }
        row+=count;
      }
      size_t selected[32];float gathered[32];
      for(size_t lane=0;lane<32;++lane)selected[lane]=(lane*7+5)%40;
      exact::squared_distances32_fp32(cache,selected,query,gathered);
      for(size_t lane=0;lane<32;++lane) {
        const size_t row=selected[lane];
        require(std::memcmp(&gathered[lane],&all_screen_sums[row],sizeof(float))==0);
        if(exact::fp32_screen_reject(gathered[lane],threshold))
          require(exact_distances[row]>worst);
      }
    }
  }
  require(rejected>0);
  std::cout<<"FP32 screen FP modes, sqrt ties, underflow/overflow and exact rejection checks passed\n";
#else
  require(!exact::fp32_screen_available(128));
#endif
}

void test_quantized_screen() {
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
  if(!exact::available() || std::fegetround()!=FE_TONEAREST) return;
  struct RestoreMxcsr {
    unsigned value=_mm_getcsr();
    ~RestoreMxcsr() {_mm_setcsr(value);}
  } restore;
  _mm_setcsr((restore.value|0x1f80u)&~(0x6000u|0x8000u|0x0040u|0x003fu));
  auto make_cache=[](const std::vector<std::vector<float>>& vectors) {
    exact::Plan plan({Type::BigInt,Type::Vector},1,vectors.front().size());
    std::vector<std::vector<Cell>> rows;
    for(size_t i=0;i<vectors.size();++i) {
      rows.push_back({int64_t(i),vectors[i]});plan.observe(rows.back());
    }
    exact::Compact cache(plan);
    for(size_t i=0;i<rows.size();++i)cache.fill(i,int64_t(i),rows[i]);
    require(!cache.quantized_codes);
    cache.prepare_quantized_codes();
    return cache;
  };
  std::mt19937 random(20261112);
  size_t rejected=0;
  for(size_t dim:{size_t(1),size_t(15),size_t(16),size_t(17),size_t(128),size_t(8192)}) {
    std::vector<std::vector<float>> vectors(12,std::vector<float>(dim));
    for(size_t i=0;i<vectors.size();++i)
      for(float& value:vectors[i])value=float(i)+float(int(random()%2001)-1000)/1024;
    auto cache=make_cache(vectors);
    require(bool(cache.quantized_codes) && cache.allocated_bytes()<=exact::budget());
    for(size_t i=0;i<vectors.size();++i)for(size_t d=0;d<dim;++d) {
      const int code=int(cache.quantized_codes[i*dim+d]);
      require(code>=-127 && code<=127);
      require(std::abs(double(vectors[i][d])-code*cache.quantized_step)<=cache.quantized_step/2);
    }
    std::vector<float> query(dim,0.25f);
    auto prepared=exact::prepare_quantized_query(cache,query,true);
    require(bool(prepared.codes));
    const double worst=cache.distance(2,query);
    const double threshold=exact::quantized_threshold(worst,cache.quantized_step,prepared.root_dim_upper);
    for(size_t i=0;i<vectors.size();++i) {
      uint32_t scalar=0;
      for(size_t d=0;d<dim;++d) {
        const int delta=int(cache.quantized_codes[i*dim+d])-int(prepared.codes[d]);
        scalar+=uint32_t(delta*delta);
      }
      const uint32_t actual=exact::quantized_squared_distance(cache,i,prepared);
      require(actual==scalar);
      if(double(actual)>threshold) {require(cache.distance(i,query)>worst);++rejected;}
    }
    require(!exact::prepare_quantized_query(cache,query,false).codes);
    std::vector<float> outside(dim,1e10f);
    require(!exact::prepare_quantized_query(cache,outside,true).codes);
  }
  require(rejected>0);
  for(float magnitude:{std::numeric_limits<float>::denorm_min(),std::numeric_limits<float>::max()}) {
    auto cache=make_cache({std::vector<float>(17,magnitude),std::vector<float>(17,-magnitude)});
    require(bool(cache.quantized_codes));
    const double expected=std::ldexp(1.0,magnitude<1 ? -155 : 122);
    require(cache.quantized_step==expected);
    std::vector<float> query(17,-magnitude);
    auto prepared=exact::prepare_quantized_query(cache,query,true);
    require(bool(prepared.codes));
    const double threshold=exact::quantized_threshold(0,cache.quantized_step,prepared.root_dim_upper);
    require(exact::quantized_squared_distance(cache,1,prepared)==0);
    require(double(exact::quantized_squared_distance(cache,0,prepared))>threshold);
    require(std::isfinite(cache.distance(0,query)));
  }
  {
    auto cache=make_cache({std::vector<float>(8192,127),std::vector<float>(8192,-127)});
    auto prepared=exact::prepare_quantized_query(cache,std::vector<float>(8192,-127),true);
    require(cache.quantized_step==1 && bool(prepared.codes));
    require(exact::quantized_squared_distance(cache,0,prepared)==528515072u);
  }
  {
    auto cache=make_cache({{1,0},{1,0x1p-26f},{0,0}});
    std::vector<float> query(2,0);
    auto prepared=exact::prepare_quantized_query(cache,query,true);
    const double worst=cache.distance(0,query);
    require(worst==cache.distance(1,query));
    const double threshold=exact::quantized_threshold(worst,cache.quantized_step,prepared.root_dim_upper);
    require(!(double(exact::quantized_squared_distance(cache,1,prepared))>threshold));
  }
  exact::Plan full_plan({Type::BigInt,Type::Vector},1,128);
  full_plan.count=22000;
  require(full_plan.fits());
  exact::Compact full(full_plan);
  full.prepare_quantized_codes();
  require(!full.quantized_codes && full.allocated_bytes()<=exact::budget());
  std::cout<<"quantized screen code bounds, exact integer sums, rejection safety and budget fallback passed\n";
#endif
}


#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
// The four-row integer kernel must return exactly what four single-row calls
// return, including short dimensions that leave a scalar tail.
void test_quantized_four_row_kernel() {
  if (!exact::available()) return;
  std::mt19937 rng(20261113);
  std::uniform_int_distribution<int> code(-127, 127);
  for (size_t dim : {size_t(1), size_t(7), size_t(16), size_t(17), size_t(64),
                     size_t(127), size_t(128), size_t(129)}) {
    std::vector<int8_t> rows(4 * dim);
    std::vector<int16_t> query(dim);
    for (auto &value : rows) value = static_cast<int8_t>(code(rng));
    for (auto &value : query) value = static_cast<int16_t>(code(rng));
    uint32_t batch[4];
    const int8_t *row0 = rows.data();
    const int8_t *row1 = rows.data() + dim;
    const int8_t *row2 = rows.data() + 2 * dim;
    const int8_t *row3 = rows.data() + 3 * dim;
    exact::quantized_squared_distance4_avx2(row0, row1, row2, row3,
                                            query.data(), dim, batch);
    const uint32_t single[4] = {
        exact::quantized_squared_distance_avx2(row0, query.data(), dim),
        exact::quantized_squared_distance_avx2(row1, query.data(), dim),
        exact::quantized_squared_distance_avx2(row2, query.data(), dim),
        exact::quantized_squared_distance_avx2(row3, query.data(), dim)};
    for (int lane = 0; lane < 4; ++lane)
      require(batch[lane] == single[lane]);
  }
}
#endif

int main() {
  // The view budget follows the memory this process may use, so it must never
  // fall below the old fixed value nor outgrow its ceiling.
  require(exact::budget() >= size_t(12) * 1024 * 1024 &&
          exact::budget() <= size_t(48) * 1024 * 1024);
  test_compact_accessors();
  test_equality_postings();
  test_fp32_screen();
  test_quantized_screen();
#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
  test_quantized_four_row_kernel();
#endif
  for(size_t n: {size_t(0),size_t(1),size_t(3),size_t(4),size_t(5),size_t(9)})
    for(size_t dim: {size_t(1),size_t(3),size_t(128)}) {
      exact::Plan plan({Type::BigInt,Type::Varchar,Type::Vector},2,dim);
      std::vector<std::vector<Cell>> rows;
      for(size_t i=0;i<n;++i) {
        std::vector<float> v(dim);
        for(size_t d=0;d<dim;++d) v[d]=float(i)-float(d)/4;
        rows.push_back({int64_t(i)-5,std::string(i%2?"中🙂":""),v});
        plan.observe(rows.back());
      }
      require(plan.fits());
      exact::Compact cache(plan);
      for(size_t i=0;i<n;++i) cache.fill(i,int64_t(i)-5,rows[i]);
      require(cache.allocated_bytes()<=exact::budget());
      std::vector<float> q(dim,0.5f);
      for(size_t i=0;i<n;++i) {
        double sum=0; const auto& v=std::get<std::vector<float>>(rows[i][2]);
        for(size_t d=0;d<dim;++d) {double x=double(v[d])-double(q[d]);sum+=x*x;}
        double want=std::sqrt(sum),got=cache.distance(i,q);
        require(std::memcmp(&want,&got,sizeof(double))==0);
        require(cache.compare_scalar(0,i,Cell(int64_t(i)-5))==0);
        require(cache.compare_scalar(1,i,rows[i][1])==0);
        require(cache.keys[i]==int64_t(i)-5);
      }
    }
  // C2: SIMD lanes must preserve every scalar bit for contiguous and gathered
  // records, finite FP32 extrema/subnormals and dimensional boundaries.
  for(size_t dim: {size_t(1),size_t(3),size_t(5),size_t(31),size_t(128),size_t(129)}) {
    exact::Plan plan({Type::BigInt,Type::Vector},1,dim);
    const float values[]={0.0f,-0.0f,std::numeric_limits<float>::max(),
      -std::numeric_limits<float>::max(),std::numeric_limits<float>::denorm_min(),
      -std::numeric_limits<float>::denorm_min(),1.0f,std::nextafter(1.0f,2.0f),1e-20f,1e20f};
    std::vector<std::vector<Cell>> rows;
    for(size_t i=0;i<12;++i) {
      std::vector<float> v(dim);
      for(size_t d=0;d<dim;++d) v[d]=values[(i*7+d)%10];
      rows.push_back({int64_t(i),v});plan.observe(rows.back());
    }
    exact::Compact cache(plan);
    for(size_t i=0;i<rows.size();++i) cache.fill(i,int64_t(i),rows[i]);
    for(size_t iteration=0;iteration<100;++iteration) {
      std::vector<float> q(dim);
      for(size_t d=0;d<dim;++d) q[d]=values[(iteration+d*3)%10];
      for(const auto& indices: {std::array<size_t,4>{0,1,2,3},
          std::array<size_t,4>{4,5,6,7},std::array<size_t,4>{0,2,5,11}}) {
        double output[4];exact::distances4(cache,indices.data(),q,output);
        for(size_t lane=0;lane<4;++lane) {
          double scalar=cache.distance(indices[lane],q);
          require(std::memcmp(&scalar,&output[lane],sizeof(double))==0);
        }
      }
    }
  }
  // Eight-record batches, both contiguous and gathered, preserve scalar bits.
  std::mt19937 random(81629);
  for(size_t dim: {size_t(1),size_t(2),size_t(3),size_t(4),size_t(5),
      size_t(7),size_t(31),size_t(32),size_t(33),size_t(127),size_t(128),size_t(129)}) {
    exact::Plan plan({Type::BigInt,Type::Vector},1,dim);
    std::vector<std::vector<Cell>> values;
    for(size_t i=0;i<45;++i) {
      std::vector<float> vector(dim);
      for(auto &x:vector)x=float(int(random()%200001)-100000)/131.0f;
      values.push_back({int64_t(i),std::move(vector)});plan.observe(values.back());
    }
    exact::Compact cache(plan);
    for(size_t i=0;i<values.size();++i)cache.fill(i,int64_t(i),values[i]);
    for(size_t iteration=0;iteration<100;++iteration) {
      std::vector<float> q(dim);
      for(auto &x:q)x=float(int(random()%200001)-100000)/73.0f;
      std::vector<std::array<size_t,8>> groups{{0,1,2,3,4,5,6,7},
        {1,2,3,4,5,6,7,8},{0,5,10,15,20,25,30,35},{0,1,2,3,7,11,19,43},
        {1,5,9,13,20,21,22,23},{44,0,43,17,16,31,29,8},{44,44,0,0,1,1,2,2}};
      for(size_t k=0;k<8;++k) {
        std::array<size_t,8> group{};for(auto &row:group)row=random()%45;
        groups.push_back(group);
      }
      if(exact::available()) {
        for(size_t start=0;start+8<=cache.count;start+=8) {
          double output[8];exact::distances8_contiguous(cache,start,q,output);
          for(size_t lane=0;lane<8;++lane) {
            double scalar=cache.distance(start+lane,q);
            require(std::memcmp(&scalar,output+lane,sizeof(double))==0);
          }
        }
      }
      for(const auto& ids:groups) {
        double output[8];exact::distances8(cache,ids.data(),q,output);
        for(size_t lane=0;lane<8;++lane) {
          double scalar=cache.distance(ids[lane],q);
          require(std::memcmp(&scalar,output+lane,sizeof(double))==0);
        }
      }
    }
  }
  exact::Plan overflow({Type::BigInt,Type::Vector},1,128);
  std::vector<Cell> row{int64_t(0),std::vector<float>(128)};
  for(int i=0;i<32000;++i) overflow.observe(row);
  require(!overflow.fits());
  exact::Plan huge({Type::Vector},0,std::numeric_limits<size_t>::max());
  require(!huge.fits());
  exact::Plan strings({Type::Varchar,Type::Vector},1,1);
  std::vector<Cell> large{std::string(exact::budget(),'x'),std::vector<float>(1)};
  strings.observe(large); require(!strings.fits());
  exact::Plan boundary({Type::BigInt,Type::Vector},1,1);
  size_t last=boundary.required_bytes();
  while(boundary.fits()) {last=boundary.required_bytes();boundary.observe({int64_t(1),std::vector<float>(1)});}
  require(last<=exact::budget() && boundary.required_bytes()>exact::budget());
  std::cout<<"compact scalar layout/budget/distance checks passed\n";
}
