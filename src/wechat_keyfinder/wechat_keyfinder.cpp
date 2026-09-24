/**
 * wechat_keyfinder - WeChat encryption key extraction helper
 *
 * Reads WeChat process memory to extract the database encryption key.
 *
 * Usage: wechat_keyfinder --config offsets.json [--db-path <path>] [--pid <pid>]
 * Output: JSON to stdout
 *
 * Security: This binary performs READ-ONLY access to WeChat process memory.
 * It does not modify any WeChat data or files.
 */

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <chrono>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_set>
#include <utility>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#include <tlhelp32.h>
#endif

// --- Minimal JSON builder (no external dependency) ---

namespace json {
struct Value {
  enum Type { Null, Bool, Number, String, Array, Object };
  Type type = Null;
  bool b_val = false;
  std::int64_t n_val = 0;
  std::string s_val;
  std::vector<Value> a_val;
  std::vector<std::pair<std::string, Value>> o_val;

  static Value null() { return {}; }
  static Value boolean(bool v) { Value r; r.type = Bool; r.b_val = v; return r; }
  static Value number(std::int64_t v) { Value r; r.type = Number; r.n_val = v; return r; }
  static Value string(const std::string& v) { Value r; r.type = String; r.s_val = v; return r; }
  static Value array() { Value r; r.type = Array; return r; }
  static Value object() { Value r; r.type = Object; return r; }

  void add(const std::string& k, Value v) { o_val.emplace_back(k, std::move(v)); }
  void add(Value v) { a_val.push_back(std::move(v)); }

  std::string dump(int = 0) const;
 private:
  static std::string escape(const std::string& s);
};

std::string Value::escape(const std::string& s) {
  std::ostringstream o;
  for (char c : s) {
    switch (c) {
      case '"': o << "\\\""; break;
      case '\\': o << "\\\\"; break;
      case '\n': o << "\\n"; break;
      case '\r': o << "\\r"; break;
      case '\t': o << "\\t"; break;
      default:
        // 控制字符与 >=0x80 的二进制字节统一 \u00XX 转义，保证输出合法 UTF-8/JSON
        if (static_cast<unsigned char>(c) < 0x20 ||
            static_cast<unsigned char>(c) >= 0x80) {
          o << "\\u" << std::hex << std::setw(4) << std::setfill('0')
            << (int)(unsigned char)c;
        } else {
          o << c;
        }
    }
  }
  return o.str();
}

std::string Value::dump(int indent) const {
  std::ostringstream o;
  switch (type) {
    case Null: o << "null"; break;
    case Bool: o << (b_val ? "true" : "false"); break;
    case Number: o << n_val; break;
    case String: o << '"' << escape(s_val) << '"'; break;
    case Array: {
      o << '[';
      for (size_t i = 0; i < a_val.size(); ++i) {
        if (i) o << ',';
        o << a_val[i].dump(indent);
      }
      o << ']';
      break;
    }
    case Object: {
      o << '{';
      for (size_t i = 0; i < o_val.size(); ++i) {
        if (i) o << ',';
        o << '"' << escape(o_val[i].first) << "\":" << o_val[i].second.dump(indent);
      }
      o << '}';
      break;
    }
  }
  return o.str();
}
}  // namespace json

// --- Minimal JSON parser (sufficient for config) ---

namespace json {

struct Parser {
  const char* p;
  Parser(const char* s) : p(s) {}
  void skip_ws() { while (*p && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) ++p; }
  bool expect(char c) { skip_ws(); if (*p == c) { ++p; return true; } return false; }

  Value parse() {
    skip_ws();
    if (*p == '"') return parse_string();
    if (*p == '{') return parse_object();
    if (*p == '[') return parse_array();
    if (*p == 't' && strncmp(p, "true", 4) == 0) { p += 4; return Value::boolean(true); }
    if (*p == 'f' && strncmp(p, "false", 5) == 0) { p += 5; return Value::boolean(false); }
    if (*p == 'n' && strncmp(p, "null", 4) == 0) { p += 4; return Value::null(); }
    if (*p == '-' || (*p >= '0' && *p <= '9')) return parse_number();
    return Value::null();
  }

  Value parse_string() {
    if (*p != '"') return Value::null();
    ++p;
    std::string s;
    while (*p && *p != '"') {
      if (*p == '\\') {
        ++p;
        switch (*p) {
          case '"': s += '"'; break;
          case '\\': s += '\\'; break;
          case 'n': s += '\n'; break;
          case 'r': s += '\r'; break;
          case 't': s += '\t'; break;
          case '/': s += '/'; break;
          default: s += *p; break;
        }
      } else {
        s += *p;
      }
      ++p;
    }
    if (*p == '"') ++p;
    return Value::string(s);
  }

  Value parse_number() {
    const char* start = p;
    if (*p == '-') ++p;
    while (*p >= '0' && *p <= '9') ++p;
    return Value::number(std::strtoll(start, nullptr, 10));
  }

  Value parse_object() {
    Value obj = Value::object();
    if (!expect('{')) return obj;
    skip_ws();
    if (*p == '}') { ++p; return obj; }
    while (true) {
      skip_ws();
      Value key = parse_string();
      if (!expect(':')) break;
      Value val = parse();
      obj.add(key.s_val, val);
      skip_ws();
      if (*p == ',') { ++p; continue; }
      if (*p == '}') { ++p; break; }
      break;
    }
    return obj;
  }

