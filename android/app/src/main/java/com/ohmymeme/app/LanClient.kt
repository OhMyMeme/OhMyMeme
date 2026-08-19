package com.ohmymeme.app

import android.content.Context
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.io.DataInputStream
import java.io.DataOutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

/**
 * 局域网互联客户端（连接电脑端 lan.py 服务）。
 * 协议对齐桌面端 src/lan.py：UDP 发现 + TCP 握手（HMAC-SHA256 挑战/应答）
 * + AES-GCM 加密会话帧。
 */
object LanClient {

    const val DEFAULT_PORT = 17852

    private const val TAG = "OhMyMeme/LanClient"
    private const val PROTOCOL_VERSION = 1
    private const val MAX_FRAME = 64 * 1024 * 1024
    private const val MAX_FILE_SIZE = 64L * 1024 * 1024
    private const val HANDSHAKE_TIMEOUT_MS = 10_000
    private const val DEVICE_CONFIRM_TIMEOUT_MS = 60_000
    private const val IDLE_TIMEOUT_MS = 60_000
    private const val IV_LEN = 12
    private const val TAG_LEN = 16
    private const val DISCOVER_TIMEOUT_MS = 1500
    private const val PBKDF2_SALT = "ohmy-meme-lan"
    private const val PBKDF2_ITERATIONS = 100_000
    private const val PBKDF2_KEY_LEN = 32

    /** 发现的电脑信息（对应 lan.py UDP hello 应答） */
    data class LanPeer(
        val name: String,
        val os: String,
        val ver: String,
        val needSecret: Boolean,
        val ip: String,
        val port: Int
    )

    /** 局域网同步结果汇总 */
    data class LanResult(
        val pulled: Int = 0,
        val pushed: Int = 0,
        val skipped: Int = 0,
        val errors: Int = 0,
        val failed: List<String> = emptyList()
    )

    class LanError(message: String) : Exception(message)

    /** UDP 广播发现局域网内电脑，返回应答列表（阻塞，勿在主线程调用） */
    fun discover(context: Context, port: Int = DEFAULT_PORT): List<LanPeer> {
        val result = mutableListOf<LanPeer>()
        val sock = DatagramSocket()
        try {
            sock.broadcast = true
            sock.soTimeout = DISCOVER_TIMEOUT_MS
            val msg = JSONObject().put("t", "discover").toString().toByteArray()
            val target = InetAddress.getByName("255.255.255.255")
            sock.send(DatagramPacket(msg, msg.size, target, port))
            val buf = ByteArray(2048)
            val deadline = System.currentTimeMillis() + DISCOVER_TIMEOUT_MS
            while (System.currentTimeMillis() < deadline) {
                try {
                    val pkt = DatagramPacket(buf, buf.size)
                    sock.receive(pkt)
                    val text = String(pkt.data, 0, pkt.length, Charsets.UTF_8)
                    val obj = JSONObject(text)
                    if (obj.optString("t", "") != "hello") continue
                    val peer = LanPeer(
                        name = obj.optString("name", "未知设备"),
                        os = obj.optString("os", ""),
                        ver = obj.optString("ver", ""),
                        needSecret = obj.optBoolean("need_secret", false),
                        ip = pkt.address.hostAddress ?: continue,
                        port = port
                    )
                    if (result.none { it.ip == peer.ip && it.port == peer.port }) {
                        result.add(peer)
                    }
                } catch (e: java.net.SocketTimeoutException) {
                    break
                }
            }
        } catch (e: Exception) {
            android.util.Log.w(TAG, "discover failed: $e")
        } finally {
            try {
                sock.close()
            } catch (e: Exception) {
                // ignore
            }
        }
        return result
    }

    /** 建立加密会话并返回操作句柄（发送本机设备描述，等待电脑端确认后可用） */
    fun connect(context: Context, ip: String, port: Int, secret: String): LanConnection {
        val conn = LanConnection()
        conn.connect(ip, port, secret, buildDeviceInfo(context))
        return conn
    }

    /** 构建设备描述（供电脑端确认弹窗展示） */
    private fun buildDeviceInfo(context: Context): JSONObject {
        val ver = try {
            context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: ""
        } catch (e: Exception) {
            ""
        }
        val model = Build.MODEL
        val manufacturer = Build.MANUFACTURER
        val name = if (manufacturer.isNotBlank() && manufacturer != "unknown") "$manufacturer $model" else model
        return JSONObject()
            .put("name", name)
            .put("model", model)
            .put("os", "Android ${Build.VERSION.RELEASE}")
            .put("ver", ver)
    }

