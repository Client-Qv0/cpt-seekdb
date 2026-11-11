#include "exact_cache.hpp"
#include <array>
#include <algorithm>
#include <chrono>
#include <iomanip>
#include <iostream>
#include <random>
#include <cstring>
using namespace mvdb;
using Clock=std::chrono::steady_clock;
volatile double sink=0;
__attribute__((target("avx2,no-fma"),noinline))
void scalar_loads4(const exact::Compact& cache,const size_t* rows,
                   const std::vector<float>& q,double* out) {
  const bool contiguous=rows[0]%4==0 && rows[1]==rows[0]+1 &&
      rows[2]==rows[0]+2 && rows[3]==rows[0]+3;
  const size_t a=cache.index(rows[0]),b=cache.index(rows[1]),
      c=cache.index(rows[2]),e=cache.index(rows[3]);
  __m256d sum=_mm256_setzero_pd();
  for(size_t d=0;d<cache.dim;++d) {
    const float* p=cache.vectors.data()+d*4;
    __m128 values=contiguous ? _mm_loadu_ps(p+a) :
        _mm_setr_ps(p[a],p[b],p[c],p[e]);
    __m256d delta=_mm256_sub_pd(_mm256_cvtps_pd(values),_mm256_set1_pd(double(q[d])));
    __m256d square=_mm256_mul_pd(delta,delta);
    sum=_mm256_add_pd(sum,square);
  }
  _mm256_storeu_pd(out,_mm256_sqrt_pd(sum));
}
__attribute__((noinline)) size_t filter_scan(const exact::Compact& c,const Cell& value) {
  size_t n=0;
  for(size_t i=0;i<c.count;++i) if(c.compare_scalar(1,i,value)==0) ++n;
  return n;
}
using Fn=void(*)(const exact::Compact&,const size_t*,const std::vector<float>&,double*);
double bench(Fn f,const exact::Compact& cache,const std::vector<std::array<size_t,4>>& groups,
             std::vector<float>& q) {
  const auto start=Clock::now();double checksum=0;
  for(size_t rep=0;rep<200;++rep) {
    q[0]=float(rep)/201;
    for(auto &g:groups) {double out[4];f(cache,g.data(),q,out);checksum+=out[rep%4];}
  }
  const auto stop=Clock::now();sink=checksum;
  return std::chrono::duration<double>(stop-start).count();
}
int main() {
  if(!exact::available()){std::cerr<<"AVX2 unavailable\n";return 77;}
  exact::Plan p({Type::BigInt,Type::Varchar,Type::Vector},2,128);
  std::vector<std::vector<Cell>> data;
  std::mt19937 rng(47219);std::uniform_real_distribution<float> dist(-1,1);
  for(size_t i=0;i<10000;++i) {
    std::vector<float> v(128);for(float &x:v)x=dist(rng);
    data.push_back({int64_t(i),"g"+std::to_string(i%5),std::move(v)});p.observe(data.back());
  }
  exact::Compact c(p);for(size_t i=0;i<data.size();++i)c.fill(i,int64_t(i),data[i]);
  std::vector<float> q(128,0.125f);
  std::vector<std::array<size_t,4>> aligned,strided,random;
  for(size_t i=0;i<10000;i+=4) aligned.push_back({i,i+1,i+2,i+3});
  for(size_t i=0;i+15<10000;i+=20) strided.push_back({i,i+5,i+10,i+15});
  for(size_t i=0;i<500;++i) random.push_back({rng()%10000,rng()%10000,rng()%10000,rng()%10000});
  for(auto *groups:{&aligned,&strided,&random}) for(auto& g:*groups) {
    double a[4],b[4];exact::distances4_avx2(c,g.data(),q,a);scalar_loads4(c,g.data(),q,b);
    if(std::memcmp(a,b,sizeof(a))!=0)return 1;
    for(size_t lane=0;lane<4;++lane){double scalar=c.distance(g[lane],q);if(std::memcmp(&scalar,b+lane,8)!=0)return 2;}
  }
  std::cout<<std::setprecision(17);
  for(size_t round=0;round<6;++round) {
    auto start=Clock::now();size_t sum=0;
    for(size_t rep=0;rep<1000;++rep) sum+=filter_scan(c,Cell("g"+std::to_string(rep%5)));
    double filter=std::chrono::duration<double>(Clock::now()-start).count();sink=double(sum);
    std::cout<<"{\"round\":"<<round+1<<",\"case\":\"filter_only\",\"seconds\":"<<filter<<",\"record_comparisons\":10000000,\"matches\":"<<sum<<"}\n";
    size_t case_id=0;
    for(auto *groups:{&aligned,&strided,&random}) {
      double gather,loads;
      if(round%2==0){gather=bench(exact::distances4_avx2,c,*groups,q);loads=bench(scalar_loads4,c,*groups,q);}
      else {loads=bench(scalar_loads4,c,*groups,q);gather=bench(exact::distances4_avx2,c,*groups,q);}
      std::cout<<"{\"round\":"<<round+1<<",\"case\":\""<<std::array<const char*,3>{"aligned","stride5","random"}[case_id++]<<"\",\"gather_seconds\":"<<gather<<",\"loads_seconds\":"<<loads<<",\"groups\":"<<groups->size()<<",\"repeats\":200,\"checksum\":"<<sink<<"}\n";
    }
    std::cout.flush();
  }
}