  Value parse_array() {
    Value arr = Value::array();
    if (!expect('[')) return arr;
    skip_ws();
    if (*p == ']') { ++p; return arr; }
    while (true) {
      arr.add(parse());
      skip_ws();
      if (*p == ',') { ++p; continue; }
      if (*p == ']') { ++p; break; }
      break;
    }
    return arr;
  }
};

Value parse(const std::string& s) { return Parser(s.c_str()).parse(); }

}  // namespace json

// --- Minimal SHA-512 / HMAC-SHA512 / PBKDF2-HMAC-SHA512 ---
// 自包含实现，替代 OpenSSL：仅需 SHA-512 系原语（PBKDF2-HMAC-SHA512 与 HMAC-SHA512），
// 引入整个静态 libcrypto 会显著增大二进制并扩大静态特征面。

namespace sha512 {

constexpr std::size_t kBlockSize = 128;
constexpr std::size_t kDigestSize = 64;

inline std::uint64_t rotr(std::uint64_t x, int n) {
  return (x >> n) | (x << (64 - n));
}

const std::uint64_t kK[80] = {
    0x428a2f98d728ae22ULL, 0x7137449123ef65cdULL, 0xb5c0fbcfec4d3b2fULL,
    0xe9b5dba58189dbbcULL, 0x3956c25bf348b538ULL, 0x59f111f1b605d019ULL,
    0x923f82a4af194f9bULL, 0xab1c5ed5da6d8118ULL, 0xd807aa98a3030242ULL,
    0x12835b0145706fbeULL, 0x243185be4ee4b28cULL, 0x550c7dc3d5ffb4e2ULL,
    0x72be5d74f27b896fULL, 0x80deb1fe3b1696b1ULL, 0x9bdc06a725c71235ULL,
    0xc19bf174cf692694ULL, 0xe49b69c19ef14ad2ULL, 0xefbe4786384f25e3ULL,
    0x0fc19dc68b8cd5b5ULL, 0x240ca1cc77ac9c65ULL, 0x2de92c6f592b0275ULL,
    0x4a7484aa6ea6e483ULL, 0x5cb0a9dcbd41fbd4ULL, 0x76f988da831153b5ULL,
    0x983e5152ee66dfabULL, 0xa831c66d2db43210ULL, 0xb00327c898fb213fULL,
    0xbf597fc7beef0ee4ULL, 0xc6e00bf33da88fc2ULL, 0xd5a79147930aa725ULL,
    0x06ca6351e003826fULL, 0x142929670a0e6e70ULL, 0x27b70a8546d22ffcULL,
    0x2e1b21385c26c926ULL, 0x4d2c6dfc5ac42aedULL, 0x53380d139d95b3dfULL,
    0x650a73548baf63deULL, 0x766a0abb3c77b2a8ULL, 0x81c2c92e47edaee6ULL,
    0x92722c851482353bULL, 0xa2bfe8a14cf10364ULL, 0xa81a664bbc423001ULL,
    0xc24b8b70d0f89791ULL, 0xc76c51a30654be30ULL, 0xd192e819d6ef5218ULL,
    0xd69906245565a910ULL, 0xf40e35855771202aULL, 0x106aa07032bbd1b8ULL,
    0x19a4c116b8d2d0c8ULL, 0x1e376c085141ab53ULL, 0x2748774cdf8eeb99ULL,
    0x34b0bcb5e19b48a8ULL, 0x391c0cb3c5c95a63ULL, 0x4ed8aa4ae3418acbULL,
    0x5b9cca4f7763e373ULL, 0x682e6ff3d6b2b8a3ULL, 0x748f82ee5defb2fcULL,
    0x78a5636f43172f60ULL, 0x84c87814a1f0ab72ULL, 0x8cc702081a6439ecULL,
    0x90befffa23631e28ULL, 0xa4506cebde82bde9ULL, 0xbef9a3f7b2c67915ULL,
    0xc67178f2e372532bULL, 0xca273eceea26619cULL, 0xd186b8c721c0c207ULL,
    0xeada7dd6cde0eb1eULL, 0xf57d4f7fee6ed178ULL, 0x06f067aa72176fbaULL,
    0x0a637dc5a2c898a6ULL, 0x113f9804bef90daeULL, 0x1b710b35131c471bULL,
    0x28db77f523047d84ULL, 0x32caab7b40c72493ULL, 0x3c9ebe0a15c9bebcULL,
    0x431d67c49c100d4cULL, 0x4cc5d4becb3e42b6ULL, 0x597f299cfc657e2aULL,
    0x5fcb6fab3ad6faecULL, 0x6c44198c4a475817ULL};

class Sha512 {
 public:
  Sha512() { reset(); }

  void reset() {
    h_[0] = 0x6a09e667f3bcc908ULL;
    h_[1] = 0xbb67ae8584caa73bULL;
    h_[2] = 0x3c6ef372fe94f82bULL;
    h_[3] = 0xa54ff53a5f1d36f1ULL;
    h_[4] = 0x510e527fade682d1ULL;
    h_[5] = 0x9b05688c2b3e6c1fULL;
    h_[6] = 0x1f83d9abfb41bd6bULL;
    h_[7] = 0x5be0cd19137e2179ULL;
    total_ = 0;
    buf_len_ = 0;
  }

