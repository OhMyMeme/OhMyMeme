cmake_minimum_required(VERSION 3.16)
project(wechat_keyfinder LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT WIN32)
    message(FATAL_ERROR "wechat_keyfinder is Windows-only")
endif()

add_executable(wechat_keyfinder wechat_keyfinder.cpp)

find_package(OpenSSL REQUIRED)
target_link_libraries(wechat_keyfinder OpenSSL::SSL OpenSSL::Crypto)

# Static link CRT for portability
if(MSVC)
    set_property(TARGET wechat_keyfinder PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()
