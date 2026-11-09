#include "engine.hpp"
#include <chrono>
#include <fstream>
#include <iostream>
#include <string>
using Clock=std::chrono::steady_clock;
long long ns(Clock::time_point a,Clock::time_point b){return std::chrono::duration_cast<std::chrono::nanoseconds>(b-a).count();}
int main(int argc,char**argv){
 std::string dir="/data";for(int i=1;i<argc;i++)if(std::string(argv[i])=="--data-dir"&&i+1<argc)dir=argv[++i];
 long long engine_ns=0,output_ns=0,first_ns=0;size_t queries=0;
 try{mvdb::Engine engine(dir);std::string sql;while(std::getline(std::cin,sql)){
 bool emitting=false;try{
 auto a=Clock::now();auto r=engine.execute(sql);auto b=Clock::now();emitting=true;mvdb::write_result_json(std::cout,r);std::cout<<'\n'<<std::flush;auto c=Clock::now();
 if(sql.rfind("SELECT",0)==0){if(queries++==0)first_ns=ns(a,b);engine_ns+=ns(a,b);output_ns+=ns(b,c);}
 }catch(const mvdb::Error&e){if(emitting)return 1;std::cout<<mvdb::error_json(e.code,e.what())<<'\n'<<std::flush;}}
 std::ofstream f("/home/li/minivectordb-v2-work/planning-20261109/query-profile-result.json");f<<"{\"queries\":"<<queries<<",\"engine_ns\":"<<engine_ns<<",\"output_flush_ns\":"<<output_ns<<",\"first_query_engine_ns\":"<<first_ns<<"}\n";
 }catch(const std::exception&e){std::cerr<<e.what();return 1;} }
