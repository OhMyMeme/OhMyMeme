cmake_minimum_required(VERSION 3.16)
project(wechat_keyfinder LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT WIN32)
    message(FATAL_ERROR "wechat_keyfinder is Windows-only")
endif()

add_executable(wechat_keyfinder wechat_keyfinder.cpp)

# 静态链接 OpenSSL，避免运行时缺失 DLL（libcrypto-3-x64.dll 等）
# 推荐通过 vcpkg 使用 x64-windows-static triplet：
#   cmake -DCMAKE_TOOLCHAIN_FILE=<vcpkg>/scripts/buildsystems/vcpkg.cmake \
#         -DVCPKG_TARGET_TRIPLET=x64-windows-static
set(OPENSSL_USE_STATIC_LIBS TRUE)
find_package(OpenSSL REQUIRED)
target_link_libraries(wechat_keyfinder OpenSSL::SSL OpenSSL::Crypto)

# 静态链接 CRT，保证单文件可移植
if(MSVC)
    set_property(TARGET wechat_keyfinder PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()