  void update(const void* data, std::size_t len) {
    const unsigned char* p = static_cast<const unsigned char*>(data);
    total_ += static_cast<std::uint64_t>(len);
    if (buf_len_ > 0) {
      std::size_t take = (std::min)(kBlockSize - buf_len_, len);
      ::memcpy(buf_ + buf_len_, p, take);
      buf_len_ += take;
      p += take;
      len -= take;
      if (buf_len_ == kBlockSize) {
        compress(buf_);
        buf_len_ = 0;
      }
    }
    while (len >= kBlockSize) {
      compress(p);
      p += kBlockSize;
      len -= kBlockSize;
    }
    if (len > 0) {
      ::memcpy(buf_, p, len);
      buf_len_ = len;
    }
  }

  void final(unsigned char out[kDigestSize]) {
    const std::uint64_t bit_len = total_ * 8;
    unsigned char pad = 0x80;
    update(&pad, 1);
    const unsigned char zero = 0x00;
    while (buf_len_ != kBlockSize - 16) update(&zero, 1);
    unsigned char len_be[16];
    for (int i = 0; i < 8; ++i) len_be[i] = 0;
    for (int i = 7; i >= 0; --i) {
      len_be[8 + i] = static_cast<unsigned char>(bit_len >> ((7 - i) * 8));
    }
    ::memcpy(buf_ + buf_len_, len_be, 16);
    compress(buf_);
    for (int i = 0; i < 8; ++i) {
      for (int j = 0; j < 8; ++j) {
        out[i * 8 + j] = static_cast<unsigned char>(h_[i] >> ((7 - j) * 8));
      }
    }
  }

