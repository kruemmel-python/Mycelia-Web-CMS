
#include "studio/MyceliaClient.hpp"
namespace mycelia {
bool MyceliaClient::connect(const std::string& host, int port){
    socket_system_start();
    s_=connect_socket(host,port);
    if(!s_) return false;
    recv_line(s_);
    return true;
}
std::string MyceliaClient::request(const std::string& command){
    if(!send_line(s_,command)) return "ERR send failed";
    return recv_line(s_);
}
void MyceliaClient::close(){ if(s_) close_socket(s_); socket_system_stop(); }
}
