
#include "studio/StudioShell.hpp"
#include "studio/MyceliaClient.hpp"
#include <iostream>
#include <string>
namespace mycelia {
int run_studio_shell(){
    MyceliaClient c;
    if(!c.connect("127.0.0.1",4555)){ std::cerr<<"Dante Studio: server not reachable\n"; return 2; }
    std::cout<<"============================================================\n";
    std::cout<<" MyceliaDB Enterprise Studio Professional\n";
    std::cout<<" Dante Manager | Mycelium Editor | Document Intelligence | Signal Trace Viewer\n";
    std::cout<<"============================================================\n";
    std::cout<<c.request("GPU_STATUS")<<"\n";
    std::cout<<"Commands: PING, SPAWN, LINK, MUTATE, GET, TRACE, PULSE, IMPORT_TEXT, IMPORT_SQL, LIST_DOCS, SEARCH, GPU_STATUS, HELP, QUIT\n";
    for(std::string line; std::cout<<"mycelia> " && std::getline(std::cin,line);){
        if(line=="QUIT"||line=="quit") break;
        std::cout<<c.request(line)<<"\n";
    }
    c.close(); return 0;
}
}
