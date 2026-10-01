
#pragma once
#include "server/MyceliaEngine.hpp"
#include "common/Socket.hpp"
#include <atomic>
#include <thread>
#include <string>
namespace mycelia {
class MyceliaServer {
public:
    bool start(const std::string& host, int port);
    void run();
    void stop();
private:
    void serve_one(socket_t client);
    std::atomic<bool> running_{false};
    std::atomic<int> activeClients_{0};
    socket_t server_{0};
    std::string authToken_;
    MyceliaEngine engine_;
};
}