    /**
     * 从电脑拉取表情：pull_manifest → 去重 → pull_file 逐文件导入 → applyRemoteOrder。
     * 每个文件先过合法性检查（文件名安全 / 大小上限 / 哈希一致 / 内容可解码），
     * 不合法跳过计入 failed 且不落盘。阻塞，勿在主线程调用。
     */
    fun pull(context: Context, conn: LanConnection): LanResult {
        val db = MemeDb.get(context)
        val manifest = conn.pullManifest()
        val remoteArr = manifest.optJSONArray("memes") ?: JSONArray()
        var pulled = 0
        var skipped = 0
        var errors = 0
        val failed = mutableListOf<String>()
        for (i in 0 until remoteArr.length()) {
            val m = remoteArr.optJSONObject(i) ?: continue
            val fname = m.optString("filename", "")
            if (!CloudSync.isSafeRemoteFname(fname)) {
                errors++
                failed.add(fname)
                continue
            }
            val existing = db.getByFilename(fname)
            if (existing != null) {
                skipped++
                continue
            }
            try {
                val data = conn.pullFile(fname)
                if (data.size.toLong() > MAX_FILE_SIZE) {
                    errors++
                    failed.add(fname)
                    continue
                }
                // 哈希一致性：与清单 sha256 比对（清单字段存在时）
                val remoteHash = m.optString("sha256", "")
                if (remoteHash.isNotEmpty() &&
                    !remoteHash.equals(FileUtils.sha256(java.io.ByteArrayInputStream(data)), ignoreCase = true)
                ) {
                    errors++
                    failed.add(fname)
                    continue
                }
                if (!MemeImporter.isValidImageContent(data)) {
                    errors++
                    failed.add(fname)
                    continue
                }
                val oname = m.optString("name", "").ifEmpty { fname.substringBeforeLast('.') }
                val imported = MemeImporter.importBytes(context, data, oname)
                if (imported) pulled++ else skipped++
            } catch (e: Exception) {
                android.util.Log.w(TAG, "pull file failed $fname: $e")
                errors++
                failed.add(fname)
            }
        }
        CloudSync.applyRemoteAiText(context, manifest)
        CloudSync.applyRemoteOrder(context, manifest)
        android.util.Log.d(TAG, "lan pull done pulled=$pulled skipped=$skipped errors=$errors")
        return LanResult(pulled = pulled, skipped = skipped, errors = errors, failed = failed)
    }

    /**
     * 推送表情到电脑：push_file 逐文件（电脑端哈希去重）→ push_manifest 同步顺序/分组。
     * 阻塞，勿在主线程调用。
     */
    fun push(context: Context, conn: LanConnection): LanResult {
        val db = MemeDb.get(context)
        val remote = conn.pullManifest()
        val remoteNames = HashMap<String, Boolean>()
        val remoteArr = remote.optJSONArray("memes")
        if (remoteArr != null) {
            for (i in 0 until remoteArr.length()) {
                val obj = remoteArr.optJSONObject(i) ?: continue
                val fname = obj.optString("filename", "")
                if (fname.isNotEmpty()) remoteNames[fname] = true
            }
        }
        var pushed = 0
        var skipped = 0
        var errors = 0
        val failed = mutableListOf<String>()
        for (m in db.getAll(0, Int.MAX_VALUE)) {
            if (m.filename in remoteNames) {
                skipped++
                continue
            }
            val file = Thumbnailer.findMemeFile(context, m.filename) ?: run {
                errors++
                failed.add(m.filename)
                continue
            }
            try {
                conn.pushFile(m.filename, file.readBytes())
                pushed++
            } catch (e: Exception) {
                android.util.Log.w(TAG, "push file failed ${m.filename}: $e")
                errors++
                failed.add(m.filename)
            }
        }
        try {
            conn.pushManifest(CloudSync.buildManifest(context))
        } catch (e: Exception) {
            android.util.Log.w(TAG, "push manifest failed: $e")
        }
        android.util.Log.d(TAG, "lan push done pushed=$pushed skipped=$skipped errors=$errors")
        return LanResult(pushed = pushed, skipped = skipped, errors = errors, failed = failed)
    }

