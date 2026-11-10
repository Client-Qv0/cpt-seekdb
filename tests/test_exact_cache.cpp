#include "exact_cache.hpp"
#include <cmath>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>
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
