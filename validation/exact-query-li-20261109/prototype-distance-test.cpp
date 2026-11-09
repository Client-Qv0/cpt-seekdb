#include "exact_distance.hpp"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <cmath>
#include <limits>
#include <random>
#include <vector>
int main(){std::mt19937 rng(9137);std::uniform_real_distribution<float> f(-100,100);
 for(size_t n:{1,3,16,128})for(int t=0;t<2000;t++){
 std::vector<float>a(n),b(n);double sum=0;for(size_t i=0;i<n;i++){a[i]=f(rng);b[i]=f(rng);double d=double(a[i])-double(b[i]);sum+=d*d;}double ref=std::sqrt(sum);
 for(double bound:{0.,ref,std::nextafter(ref,0.),std::nextafter(ref,std::numeric_limits<double>::infinity()),std::numeric_limits<double>::infinity()}){
 auto d=mvdb::bounded_exact_distance(a,b,bound);if(ref<=bound)assert(d&&*d==ref);if(d)assert(*d==ref);
 }}
 std::vector<float> z(128,0);assert(*mvdb::bounded_exact_distance(z,z,0)==0);
 std::vector<float> hi(128,std::numeric_limits<float>::max());auto r=mvdb::bounded_exact_distance(hi,z,std::numeric_limits<double>::infinity());assert(r&&std::isfinite(*r));assert(!mvdb::bounded_exact_distance(hi,z,0));
}
