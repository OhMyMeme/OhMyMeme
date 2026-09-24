// wechat_keyfinder 单元测试：SHA-512 系原语已知答案向量 + 密钥提取路径端到端
//
// 构建：cmake -S src/wechat_keyfinder -B build/wk-tests -DWKF_BUILD_TESTS=ON
//       cmake --build build/wk-tests --config Release && ctest --test-dir build/wk-tests -C Release
//
// 说明：
//   * 直接 #include 被测实现（把 main 改名），不改动产品源码结构
//   * 全部期望值由 Python hashlib/hmac 生成后内联 —— 权威参考实现，而非
//     手写或由本实现自产（后者会把实现错误一并固化成"期望值"）
//   * MAC 校验路径（旧 RVA 回退）是唯一真正使用 SHA-512 的分支，生产环境
//     通常走掩码恢复，故该路径更依赖这里的回归保护
#define main wk_production_main
#include "wechat_keyfinder.cpp"
#undef main

#include <filesystem>
#include <fstream>

namespace {

int g_fails = 0;

void expect(bool cond, const char* name, const std::string& detail = "") {
  if (cond) {
    std::printf("[PASS] %s\n", name);
  } else {
    ++g_fails;
    std::printf("[FAIL] %s%s\n", name, detail.empty() ? "" : ("  " + detail).c_str());
  }
}

void expect_eq(const char* name, const std::string& got, const std::string& want) {
  if (got == want) {
    std::printf("[PASS] %s\n", name);
  } else {
    ++g_fails;
    std::printf("[FAIL] %s\n       got  %s\n       want %s\n", name,
                got.c_str(), want.c_str());
  }
}

std::vector<unsigned char> unhex(const std::string& s) {
  std::vector<unsigned char> out;
  out.reserve(s.size() / 2);
  for (std::size_t i = 0; i + 1 < s.size(); i += 2)
    out.push_back((unsigned char)std::stoi(s.substr(i, 2), nullptr, 16));
  return out;
}

std::string hex(const unsigned char* d, std::size_t n) {
  static const char* H = "0123456789abcdef";
  std::string s;
  s.reserve(n * 2);
  for (std::size_t i = 0; i < n; ++i) {
    s += H[d[i] >> 4];
    s += H[d[i] & 0x0f];
  }
  return s;
}

std::string sha512_hex(const void* data, std::size_t len) {
  sha512::Sha512 s;
  s.update(data, len);
  unsigned char d[sha512::kDigestSize];
  s.final(d);
  return hex(d, sizeof(d));
}

// --- 合成 DB 首页与掩码缓冲（layout 与 gen 脚本一致）---

void build_page(unsigned char* page, const unsigned char* salt,
                const unsigned char* digest_tail) {
  for (int i = 0; i < 4096; ++i) page[i] = (unsigned char)(i % 251);
  ::memcpy(page, salt, 16);
  if (digest_tail) ::memcpy(page + 4032, digest_tail, 64);
}

}  // namespace

