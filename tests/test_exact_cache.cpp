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
int main() {
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
      require(cache.allocated_bytes()<=exact::budget);
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
  std::vector<Cell> large{std::string(exact::budget,'x'),std::vector<float>(1)};
  strings.observe(large); require(!strings.fits());
  exact::Plan boundary({Type::BigInt,Type::Vector},1,1);
  size_t last=boundary.required_bytes();
  while(boundary.fits()) {last=boundary.required_bytes();boundary.observe({int64_t(1),std::vector<float>(1)});}
  require(last<=exact::budget && boundary.required_bytes()>exact::budget);
  std::cout<<"compact scalar layout/budget/distance checks passed\n";
}
