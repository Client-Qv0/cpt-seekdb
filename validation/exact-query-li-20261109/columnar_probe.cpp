// Standalone layout prototype; not integrated into Engine and not a DB score.
#include "engine.hpp"
#include <algorithm>
#include <cassert>
#include <chrono>
#include <cmath>
#include <iostream>
#include <map>
#include <random>
using Clock=std::chrono::steady_clock;
struct Row{int64_t id;std::vector<mvdb::Cell> cells;};
using Hits=std::vector<std::pair<double,int64_t>>;
int main(int argc,char**argv){
 const size_t n=argc>1?std::stoull(argv[1]):10000,d=argc>2?std::stoull(argv[2]):128,groups=argc>3?std::stoull(argv[3]):7;
 const size_t budget=12*1024*1024;
 // Conservative admission estimate, bounded multiplication before allocation.
 if(!d||!groups||d>budget/4||n>budget/(d*4+128)){std::cout<<"{\"admitted\":false}\n";return 0;}
 std::mt19937 rng(58491);std::uniform_real_distribution<float> draw(-1,1);
 std::vector<Row> rows;rows.reserve(n);for(size_t i=0;i<n;i++){std::vector<float>v(d);for(auto&x:v)x=draw(rng);rows.push_back({int64_t(i),{std::string("group-")+std::to_string(i%groups),std::move(v)}});}
 auto begin=Clock::now();std::vector<float> matrix(n*d);std::vector<int64_t> ids(n);std::map<std::string,std::vector<size_t>> postings;
 for(size_t i=0;i<n;i++){ids[i]=rows[i].id;const auto&v=std::get<std::vector<float>>(rows[i].cells[1]);std::copy(v.begin(),v.end(),matrix.begin()+i*d);postings[std::get<std::string>(rows[i].cells[0])].push_back(i);}
 auto built=Clock::now();long long old_ns=0,new_ns=0;size_t checked=0;
 auto trim=[](Hits&h){std::sort(h.begin(),h.end());if(h.size()>10)h.resize(10);};
 for(size_t qn=0;qn<100;qn++){
 std::vector<float>query(d);for(auto&x:query)x=draw(rng);std::string filter="group-"+std::to_string(qn%groups);bool filtered=qn%2;Hits a,b;
 auto start=Clock::now();for(const auto&r:rows){if(filtered&&std::get<std::string>(r.cells[0])!=filter)continue;const auto&v=std::get<std::vector<float>>(r.cells[1]);double sum=0;for(size_t j=0;j<d;j++){double diff=double(v[j])-double(query[j]);sum+=diff*diff;}a.emplace_back(std::sqrt(sum),r.id);}trim(a);auto middle=Clock::now();
 auto visit=[&](size_t i){double sum=0;const float*v=matrix.data()+i*d;for(size_t j=0;j<d;j++){double diff=double(v[j])-double(query[j]);sum+=diff*diff;}b.emplace_back(std::sqrt(sum),ids[i]);};
 if(filtered){for(size_t i:postings.at(filter))visit(i);}else for(size_t i=0;i<n;i++)visit(i);trim(b);auto finish=Clock::now();assert(a==b);checked++;
 old_ns+=std::chrono::duration_cast<std::chrono::nanoseconds>(middle-start).count();new_ns+=std::chrono::duration_cast<std::chrono::nanoseconds>(finish-middle).count();
 }
 size_t allocated=matrix.capacity()*sizeof(float)+ids.capacity()*sizeof(int64_t);for(const auto&e:postings)allocated+=e.first.capacity()+sizeof(e)+64+e.second.capacity()*sizeof(size_t);assert(allocated<=budget);
 std::cout<<"{\"admitted\":true,\"checked_queries\":"<<checked<<",\"rows\":"<<n<<",\"dimension\":"<<d<<",\"matrix_and_postings_estimated_capacity_bytes\":"<<allocated<<",\"row_scan_ns\":"<<old_ns<<",\"columnar_scan_ns\":"<<new_ns<<",\"build_ns\":"<<std::chrono::duration_cast<std::chrono::nanoseconds>(built-begin).count()<<",\"scope\":\"standalone in-process layout, holds reference rows too; not end-to-end DB performance or cgroup memory\"}\n";
}