 private:
  void compress(const unsigned char* block) {
    std::uint64_t w[80];
    for (int i = 0; i < 16; ++i) {
      std::uint64_t v = 0;
      for (int j = 0; j < 8; ++j) v = (v << 8) | block[i * 8 + j];
      w[i] = v;
    }
    for (int i = 16; i < 80; ++i) {
      const std::uint64_t s0 = rotr(w[i - 15], 1) ^ rotr(w[i - 15], 8) ^ (w[i - 15] >> 7);
      const std::uint64_t s1 = rotr(w[i - 2], 19) ^ rotr(w[i - 2], 61) ^ (w[i - 2] >> 6);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    std::uint64_t a = h_[0], b = h_[1], c = h_[2], d = h_[3];
    std::uint64_t e = h_[4], f = h_[5], g = h_[6], hh = h_[7];
    for (int i = 0; i < 80; ++i) {
      const std::uint64_t s1 = rotr(e, 14) ^ rotr(e, 18) ^ rotr(e, 41);
      const std::uint64_t ch = (e & f) ^ ((~e) & g);
      const std::uint64_t t1 = hh + s1 + ch + kK[i] + w[i];
      const std::uint64_t s0 = rotr(a, 28) ^ rotr(a, 34) ^ rotr(a, 39);
      const std::uint64_t maj = (a & b) ^ (a & c) ^ (b & c);
      const std::uint64_t t2 = s0 + maj;
      hh = g; g = f; f = e; e = d + t1;
      d = c; c = b; b = a; a = t1 + t2;
    }
    h_[0] += a; h_[1] += b; h_[2] += c; h_[3] += d;
    h_[4] += e; h_[5] += f; h_[6] += g; h_[7] += hh;
  }

  std::uint64_t h_[8];
  std::uint64_t total_;
  unsigned char buf_[kBlockSize];
  std::size_t buf_len_;
};

void hmac(const unsigned char* key, std::size_t key_len,
          const unsigned char* msg, std::size_t msg_len,
          unsigned char out[kDigestSize]) {
  unsigned char k[kBlockSize];
  ::memset(k, 0, sizeof(k));
  if (key_len > kBlockSize) {
    Sha512 tmp;
    tmp.update(key, key_len);
    tmp.final(k);
  } else {
    ::memcpy(k, key, key_len);
  }
  unsigned char ipad[kBlockSize];
  unsigned char opad[kBlockSize];
  for (std::size_t i = 0; i < kBlockSize; ++i) {
    ipad[i] = static_cast<unsigned char>(k[i] ^ 0x36);
    opad[i] = static_cast<unsigned char>(k[i] ^ 0x5c);
  }
  unsigned char inner[kDigestSize];
  Sha512 s1;
  s1.update(ipad, sizeof(ipad));
  s1.update(msg, msg_len);
  s1.final(inner);
  Sha512 s2;
  s2.update(opad, sizeof(opad));
  s2.update(inner, sizeof(inner));
  s2.final(out);
}

void pbkdf2_hmac(const unsigned char* password, std::size_t password_len,
                 const unsigned char* salt, std::size_t salt_len,
                 int iterations, unsigned char* out, std::size_t out_len) {
  const std::size_t blocks = (out_len + kDigestSize - 1) / kDigestSize;
  std::vector<unsigned char> msg(salt_len + 4);
  if (salt_len > 0) ::memcpy(msg.data(), salt, salt_len);
  for (std::size_t block = 1; block <= blocks; ++block) {
    const std::uint32_t idx = static_cast<std::uint32_t>(block);
    msg[salt_len] = static_cast<unsigned char>((idx >> 24) & 0xff);
    msg[salt_len + 1] = static_cast<unsigned char>((idx >> 16) & 0xff);
    msg[salt_len + 2] = static_cast<unsigned char>((idx >> 8) & 0xff);
    msg[salt_len + 3] = static_cast<unsigned char>(idx & 0xff);
    unsigned char u[kDigestSize];
    unsigned char acc[kDigestSize];
    hmac(password, password_len, msg.data(), msg.size(), u);
    ::memcpy(acc, u, sizeof(acc));
    for (int iter = 1; iter < iterations; ++iter) {
      unsigned char next[kDigestSize];
      hmac(password, password_len, u, sizeof(u), next);
      ::memcpy(u, next, sizeof(u));
      for (std::size_t i = 0; i < kDigestSize; ++i) acc[i] ^= u[i];
    }
    const std::size_t offset = (block - 1) * kDigestSize;
    const std::size_t take = (std::min)(kDigestSize, out_len - offset);
    ::memcpy(out + offset, acc, take);
  }
}

}  // namespace sha512

// --- Config structure ---

struct Config {
  std::string version = "4.1.11.55";
  std::string module_name = "Weixin.dll";
  std::string process_name = "Weixin.exe";
  std::uintptr_t cipher_literal_rva = 0x8779C8;
  std::uintptr_t mask_offset = 0x5c8;
  int key_length = 99;
  int salt_length = 16;
  int key_xor_mask_length = 32;
  std::size_t max_cipher_scan_bytes = 536870912ULL;  // 512 MiB
  std::size_t max_scan_region = 536870912ULL;
  std::size_t scan_chunk_size = 4194304ULL;
  unsigned char mac_salt_xor_byte = 0x3a;
  int pbkdf2_iterations = 2;
  int mac_input_length = 4016;
  int mac_digest_length = 64;
  int database_page_size = 4096;
  int database_encrypted_data_size = 4016;
  int database_encrypted_offset_page1 = 16;
  int database_iv_offset_from_end = 80;
};

// --- Config loading helpers ---

std::string read_file(const std::string& path) {
  std::ifstream f(path);
  if (!f) return "";
  std::ostringstream ss;
  ss << f.rdbuf();
  return ss.str();
}

std::optional<std::uint64_t> parse_hex(const std::string& s) {
  if (s.size() < 3 || s[0] != '0' || (s[1] != 'x' && s[1] != 'X')) return std::nullopt;
  try {
    return std::stoull(s.substr(2), nullptr, 16);
  } catch (...) {
    return std::nullopt;
  }
}

std::int64_t json_as_int(const json::Value& v, std::int64_t def = 0) {
  if (v.type == json::Value::Number) return v.n_val;
  if (v.type == json::Value::String) {
    try { return std::stoll(v.s_val); } catch (...) {}
  }
  return def;
}

std::string json_as_string(const json::Value& v, const std::string& def = "") {
  if (v.type == json::Value::String) return v.s_val;
  return def;
}

bool load_config(const std::string& path, Config& cfg) {
  std::string content = read_file(path);
  if (content.empty()) return false;
  json::Value j = json::parse(content);
  if (j.type != json::Value::Object) return false;
  if (j.o_val.empty()) return false;
  for (const auto& kv : j.o_val) {
    const auto& k = kv.first;
    const auto& v = kv.second;
    if (k == "version") cfg.version = json_as_string(v, cfg.version);
    else if (k == "module_name") cfg.module_name = json_as_string(v, cfg.module_name);
    else if (k == "process_name") cfg.process_name = json_as_string(v, cfg.process_name);
    else if (k == "cipher_literal_rva") {
      if (v.type == json::Value::String) { auto h = parse_hex(v.s_val); if (h) cfg.cipher_literal_rva = (std::uintptr_t)*h; }
      else if (v.type == json::Value::Number) cfg.cipher_literal_rva = (std::uintptr_t)json_as_int(v, 0x8779C8);
    }
    else if (k == "mask_offset") {
      if (v.type == json::Value::String) { auto h = parse_hex(v.s_val); if (h) cfg.mask_offset = (std::uintptr_t)*h; }
      else if (v.type == json::Value::Number) cfg.mask_offset = (std::uintptr_t)json_as_int(v, 0x5c8);
    }
    else if (k == "key_length") cfg.key_length = (int)json_as_int(v, cfg.key_length);
    else if (k == "salt_length") cfg.salt_length = (int)json_as_int(v, cfg.salt_length);
    else if (k == "key_xor_mask_length") cfg.key_xor_mask_length = (int)json_as_int(v, cfg.key_xor_mask_length);
    else if (k == "max_cipher_scan_bytes") {
      std::int64_t scan_bytes = json_as_int(v, (std::int64_t)cfg.max_cipher_scan_bytes);
      if (scan_bytes <= 0) return false;
      cfg.max_cipher_scan_bytes = (std::size_t)scan_bytes;
    }
    else if (k == "max_scan_region") cfg.max_scan_region = (std::size_t)json_as_int(v, (std::int64_t)cfg.max_scan_region);
    else if (k == "scan_chunk_size") cfg.scan_chunk_size = (std::size_t)json_as_int(v, (std::int64_t)cfg.scan_chunk_size);
    else if (k == "mac_salt_xor_byte") {
      if (v.type == json::Value::String) { auto h = parse_hex(v.s_val); if (h) cfg.mac_salt_xor_byte = (unsigned char)*h; }
      else if (v.type == json::Value::Number) cfg.mac_salt_xor_byte = (unsigned char)json_as_int(v, 0x3a);
    }
    else if (k == "pbkdf2_iterations") cfg.pbkdf2_iterations = (int)json_as_int(v, cfg.pbkdf2_iterations);
    else if (k == "mac_input_length") cfg.mac_input_length = (int)json_as_int(v, cfg.mac_input_length);
    else if (k == "mac_digest_length") cfg.mac_digest_length = (int)json_as_int(v, cfg.mac_digest_length);
    else if (k == "database_page_size") cfg.database_page_size = (int)json_as_int(v, cfg.database_page_size);
    else if (k == "database_encrypted_data_size") cfg.database_encrypted_data_size = (int)json_as_int(v, cfg.database_encrypted_data_size);
    else if (k == "database_encrypted_offset_page1") cfg.database_encrypted_offset_page1 = (int)json_as_int(v, cfg.database_encrypted_offset_page1);
    else if (k == "database_iv_offset_from_end") cfg.database_iv_offset_from_end = (int)json_as_int(v, cfg.database_iv_offset_from_end);
  }
  // 校验易错值：掩码长度需为 2 的幂、分块大小需足够大、密钥长度需能容纳 99 字节格式
  if (cfg.key_xor_mask_length <= 0 ||
      (cfg.key_xor_mask_length & (cfg.key_xor_mask_length - 1)) != 0) {
    return false;
  }
  if (cfg.scan_chunk_size < 1024) {
    return false;
  }
  if (cfg.key_length < 99 || cfg.salt_length <= 0 || cfg.salt_length > 16) {
    return false;
  }
  if (cfg.database_page_size < 1024 || cfg.database_page_size > 65536) {
    return false;
  }
  return true;
}

// --- Platform-specific implementation (Windows only) ---

#ifdef _WIN32

std::string to_hex(const std::vector<unsigned char>& bytes) {
  std::ostringstream o;
  o << std::hex << std::setfill('0');
  for (auto b : bytes) o << std::setw(2) << (int)b;
  return o.str();
}

int hex_nibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

std::optional<std::vector<unsigned char>> decode_hex(std::string_view value) {
  if (value.size() % 2 != 0) return std::nullopt;
  std::vector<unsigned char> result(value.size() / 2);
  for (size_t i = 0; i < result.size(); ++i) {
    int hi = hex_nibble(value[i * 2]);
    int lo = hex_nibble(value[i * 2 + 1]);
    if (hi < 0 || lo < 0) return std::nullopt;
    result[i] = static_cast<unsigned char>((hi << 4) | lo);
  }
  return result;
}

std::optional<std::uintptr_t> find_module_base(DWORD pid, const std::string& module_name) {
  HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid);
  if (snap == INVALID_HANDLE_VALUE) return std::nullopt;
  std::uintptr_t base = 0;
  MODULEENTRY32W entry{};
  entry.dwSize = sizeof(entry);
  std::wstring wname(module_name.begin(), module_name.end());
  if (Module32FirstW(snap, &entry)) {
    do {
      if (_wcsicmp(entry.szModule, wname.c_str()) == 0) {
        base = reinterpret_cast<std::uintptr_t>(entry.modBaseAddr);
        break;
      }
    } while (Module32NextW(snap, &entry));
  }
  CloseHandle(snap);
  return base ? std::optional(base) : std::nullopt;
}

