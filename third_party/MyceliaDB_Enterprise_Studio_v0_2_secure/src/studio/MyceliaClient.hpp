
#pragma once
#include "common/Socket.hpp"
#include <string>
namespace mycelia {
class MyceliaClient {
public:
    bool connect(const std::string& host, int port);
    std::string request(const std::string& command);
    void close();
private:
    socket_t s_{0};
};
}
