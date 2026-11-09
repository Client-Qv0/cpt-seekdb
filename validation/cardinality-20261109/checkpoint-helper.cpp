#include "storage.hpp"
#include <iostream>
#include <string>
int main(int argc,char **argv) {
  std::string directory="/data";
  for(int i=1;i<argc;++i) if(std::string(argv[i])=="--data-dir" && i+1<argc) directory=argv[++i];
  try {
    mvdb::Store store(directory);
    std::string command;
    while(std::getline(std::cin,command)) {
      if(command=="READY") std::cout << "{\"ok\":true,\"phase\":\"recovered\"}\n" << std::flush;
      else if(command=="CHECKPOINT") { store.checkpoint(); std::cout << "{\"ok\":true,\"phase\":\"checkpoint_complete\"}\n" << std::flush; }
      else return 2;
    }
  } catch(const std::exception &e) { std::cerr<<e.what()<<'\n';return 1; }
}
