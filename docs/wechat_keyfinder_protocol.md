# wechat_keyfinder Binary Protocol

## Overview

`wechat_keyfinder` is a helper binary that performs Windows process memory forensics
to extract WeChat's database encryption key and in-memory sticker URL snapshots.

Python calls it via subprocess with JSON input/output for memory safety and auditability.

## Invocation

```console
wechat_keyfinder --config offsets.json [--db-path <path>] [--pid <pid>] [--no-snapshot]
```

### Key Extraction Strategy (priority order)

1. **Mask recovery** (default) — scans process memory for the 99-byte masked
   `x'<96hex>'` buffer; the 32-byte XOR mask is recovered from the known DB
   salt (first 16 bytes of emoticon.db). **No RVA offset needed**, robust across
   WeChat versions.
2. Legacy RVA pattern scan (fallback) — uses `cipher_literal_rva`/`mask_offset`
   from offsets.json.

> **Test-only `--key`**: for manual verification a verified 64-hex key may be
> injected via `--key <hex64>` to skip memory forensics. This passes the key on
> the command line (visible in the process list), so it is **NOT part of the
> production protocol** and must never be used in automated/release flows.
> Production callers obtain the key via the default mask-recovery path only.

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--config` | Yes | Path to offsets.json config file |
| `--db-path` | No | Path to the encrypted `emoticon.db`; when absent no key extraction is attempted |
| `--pid` | No | WeChat process ID (auto-detected if omitted) |
| `--no-snapshot` | No | Skip the in-memory URL snapshot scan (Python uses this; default output then omits `memory_snapshot`) |
| `--key` | No | **Test-only**: inject a verified 64-hex key directly, skip forensics (see note above) |

### Config File (offsets.json)

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
  "max_cipher_scan_bytes": 1099511627776,
  "max_scan_region": 536870912,
  "scan_chunk_size": 4194304,
  "scan_overlap": 2048,
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

## Output (stdout, JSON)

### Success

Default invocation (with `--no-snapshot`) omits `memory_snapshot`:

```json
{
  "ok": true,
  "pid": 1234,
  "module_base": "0x1A2B3C00",
  "key": "a1b2c3d4e5f6...",
  "salt": "f6e5d4c3b2a1...",
  "regions_scanned": 0,
  "bytes_scanned": 1048576
}
```

Without `--no-snapshot`, `memory_snapshot` is included (capped at 8 MiB):

### Error

```json
{
  "ok": false,
  "reason": "wechat_not_running",
  "detail": "No Weixin.exe process found"
}
```

### Error Codes

| reason | Description |
|--------|-------------|
| `wechat_not_running` | WeChat process not found |
| `version_unsupported` | WeChat version doesn't match config |
| `process_open_failed` | Cannot open process (permission denied) |
| `module_not_found` | Weixin.dll not found in process |
| `key_not_found` | Encryption key not found in memory |
| `key_validation_failed` | Found key but HMAC validation failed |
| `config_invalid` | Config file missing or malformed |
| `platform_unsupported` | Not running on Windows |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (see JSON output) |
| 2 | Invalid arguments |

## Security Considerations

1. **Binary integrity**: SHA-256 checksum verified before execution; **fails
   closed** when no real hash is configured (see below)
2. **No network access**: Binary performs only local memory reads
3. **Read-only**: Never writes to WeChat process or files
4. **Timeout**: Python enforces 90s execution timeout
5. **Output limits**: Memory snapshot capped at 8 MiB

## Integrity Verification

Python side verifies binary before execution. The shipped code **must** carry a
real SHA-256 for the release binary; the placeholder
`PLACEHOLDER_UPDATE_ON_RELEASE` causes verification to **fail closed** (the
helper is refused). Development/testing can opt out explicitly via the
`OHMYMEME_INSECURE_SKIP_HELPER_HASH=1` environment variable — never rely on the
placeholder in production:

```python
import hashlib

EXPECTED_SHA256 = "abc123..."  # real hash set at release time

def verify_binary(path: str) -> bool:
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest() == EXPECTED_SHA256
```

Checksum is updated alongside binary releases. Compute it with
`certutil -hashfile wechat_keyfinder.exe SHA256` and replace the placeholder in
`src/wechat_probe.py` before release.
