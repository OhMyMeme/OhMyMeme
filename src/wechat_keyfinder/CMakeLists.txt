cmake_minimum_required(VERSION 3.16)
project(wechat_keyfinder LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT WIN32)
    message(FATAL_ERROR "wechat_keyfinder is Windows-only")
endif()

add_executable(wechat_keyfinder wechat_keyfinder.cpp)

# 静态链接 libcrypto（OpenSSL 官方安装包的 libcrypto_static.lib），
# 避免运行时缺失 libcrypto-3-x64.dll。
# 注意：OpenSSL-Win64 的静态库位于 lib/VC/x64/MD/，是用动态 CRT(/MD)
# 编译的，故 exe 必须也用 /MD，否则链接报 __imp_* 无法解析。
set(OPENSSL_USE_STATIC_LIBS TRUE)
find_package(OpenSSL REQUIRED)
target_link_libraries(wechat_keyfinder OpenSSL::SSL OpenSSL::Crypto)

if(MSVC)
    # 与 OpenSSL 静态库保持一致使用动态 CRT(/MD)；仍为单文件 exe（无 OpenSSL DLL）
    set_property(TARGET wechat_keyfinder PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:DebugDLL>")
endif()
