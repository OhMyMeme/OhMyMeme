# wechat_keyfinder Binary Protocol

## Overview

`wechat_keyfinder` is a helper binary that performs Windows process memory forensics
to extract WeChat's database encryption key.

It is **bundled inside the installer** (no runtime download) and reports version
information in its PE resources so the file is not an unsigned, metadata-less
binary. Build it with `cmake -S src/wechat_keyfinder -B build/wechat_keyfinder -A x64`
(MSVC only; there is no OpenSSL dependency — the required SHA-512 primitives are
implemented in-tree).

Python calls it via subprocess with command-line arguments and reads JSON from stdout.

## Invocation

```console
wechat_keyfinder --config offsets.json [--db-path <path>] [--pid <pid>]
```

### Key Extraction Strategy (priority order)

1. **Mask recovery** (default) — scans process memory for the 99-byte masked
   `x'<96hex>'` buffer; the 32-byte XOR mask is recovered from the known DB
   salt (first 16 bytes of emoticon.db). **No RVA offset needed**, robust across
   WeChat versions.
2. Legacy RVA pattern scan (fallback) — uses `cipher_literal_rva`/`mask_offset`
   from offsets.json.

> **Process selection**: when `--pid` is omitted, all matching `Weixin.exe`
> processes are enumerated and tried in turn. Only the process running the target
> account holds the key buffer in memory, so mask recovery naturally selects the
> correct one; `key_not_found` is reported if none yields a key.
>
> **Test-only `--key`**: a verified 64-hex key may be injected via `--key <hex64>`
> to skip memory forensics for manual verification. Because it passes the key on
> the command line (visible in the process list), the branch is compiled out of
> release builds entirely: it exists only when CMake is configured with
> `-DWKF_ENABLE_TEST_KEY=ON` (default `OFF`). Production callers obtain the key
> via mask recovery first, then the legacy RVA fallback when mask recovery fails.

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--config` | Yes | Path to offsets.json config file |
| `--db-path` | No | Path to the encrypted `emoticon.db`; when absent no key extraction is attempted |
| `--pid` | No | WeChat process ID (auto-detected if omitted) |
| `--key` | No | **Test-only, not present in release builds**: inject a verified 64-hex key directly (requires `-DWKF_ENABLE_TEST_KEY=ON`) |

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

## Output (stdout, JSON)

### Success

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

Field types: `key`/`salt` are lowercase hex strings (64 hex chars = 32-byte key,
32 hex chars = 16-byte salt); `pid`/`bytes_scanned` are integers; `module_base`
is a hex string. The in-memory URL snapshot scan and its `memory_snapshot` /
`regions_scanned` output fields were removed: no caller ever consumed them and
the associated string constants were the strongest static signal in the binary.

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
| `missing_config` | `--config` argument not provided |
| `invalid_pid` | `--pid` is not a number |
| `invalid_key` | `--key` is not exactly 64 hex characters (test-only builds) |
| `config_invalid` | Config file missing, malformed, or failed validation |
| `wechat_not_running` | WeChat process not found |
| `process_open_failed` | Cannot open process (permission denied) |
| `key_not_found` | Encryption key not found in memory (exit code 1) |
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
2. **No network access**: Binary makes no network requests; it reads only the
   target WeChat process memory and the explicitly specified local input files
   (e.g. the `emoticon.db` salt used by `--db-path` and mask recovery)
3. **Read-only**: Never writes to WeChat process or files
4. **Timeout**: Python enforces 90s execution timeout
5. **No runtime download**: the helper ships inside the installer and is resolved
   from the bundled resources; the app never fetches an executable at runtime

## Scan Budgets & Timeouts

| Scope | Limit |
|-------|-------|
| Mask-recovery scan (per process) | 30s wall-clock + `max_cipher_scan_bytes` read budget |
| RVA fallback scan (per process) | 30s wall-clock + `max_cipher_scan_bytes` read budget |
| Python wrapper | 90s subprocess timeout (bounds the total across all processes) |

`max_cipher_scan_bytes` caps the total bytes read during key scans. Reads are
bounded to the remaining budget on every chunk (including the final partial
read); negative or overflowing config values are rejected at load time. The
default is 512 MiB; lower it if scan latency is a concern. When `--pid` is omitted and multiple
`Weixin.exe` processes exist, each process receives its own 30s per-phase budget;
the total time across all processes is bounded by the Python wrapper's 90s
subprocess timeout.

## Integrity Verification

Python verifies the helper before execution. The expected hash lives in
`_WECHAT_KEYFINDER_SHA256` in `src/wechat_probe.py`; a missing or placeholder
value causes verification to **fail closed** (the helper is refused).
Development/testing can opt out explicitly via the
`OHMYMEME_INSECURE_SKIP_HELPER_HASH=1` environment variable.

MSVC builds are not reproducible (they embed timestamps), so the hash is pinned
**at build time** rather than committed by hand: `scripts/build.py` compiles the
helper, computes the digest of the actual artifact, rewrites
`_WECHAT_KEYFINDER_SHA256`, runs PyInstaller, and then restores the source file.
The check therefore protects against tampering after installation, which is what
it is for — it is not a statement about one particular build. `verify_binary_integrity`
reads the file in 64 KiB chunks and refuses to run anything that does not match.
