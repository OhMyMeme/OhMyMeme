# wechat_keyfinder Binary Protocol

## Overview

`wechat_keyfinder` is a helper binary that performs Windows process memory forensics
to extract WeChat's database encryption key and in-memory sticker URL snapshots.

Python calls it via subprocess with command-line arguments and reads JSON from stdout.

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

> **Process selection**: when `--pid` is omitted, all matching `Weixin.exe`
> processes are enumerated and tried in turn. Only the process running the target
> account holds the key buffer in memory, so mask recovery naturally selects the
> correct one; `key_not_found` is reported if none yields a key.
>
> **Test-only `--key`**: for manual verification a verified 64-hex key may be
> injected via `--key <hex64>` to skip memory forensics. This passes the key on
> the command line (visible in the process list), so it is **NOT part of the
> production protocol** and must never be used in automated/release flows.
> Production callers obtain the key via the full chain: mask recovery first,
> then the legacy RVA fallback when mask recovery fails — and never pass `--key`.

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
  "max_cipher_scan_bytes": 536870912,
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
  "key": "e4d2710a01d2c580d6277eb984af60547e9d9c30370e63d1534fe7c2f1ce6847",
  "salt": "02c6f1b8028410300d12d2a2f595586c",
  "regions_scanned": 0,
  "bytes_scanned": 1048576
}
```

Field types: `key`/`salt` are lowercase hex strings (64 hex chars = 32-byte key,
32 hex chars = 16-byte salt); `pid`/`regions_scanned`/`bytes_scanned` are
integers; `module_base` is a hex string.

`memory_snapshot` is **optional** and may be omitted whenever it is empty —
e.g. when scanning found no marker matches, the process could not be opened, or
`--no-snapshot` was passed. When present it is a single JSON string containing
raw UTF-8-decoded process bytes (marker lines matched during scanning), capped
at 8 MiB and truncated at a marker boundary on overflow. Callers should treat
the snapshot as best-effort, parse it for URL/md5 markers, and tolerate
truncation (the `key`/`salt` fields are always complete and authoritative):

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
| `invalid_key` | `--key` is not exactly 64 hex characters |
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
5. **Output limits**: Memory snapshot capped at 8 MiB

## Scan Budgets & Timeouts

| Scope | Limit |
|-------|-------|
| Mask-recovery scan (per process) | 30s wall-clock + `max_cipher_scan_bytes` read budget |
| RVA fallback scan (per process) | 30s wall-clock + `max_cipher_scan_bytes` read budget |
| Snapshot scan | 10s wall-clock + fixed 8 MiB output cap |
| Python wrapper | 90s subprocess timeout (bounds the total across all processes) |

`max_cipher_scan_bytes` caps the total bytes read during **key scans only**; it
does not affect the snapshot scan. The snapshot's 8 MiB cap is fixed and limits
the *output* string only (not reads). Reads during key scans are bounded to the
remaining budget on every chunk (including the final partial read); negative or
overflowing config values are rejected at load time. The default is 512 MiB;
lower it if scan latency is a concern. When `--pid` is omitted and multiple
`Weixin.exe` processes exist, each process receives its own 30s per-phase budget;
the total time across all processes is bounded by the Python wrapper's 90s
subprocess timeout.

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
`ohmymeme.integrations.imports.wechat` before release.
