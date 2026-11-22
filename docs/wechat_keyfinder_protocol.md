# wechat_keyfinder 二进制协议

简体中文（[English](wechat_keyfinder_protocol-en.md)）

## 概述

`wechat_keyfinder` 是一个辅助二进制，通过 Windows 进程内存取证提取微信的数据库解密密钥。

该二进制**打包在安装程序内**（运行时无下载），并在 PE 资源中报告版本信息，使文件不是无签名、无元数据的二进制。使用 `cmake -S src/wechat_keyfinder -B build/wechat_keyfinder -A x64` 构建（仅 MSVC；无 OpenSSL 依赖 —— 所需的 SHA-512 原语在库内实现）。

Python 通过子进程以命令行参数调用它，并从 stdout 读取 JSON。

## 调用

```console
wechat_keyfinder --config offsets.json [--db-path <path>] [--pid <pid>]
```

### 密钥提取策略（优先级顺序）

1. **掩码恢复**（默认）—— 在进程内存中扫描 99 字节的 `x'<96hex>'` 掩码缓冲；32 字节 XOR 掩码从已知 DB salt（emoticon.db 的前 16 字节）恢复。**无需 RVA 偏移**，跨微信版本稳健。
2. 旧版 RVA 模式扫描（回退）—— 使用 offsets.json 的 `cipher_literal_rva`/`mask_offset`。

> **进程选择**：省略 `--pid` 时，枚举所有匹配的 `Weixin.exe` 进程并逐一尝试。只有运行目标账号的进程内存中才持有密钥缓冲，因此掩码恢复会自然选中正确的进程；若无任何进程产出密钥则上报 `key_not_found`。
>
> **仅测试用 `--key`**：可通过 `--key <hex64>` 注入一个已验证的 64 位十六进制密钥以跳过内存取证，用于人工验证。因为它在命令行上传递密钥（在进程列表中可见），该分支在 release 构建中被整体编译移除：仅当 CMake 配置了 `-DWKF_ENABLE_TEST_KEY=ON`（默认 `OFF`）时才存在。生产调用方先经掩码恢复取密钥，掩码恢复失败时再用旧版 RVA 回退。

### 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--config` | 是 | offsets.json 配置文件路径 |
| `--db-path` | 否 | 加密的 `emoticon.db` 路径；缺省时不尝试密钥提取 |
| `--pid` | 否 | 微信进程 ID（省略时自动检测） |
| `--key` | 否 | **仅测试用，release 构建中不存在**：直接注入已验证的 64 位十六进制密钥（需要 `-DWKF_ENABLE_TEST_KEY=ON`） |

### 配置文件（offsets.json）

```json
{
  "version": "4.1.12.26",
  "module_name": "Weixin.dll",
  "process_name": "Weixin.exe",
  "cipher_literal_rva": "0x8779C8",
  "mask_offset": "0x5c8",
  "key_length": 99,
  "salt_length": 16,
  "key_xor_mask_length": 32,
  "max_cipher_scan_bytes": 536870912,
  "max_scan_region": 536870912,
  "scan_chunk_size": 4194304,
  "mac_salt_xor_byte": "0x3a",
  "pbkdf2_iterations": 2,
  "mac_input_length": 4016,
  "mac_digest_length": 64,
  "database_page_size": 4096,
  "database_encrypted_data_size": 4016,
  "database_encrypted_offset_page1": 16,
  "database_iv_offset_from_end": 80
}
```

## 输出（stdout，JSON）

### 成功

```json
{
  "ok": true,
  "pid": 1234,
  "module_base": "0x1A2B3C00",
  "key": "e4d2710a01d2c580d6277eb984af60547e9d9c30370e63d1534fe7c2f1ce6847",
  "salt": "02c6f1b8028410300d12d2a2f595586c",
  "bytes_scanned": 1048576
}
```

字段类型：`key`/`salt` 为小写十六进制字符串（64 位十六进制 = 32 字节密钥，32 位十六进制 = 16 字节 salt）；`pid`/`bytes_scanned` 为整数；`module_base` 为十六进制字符串。内存 URL 快照扫描及其 `memory_snapshot` / `regions_scanned` 输出字段已移除：没有任何调用方消费它们，且相关字符串常量是该二进制中最强的静态特征。

### 错误

```json
{
  "ok": false,
  "reason": "wechat_not_running",
  "detail": "No Weixin.exe process found"
}
```

### 错误码

| reason | 说明 |
|--------|------|
| `missing_config` | 未提供 `--config` 参数 |
| `invalid_pid` | `--pid` 不是数字 |
| `invalid_key` | `--key` 不是恰好 64 位十六进制（仅测试构建） |
| `config_invalid` | 配置文件缺失、格式错误或校验失败 |
| `wechat_not_running` | 未找到微信进程 |
| `process_open_failed` | 无法打开进程（权限不足） |
| `key_not_found` | 内存中未找到解密密钥（退出码 1） |
| `platform_unsupported` | 非 Windows 平台 |

## 退出码

| 码 | 含义 |
|------|---------|
| 0 | 成功 |
| 1 | 错误（见 JSON 输出） |
| 2 | 参数无效 |

## 安全考虑

1. **二进制完整性**：执行前校验 SHA-256 校验和；未配置真实哈希时**失败即拒绝**（fail closed，见下文）
2. **无网络访问**：二进制不发起任何网络请求；只读取目标微信进程内存和显式指定的本地输入文件（例如 `--db-path` 与掩码恢复使用的 `emoticon.db` salt）
3. **只读**：从不写入微信进程或文件
4. **超时**：Python 强制 90 秒执行超时
5. **无运行时下载**：辅助程序打包在安装程序内，从内置资源中解析；应用运行期间从不获取可执行文件

## 扫描预算与超时

| 范围 | 上限 |
|-------|------|
| 掩码恢复扫描（每进程） | 30 秒墙钟 + `max_cipher_scan_bytes` 读取预算 |
| RVA 回退扫描（每进程） | 30 秒墙钟 + `max_cipher_scan_bytes` 读取预算 |
| Python 包装层 | 90 秒子进程超时（限定所有进程的总时间） |

`max_cipher_scan_bytes` 限定密钥扫描期间的总读取字节数。每次分块读取（包括最后一次部分读取）都按剩余预算限界；负数或溢出的配置值在加载时即被拒绝。默认 512 MiB；若担心扫描延迟可降低该值。省略 `--pid` 且存在多个 `Weixin.exe` 进程时，每个进程获得各自 30 秒每阶段预算；所有进程的总时间受 Python 包装层 90 秒子进程超时的限定。

## 完整性校验

Python 在执行前校验辅助程序。期望哈希位于 `src/wechat_probe.py` 的 `_WECHAT_KEYFINDER_SHA256`；缺失或占位值会导致校验**失败即拒绝**（拒绝运行该辅助程序）。开发/测试可通过环境变量 `OHMYMEME_INSECURE_SKIP_HELPER_HASH=1` 显式跳过。

MSVC 构建不可复现（内嵌时间戳），因此哈希在**构建时**固定而非手工提交：`scripts/build.py` 编译辅助程序、计算实际产物的摘要、改写 `_WECHAT_KEYFINDER_SHA256`、运行 PyInstaller，然后恢复源文件。因此该校验防范的是安装后的篡改——这正是它的用途——而非对某一次特定构建的陈述。`verify_binary_integrity` 以 64 KiB 分块读取文件，拒绝运行任何不匹配的文件。
