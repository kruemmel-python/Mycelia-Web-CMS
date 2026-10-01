
cmake_minimum_required(VERSION 3.20)
project(MyceliaDB_Enterprise_Studio_Professional VERSION 0.2.0 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

add_library(mycelia_common
  src/common/Protocol.cpp
  src/common/Socket.cpp
  src/common/GpuDriver.cpp
)
target_include_directories(mycelia_common PUBLIC src)

add_executable(myceliadb-server
  src/server/main.cpp
  src/server/MyceliaServer.cpp
  src/server/MyceliaEngine.cpp
)
target_link_libraries(myceliadb-server PRIVATE mycelia_common)

add_executable(myceliadb-studio
  src/studio/main.cpp
  src/studio/MyceliaClient.cpp
  src/studio/StudioShell.cpp
)
target_link_libraries(myceliadb-studio PRIVATE mycelia_common)

add_executable(myceliadb-smoketest
  src/tests/smoke.cpp
  src/server/MyceliaServer.cpp
  src/server/MyceliaEngine.cpp
  src/studio/MyceliaClient.cpp
  src/studio/StudioShell.cpp
)
target_compile_definitions(myceliadb-smoketest PRIVATE MYCELIA_EMBEDDED_TEST=1)
target_link_libraries(myceliadb-smoketest PRIVATE mycelia_common)

if(WIN32)
  target_link_libraries(mycelia_common PUBLIC ws2_32)
else()
  target_link_libraries(mycelia_common PUBLIC pthread dl)
endif()


# Optional real Qt Enterprise desktop surface.
# The console studio remains available when Qt is not installed.
find_package(Qt6 COMPONENTS Widgets Network QUIET)
if(Qt6_FOUND)
  set(CMAKE_AUTOMOC ON)
  add_executable(myceliadb-qtstudio
    src/qtstudio/main.cpp
  )
  target_link_libraries(myceliadb-qtstudio PRIVATE Qt6::Widgets Qt6::Network)
  target_compile_definitions(myceliadb-qtstudio PRIVATE MYCELIA_QT_PREMIUM=1)
  message(STATUS "Qt6 found: building myceliadb-qtstudio")
else()
  message(STATUS "Qt6 not found: skipping myceliadb-qtstudio. Install Qt6 Widgets/Network to build the premium GUI.")
endif()

# Hardened CMS runtime profile. Warnings are build failures by policy.
if(MSVC)
  foreach(t mycelia_common myceliadb-server)
    target_compile_options(${t} PRIVATE /W4 /WX /sdl /guard:cf /permissive-)
    target_compile_definitions(${t} PRIVATE _CRT_SECURE_NO_WARNINGS NOMINMAX)
  endforeach()
  target_link_options(myceliadb-server PRIVATE /guard:cf /DYNAMICBASE /NXCOMPAT)
else()
  foreach(t mycelia_common myceliadb-server)
    target_compile_options(${t} PRIVATE -Wall -Wextra -Wpedantic -Werror -fstack-protector-strong)
  endforeach()
  target_link_options(myceliadb-server PRIVATE -Wl,-z,relro,-z,now)
endif()