    /**
     * 从电脑同步配置到本地。
     * 默认剔除密钥字段（电脑端未开 `allow_secret_config` 时也会过滤）；
     * `includeSecrets` 仅在电脑端确认 `allow_secret_config=true` 时才传 true，密钥随配置一并同步。
     * 覆盖本地配置，需谨慎调用。
     */
    fun pullConfig(context: Context, conn: LanConnection, includeSecrets: Boolean = false) {
        val resp = conn.getConfig()
        val cfg = resp.optJSONObject("config") ?: throw LanError("配置格式错误")
        val local = ConfigStore.get(context)
        val keys = cfg.keys()
        while (keys.hasNext()) {
            val k = keys.next()
            if (!includeSecrets && ConfigStore.isSecretKey(k)) continue
            val v = cfg.opt(k)
            if (v != null) local.put(k, v)
        }
        ConfigStore.save(context)
        ConfigStore.reload(context)
    }

    /**
     * 把本地配置推送到电脑。
     * 默认剔除密钥字段（电脑端 `allow_secret_config=false` 时也会过滤）；
     * `includeSecrets` 仅在电脑端确认 `allow_secret_config=true` 时才传 true。
     * 覆盖电脑配置，需谨慎调用。
     */
    fun pushConfig(context: Context, conn: LanConnection, includeSecrets: Boolean = false) {
        val cfg = ConfigStore.get(context)
        val copy = JSONObject()
        val keys = cfg.keys()
        while (keys.hasNext()) {
            val k = keys.next()
            if (!includeSecrets && ConfigStore.isSecretKey(k)) continue
            copy.put(k, cfg.opt(k))
        }
        conn.sendConfig(copy)
    }

    /** TCP 加密会话句柄 */
    class LanConnection {
        private var sock: Socket? = null
        private var key: ByteArray = ByteArray(32)
        private val writeLock = Any()

        /** 电脑端是否允许密钥同步（由 device_info 确认响应携带） */
        @Volatile
        var allowSecretConfig: Boolean = false

        fun connect(ip: String, port: Int, secret: String, deviceInfo: JSONObject) {
            val s = Socket()
            try {
                s.connect(InetSocketAddress(ip, port), HANDSHAKE_TIMEOUT_MS)
                s.soTimeout = HANDSHAKE_TIMEOUT_MS
                sock = s
                val out = DataOutputStream(s.getOutputStream())
                val input = DataInputStream(s.getInputStream())

                if (secret.isNotEmpty()) {
                    val challenge = recvPlain(input) ?: throw LanError("握手失败：无挑战")
                    if (challenge.optString("t", "") != "challenge") {
                        throw LanError("握手失败：期望 challenge")
                    }
                    val nonce = challenge.optString("nonce", "")
                    val mac = hmacSha256(secret, nonce)
                    sendPlain(out, JSONObject().put("t", "proof").put("mac", mac))
                    val reply = recvPlain(input) ?: throw LanError("握手失败：无应答")
                    if (reply.optString("t", "") != "ok") {
                        throw LanError("配对失败：密钥不正确")
                    }
                } else {
                    val reply = recvPlain(input) ?: throw LanError("握手失败：无应答")
                    if (reply.optString("t", "") != "ok") {
                        throw LanError("握手失败")
                    }
                }
                key = deriveKey(secret)
                s.soTimeout = DEVICE_CONFIRM_TIMEOUT_MS
                val confirm = request("device_info", deviceInfo)
                if (!confirm.optBoolean("ok", false)) {
                    val err = confirm.optString("error", "")
                    if (err.contains("未知命令")) {
                        throw LanError("电脑端版本过旧，不支持设备确认，请升级电脑端 OhMyMeme")
                    }
                    throw LanError(err.ifEmpty { "电脑端未确认设备信息" })
                }
                if (!confirm.optBoolean("approved", false)) {
                    throw LanError("电脑端拒绝了本次连接")
                }
                allowSecretConfig = confirm.optBoolean("allow_secret_config", false)
                s.soTimeout = IDLE_TIMEOUT_MS
            } catch (e: Exception) {
                close()
                if (e is LanError) throw e
                throw LanError("连接失败：${e.message}")
            }
        }

        /** 发送加密请求并等待加密响应（线程安全，阻塞） */
        fun request(cmd: String, params: JSONObject? = null): JSONObject {
            val s = sock ?: throw LanError("未连接")
            val msg = JSONObject().put("cmd", cmd)
            if (params != null) {
                val keys = params.keys()
                while (keys.hasNext()) {
                    val k = keys.next()
                    msg.put(k, params.opt(k))
                }
            }
            return synchronized(writeLock) {
                val out = DataOutputStream(s.getOutputStream())
                sendFrame(out, key, msg)
                val input = DataInputStream(s.getInputStream())
                recvFrame(input, key) ?: throw LanError("连接已断开")
            }
        }