std::optional<std::vector<unsigned char>> read_process_bytes(HANDLE process, std::uintptr_t address, std::size_t size) {
  if (size == 0 || size > 4096) return std::nullopt;
  std::vector<unsigned char> bytes(size);
  SIZE_T read = 0;
  if (!ReadProcessMemory(process, reinterpret_cast<const void*>(address), bytes.data(), size, &read) || read != size)
    return std::nullopt;
  return bytes;
}

bool readable_protection(DWORD protect) {
  DWORD base = protect & 0xff;
  return base == PAGE_READONLY || base == PAGE_READWRITE ||
         base == PAGE_WRITECOPY || base == PAGE_EXECUTE_READ ||
         base == PAGE_EXECUTE_READWRITE || base == PAGE_EXECUTE_WRITECOPY;
}

struct WechatRawKey {
  std::vector<unsigned char> key;
  std::vector<unsigned char> salt;
};

std::optional<WechatRawKey> find_wechat_key(HANDLE process, std::uintptr_t module_base,
                                            const std::string& db_path,
                                            const Config& cfg, std::size_t& scanned) {
  std::ifstream db(db_path, std::ios::binary);
  if (!db) return std::nullopt;
  std::array<unsigned char, 4096> first_page{};
  db.read(reinterpret_cast<char*>(first_page.data()), first_page.size());
  if (db.gcount() != static_cast<std::streamsize>(first_page.size())) return std::nullopt;

  std::vector<unsigned char> db_salt(first_page.begin(), first_page.begin() + cfg.salt_length);
  auto mask = read_process_bytes(process, module_base + cfg.cipher_literal_rva + cfg.mask_offset, cfg.key_xor_mask_length);
  if (!mask) return std::nullopt;

  auto literal = module_base + cfg.cipher_literal_rva;
  std::array<unsigned char, 16> pattern{};
  ::memcpy(pattern.data(), &literal, sizeof(literal));
  std::uint64_t node_length = 30;
  ::memcpy(pattern.data() + 8, &node_length, sizeof(node_length));

  SYSTEM_INFO si{};
  GetNativeSystemInfo(&si);
  auto address = reinterpret_cast<std::uintptr_t>(si.lpMinimumApplicationAddress);
  auto maximum = reinterpret_cast<std::uintptr_t>(si.lpMaximumApplicationAddress);
  std::unordered_set<std::uintptr_t> objects;
  auto started = std::chrono::steady_clock::now();

  while (address < maximum && scanned < cfg.max_cipher_scan_bytes &&
         std::chrono::duration_cast<std::chrono::seconds>(std::chrono::steady_clock::now() - started).count() < 30) {
    MEMORY_BASIC_INFORMATION mem{};
    if (VirtualQueryEx(process, reinterpret_cast<void*>(address), &mem, sizeof(mem)) != sizeof(mem)) break;
    auto next = reinterpret_cast<std::uintptr_t>(mem.BaseAddress) + mem.RegionSize;
    if (next <= address) break;
    if (mem.State == MEM_COMMIT && mem.Type == MEM_PRIVATE &&
        mem.RegionSize <= cfg.max_scan_region && readable_protection(mem.Protect) &&
        !(mem.Protect & PAGE_GUARD)) {
      for (std::size_t offset = 0; offset < mem.RegionSize && scanned < cfg.max_cipher_scan_bytes;
           offset += cfg.scan_chunk_size - 15) {
        const auto remaining = cfg.max_cipher_scan_bytes - scanned;
        auto count = (std::min)((std::min)(cfg.scan_chunk_size, mem.RegionSize - offset), remaining);
        std::vector<unsigned char> buffer(count);
        SIZE_T read = 0;
        if (!ReadProcessMemory(process, reinterpret_cast<const void*>(
            reinterpret_cast<std::uintptr_t>(mem.BaseAddress) + offset), buffer.data(), count, &read) || read == 0)
          continue;
        scanned += read;
        buffer.resize(read);
        for (size_t hit = 0; hit + pattern.size() <= buffer.size(); ++hit) {
          if (!std::equal(pattern.begin(), pattern.end(), buffer.begin() + hit, buffer.begin() + hit + pattern.size())) continue;
          auto hit_addr = reinterpret_cast<std::uintptr_t>(mem.BaseAddress) + offset + hit;
          auto ptr = read_process_bytes(process, hit_addr + 24, 8);
          if (!ptr) continue;
          std::uintptr_t object = 0;
          ::memcpy(&object, ptr->data(), sizeof(object));
          if (object == 0 || !objects.insert(object).second) continue;
          auto raw_meta = read_process_bytes(process, object + 0x88, 24);
          if (!raw_meta) continue;
          std::uintptr_t raw_buffer = 0;
          std::uint64_t raw_length = 0;
          ::memcpy(&raw_buffer, raw_meta->data() + 8, 8);
          ::memcpy(&raw_length, raw_meta->data() + 16, 8);
          if (raw_buffer == 0 || raw_length != (std::uint64_t)cfg.key_length) continue;
          auto encoded = read_process_bytes(process, raw_buffer, cfg.key_length);
          if (!encoded) continue;
          std::vector<unsigned char> decoded(cfg.key_length);
          for (size_t i = 0; i < decoded.size(); ++i)
            decoded[i] =
                (*encoded)[i] ^ (*mask)[i % cfg.key_xor_mask_length];

          if (decoded[0] != 'x' || decoded[1] != '\'' || decoded[cfg.key_length - 1] != '\'') continue;
          auto key_hex = std::string_view(reinterpret_cast<const char*>(decoded.data()) + 2, 64);
          auto salt_hex = std::string_view(reinterpret_cast<const char*>(decoded.data()) + 66, 32);
          auto key = decode_hex(key_hex);
          auto salt = decode_hex(salt_hex);
          if (!key || !salt || key->size() != 32 || salt->size() != (size_t)cfg.salt_length) continue;
          if (*salt != db_salt) continue;

          std::array<unsigned char, 16> mac_salt{};
          for (size_t i = 0; i < mac_salt.size(); ++i) mac_salt[i] = first_page[i] ^ cfg.mac_salt_xor_byte;
          std::array<unsigned char, 32> mac_key{};
          sha512::pbkdf2_hmac(key->data(), key->size(), mac_salt.data(), mac_salt.size(),
                              cfg.pbkdf2_iterations, mac_key.data(), mac_key.size());
          std::array<unsigned char, 4020> input{};
          ::memcpy(input.data(), first_page.data() + 16, 4016);
          input[4016] = 1;
          std::array<unsigned char, sha512::kDigestSize> digest{};
          sha512::hmac(mac_key.data(), mac_key.size(), input.data(), input.size(), digest.data());
          if (cfg.mac_digest_length == (int)sha512::kDigestSize &&
              std::equal(digest.begin(), digest.begin() + cfg.mac_digest_length, first_page.end() - cfg.mac_digest_length, first_page.end())) {
            return WechatRawKey{*key, *salt};
          }
        }
      }
    }
    address = next;
  }
  return std::nullopt;
}

