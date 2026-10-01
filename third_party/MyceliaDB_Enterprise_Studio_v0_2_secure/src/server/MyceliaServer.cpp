
#include "server/MyceliaServer.hpp"
#include "common/Socket.hpp"
#include <iostream>
#include <thread>
#include <cstdlib>
#include <chrono>
namespace mycelia {
namespace {
bool constant_time_equal(const std::string& a, const std::string& b){
    const size_t n = a.size() > b.size() ? a.size() : b.size();
    unsigned char diff = static_cast<unsigned char>(a.size() ^ b.size());
    for(size_t i=0;i<n;++i){
        const unsigned char av = i<a.size() ? static_cast<unsigned char>(a[i]) : 0;
        const unsigned char bv = i<b.size() ? static_cast<unsigned char>(b[i]) : 0;
        diff = static_cast<unsigned char>(diff | (av ^ bv));
    }
    return diff == 0;
}
}

bool MyceliaServer::start(const std::string& host, int port){
    const char* token = std::getenv("MYCELIA_DB_AUTH_TOKEN");
    if(!token || std::string(token).size() < 48){
        std::cerr << "MyceliaDB refused startup: MYCELIA_DB_AUTH_TOKEN missing/too short\n";
        return false;
    }
    authToken_ = token;
    const char* storageRoot = std::getenv("MYCELIA_DB_STORAGE_ROOT");
    if(!storageRoot || !*storageRoot){
        std::cerr << "MyceliaDB refused startup: MYCELIA_DB_STORAGE_ROOT missing\n";
        return false;
    }
    if(host != "127.0.0.1" && host != "::1"){
        std::cerr << "MyceliaDB refused non-loopback bind\n";
        return false;
    }
    socket_system_start();
    server_=open_server_socket(host,port);
    running_=server_!=0;
    if(running_) std::cout<<"MyceliaDB Secure V2 listening "<<host<<":"<<port<<"\n";
    return running_;
}
void MyceliaServer::run(){
    constexpr int MAX_CLIENTS = 32;
    while(running_){
        socket_t c=accept_client(server_);
        if(!c) continue;
        const int previous = activeClients_.fetch_add(1);
        if(previous >= MAX_CLIENTS){
            activeClients_.fetch_sub(1);
            close_socket(c);
            continue;
        }
        std::thread(&MyceliaServer::serve_one,this,c).detach();
    }
}
void MyceliaServer::serve_one(socket_t client){
    struct ClientGuard {
        std::atomic<int>& counter;
        ~ClientGuard(){ counter.fetch_sub(1); }
    } guard{activeClients_};

    set_socket_timeouts(client, 2000, 5000);
    send_line(client,"MYCELIADB ENTERPRISE SECURE AUTH_REQUIRED");
    const auto authLine = recv_line(client);
    const std::string prefix = "AUTH ";
    const bool authOk = authLine.rfind(prefix,0)==0 && constant_time_equal(authLine.substr(prefix.size()), authToken_);
    if(!authOk){
        std::this_thread::sleep_for(std::chrono::milliseconds(250));
        send_line(client,"ERR AUTH");
        close_socket(client);
        return;
    }
    send_line(client,"OK AUTH");
    set_socket_timeouts(client, 600000, 120000);
    while(running_){
        auto line=recv_line(client);
        if(line.empty() || line=="QUIT") break;
        send_line(client, engine_.execute(line));
    }
    close_socket(client);
}
void MyceliaServer::stop(){ running_=false; if(server_) close_socket(server_); socket_system_stop(); }
}