        fun ping(): Boolean {
            return try {
                request("ping").optBoolean("ok", false)
            } catch (e: Exception) {
                false
            }
        }

        fun pullManifest(): JSONObject {
            val resp = request("pull_manifest")
            if (!resp.optBoolean("ok", false)) throw LanError(resp.optString("error", "获取清单失败"))
            return resp.optJSONObject("manifest") ?: throw LanError("清单为空")
        }

        fun pushManifest(manifest: JSONObject) {
            val resp = request("push_manifest", JSONObject().put("manifest", manifest))
            if (!resp.optBoolean("ok", false)) throw LanError(resp.optString("error", "推送清单失败"))
        }

        fun pullFile(filename: String): ByteArray {
            val resp = request("pull_file", JSONObject().put("filename", filename))
            if (!resp.optBoolean("ok", false)) throw LanError(resp.optString("error", "拉取文件失败"))
            val b64 = resp.optString("data", "")
            return try {
                Base64.getDecoder().decode(b64)
            } catch (e: Exception) {
                throw LanError("文件数据解码失败")
            }
        }

        fun pushFile(filename: String, data: ByteArray) {
            val b64 = Base64.getEncoder().encodeToString(data)
            val resp = request("push_file", JSONObject().put("filename", filename).put("data", b64))
            if (!resp.optBoolean("ok", false)) throw LanError(resp.optString("error", "推送文件失败"))
        }

        fun getConfig(): JSONObject {
            val resp = request("get_config")
            if (!resp.optBoolean("ok", false)) throw LanError(resp.optString("error", "获取配置失败"))
            return resp
        }

        fun sendConfig(config: JSONObject) {
            val resp = request("send_config", JSONObject().put("config", config))
            if (!resp.optBoolean("ok", false)) throw LanError(resp.optString("error", "推送配置失败"))
        }

        fun close() {
            try {
                sock?.close()
            } catch (e: Exception) {
                // ignore
            }
            sock = null
        }

        // --- 明文帧（握手阶段） ---

        private fun sendPlain(out: DataOutputStream, obj: JSONObject) {
            val data = obj.toString().toByteArray(Charsets.UTF_8)
            out.writeInt(data.size)
            out.write(data)
            out.flush()
        }

        private fun recvPlain(input: DataInputStream): JSONObject? {
            return try {
                val ln = input.readInt()
                if (ln > MAX_FRAME) throw LanError("帧过大")
                val buf = ByteArray(ln)
                input.readFully(buf)
                JSONObject(String(buf, Charsets.UTF_8))
            } catch (e: Exception) {
                null
            }
        }

        // --- 加密帧 ---

        private fun sendFrame(out: DataOutputStream, key: ByteArray, obj: JSONObject) {
            val plain = obj.toString().toByteArray(Charsets.UTF_8)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"))
            val ct = cipher.doFinal(plain)
            val iv = cipher.iv
            out.writeInt(iv.size + ct.size)
            out.write(iv)
            out.write(ct)
            out.flush()
        }

        private fun recvFrame(input: DataInputStream, key: ByteArray): JSONObject? {
            return try {
                val ln = input.readInt()
                if (ln > MAX_FRAME || ln < IV_LEN + TAG_LEN) throw LanError("帧长度非法")
                val body = ByteArray(ln)
                input.readFully(body)
                val iv = body.copyOfRange(0, IV_LEN)
                val ct = body.copyOfRange(IV_LEN, body.size)
                val cipher = Cipher.getInstance("AES/GCM/NoPadding")
                cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(TAG_LEN * 8, iv))
                val plain = cipher.doFinal(ct)
                JSONObject(String(plain, Charsets.UTF_8))
            } catch (e: Exception) {
                null
            }
        }
    }

    private fun hmacSha256(secret: String, nonce: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(secret.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        val bytes = mac.doFinal(nonce.toByteArray(Charsets.UTF_8))
        return bytes.joinToString("") { "%02x".format(it) }
    }

    /** 由共享密钥派生 AES-GCM 会话密钥（对齐桌面端 _derive_key） */
    fun deriveKey(secret: String): ByteArray {
        if (secret.isEmpty()) return ByteArray(32)
        val spec = PBEKeySpec(
            secret.toCharArray(),
            PBKDF2_SALT.toByteArray(Charsets.UTF_8),
            PBKDF2_ITERATIONS,
            PBKDF2_KEY_LEN * 8
        )
        val factory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
        return factory.generateSecret(spec).encoded
    }
}