// --- 掩码恢复式密钥提取（按格式扫描，无需 RVA 偏移） ---

bool is_hex_char(unsigned char c) {
  return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
}

std::optional<WechatRawKey> find_wechat_key_masked(HANDLE process,
                                                   const std::string& db_path,
                                                   const Config& cfg,
                                                   std::size_t& scanned) {
  std::ifstream db(db_path, std::ios::binary);
  if (!db) return std::nullopt;
  std::array<unsigned char, 4096> first_page{};
  db.read(reinterpret_cast<char*>(first_page.data()), first_page.size());
  if (db.gcount() != static_cast<std::streamsize>(first_page.size())) return std::nullopt;

  // db_salt 前 16 字节 -> 32 字符 ASCII hex（掩码恢复的已知明文）
  std::string salt_ascii;
  salt_ascii.reserve(32);
  char hex_buf[3];
  for (int i = 0; i < 16; ++i) {
    std::snprintf(hex_buf, sizeof(hex_buf), "%02x", first_page[i]);
    salt_ascii += hex_buf;
  }

  SYSTEM_INFO si{};
  GetNativeSystemInfo(&si);
  auto address = reinterpret_cast<std::uintptr_t>(si.lpMinimumApplicationAddress);
  auto maximum = reinterpret_cast<std::uintptr_t>(si.lpMaximumApplicationAddress);
  auto started = std::chrono::steady_clock::now();
  const std::size_t window = static_cast<std::size_t>(cfg.key_length);

  while (address < maximum && scanned < cfg.max_cipher_scan_bytes &&
         std::chrono::duration_cast<std::chrono::seconds>(std::chrono::steady_clock::now() - started).count() < 30) {
    MEMORY_BASIC_INFORMATION mem{};
    if (VirtualQueryEx(process, reinterpret_cast<void*>(address), &mem, sizeof(mem)) != sizeof(mem)) break;
    auto next = reinterpret_cast<std::uintptr_t>(mem.BaseAddress) + mem.RegionSize;
    if (next <= address) break;
    if (mem.State == MEM_COMMIT && mem.RegionSize <= cfg.max_scan_region &&
        readable_protection(mem.Protect) && !(mem.Protect & PAGE_GUARD)) {
      for (std::size_t offset = 0; offset < mem.RegionSize && scanned < cfg.max_cipher_scan_bytes;
           offset += cfg.scan_chunk_size - 128) {
        const auto remaining = cfg.max_cipher_scan_bytes - scanned;
        auto count = (std::min)((std::min)(cfg.scan_chunk_size, mem.RegionSize - offset), remaining);
        std::vector<unsigned char> buffer(count);
        SIZE_T read = 0;
        if (!ReadProcessMemory(process, reinterpret_cast<const void*>(
            reinterpret_cast<std::uintptr_t>(mem.BaseAddress) + offset), buffer.data(), count, &read) || read == 0)
          continue;
        scanned += read;
        buffer.resize(read);
        if (buffer.size() < window) continue;
        for (std::size_t i = 0; i + window <= buffer.size(); ++i) {
          // 快速预检：mask[0]/mask[1] 由位置 96/97 与 salt_ascii 尾部推出
          unsigned char m0 = buffer[i + 96] ^ static_cast<unsigned char>(salt_ascii[30]);
          if ((buffer[i] ^ m0) != static_cast<unsigned char>('x')) continue;
          unsigned char m1 = buffer[i + 97] ^ static_cast<unsigned char>(salt_ascii[31]);
          if ((buffer[i + 1] ^ m1) != static_cast<unsigned char>('\'')) continue;
          // 完整掩码恢复：(66+k)%32 覆盖全部 32 字节掩码
          std::array<unsigned char, 32> mask{};
          for (int k = 0; k < 32; ++k)
            mask[(66 + k) % 32] = buffer[i + 66 + k] ^ static_cast<unsigned char>(salt_ascii[k]);
          if ((buffer[i + 98] ^ mask[2]) != static_cast<unsigned char>('\'')) continue;
          bool ok = true;
          for (int k = 2; k < 66; ++k) {
            if (!is_hex_char(buffer[i + k] ^ mask[k % 32])) {
              ok = false;
              break;
            }
          }
          if (!ok) continue;
          std::string key_hex;
          key_hex.reserve(64);
          for (int k = 0; k < 64; ++k)
            key_hex += static_cast<char>(buffer[i + 2 + k] ^ mask[(2 + k) % 32]);
          auto key = decode_hex(key_hex);
          if (key && key->size() == 32) {
            std::vector<unsigned char> salt(first_page.begin(), first_page.begin() + 16);
            return WechatRawKey{*key, salt};
          }
        }
      }
    }
    address = next;
  }
  return std::nullopt;
}

