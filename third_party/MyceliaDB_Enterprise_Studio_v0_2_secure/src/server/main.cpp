
#include "server/MyceliaServer.hpp"
int main(){
    mycelia::MyceliaServer server;
    if(!server.start("127.0.0.1",4555)) return 2;
    server.run();
}
