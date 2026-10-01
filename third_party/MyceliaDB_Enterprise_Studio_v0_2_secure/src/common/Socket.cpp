
#include "common/Socket.hpp"
#include <cstring>
#include <cstdint>
#include <stdexcept>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
using native_socket_t = SOCKET;
static native_socket_t to_native(mycelia::socket_t s) { return static_cast<native_socket_t>(s); }
static mycelia::socket_t from_native(native_socket_t s) { return static_cast<mycelia::socket_t>(s); }
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
using native_socket_t = int;
static native_socket_t to_native(mycelia::socket_t s) { return s; }
static mycelia::socket_t from_native(native_socket_t s) { return s; }
#endif

namespace mycelia {

static bool is_invalid(socket_t s) {
#ifdef _WIN32
    return to_native(s) == INVALID_SOCKET || s == 0;
#else
    return s < 0;
#endif
}

bool socket_system_start(){
#ifdef _WIN32
    WSADATA d{};
    return WSAStartup(MAKEWORD(2,2), &d)==0;
#else
    return true;
#endif
}

void socket_system_stop(){
#ifdef _WIN32
    WSACleanup();
#endif
}

void close_socket(socket_t s){
    if (is_invalid(s)) return;
#ifdef _WIN32
    closesocket(to_native(s));
#else
    close(s);
#endif
}

socket_t open_server_socket(const std::string& host, int port){
    native_socket_t fd = ::socket(AF_INET, SOCK_STREAM, 0);
#ifdef _WIN32
    if(fd == INVALID_SOCKET) return 0;
#else
    if(fd < 0) return -1;
#endif

    int yes = 1;
#ifdef _WIN32
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<const char*>(&yes), sizeof(yes));
#else
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
#endif

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(static_cast<uint16_t>(port));
    inet_pton(AF_INET, host.c_str(), &addr.sin_addr);

    if(::bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        close_socket(from_native(fd));
        return 0;
    }
    if(::listen(fd, 16) < 0) {
        close_socket(from_native(fd));
        return 0;
    }
    return from_native(fd);
}

socket_t accept_client(socket_t server){
    native_socket_t c = ::accept(to_native(server), nullptr, nullptr);
#ifdef _WIN32
    if (c == INVALID_SOCKET) return 0;
#else
    if (c < 0) return -1;
#endif
    return from_native(c);
}

socket_t connect_socket(const std::string& host, int port){
    native_socket_t fd = ::socket(AF_INET, SOCK_STREAM, 0);
#ifdef _WIN32
    if(fd == INVALID_SOCKET) return 0;
#else
    if(fd < 0) return -1;
#endif
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(static_cast<uint16_t>(port));
    inet_pton(AF_INET, host.c_str(), &addr.sin_addr);
    if(::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        close_socket(from_native(fd));
        return 0;
    }
    return from_native(fd);
}


bool set_socket_timeouts(socket_t s, int receive_ms, int send_ms){
    if (is_invalid(s)) return false;
#ifdef _WIN32
    DWORD rcv = static_cast<DWORD>(receive_ms);
    DWORD snd = static_cast<DWORD>(send_ms);
    const int a = setsockopt(to_native(s), SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&rcv), sizeof(rcv));
    const int b = setsockopt(to_native(s), SOL_SOCKET, SO_SNDTIMEO, reinterpret_cast<const char*>(&snd), sizeof(snd));
#else
    timeval rcv{}; rcv.tv_sec=receive_ms/1000; rcv.tv_usec=(receive_ms%1000)*1000;
    timeval snd{}; snd.tv_sec=send_ms/1000; snd.tv_usec=(send_ms%1000)*1000;
    const int a = setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &rcv, sizeof(rcv));
    const int b = setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, &snd, sizeof(snd));
#endif
    return a==0 && b==0;
}

bool send_line(socket_t s, const std::string& line){
    if (is_invalid(s)) return false;
    std::string out = line + "\n";
    const char* p = out.data();
    size_t n = out.size();
    while(n > 0){
#ifdef _WIN32
        int r = ::send(to_native(s), p, static_cast<int>(n), 0);
#else
        ssize_t r = ::send(s, p, n, 0);
#endif
        if(r <= 0) return false;
        p += r;
        n -= static_cast<size_t>(r);
    }
    return true;
}

std::string recv_line(socket_t s){
    std::string out;
    out.reserve(4096);
    constexpr size_t MAX_LINE_BYTES = 1024 * 1024;
    char c = 0;
    while(true){
#ifdef _WIN32
        int r = ::recv(to_native(s), &c, 1, 0);
#else
        ssize_t r = ::recv(s, &c, 1, 0);
#endif
        if(r <= 0) break;
        if(c == '\n') break;
        if(c != '\r') {
            if(out.size() >= MAX_LINE_BYTES) return {};
            out.push_back(c);
        }
    }
    return out;
}

}