#endif  // _WIN32 platform-specific implementation

// --- Error reporting ---

#ifdef _WIN32

void emit_error(const std::string& reason, const std::string& detail = "") {
  json::Value obj = json::Value::object();
  obj.add("ok", json::Value::boolean(false));
  obj.add("reason", json::Value::string(reason));
  if (!detail.empty()) obj.add("detail", json::Value::string(detail));
  std::cout << obj.dump() << std::endl;
  std::exit(1);
}

#else  // Non-Windows: stub implementation

void emit_error(const std::string& reason, const std::string& detail = "") {
  json::Value obj = json::Value::object();
  obj.add("ok", json::Value::boolean(false));
  obj.add("reason", json::Value::string(reason));
  if (!detail.empty()) obj.add("detail", json::Value::string(detail));
  std::cout << obj.dump() << std::endl;
  std::exit(1);
}

#endif  // _WIN32

// --- Main ---

#ifdef _WIN32

std::vector<DWORD> find_wechat_pids(const std::string& process_name) {
  HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
  std::vector<DWORD> pids;
  if (snap == INVALID_HANDLE_VALUE) return pids;
  PROCESSENTRY32W entry{};
  entry.dwSize = sizeof(entry);
  std::wstring wname(process_name.begin(), process_name.end());
  if (Process32FirstW(snap, &entry)) {
    do {
      if (_wcsicmp(entry.szExeFile, wname.c_str()) == 0) {
        pids.push_back(entry.th32ProcessID);
      }
    } while (Process32NextW(snap, &entry));
  }
  CloseHandle(snap);
  return pids;
}

