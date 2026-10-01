
#include "common/GpuDriver.hpp"

#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <dlfcn.h>
#endif

namespace fs = std::filesystem;

namespace mycelia {

#ifdef _WIN32
namespace {
constexpr unsigned short PE_MACHINE_I386  = 0x014c;
constexpr unsigned short PE_MACHINE_AMD64 = 0x8664;
constexpr unsigned short PE_MACHINE_ARM64 = 0xaa64;

static bool read_at(std::ifstream& in, std::streamoff off, char* data, std::streamsize n) {
    in.seekg(off, std::ios::beg);
    if (!in.good()) return false;
    in.read(data, n);
    return in.gcount() == n;
}

static unsigned short u16le(const unsigned char* p) {
    return static_cast<unsigned short>(p[0] | (p[1] << 8));
}

static unsigned int u32le(const unsigned char* p) {
    return static_cast<unsigned int>(p[0] | (p[1] << 8) | (p[2] << 16) | (p[3] << 24));
}

static bool pe_machine_is_compatible(const fs::path& path, std::string& reason) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        reason = "not-readable";
        return false;
    }

    unsigned char mz[64]{};
    if (!read_at(in, 0, reinterpret_cast<char*>(mz), 64)) {
        reason = "too-small";
        return false;
    }

    if (mz[0] != 'M' || mz[1] != 'Z') {
        reason = "not-pe";
        return false;
    }

    const auto pe_off = static_cast<std::streamoff>(u32le(mz + 0x3c));
    unsigned char pe[6]{};
    if (!read_at(in, pe_off, reinterpret_cast<char*>(pe), 6)) {
        reason = "missing-pe-header";
        return false;
    }

    if (pe[0] != 'P' || pe[1] != 'E' || pe[2] != 0 || pe[3] != 0) {
        reason = "bad-pe-signature";
        return false;
    }

    const unsigned short machine = u16le(pe + 4);

#if defined(_M_X64) || defined(__x86_64__) || defined(_WIN64)
    if (machine == PE_MACHINE_AMD64) return true;
    std::ostringstream oss;
    oss << "wrong-architecture machine=0x" << std::hex << machine << " expected=x64";
    reason = oss.str();
    return false;
#elif defined(_M_ARM64) || defined(__aarch64__)
    if (machine == PE_MACHINE_ARM64) return true;
    std::ostringstream oss;
    oss << "wrong-architecture machine=0x" << std::hex << machine << " expected=arm64";
    reason = oss.str();
    return false;
#else
    if (machine == PE_MACHINE_I386) return true;
    std::ostringstream oss;
    oss << "wrong-architecture machine=0x" << std::hex << machine << " expected=x86";
    reason = oss.str();
    return false;
#endif
}

static HMODULE safe_load_library(const char* path) {
    // Load original Mycelia/OpenCL DLLs from their own folder so dependent
    // DLLs such as CC_OpenCl.dll are resolved next to mycelia_gpu_envelope.dll.
    // This is important when the Qt app is launched from build/bin.
    const fs::path dllPath = fs::absolute(path);
    const fs::path dllDir = dllPath.parent_path();

    const UINT previous = SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX);

    // Older Windows-compatible dependency directory hint.
    SetDllDirectoryW(dllDir.wstring().c_str());

    HMODULE h = LoadLibraryExW(
        dllPath.wstring().c_str(),
        nullptr,
        LOAD_WITH_ALTERED_SEARCH_PATH
    );

    SetDllDirectoryW(nullptr);
    SetErrorMode(previous);
    return h;
}
}
#endif

bool GpuDriver::load(){
    const char* candidates[] = {
#ifndef _WIN32
        "./third_party/prebuilt/libmycelia_gpu_envelope.so",
        "./third_party/prebuilt/libCC_OpenCl.so",
#else
        "./third_party/prebuilt/mycelia_gpu_envelope.dll",
        "./third_party/prebuilt/CC_OpenCl.dll",
        "mycelia_gpu_envelope.dll",
        "CC_OpenCl.dll",
#endif
        nullptr
    };

    std::string lastSkipped;

    for(int i=0;candidates[i];++i){
        const char* p=candidates[i];
        if(!fs::exists(p)) {
            continue;
        }

#ifdef _WIN32
        std::string reason;
        if(!pe_machine_is_compatible(p, reason)) {
            lastSkipped = std::string(p) + " skipped: " + reason;
            continue;
        }

        HMODULE h = safe_load_library(p);
        if(h){
            loaded_ = true;
            path_ = p;
            return true;
        }

        lastSkipped = std::string(p) + " skipped: LoadLibrary failed";
#else
        void* h=dlopen(p, RTLD_LAZY);
        if(h){
            loaded_=true;
            path_=p;
            return true;
        }

        // Linux packaging mode: if a generated .so exists but cannot be opened on
        // the build host, do not crash the database; report CPU fallback.
#endif
    }

    if(!lastSkipped.empty()){
        path_ = lastSkipped;
    }
    return false;
}

std::string GpuDriver::status() const{
    if(loaded_) return std::string("GPU_BRIDGE OK driver=")+path_;
    if(!path_.empty()) return std::string("GPU_BRIDGE FALLBACK cpu-propagation (") + path_ + ")";
    return "GPU_BRIDGE FALLBACK cpu-propagation";
}

}
