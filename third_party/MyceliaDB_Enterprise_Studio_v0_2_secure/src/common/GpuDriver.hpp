
#pragma once
#include <string>
namespace mycelia {
class GpuDriver {
public:
    bool load();
    std::string status() const;
private:
    bool loaded_{false};
    std::string path_;
};
}