#endif  // _WIN32

int main(int argc, char** argv) {
  std::string config_path;
  std::string db_path;
#ifdef WKF_ENABLE_TEST_KEY
  std::string override_key;
#endif
  std::optional<unsigned long> explicit_pid;

  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg == "--config" && i + 1 < argc) {
      config_path = argv[++i];
    } else if (arg == "--db-path" && i + 1 < argc) {
      db_path = argv[++i];
#ifdef WKF_ENABLE_TEST_KEY
    } else if (arg == "--key" && i + 1 < argc) {
      override_key = argv[++i];
#endif
    } else if (arg == "--pid" && i + 1 < argc) {
      try {
        explicit_pid = std::stoul(argv[++i]);
      } catch (...) {
        emit_error("invalid_pid", "PID must be a number: " + std::string(argv[i]));
      }
    } else if (arg == "--help" || arg == "-h") {
      std::cerr << "Usage: wechat_keyfinder --config offsets.json [--db-path <path>] [--pid <pid>]" << std::endl;
      return 0;
    }
  }

  if (config_path.empty()) {
    emit_error("missing_config", "--config is required");
  }
#ifdef WKF_ENABLE_TEST_KEY
  if (!override_key.empty()) {
    if (override_key.size() != 64) {
      emit_error("invalid_key", "--key must be 64 hex chars (32 bytes)");
    }
    for (char c : override_key) {
      if (!std::isxdigit(static_cast<unsigned char>(c))) {
        emit_error("invalid_key", "--key contains a non-hex character");
      }
    }
    // 归一化为小写后输出
    for (auto& c : override_key) {
      c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
  }
#endif

  Config cfg;
  if (!load_config(config_path, cfg)) {
    emit_error("config_invalid", "Cannot load or parse config file: " + config_path);
  }

#ifdef _WIN32
  std::vector<DWORD> pids;
  if (explicit_pid.has_value()) {
    pids.push_back((DWORD)explicit_pid.value());
  } else {
    pids = find_wechat_pids(cfg.process_name);
    if (pids.empty()) {
      emit_error("wechat_not_running", "No " + cfg.process_name + " process found");
    }
  }

  // Extract encryption key: (test-only --key 覆盖) > 掩码恢复 > 旧 RVA 模式
  // 多实例时逐个进程尝试掩码恢复，只有运行该账号的进程内存里才有对应密钥缓冲
  std::string key_hex;
  std::string salt_hex;
  std::size_t scanned = 0;
  std::uintptr_t module_base = 0;
  DWORD pid = pids.front();
  bool opened_any = false;
#ifdef WKF_ENABLE_TEST_KEY
  if (!override_key.empty()) {
    key_hex = override_key;
    std::ifstream db(db_path, std::ios::binary);
    if (db) {
      std::array<unsigned char, 16> db_salt{};
      db.read(reinterpret_cast<char*>(db_salt.data()), db_salt.size());
      salt_hex = to_hex(std::vector<unsigned char>(db_salt.begin(), db_salt.end()));
    }
  } else if (!db_path.empty()) {
#else
  if (!db_path.empty()) {
#endif
    for (DWORD candidate : pids) {
      HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, FALSE, candidate);
      if (!process) continue;
      opened_any = true;
      pid = candidate;
      auto key = find_wechat_key_masked(process, db_path, cfg, scanned);
      if (!key) {
        // 掩码恢复失败才需要 module_base（旧 RVA 模式）
        auto mb = find_module_base(candidate, cfg.module_name);
        if (mb) {
          module_base = *mb;
          key = find_wechat_key(process, module_base, db_path, cfg, scanned);
        }
      }
      CloseHandle(process);
      if (key) {
        key_hex = to_hex(key->key);
        salt_hex = to_hex(key->salt);
        break;
      }
      if (module_base == 0) {
        auto mb = find_module_base(candidate, cfg.module_name);
        if (mb) module_base = *mb;
      }
    }
    if (!opened_any) {
      emit_error("process_open_failed", "Cannot open " + cfg.process_name + " (permission denied)");
    }
  } else {
    auto mb = find_module_base(pid, cfg.module_name);
    if (mb) module_base = *mb;
  }

  std::ostringstream base_hex;
  base_hex << "0x" << std::hex << module_base;

  json::Value result = json::Value::object();
  bool ok = true;
  if (!db_path.empty() && key_hex.empty()) {
    ok = false;
    result.add("ok", json::Value::boolean(false));
    result.add("reason", json::Value::string("key_not_found"));
  } else {
    result.add("ok", json::Value::boolean(true));
  }
  result.add("pid", json::Value::number((std::int64_t)pid));
  result.add("module_base", json::Value::string(base_hex.str()));
  if (!key_hex.empty()) result.add("key", json::Value::string(key_hex));
  if (!salt_hex.empty()) result.add("salt", json::Value::string(salt_hex));
  result.add("bytes_scanned", json::Value::number((std::int64_t)scanned));
  std::cout << result.dump() << std::endl;

  return ok ? 0 : 1;
#else
  emit_error("platform_unsupported", "wechat_keyfinder requires Windows");
  return 1;  // unreachable
#endif
}
