
#pragma once
#include <string>
namespace mycelia {
#ifdef _WIN32
using socket_t = unsigned long long;
#else
using socket_t = int;
#endif
bool socket_system_start();
void socket_system_stop();
socket_t open_server_socket(const std::string& host, int port);
socket_t accept_client(socket_t server);
socket_t connect_socket(const std::string& host, int port);
bool set_socket_timeouts(socket_t s, int receive_ms, int send_ms);
bool send_line(socket_t s, const std::string& line);
std::string recv_line(socket_t s);
void close_socket(socket_t s);
}
