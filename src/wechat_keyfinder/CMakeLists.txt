cmake_minimum_required(VERSION 3.16)
project(wechat_keyfinder LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT WIN32)
    message(FATAL_ERROR "wechat_keyfinder is Windows-only")
endif()

add_executable(wechat_keyfinder wechat_keyfinder.cpp)

if(WIN32)
    # 版本资源（发布者/产品/描述），避免"无签名+零元数据"特征组合
    target_sources(wechat_keyfinder PRIVATE wechat_keyfinder.rc)
endif()

# 测试用 --key 注入：发布构建必须保持 OFF（发布产物不得含该分支）
option(WKF_ENABLE_TEST_KEY "Enable the test-only --key argument" OFF)
if(WKF_ENABLE_TEST_KEY)
    target_compile_definitions(wechat_keyfinder PRIVATE WKF_ENABLE_TEST_KEY)
    message(WARNING "WKF_ENABLE_TEST_KEY=ON: 构建产物包含测试用 --key 分支，禁止用于发布")
endif()

# 仅需 SHA-512 系原语（PBKDF2-HMAC-SHA512 / HMAC-SHA512），源码内自包含实现，
# 不依赖 OpenSSL：避免链接静态 libcrypto 导致的体积膨胀与额外的静态特征面，
# 同时让构建只需 MSVC（CI 无需预装 OpenSSL）。
if(MSVC)
    # 源码为 UTF-8：强制 /utf-8，避免代码页(如 936)误读中文注释为 \ 续行吞掉代码
    target_compile_options(wechat_keyfinder PRIVATE /utf-8)
endif()
