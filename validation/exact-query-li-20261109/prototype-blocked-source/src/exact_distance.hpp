#pragma once
#include <cmath>
#include <limits>
#include <optional>
#include <vector>
namespace mvdb {
// Inputs already validated/quantized by SQL conversion. Preserve the original
// accumulation order. A full ULP above the rounded worst distance protects
// candidates whose rounded sqrt ties that distance (PK must still break ties).
inline std::optional<double> bounded_exact_distance(const std::vector<float>& a,
 const std::vector<float>& b,double worst) {
 const double upper=std::nextafter(worst,std::numeric_limits<double>::infinity());
 const double cutoff=upper*upper;
 double sum=0;
 size_t i=0;
 while(i<a.size()){
  const size_t end=a.size()-i>8 ? i+8 : a.size();
  for(;i<end;++i){double d=double(a[i])-double(b[i]);sum+=d*d;}
  if(sum>cutoff)return std::nullopt;
 }
 return std::sqrt(sum);
}
}
