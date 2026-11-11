#include "exact_cache.hpp"
#include <iostream>
int main(){std::cout << "mvdb::exact::available=" << mvdb::exact::available() << "\n";return mvdb::exact::available()?0:1;}