int main() {
  // ===== 1. SHA-512 已知答案向量（含块边界 55/56/111/112/113/127/128/129）=====
  {
    static const struct { int len; const char* want; } kShaVecs[] = {
        {0, "cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e"},
        {1, "e45bf5817ddf94aa2f7a407071f0eedc6beb98f768b4cd33d1176d44d1563a45a5d7212290eb7670c6786b13591aedac86478993895e8b24e612014abaa6ba04"},
        {55, "14fd424b1fcadee624da946ab03f7e1def7c0d6e00f689594319881a26ff30b875ba4c622ac13100c8cc784c9c2eb23159aecbb4a02e3999062f551193e2b256"},
        {56, "480fa85be41ef55a41208ca28ffc8743c91cf7d24758defe6f95bfb16de614fc86b701034896b047dd571de4318853d80e0809df162f1752cb26da6ddb94a0dd"},
        {111, "68cffa6d0d76f309c9ce0d35280939f8e25990c43b7b086ccdf709be35b07d4ddba599541ff2b1c19d34ea49aeafb9659adb7ac3c0b078bb30a22d57fc6687ef"},
        {112, "d0865c524d1dddf7c23b799c413f5adcd7caefd3f66a9b49750ec81066012c25a8bcf94ddea6dc525691673097ca40e0101e897fc97218cfdb0704084e2bef4b"},
        {113, "606314353bd419f9f7720e8297f2af8a9ed5f0bb0bed29b716bf18e34577623ae7effa46f496bd4282134e7e895284a4760a910d2ad8ec11e9dd75863058cd9c"},
        {127, "e0b6a20f1c0c88970a9340152cd5a1c1ecf3d3b8de55102741879438079473540133b812706e5dbec322c8c9523b6fc8c6d16ee626e87ad5fe3d2916afedc369"},
        {128, "99b16f17aa0b969a5b8f08f367719d516e330ccd2660b6f0688ec031dbc783de50a1cd185a2568dba75070a2403d17d4741d163578515dfd2ff756ddfe4d47b1"},
        {129, "a1556e29185778aa5991e34b8884c840d589f0fbb4b8ed590e51e9ac4eb03a008125000db2671f8fe7f485b59a77b518670078ecb41a54b4cd02a7f1d2ca4c6d"},
        {255, "c2e3bb67012f9eb526202efa59997933f7d3e75e7ded738818bc27d94977f4573afddb1b2793745701e62affa3b7a1c8262c992a321f488a6b1942a4795bab98"},
        {256, "e49c208e41556e859d1a52d14784a061c2d5ae2c8690a5360e9f9344f60861c1362a9ec05a9f08a4167b3da41bdd122a387413dd06976470e4beff5053f2ac71"},
        {1000, "00e36fccf193e59697a92b5ab24666ce6326d7fa16bf10832d0991ddc591112e9dfa6a636950ed9c4d67344a760654c2ff7785e1d60094d651038735b5dccabd"},
    };
    for (const auto& v : kShaVecs) {
      std::vector<unsigned char> data(v.len);
      for (int i = 0; i < v.len; ++i) data[i] = (unsigned char)((i * 7 + 3) & 0xff);
      char name[64];
      std::snprintf(name, sizeof(name), "sha512(len=%d)", v.len);
      expect_eq(name, sha512_hex(data.data(), data.size()), v.want);
    }

    // 分块 update 必须与一次性 update 结果一致（模拟分块读取）
    sha512::Sha512 s;
    for (int i = 0; i < 1000; i += 7) {
      int n = (1000 - i) < 7 ? (1000 - i) : 7;
      unsigned char chunk[7];
      for (int j = 0; j < n; ++j) chunk[j] = (unsigned char)(((i + j) * 7 + 3) & 0xff);
      s.update(chunk, n);
    }
    unsigned char sd[sha512::kDigestSize];
    s.final(sd);
    expect_eq("sha512(streamed 7-byte chunks)", hex(sd, sizeof(sd)),
              "00e36fccf193e59697a92b5ab24666ce6326d7fa16bf10832d0991ddc591112e9dfa6a636950ed9c4d67344a760654c2ff7785e1d60094d651038735b5dccabd");
  }

  // ===== 2. HMAC-SHA512（含 128 字节 block 边界与超块长 key 分支）=====
  {
    static const struct { const char* key; const char* msg; const char* want; } kVecs[] = {
        {"0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b", "Hi There", "87aa7cdea5ef619d4ff0b4241a1d6cb02379f4e2ce4ec2787ad0b30545e17cdedaa833b7d6b8a702038b274eaea3f4e4be9d914eeb61f1702e696c203a126854"},
        {"4a656665", "what do ya want for nothing?", "164b7a7bfcf819e2e395fbe73b56e0a387bd64222e831fd610270cd7ea2505549758bf75c05a994a6d034f65f8f0e6fdcaeab1a34d4a6b4b636e070a38bce737"},
        {"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "Test Using Larger Than Block-Size Key - Hash Key First", "80b24263c7c1a3ebb71493c1dd7be8b49b46d1f41b4aeec1121b013783f8f3526b56d037e05f2598bd0fd2215d6a1e5295e64f73f63f0aec8b915a985d786598"},
        {"5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a", "exactly block size key", "04abfa798de515fde1b3d7c4623b5ab2a4ce8f586ba91f78e3ecaa04de0ed4deb309ce065e01a9f561a3209d2e6964727874ca1f63bdf4a258bb01463bea3047"},
    };
    for (const auto& v : kVecs) {
      auto key = unhex(v.key);
      unsigned char out[sha512::kDigestSize];
      sha512::hmac(key.data(), key.size(), (const unsigned char*)v.msg,
                   ::strlen(v.msg), out);
      expect_eq(("hmac(key=" + std::to_string(key.size()) + "B)").c_str(),
                hex(out, sizeof(out)), v.want);
    }
  }

  // ===== 3. PBKDF2-HMAC-SHA512 =====
  {
    static const struct {
      const char* pw; const char* salt; int iter; int dklen; const char* want;
    } kVecs[] = {
        {"70617373776f7264", "73616c74", 1, 64, "867f70cf1ade02cff3752599a3a53dc4af34c7a669815ae5d513554e1c8cf252c02d470a285a0501bad999bfe943c08f050235d7d68b1da55e63f73b60a57fce"},
        {"70617373776f7264", "73616c74", 2, 64, "e1d9c16aa681708a45f5c7c4e215ceb66e011a2e9f0040713f18aefdb866d53cf76cab2868a39b9f7840edce4fef5a82be67335c77a6068e04112754f27ccf4e"},
        {"70617373776f7264", "73616c74", 4096, 64, "d197b1b33db0143e018b12f3d1d1479e6cdebdcc97c5c0f87f6902e072f457b5143f30602641b3d55cd335988cb36b84376060ecd532e039b742a239434af2d5"},
        {"70617373776f7264", "73616c74", 2, 32, "e1d9c16aa681708a45f5c7c4e215ceb66e011a2e9f0040713f18aefdb866d53c"},
        {"000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f", "000102030405060708090a0b0c0d0e0f", 2, 32, "d79dbd9933d918bed27486b7594d68efc13ff727bfb7767cf012d67cf3bee109"},
    };
    for (const auto& v : kVecs) {
      auto pw = unhex(v.pw);
      auto salt = unhex(v.salt);
      std::vector<unsigned char> out(v.dklen);
      sha512::pbkdf2_hmac(pw.data(), pw.size(), salt.data(), salt.size(),
                          v.iter, out.data(), out.size());
      char name[96];
      std::snprintf(name, sizeof(name), "pbkdf2(iter=%d, dklen=%d, pw=%dB)",
                    v.iter, v.dklen, (int)pw.size());
      expect_eq(name, hex(out.data(), out.size()), v.want);
    }
  }

#if defined(_WIN32)
  // ===== 4. 密钥提取路径端到端（真实内存布局，不走 --key 旁路）=====
  {
    const auto salt = unhex("000102030405060708090a0b0c0d0e0f");
    const auto key = unhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f");
    const auto mask = unhex("05101b26313c47525d68737e89949faab5c0cbd6e1ecf7020d18232e39444f5a");
    const auto digest = unhex("c6c6978fb3329b2b6d42dbfe41f1ef810860f99b9b5d6e75e72390d59ce5ee932b0f9dbab11533aa5caf5f80dfe285f1ccc23f4920ea0b46562d31eb19aa6bd9");
    const auto bad_digest = unhex("c6c6978fb3329b2b6d42dbfe41f1ef810860f99b9b5d6e75e72390d59ce5ee932b0f9dbab11533aa5caf5f80dfe285f1ccc23f4920ea0b46562d31eb19aa6bd8");
    const auto masked = unhex("7d372b16010d77606d5b434ab9a1af9c85f7fbeed1d5c7633d7a134d09207f3f35762a16000d76606c5b424ab8a1ae9c84f7faeed0d5c6633c7a124d08207e3f34762b16010d77606d5b434ab9a1af9c85f7fbeed1d5c7633d7a134d09207f3f35763c");

    // 写入系统临时目录：避免测试异常中断时在仓库/CWD 留下残留文件
    auto dir = std::filesystem::temp_directory_path() / "wk_test_artifacts";
    std::filesystem::create_directories(dir);
    const auto page_good = (dir / "page1.bin").string();
    const auto page_bad = (dir / "page1_bad.bin").string();
    {
      unsigned char page[4096];
      std::ofstream o1(page_good, std::ios::binary);
      build_page(page, salt.data(), digest.data());
      o1.write((const char*)page, sizeof(page));
      std::ofstream o2(page_bad, std::ios::binary);
      build_page(page, salt.data(), bad_digest.data());
      o2.write((const char*)page, sizeof(page));
    }

    // 在自身进程内布下 helper 期望的结构
    const std::size_t kRegion = 0x100000;
    auto* mem = VirtualAlloc(nullptr, kRegion, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    expect(mem != nullptr, "VirtualAlloc for fixture region");
    if (!mem) return 1;
    auto base = (std::uintptr_t)mem;
    auto* p = (unsigned char*)mem;
    ::memset(p, 0, kRegion);

    const std::uintptr_t kMaskOff = 0x1000, kPatternOff = 0x2000;
    const std::uintptr_t kObjectOff = 0x3000, kRawOff = 0x4000;
    ::memcpy(p + kMaskOff, mask.data(), mask.size());
    ::memcpy(p + kRawOff, masked.data(), masked.size());

    const std::uintptr_t raw_ptr = base + kRawOff;
    const std::uint64_t raw_len = masked.size();
    ::memcpy(p + kObjectOff + 0x88 + 8, &raw_ptr, 8);
    ::memcpy(p + kObjectOff + 0x88 + 16, &raw_len, 8);

    const std::uintptr_t literal = base;  // cipher_literal_rva == 0
    const std::uint64_t node_len = 30;
    ::memcpy(p + kPatternOff, &literal, 8);
    ::memcpy(p + kPatternOff + 8, &node_len, 8);
    const std::uintptr_t object = base + kObjectOff;
    ::memcpy(p + kPatternOff + 24, &object, 8);

    HANDLE self = GetCurrentProcess();

    // 4a. 掩码恢复（主路径，不需要 SHA-512）
    {
      Config cfg;
      cfg.key_length = 99;
      cfg.salt_length = 16;
      cfg.key_xor_mask_length = 32;
      cfg.max_cipher_scan_bytes = 512u * 1024 * 1024;
      cfg.max_scan_region = 512u * 1024 * 1024;
      cfg.scan_chunk_size = 4u * 1024 * 1024;
      std::size_t scanned = 0;
      auto got = find_wechat_key_masked(self, page_good, cfg, scanned);
      expect(got.has_value(), "masked recovery: found key");
      if (got) {
        expect(got->key == key, "masked recovery: key matches Python reference");
        expect(got->salt == salt, "masked recovery: salt matches Python reference");
      }
    }

    // 4b. 旧 RVA 回退 + PBKDF2/HMAC MAC 校验（唯一真正使用 SHA-512 的路径）
    {
      Config cfg;
      cfg.cipher_literal_rva = 0;
      cfg.mask_offset = kMaskOff;
      cfg.key_length = 99;
      cfg.salt_length = 16;
      cfg.key_xor_mask_length = 32;
      cfg.mac_salt_xor_byte = 0x3a;
      cfg.pbkdf2_iterations = 2;
      cfg.mac_digest_length = 64;
      cfg.max_cipher_scan_bytes = 512u * 1024 * 1024;
      cfg.max_scan_region = 512u * 1024 * 1024;
      cfg.scan_chunk_size = 4u * 1024 * 1024;
      std::size_t scanned = 0;
      auto got = find_wechat_key(self, base, page_good, cfg, scanned);
      expect(got.has_value(), "rva path: found key (PBKDF2 + HMAC verified)");
      if (got) {
        expect(got->key == key, "rva path: key matches Python reference");
        expect(got->salt == salt, "rva path: salt matches Python reference");
      }

      // 4c. 篡改 DB 页中的 MAC 必须被拒
      std::size_t scanned2 = 0;
      auto bad = find_wechat_key(self, base, page_bad, cfg, scanned2);
      expect(!bad.has_value(), "rva path: tampered MAC rejected");

      // 4d. 篡改内存中的密钥缓冲必须因 MAC 不符而拒绝。
      //     篡改点选在 key hex 区（下标 2）且保持合法 hex 字符：这样格式校验
      //     （x'...'、全 hex）与 salt 比对都会通过，只有 MAC 比对能拦下它。
      //     若 MAC 校验被绕过，本用例即 FAIL。
      //     注意：改在末字节（下标 98，闭合单引号）会先被格式校验拦下，
      //     那样"通过"是假象，覆盖不到 MAC 层。
      auto* raw_buf = p + kRawOff;
      const unsigned char saved = raw_buf[2];
      raw_buf[2] = (unsigned char)('1' ^ mask[2]);  // key.hex() 首位 '0' -> '1'
      std::size_t scanned3 = 0;
      auto tampered = find_wechat_key(self, base, page_good, cfg, scanned3);
      expect(!tampered.has_value(),
             "rva path: tampered key buffer rejected by MAC check");
      raw_buf[2] = saved;

      // 还原后应重新命中，确认上面并非因其他原因失败
      std::size_t scanned4 = 0;
      auto restored = find_wechat_key(self, base, page_good, cfg, scanned4);
      expect(restored.has_value(), "rva path: recovers after buffer restored");
    }

    VirtualFree(mem, 0, MEM_RELEASE);
    std::error_code ec;
    std::filesystem::remove_all(dir, ec);
  }
#else
  std::printf("[SKIP] key extraction paths require Windows\n");
#endif

  std::printf("\n%s (fails=%d)\n",
              g_fails ? "SOME TESTS FAILED" : "ALL TESTS PASSED", g_fails);
  return g_fails ? 1 : 0;
}
