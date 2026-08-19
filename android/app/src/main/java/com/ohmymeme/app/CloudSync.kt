package com.ohmymeme.app

import android.content.Context
import android.graphics.BitmapFactory
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.BufferedReader
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.io.InputStreamReader
import java.io.PrintWriter
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.Socket
import java.net.URL
import java.net.URLDecoder
import java.security.MessageDigest
import java.util.Base64
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.Future
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import javax.net.ssl.SSLSocket
import javax.net.ssl.SSLSocketFactory

/**
 * 云端同步：FTP / S3（兼容 R2 / MinIO）/ WebDAV。
 * 与桌面端 sync.py + manifest.py 对齐：远端 memes/ 目录 + meme-index.json 清单，
 * 流式哈希比对跳过已同步文件。push/pull 多线程（sync_threads 并发，默认 3）。
 */
object CloudSync {

    private const val TAG = "OhMyMeme"
    private const val INDEX_FILENAME = "meme-index.json"
    private const val REMOTE_MEME_DIR = "memes"
    private const val MANIFEST_VERSION = 3

    class SyncError(message: String) : Exception(message)

    data class SyncResult(
        val uploaded: Int = 0,
        val downloaded: Int = 0,
        val skipped: Int = 0,
        val errors: Int = 0,
        val deleted: Int = 0,
        val removedLocal: Int = 0,
        val failed: List<String> = emptyList()
    )

    /** 多线程同步进度（线程安全）；onProgress 在 worker 线程回调，UI 需自行 runOnUiThread */
    class SyncProgress {
        @Volatile var filesTotal: Int = 0
        @Volatile var bytesTotal: Long = 0L
        private val lock = Any()
        private var filesDone = 0
        private var bytesDone = 0L
        @Volatile var currentFile: String = ""
        var startTime: Long = System.currentTimeMillis()
        var onProgress: ((SyncProgress) -> Unit)? = null

        fun report(bytes: Long, file: String) {
            synchronized(lock) {
                filesDone++
                bytesDone += bytes
                currentFile = file
            }
            onProgress?.invoke(this)
        }

        fun done(): Int = synchronized(lock) { filesDone }
        fun bytesDone(): Long = synchronized(lock) { bytesDone }
    }

    private data class WorkerResult(
        val done: Int = 0,
        val errors: Int = 0,
        val failed: List<String> = emptyList()
    )

    private fun <T> chunkList(list: List<T>, n: Int): List<List<T>> {
        if (n <= 1 || list.size <= 1) return listOf(list)
        val k = list.size / n
        val m = list.size % n
        val result = mutableListOf<List<T>>()
        var idx = 0
        for (i in 0 until n) {
            val len = k + if (i < m) 1 else 0
            if (len <= 0) continue
            result.add(list.subList(idx, idx + len))
            idx += len
        }
        return result
    }

    // ─── 清单（对齐 manifest.py build/load） ───

    internal fun buildManifest(ctx: Context): JSONObject {
        val db = MemeDb.get(ctx)
        val memes = JSONArray()
        for (m in db.getAll(0, Int.MAX_VALUE)) {
            val entry = JSONObject()
                .put("filename", m.filename)
                .put("name", m.originalName.ifEmpty { m.filename.substringBeforeLast('.') })
                .put("sha256", m.fileHash)
                .put("file_size", m.fileSize)
                .put("ai_description", m.aiDescription)
                .put("ai_ocr_text", m.aiOcrText)
            val cacheFile = StoragePaths.cacheDir(ctx).child(m.filename)
            if (cacheFile.exists) {
                entry.put("mtime", (cacheFile.lastModified / 1000).toString())
            }
            memes.put(entry)
        }
        val data = JSONObject()
            .put("version", MANIFEST_VERSION)
            .put("memes", memes)
            .put("collections", buildCollectionTree(ctx, null))
        return data
    }

    internal fun applyRemoteAiText(ctx: Context, data: JSONObject) {
        val db = MemeDb.get(ctx)
        val memes = data.optJSONArray("memes") ?: return
        for (i in 0 until memes.length()) {
            val entry = memes.optJSONObject(i) ?: continue
            if (!entry.has("ai_description") && !entry.has("ai_ocr_text")) continue
            val filename = entry.optString("filename", "")
            if (filename.isBlank() || db.getByFilename(filename) == null) continue
            db.applyRemoteAiText(
                filename,
                entry.optString("ai_description", ""),
                entry.optString("ai_ocr_text", "")
            )
        }
    }

    private fun buildCollectionTree(ctx: Context, parentId: Long?): JSONArray {
        val db = MemeDb.get(ctx)
        val arr = JSONArray()
        for (c in db.getCollections()) {
            val pid = c.parentId ?: 0L
            if (parentId == null) {
                if (pid != 0L) continue
            } else {
                if (pid != parentId) continue
            }
            val members = db.search(collectionId = c.id, limit = Int.MAX_VALUE)
            val filenames = JSONArray()
            for (m in members) filenames.put(m.filename)
            val children = buildCollectionTree(ctx, c.id)
            if (filenames.length() == 0 && children.length() == 0) {
                db.deleteCollection(c.id)
                continue
            }
            val node = JSONObject().put("name", c.name).put("filenames", filenames)
            if (children.length() > 0) node.put("children", children)
            arr.put(node)
        }
        return arr
    }

    private fun parseMemes(data: JSONObject): Map<String, JSONObject> {
        val map = HashMap<String, JSONObject>()
        val arr = data.optJSONArray("memes")
        if (arr != null) {
            for (i in 0 until arr.length()) {
                val obj = arr.optJSONObject(i) ?: continue
                val fname = obj.optString("filename", "")
                if (fname.isNotEmpty()) map[fname] = obj
            }
        }
        return map
    }

    private fun entriesFromDb(ctx: Context): Map<String, JSONObject> {
        val db = MemeDb.get(ctx)
        val map = HashMap<String, JSONObject>()
        for (m in db.getAll(0, Int.MAX_VALUE)) {
            map[m.filename] = JSONObject()
                .put("filename", m.filename)
                .put("name", m.originalName.ifEmpty { m.filename.substringBeforeLast('.') })
                .put("sha256", m.fileHash)
                .put("file_size", m.fileSize)
                .put("ai_description", m.aiDescription)
                .put("ai_ocr_text", m.aiOcrText)
        }
        return map
    }

    // ─── 后端抽象 ───

    private interface Backend {
        fun connect()
        fun testConnection()
        fun ensureRemoteDir(path: String)
        fun uploadFile(local: File, remotePath: String): Boolean
        fun downloadFile(remotePath: String, dest: File): Boolean
        fun fileExists(path: String): Boolean
        fun deleteFile(path: String): Boolean
        fun listFiles(path: String): List<String>
        fun close()
    }

    // ─── FTP 后端（java.net 直写，被动模式） ───

    private class FtpBackend(private val cfg: JSONObject) : Backend {
        private var control: Socket? = null
        private var reader: BufferedReader? = null
        private var writer: PrintWriter? = null

        override fun connect() {
            val host = cfg.optString("ftp_host", "")
            if (host.isEmpty()) throw SyncError("FTP host not configured")
            val port = cfg.optInt("ftp_port", 21)
            val user = cfg.optString("ftp_user", "")
            val password = cfg.optString("ftp_password", "")
            try {
                android.util.Log.d(TAG, "FTP connecting $host:$port")
                val sock = Socket()
                sock.connect(InetSocketAddress(host, port), 30000)
                sock.soTimeout = 60000
                val rd = BufferedReader(InputStreamReader(sock.getInputStream(), Charsets.UTF_8))
                val wr = PrintWriter(sock.getOutputStream(), true)
                val greeting = readReply(rd)
                android.util.Log.d(TAG, "FTP greeting: $greeting")
                wr.println("USER ${user.ifEmpty { "anonymous" }}")
                val userReply = readReply(rd)
                android.util.Log.d(TAG, "FTP USER reply: $userReply")
                wr.println("PASS $password")
                val passReply = readReply(rd)
                android.util.Log.d(TAG, "FTP PASS reply: $passReply")
                control = sock
                reader = rd
                writer = wr
            } catch (e: Exception) {
                android.util.Log.e(TAG, "FTP connect failed: $e")
                close()
                throw SyncError("FTP connect failed: $e")
            }
        }

        override fun testConnection() {}

        private fun readReply(rd: BufferedReader): String {
            val line = rd.readLine() ?: throw SyncError("FTP connection closed")
            val code = line.take(3)
            var last = line
            if (code.toIntOrNull() != null && line.length > 3 && line[3] == '-') {
                while (true) {
                    last = rd.readLine() ?: throw SyncError("FTP connection closed")
                    if (last.length >= 4 && last.startsWith("$code ")) break
                }
            }
            if (code.startsWith("4") || code.startsWith("5")) {
                throw SyncError("FTP server error: $last")
            }
            return last
        }

        private fun cmd(line: String): String {
            val rd = reader ?: throw SyncError("FTP not connected")
            writer?.println(line) ?: throw SyncError("FTP not connected")
            return readReply(rd)
        }

        private fun dataSocket(line: String): Socket {
            val reply = cmd(line)
            if (reply.isEmpty()) throw SyncError("FTP data command failed")
            val hostPort = reply.substringAfter('(').substringBefore(')')
            if (hostPort.isEmpty() || hostPort == reply) {
                throw SyncError("FTP 服务器未返回 PASV 地址")
            }
            val parts = hostPort.split(",")
            if (parts.size != 6) throw SyncError("FTP PASV 响应格式错误")
            val host = "${parts[0]}.${parts[1]}.${parts[2]}.${parts[3]}"
            val p = parts[4].toInt() * 256 + parts[5].toInt()
            val s = Socket()
            s.connect(InetSocketAddress(host, p), 15000)
            s.soTimeout = 30000
            return s
        }

        override fun ensureRemoteDir(path: String) {
            val parts = path.trim('/').split("/").filter { it.isNotEmpty() }
            var sofar = ""
            for (p in parts) {
                sofar += "/" + p
                try {
                    cmd("CWD $sofar")
                } catch (e: SyncError) {
                    cmd("MKD $sofar")
                    cmd("CWD $sofar")
                }
            }
        }

        override fun uploadFile(local: File, remotePath: String): Boolean {
            return try {
                val data = dataSocket("PASV")
                data.use {
                    local.inputStream().use { ins ->
                        val buf = ByteArray(65536)
                        while (true) {
                            val n = ins.read(buf)
                            if (n <= 0) break
                            it.getOutputStream().write(buf, 0, n)
                        }
                    }
                }
                cmd("STOR $remotePath")
                true
            } catch (e: Exception) {
                false
            }
        }

        override fun downloadFile(remotePath: String, dest: File): Boolean {
            return try {
                val data = dataSocket("PASV")
                data.use {
                    dest.parentFile?.mkdirs()
                    dest.outputStream().use { out ->
                        val buf = ByteArray(65536)
                        val ins = it.getInputStream()
                        while (true) {
                            val n = ins.read(buf)
                            if (n <= 0) break
                            out.write(buf, 0, n)
                        }
                    }
                }
                cmd("RETR $remotePath")
                true
            } catch (e: Exception) {
                false
            }
        }

        override fun fileExists(path: String): Boolean {
            return try {
                cmd("SIZE $path")
                true
            } catch (e: SyncError) {
                false
            }
        }

        override fun deleteFile(path: String): Boolean {
            return try {
                cmd("DELE $path")
                true
            } catch (e: SyncError) {
                false
            }
        }

        override fun listFiles(path: String): List<String> {
            return try {
                val names = mutableListOf<String>()
                val data = dataSocket("PASV")
                data.use {
                    val rd = BufferedReader(InputStreamReader(it.getInputStream(), Charsets.UTF_8))
                    while (true) {
                        val line = rd.readLine() ?: break
                        if (line.isNotEmpty() && !line.endsWith("/")) {
                            names.add(line.substringAfterLast('/'))
                        }
                    }
                }
                cmd("NLST $path")
                names
            } catch (e: Exception) {
                emptyList()
            }
        }

        override fun close() {
            try {
                writer?.println("QUIT")
            } catch (e: Exception) {
            }
            try {
                control?.close()
            } catch (e: Exception) {
            }
            control = null
            reader = null
            writer = null
        }
    }

    // ─── S3 后端（SigV4，兼容 R2 / MinIO） ───

    private class S3Backend(private val cfg: JSONObject, private val isR2: Boolean) : Backend {
        private var endpoint = ""
        private var region = ""
        private var accessKey = ""
        private var secretKey = ""
        private var bucket = ""
        private var prefix = ""
        private val awsDate = java.text.SimpleDateFormat("yyyyMMdd", java.util.Locale.US).apply {
            timeZone = java.util.TimeZone.getTimeZone("UTC")
        }
        private val awsTimestamp = java.text.SimpleDateFormat("yyyyMMdd'T'HHmmss'Z'", java.util.Locale.US).apply {
            timeZone = java.util.TimeZone.getTimeZone("UTC")
        }

        override fun connect() {
            if (isR2) {
                val accountId = cfg.optString("r2_account_id", "")
                bucket = cfg.optString("r2_bucket", "")
                accessKey = cfg.optString("r2_access_key_id", "")
                secretKey = cfg.optString("r2_secret_access_key", "")
                if (accountId.isEmpty() || bucket.isEmpty()) throw SyncError("R2 account ID and bucket not configured")
                if (accessKey.isEmpty() || secretKey.isEmpty()) throw SyncError("R2 credentials not configured")
                endpoint = "https://$accountId.r2.cloudflarestorage.com"
                prefix = cfg.optString("r2_path", "").trim('/')
            } else {
                endpoint = cfg.optString("s3_endpoint", "")
                bucket = cfg.optString("s3_bucket", "")
                region = cfg.optString("s3_region", "")
                accessKey = cfg.optString("s3_access_key", "")
                secretKey = cfg.optString("s3_secret_key", "")
                if (endpoint.isEmpty() || bucket.isEmpty()) throw SyncError("S3 endpoint or bucket not configured")
                prefix = cfg.optString("s3_path", "").trim('/')
            }
            if (region.isEmpty()) region = "us-east-1"
        }

        override fun testConnection() {}

        private fun key(remotePath: String): String {
            val rel = remotePath.trimStart('/')
            return if (prefix.isEmpty()) rel else "$prefix/$rel"
        }

        private fun encodeSegment(seg: String): String {
            val out = StringBuilder()
            for (b in seg.toByteArray(Charsets.UTF_8)) {
                val c = b.toInt() and 0xFF
                if (c in 'a'.code..'z'.code || c in 'A'.code..'Z'.code || c in '0'.code..'9'.code ||
                    c == '-'.code || c == '_'.code || c == '.'.code || c == '~'.code
                ) {
                    out.append(c.toChar())
                } else {
                    out.append("%").append("%02X".format(c))
                }
            }
            return out.toString()
        }

        private fun urlForKey(key: String): String {
            val base = endpoint.trimEnd('/')
            val encoded = key.split("/").joinToString("/") { encodeSegment(it) }
            return "$base/$bucket/$encoded"
        }

        private fun hmac(key: ByteArray, data: String): ByteArray {
            val mac = Mac.getInstance("HmacSHA256")
            mac.init(SecretKeySpec(key, "HmacSHA256"))
            return mac.doFinal(data.toByteArray(Charsets.UTF_8))
        }

        private fun sha256Hex(data: ByteArray): String {
            val md = MessageDigest.getInstance("SHA-256")
            return md.digest(data).joinToString("") { "%02x".format(it) }
        }

        private fun sign(method: String, url: String): HttpURLConnection {
            val u = URL(url)
            val host = u.host
            val path = if (u.path.isEmpty()) "/" else u.path
            val query = u.query ?: ""
            val now = java.util.Date()
            val amzDate = awsTimestamp.format(now)
            val dateStamp = awsDate.format(now)
            val payloadHash = "UNSIGNED-PAYLOAD"

            val canonicalHeaders =
                "host:$host\n" +
                    "x-amz-content-sha256:$payloadHash\n" +
                    "x-amz-date:$amzDate\n"
            val signedHeaders = "host;x-amz-content-sha256;x-amz-date"
            val canonicalRequest = "$method\n$path\n$query\n$canonicalHeaders\n$signedHeaders\n$payloadHash"
            val scope = "$dateStamp/$region/s3/aws4_request"
            val stringToSign = "AWS4-HMAC-SHA256\n$amzDate\n$scope\n${sha256Hex(canonicalRequest.toByteArray(Charsets.UTF_8))}"

            val dateKey = hmac(("AWS4$secretKey").toByteArray(Charsets.UTF_8), dateStamp)
            val regionKey = hmac(dateKey, region)
            val serviceKey = hmac(regionKey, "s3")
            val signingKey = hmac(serviceKey, "aws4_request")
            val signature = hmac(signingKey, stringToSign).joinToString("") { "%02x".format(it) }

            val conn = u.openConnection() as HttpURLConnection
            conn.requestMethod = method
            conn.connectTimeout = 30000
            conn.readTimeout = 60000
            conn.setRequestProperty("Host", host)
            conn.setRequestProperty("x-amz-date", amzDate)
            conn.setRequestProperty("x-amz-content-sha256", payloadHash)
            conn.setRequestProperty(
                "Authorization",
                "AWS4-HMAC-SHA256 Credential=$accessKey/$scope, SignedHeaders=$signedHeaders, Signature=$signature"
            )
            return conn
        }

        override fun ensureRemoteDir(path: String) {}

        override fun uploadFile(local: File, remotePath: String): Boolean {
            return try {
                val conn = sign("PUT", urlForKey(key(remotePath)))
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/octet-stream")
                conn.setFixedLengthStreamingMode(local.length())
                local.inputStream().use { ins ->
                    val buf = ByteArray(65536)
                    val out = conn.outputStream
                    while (true) {
                        val n = ins.read(buf)
                        if (n <= 0) break
                        out.write(buf, 0, n)
                    }
                }
                val code = conn.responseCode
                conn.disconnect()
                android.util.Log.d(TAG, "S3 PUT $remotePath -> HTTP $code")
                code in 200..299
            } catch (e: Exception) {
                android.util.Log.e(TAG, "S3 upload failed $remotePath: $e")
                false
            }
        }

        override fun downloadFile(remotePath: String, dest: File): Boolean {
            return try {
                val conn = sign("GET", urlForKey(key(remotePath)))
                val code = conn.responseCode
                if (code !in 200..299) {
                    android.util.Log.e(TAG, "S3 GET $remotePath -> HTTP $code")
                    conn.disconnect()
                    return false
                }
                dest.parentFile?.mkdirs()
                conn.inputStream.use { ins ->
                    dest.outputStream().use { out ->
                        val buf = ByteArray(65536)
                        while (true) {
                            val n = ins.read(buf)
                            if (n <= 0) break
                            out.write(buf, 0, n)
                        }
                    }
                }
                conn.disconnect()
                true
            } catch (e: Exception) {
                android.util.Log.e(TAG, "S3 download failed $remotePath: $e")
                false
            }
        }

        override fun fileExists(path: String): Boolean {
            return try {
                val conn = sign("HEAD", urlForKey(key(path)))
                val code = conn.responseCode
                conn.disconnect()
                android.util.Log.d(TAG, "S3 HEAD $path -> HTTP $code")
                code in 200..299
            } catch (e: Exception) {
                android.util.Log.e(TAG, "S3 HEAD $path failed: $e")
                false
            }
        }

        override fun deleteFile(path: String): Boolean {
            return try {
                val conn = sign("DELETE", urlForKey(key(path)))
                val code = conn.responseCode
                conn.disconnect()
                android.util.Log.d(TAG, "S3 DELETE $path -> HTTP $code")
                code in 200..299
            } catch (e: Exception) {
                false
            }
        }

        override fun listFiles(path: String): List<String> {
            return try {
                val p = prefixPath(path)
                val listKey = if (prefix.isEmpty()) p.trim('/') else "$prefix/${p.trim('/')}"
                val conn = sign("GET", urlForKey(listKey))
                val code = conn.responseCode
                if (code !in 200..299) {
                    conn.disconnect()
                    return emptyList()
                }
                val body = conn.inputStream.bufferedReader().use { it.readText() }
                conn.disconnect()
                val files = mutableListOf<String>()
                var idx = 0
                val re = Regex("<Key>(.*?)</Key>")
                for (m in re.findAll(body)) {
                    val k = m.groupValues[1]
                    if (!k.endsWith("/")) {
                        val base = if (p.isEmpty()) "" else p.trim('/') + "/"
                        if (k.startsWith(base)) files.add(k.substring(base.length))
                    }
                }
                files
            } catch (e: Exception) {
                emptyList()
            }
        }

        private fun prefixPath(path: String): String {
            val rel = path.trim('/')
            return if (prefix.isEmpty()) rel else rel.removePrefix(prefix.trimStart('/'))
        }

        override fun close() {}
    }

    // ─── WebDAV 后端 ───

    private class WebDavBackend(private val cfg: JSONObject) : Backend {
        private var baseUrl = ""
        private var authHeader = ""
        private var timeout = 30

        /** 简单 HTTP/1.1 响应：状态码 + 响应体字节 */
        private class DavResponse(val code: Int, val body: ByteArray)        override fun connect() {
            val url = cfg.optString("webdav_url", "")
            if (url.isEmpty()) throw SyncError("WebDAV url not configured")
            val u = URL(url)
            if (u.protocol != "http" && u.protocol != "https") {
                throw SyncError("WebDAV URL 必须以 http:// 或 https:// 开头")
            }
            if (u.host.isEmpty()) throw SyncError("WebDAV URL 缺少主机名")
            val encPath = u.path.split("/").joinToString("/") { encodeSegment(it) }
            baseUrl = "${u.protocol}://${u.host}${if (u.port > 0) ":${u.port}" else ""}${encPath.trimEnd('/')}"
            val user = cfg.optString("webdav_user", "")
            val password = cfg.optString("webdav_password", "")
            if (user.isNotEmpty()) {
                authHeader = "Basic " + Base64.getEncoder().encodeToString("$user:$password".toByteArray(Charsets.UTF_8))
            }
            timeout = cfg.optInt("webdav_timeout", 30).coerceAtLeast(5)
        }

        override fun testConnection() {
            val url = davUrl(cfg.optString("webdav_path", ""))
            try {
                val resp = davHttp("PROPFIND", url, null, mapOf("Depth" to "0"))
                if (resp.code !in 200..299) throw SyncError("WebDAV PROPFIND returned HTTP ${resp.code}")
            } catch (e: SyncError) {
                throw e
            } catch (e: IOException) {
                throw SyncError("WebDAV 网络不可达: $e")
            }
        }

        private fun encodeSegment(seg: String): String {
            if (seg.isEmpty()) return seg
            val out = StringBuilder()
            for (b in seg.toByteArray(Charsets.UTF_8)) {
                val c = b.toInt() and 0xFF
                if (c in 'a'.code..'z'.code || c in 'A'.code..'Z'.code || c in '0'.code..'9'.code ||
                    c == '-'.code || c == '_'.code || c == '.'.code || c == '~'.code || c == '%'.code
                ) {
                    out.append(c.toChar())
                } else {
                    out.append("%").append("%02X".format(c))
                }
            }
            return out.toString()
        }

        private fun davUrl(remotePath: String): String {
            val rel = remotePath.trimStart('/')
            val enc = rel.split("/").joinToString("/") { encodeSegment(it) }
            return if (enc.isEmpty()) baseUrl.trimEnd('/') else baseUrl.trimEnd('/') + "/" + enc
        }

        /**
         * 原始 socket HTTP/1.1 请求，支持任意方法（PROPFIND/MKCOL 等 HttpURLConnection 拒绝的方法）。
         * 每次请求独立建连、Connection: close，不复用连接（规避 Android HttpURLConnection 方法白名单与
         * chunked 连接池问题）。HTTPS 走 SSLSocket。
         */
        private fun davHttp(
            method: String,
            url: String,
            data: Any?,
            headers: Map<String, String> = emptyMap(),
            sink: java.io.OutputStream? = null
        ): DavResponse {
            val u = URL(url)
            val isTls = u.protocol == "https"
            val host = u.host
            val port = if (u.port > 0) u.port else if (isTls) 443 else 80
            val path = u.path.ifEmpty { "/" } + (u.query?.let { "?$it" } ?: "")
            val raw = Socket()
            try {
                raw.connect(InetSocketAddress(host, port), timeout * 1000)
                raw.soTimeout = timeout * 1000
                val sock: Socket = if (isTls) {
                    val ssl = (SSLSocketFactory.getDefault() as SSLSocketFactory)
                        .createSocket(raw, host, port, true) as SSLSocket
                    ssl.startHandshake()
                    ssl
                } else {
                    raw
                }
                return try {
                    val out = BufferedOutputStream(sock.getOutputStream())
                    val sb = StringBuilder()
                    sb.append("$method $path HTTP/1.1\r\n")
                    sb.append("Host: $host\r\n")
                    sb.append("User-Agent: OhMyMeme-Android\r\n")
                    sb.append("Connection: close\r\n")
                    if (authHeader.isNotEmpty()) sb.append("Authorization: $authHeader\r\n")
                    for ((k, v) in headers) sb.append("$k: $v\r\n")
                    var payload: ByteArray? = null
                    var payloadLen = -1L
                    if (data is ByteArray) {
                        payload = data
                        payloadLen = data.size.toLong()
                    } else if (data is File) {
                        payloadLen = data.length()
                    }
                    if (payloadLen >= 0) sb.append("Content-Length: $payloadLen\r\n")
                    sb.append("\r\n")
                    out.write(sb.toString().toByteArray(Charsets.UTF_8))
                    if (payload != null) {
                        out.write(payload)
                    } else if (data is File) {
                        data.inputStream().use { ins ->
                            val buf = ByteArray(65536)
                            while (true) {
                                val n = ins.read(buf)
                                if (n <= 0) break
                                out.write(buf, 0, n)
                            }
                        }
                    }
                    out.flush()

                    val input = BufferedInputStream(sock.getInputStream())
                    val statusLine = readHttpLine(input) ?: throw IOException("WebDAV 无响应")
                    val parts = statusLine.split(" ")
                    val code = parts.getOrNull(1)?.toIntOrNull()
                        ?: throw IOException("WebDAV 状态行异常: $statusLine")
                    val respHeaders = LinkedHashMap<String, String>()
                    while (true) {
                        val line = readHttpLine(input) ?: break
                        if (line.isEmpty()) break
                        val idx = line.indexOf(':')
                        if (idx > 0) {
                            respHeaders[line.substring(0, idx).trim().lowercase()] =
                                line.substring(idx + 1).trim()
                        }
                    }
                    val body = if (sink != null) {
                        readHttpBodyToSink(input, respHeaders, method, sink)
                        ByteArray(0)
                    } else {
                        readHttpBody(input, respHeaders, method)
                    }
                    DavResponse(code, body)
                } finally {
                    try {
                        sock.close()
                    } catch (e: Exception) {
                        // ignore
                    }
                }
            } finally {
                try {
                    raw.close()
                } catch (e: Exception) {
                    // ignore
                }
            }
        }

        /** 读一行（\r\n 或 \n 结尾，不含换行） */
        private fun readHttpLine(input: InputStream): String? {
            val sb = StringBuilder()
            var prev = -1
            while (true) {
                val c = input.read()
                if (c < 0) {
                    if (sb.isEmpty() && prev < 0) return null
                    return sb.toString()
                }
                if (c == '\n'.code) {
                    if (sb.isNotEmpty() && sb.last() == '\r') sb.setLength(sb.length - 1)
                    return sb.toString()
                }
                sb.append(c.toChar())
                prev = c
            }
        }

        /** 按 Content-Length / chunked / 读到连接关闭 三种方式读取响应体 */
        private fun readHttpBody(input: InputStream, headers: Map<String, String>, method: String): ByteArray {
            if (method.equals("HEAD", ignoreCase = true)) return ByteArray(0)
            val te = headers["transfer-encoding"]
            if (te != null && te.contains("chunked", ignoreCase = true)) {
                val body = ByteArrayOutputStream()
                readChunked(input, body)
                return body.toByteArray()
            }
            val cl = headers["content-length"]?.toLongOrNull()
            if (cl != null && cl >= 0) {
                val buf = ByteArray(cl.toInt())
                readFully(input, buf, cl.toInt())
                return buf
            }
            // 无长度信息：读到连接关闭
            val body = ByteArrayOutputStream()
            val buf = ByteArray(65536)
            while (true) {
                val n = input.read(buf)
                if (n <= 0) break
                body.write(buf, 0, n)
            }
            return body.toByteArray()
        }

        /** 分块读取响应体并写入 sink（用于流式下载到文件，避免大文件撑爆内存） */
        private fun readHttpBodyToSink(input: InputStream, headers: Map<String, String>, method: String, sink: java.io.OutputStream) {
            if (method.equals("HEAD", ignoreCase = true)) return
            val te = headers["transfer-encoding"]
            if (te != null && te.contains("chunked", ignoreCase = true)) {
                readChunked(input, sink)
                return
            }
            val cl = headers["content-length"]?.toLongOrNull()
            if (cl != null && cl >= 0) {
                var remaining = cl
                val buf = ByteArray(65536)
                while (remaining > 0) {
                    val want = minOf(buf.size.toLong(), remaining).toInt()
                    val n = input.read(buf, 0, want)
                    if (n < 0) break
                    sink.write(buf, 0, n)
                    remaining -= n
                }
                return
            }
            // 无长度信息：读到连接关闭
            val buf = ByteArray(65536)
            while (true) {
                val n = input.read(buf)
                if (n <= 0) break
                sink.write(buf, 0, n)
            }
        }

        /** 解析 chunked 块并写入 out */
        private fun readChunked(input: InputStream, out: java.io.OutputStream) {
            while (true) {
                val sizeLine = readHttpLine(input) ?: break
                val size = sizeLine.trim().substringBefore(';').toIntOrNull(16) ?: break
                if (size == 0) {
                    // 读到 trailer 直到空行
                    while (true) {
                        val t = readHttpLine(input) ?: break
                        if (t.isEmpty()) break
                    }
                    break
                }
                var remaining = size
                val chunk = ByteArray(65536)
                while (remaining > 0) {
                    val want = minOf(chunk.size.toLong(), remaining.toLong()).toInt()
                    val n = input.read(chunk, 0, want)
                    if (n <= 0) break
                    out.write(chunk, 0, n)
                    remaining -= n
                }
                readHttpLine(input) // chunk 后的 CRLF
            }
        }

        /** 尝试读满 buf 的 len 字节，返回实际读取字节数 */
        private fun readFully(input: InputStream, buf: ByteArray, len: Int): Int {
            var total = 0
            while (total < len) {
                val n = input.read(buf, total, len - total)
                if (n < 0) break
                total += n
            }
            return total
        }

        override fun ensureRemoteDir(path: String) {
            var rel = ""
            for (p in path.trim('/').split("/").filter { it.isNotEmpty() }) {
                rel += "/" + p
                try {
                    val resp = davHttp("MKCOL", davUrl(rel), null)
                    if (resp.code in 200..399) continue
                    if (fileExists(rel)) continue
                    throw SyncError("MKCOL $rel 失败: HTTP ${resp.code}")
                } catch (e: SyncError) {
                    throw e
                } catch (e: IOException) {
                    if (fileExists(rel)) continue
                    throw SyncError("MKCOL $rel 失败: $e")
                }
            }
        }

        override fun uploadFile(local: File, remotePath: String): Boolean {
            return try {
                val resp = davHttp(
                    "PUT", davUrl(remotePath), local,
                    mapOf("Content-Type" to "application/octet-stream")
                )
                resp.code in 200..299
            } catch (e: Exception) {
                false
            }
        }

        override fun downloadFile(remotePath: String, dest: File): Boolean {
            return try {
                dest.parentFile?.mkdirs()
                val tmp = File(dest.parentFile, dest.name + ".tmp")
                var respCode = 0
                tmp.outputStream().use { out ->
                    val resp = davHttp("GET", davUrl(remotePath), null, sink = out)
                    respCode = resp.code
                }
                if (respCode !in 200..299) {
                    tmp.delete()
                    return false
                }
                if (dest.exists()) dest.delete()
                tmp.renameTo(dest)
                true
            } catch (e: Exception) {
                try {
                    if (dest.parentFile != null) {
                        File(dest.parentFile, dest.name + ".tmp").delete()
                    }
                } catch (e2: Exception) {
                    // ignore
                }
                false
            }
        }

        override fun fileExists(path: String): Boolean {
            return try {
                val resp = davHttp("PROPFIND", davUrl(path), null, mapOf("Depth" to "0"))
                resp.code in 200..299
            } catch (e: IOException) {
                try {
                    val resp = davHttp("HEAD", davUrl(path), null)
                    resp.code in 200..299
                } catch (e2: Exception) {
                    false
                }
            }
        }

        override fun deleteFile(path: String): Boolean {
            return try {
                val resp = davHttp("DELETE", davUrl(path), null)
                resp.code == 404 || resp.code in 200..299
            } catch (e: Exception) {
                false
            }
        }

        override fun listFiles(path: String): List<String> {
            return try {
                val resp = davHttp("PROPFIND", davUrl(path), null, mapOf("Depth" to "1"))
                if (resp.code !in 200..299) return emptyList()
                val raw = String(resp.body, Charsets.UTF_8)
                val files = mutableListOf<String>()
                val re = Regex("<D:href>(.*?)</D:href>|<d:href>(.*?)</d:href>")
                for (m in re.findAll(raw)) {
                    val href = m.groupValues[1].ifEmpty { m.groupValues[2] }
                    if (href.endsWith("/")) continue
                    val decoded = URLDecoder.decode(href, Charsets.UTF_8.name())
                    val name = decoded.substringAfterLast('/')
                    if (name.isNotEmpty()) files.add(name)
                }
                files
            } catch (e: Exception) {
                emptyList()
            }
        }

        override fun close() {}
    }

    // ─── 后端工厂 ───

    private fun createBackend(cfg: JSONObject): Backend {
        return when (cfg.optString("sync_type", "")) {
            "ftp" -> FtpBackend(cfg)
            "s3" -> S3Backend(cfg, false)
            "r2" -> S3Backend(cfg, true)
            "webdav" -> WebDavBackend(cfg)
            else -> throw SyncError("No sync type configured")
        }
    }

    private fun remoteRoot(cfg: JSONObject): String {
        return when (cfg.optString("sync_type", "")) {
            "ftp" -> cfg.optString("ftp_path", "/")
            "webdav" -> cfg.optString("webdav_path", "")
            else -> ""
        }
    }

    private fun remoteIndexPath(root: String): String {
        return root.trimEnd('/') + "/" + INDEX_FILENAME
    }

    private fun remoteMemePath(root: String, filename: String): String {
        return root.trimEnd('/') + "/" + REMOTE_MEME_DIR + "/" + filename
    }

    // ─── 公开 API ───

    fun syncTest(ctx: Context): String {
        return try {
            val cfg = ConfigStore.get(ctx)
            val bk = createBackend(cfg)
            try {
                bk.connect()
                bk.testConnection()
            } finally {
                bk.close()
            }
            "ok"
        } catch (e: Exception) {
            e.message ?: "unknown error"
        }
    }

    fun checkSyncStatus(ctx: Context): String {
        return try {
            val cfg = ConfigStore.get(ctx)
            val bk = createBackend(cfg)
            try {
                bk.connect()
                val data = downloadIndex(ctx, bk, cfg)
                if (data == null) return "无法获取远端清单"
                val remote = parseMemes(data).keys
                val local = entriesFromDb(ctx).keys
                val extra = local - remote
                val missing = remote - local
                if (extra.isEmpty() && missing.isEmpty()) {
                    return "已同步（本地 ${local.size}，远端 ${remote.size}）"
                }
                val sb = StringBuilder("本地 ${local.size}，远端 ${remote.size}")
                if (extra.isNotEmpty()) sb.append("\n仅本地: ${extra.joinToString(", ") { it }.take(120)}")
                if (missing.isNotEmpty()) sb.append("\n仅远端: ${missing.joinToString(", ") { it }.take(120)}")
                sb.toString()
            } finally {
                bk.close()
            }
        } catch (e: Exception) {
            e.message ?: "unknown error"
        }
    }

    fun push(ctx: Context, progress: SyncProgress? = null): SyncResult {
        android.util.Log.d(TAG, "push start")
        val cfg = ConfigStore.get(ctx)
        val root = remoteRoot(cfg)
        val cacheDir = StoragePaths.cacheDir(ctx)
        val deleteRemote = cfg.optBoolean("sync_delete_remote", false)
        val maxWorkers = cfg.optInt("sync_threads", 3).coerceIn(1, 8)
        val local = entriesFromDb(ctx)
        if (local.isEmpty()) throw SyncError("local manifest is empty, nothing to push")

        val remote: Map<String, JSONObject>
        val bkMain = createBackend(cfg)
        try {
            bkMain.connect()
            bkMain.ensureRemoteDir(root)
            val remoteData = downloadIndex(ctx, bkMain, cfg)
            remote = if (remoteData != null) parseMemes(remoteData) else emptyMap()
        } finally {
            bkMain.close()
        }

        val entries = local.entries.toList()
        val filesTotal = entries.size
        val bytesTotal = entries.sumOf { (fname, _) -> cacheDir.child(fname).length }
        progress?.let {
            it.filesTotal = filesTotal
            it.bytesTotal = bytesTotal
        }
        val chunks = chunkList(entries, minOf(maxWorkers, filesTotal))

        val pool = Executors.newFixedThreadPool(chunks.size)
        var uploaded = 0
        var skipped = 0
        var errors = 0
        val failed = mutableListOf<String>()
        try {
            val futures = chunks.map { chunk ->
                pool.submit(Callable {
                    pushWorker(ctx, chunk, root, cacheDir, remote, progress)
                })
            }
            for (f in futures) {
                val r = f.get()
                uploaded += r.done
                errors += r.errors
                failed.addAll(r.failed)
            }
            skipped = filesTotal - uploaded - errors
        } catch (e: Exception) {
            throw SyncError(e.message ?: "sync push failed")
        } finally {
            pool.shutdownNow()
        }
        if (errors > 0) {
            throw SyncError("$errors 个文件上传失败，未更新远端清单")
        }
        var deleted = 0
        val bkFin = createBackend(cfg)
        try {
            bkFin.connect()
            if (deleteRemote) {
                for (fname in remote.keys) {
                    if (fname in local) continue
                    if (bkFin.deleteFile(remoteMemePath(root, fname))) deleted++
                }
            }
            var data = buildManifest(ctx)
            val kept = remote.values.filter { it.optString("filename", "") !in local.keys }
            if (kept.isNotEmpty()) {
                val arr = data.optJSONArray("memes")!!
                for (m in kept) arr.put(m)
                data.put("memes", arr)
            }
            val indexFile = writeTempIndex(ctx, data)
            if (!bkFin.uploadFile(indexFile, remoteIndexPath(root))) {
                indexFile.delete()
                throw SyncError("远端清单上传失败")
            }
            indexFile.delete()
        } finally {
            bkFin.close()
        }
        android.util.Log.d(TAG, "push done uploaded=$uploaded skipped=$skipped deleted=$deleted")
        return SyncResult(uploaded = uploaded, skipped = skipped, errors = 0, deleted = deleted, failed = failed)
    }

    private fun pushWorker(
        ctx: Context,
        chunk: List<Map.Entry<String, JSONObject>>,
        root: String,
        cacheDir: StorFile,
        remote: Map<String, JSONObject>,
        progress: SyncProgress?
    ): WorkerResult {
        val cfg = ConfigStore.get(ctx)
        val bk = createBackend(cfg)
        var done = 0
        var errors = 0
        val failed = mutableListOf<String>()
        try {
            bk.connect()
            bk.ensureRemoteDir(root)
            val memeDir = root + "/" + REMOTE_MEME_DIR
            for ((fname, entry) in chunk) {
                val remoteEntry = remote[fname]
                val localFile = cacheDir.child(fname)
                if (remoteEntry != null &&
                    remoteEntry.optString("sha256", "") == entry.optString("sha256", "")
                ) {
                    if (bk.fileExists(remoteMemePath(root, fname))) {
                        done++
                        progress?.report(0, fname)
                        continue
                    }
                }
                if (!localFile.exists) {
                    errors++
                    failed.add(fname)
                    progress?.report(0, fname)
                    continue
                }
                bk.ensureRemoteDir(memeDir)
                val tmp = File(ctx.cacheDir, "push_${System.nanoTime()}.tmp")
                val ok = try {
                    localFile.copyTo(tmp)
                    bk.uploadFile(tmp, remoteMemePath(root, fname))
                } catch (e: Exception) {
                    false
                } finally {
                    tmp.delete()
                }
                if (ok) {
                    done++
                    progress?.report(localFile.length, fname)
                } else {
                    errors++
                    failed.add(fname)
                    progress?.report(0, fname)
                }
            }
        } catch (e: Exception) {
            android.util.Log.e(TAG, "push worker failed: $e")
            val remaining = chunk.size - done - errors
            if (remaining > 0) {
                errors += remaining
                failed.add("$remaining 个文件因 worker 中断未处理")
            }
        } finally {
            bk.close()
        }
        return WorkerResult(done, errors, failed)
    }

    fun pull(ctx: Context, progress: SyncProgress? = null): SyncResult {
        android.util.Log.d(TAG, "pull start")
        val cfg = ConfigStore.get(ctx)
        val root = remoteRoot(cfg)
        val cacheDir = StoragePaths.cacheDir(ctx)
        val removeLocal = cfg.optBoolean("sync_remove_local", false)
        val maxWorkers = cfg.optInt("sync_threads", 3).coerceIn(1, 8)

        val bkMain = createBackend(cfg)
        val data: JSONObject
        try {
            bkMain.connect()
            data = downloadIndex(ctx, bkMain, cfg) ?: throw SyncError("no remote manifest available")
        } finally {
            bkMain.close()
        }
        val remote = parseMemes(data)
        val local = entriesFromDb(ctx)
        val entries = remote.entries.toList()
        val filesTotal = entries.size
        val bytesTotal = entries.sumOf { (fname, rentry) ->
            if (local[fname]?.optString("sha256", "") == rentry.optString("sha256", "") &&
                cacheDir.child(fname).exists
            ) 0L else rentry.optLong("file_size", 0L)
        }
        progress?.let {
            it.filesTotal = filesTotal
            it.bytesTotal = bytesTotal
        }
        val chunks = chunkList(entries, minOf(maxWorkers, filesTotal))

        val pool = Executors.newFixedThreadPool(chunks.size)
        var downloaded = 0
        var skipped = 0
        var errors = 0
        val failed = mutableListOf<String>()
        try {
            val futures = chunks.map { chunk ->
                pool.submit(Callable {
                    pullWorker(ctx, chunk, root, cacheDir, local, progress)
                })
            }
            for (f in futures) {
                val r = f.get()
                downloaded += r.done
                errors += r.errors
                failed.addAll(r.failed)
            }
            skipped = filesTotal - downloaded - errors
        } catch (e: Exception) {
            throw SyncError(e.message ?: "sync pull failed")
        } finally {
            pool.shutdownNow()
        }

        val db = MemeDb.get(ctx)
        for (fname in remote.keys) {
            val localFile = cacheDir.child(fname)
            if (!localFile.exists || localFile.length == 0L) continue
            if (db.getByFilename(fname) != null) continue
            val rentry = remote[fname] ?: continue
            val dims = readDimensions(localFile)
            val oname = rentry.optString("name", "").ifEmpty { fname.substringBeforeLast('.') }
            db.addMeme(
                filename = fname,
                fileHash = rentry.optString("sha256", ""),
                width = dims.first,
                height = dims.second,
                fileSize = localFile.length,
                mimeType = "image/${fname.substringAfterLast('.', "png").lowercase()}",
                originalName = oname,
                aiDescription = rentry.optString("ai_description", ""),
                aiOcrText = rentry.optString("ai_ocr_text", "")
            )
        }
        if (removeLocal) {
            var removed = 0
            val thumbs = StoragePaths.thumbnailDir(ctx)
            for (fname in local.keys) {
                if (fname in remote) continue
                val row = db.getByFilename(fname)
                if (row != null) {
                    thumbs.listFiles().forEach { t ->
                        if (t.name.startsWith("${row.id}_")) t.delete()
                    }
                    db.deleteMeme(row.id)
                }
                val f = cacheDir.child(fname)
                if (f.exists && f.delete()) removed++
            }
            applyRemoteOrder(ctx, data)
            return SyncResult(
                downloaded = downloaded, skipped = skipped, errors = errors,
                removedLocal = removed, failed = failed
            )
        }
        applyRemoteCollections(ctx, data)
        applyRemoteAiText(ctx, data)
        applyRemoteOrder(ctx, data)
        if (errors > 0) {
            throw SyncError("$errors 个文件下载失败，本地清单仅包含成功项")
        }
        android.util.Log.d(TAG, "pull done downloaded=$downloaded skipped=$skipped")
        return SyncResult(downloaded = downloaded, skipped = skipped, errors = 0, failed = failed)
    }

    private fun pullWorker(
        ctx: Context,
        chunk: List<Map.Entry<String, JSONObject>>,
        root: String,
        cacheDir: StorFile,
        local: Map<String, JSONObject>,
        progress: SyncProgress?
    ): WorkerResult {
        val cfg = ConfigStore.get(ctx)
        val bk = createBackend(cfg)
        var done = 0
        var errors = 0
        val failed = mutableListOf<String>()
        try {
            bk.connect()
            for ((fname, rentry) in chunk) {
                val localFile = cacheDir.child(fname)
                if (local[fname]?.optString("sha256", "") == rentry.optString("sha256", "") &&
                    localFile.exists
                ) {
                    done++
                    progress?.report(0, fname)
                    continue
                }
                val tmp = File(ctx.cacheDir, "pull_${System.nanoTime()}.tmp")
                val ok = try {
                    bk.downloadFile(remoteMemePath(root, fname), tmp)
                } catch (e: Exception) {
                    false
                }
                if (ok && tmp.length() == 0L) {
                    errors++
                    failed.add(fname)
                    progress?.report(0, fname)
                } else if (ok) {
                    val mime = "image/${fname.substringAfterLast('.', "png").lowercase()}"
                    val dst = cacheDir.createFile(fname, mime)
                    dst.writeFrom(tmp)
                    done++
                    progress?.report(tmp.length(), fname)
                } else {
                    errors++
                    failed.add(fname)
                    progress?.report(0, fname)
                }
                tmp.delete()
            }
        } catch (e: Exception) {
            android.util.Log.e(TAG, "pull worker failed: $e")
            val remaining = chunk.size - done - errors
            if (remaining > 0) {
                errors += remaining
                failed.add("$remaining 个文件因 worker 中断未处理")
            }
        } finally {
            bk.close()
        }
        return WorkerResult(done, errors, failed)
    }

    fun deleteAllRemote(ctx: Context): Pair<Boolean, String> {
        return try {
            val cfg = ConfigStore.get(ctx)
            val root = remoteRoot(cfg)
            val bk = createBackend(cfg)
            try {
                bk.connect()
                val data = downloadIndex(ctx, bk, cfg)
                val remote = if (data != null) parseMemes(data) else emptyMap()
                var count = 0
                for (fname in remote.keys) {
                    if (bk.deleteFile(remoteMemePath(root, fname))) count++
                }
                bk.deleteFile(remoteIndexPath(root))
                return true to "已删除 $count 个远端文件"
            } finally {
                bk.close()
            }
        } catch (e: Exception) {
            false to (e.message ?: "unknown error")
        }
    }

    fun cleanupRemoteOrphans(ctx: Context, delete: Boolean = false): Pair<Boolean, String> {
        return try {
            val cfg = ConfigStore.get(ctx)
            val root = remoteRoot(cfg)
            val bk = createBackend(cfg)
            try {
                bk.connect()
                val memeDir = root.trimEnd('/') + "/" + REMOTE_MEME_DIR
                val remoteFiles = try {
                    bk.listFiles(memeDir)
                } catch (e: NotImplementedError) {
                    emptyList()
                } catch (e: Exception) {
                    emptyList()
                }
                val data = downloadIndex(ctx, bk, cfg)
                val remoteMemes = if (data != null) parseMemes(data).keys else emptySet()
                val orphans = remoteFiles.filter { it !in remoteMemes }
                var removed = 0
                if (delete) {
                    for (fname in orphans) {
                        if (bk.deleteFile(remoteMemePath(root, fname))) removed++
                    }
                }
                val msg = if (delete) "已删除 $removed 个孤儿文件（共 ${orphans.size}）"
                else "发现孤儿文件 ${orphans.size} 个"
                true to msg
            } finally {
                bk.close()
            }
        } catch (e: Exception) {
            false to (e.message ?: "unknown error")
        }
    }

    fun deleteAllLocal(ctx: Context): Int {
        val db = MemeDb.get(ctx)
        val memes = db.getAll(0, Int.MAX_VALUE)
        val cache = StoragePaths.cacheDir(ctx)
        val thumbs = StoragePaths.thumbnailDir(ctx)
        var count = 0
        for (m in memes) {
            val f = cache.child(m.filename)
            if (f.exists && f.delete()) count++
            thumbs.listFiles().forEach { t ->
                if (t.name.startsWith("${m.id}_")) t.delete()
            }
        }
        db.deleteAll()
        return count
    }

    private fun downloadIndex(ctx: Context, bk: Backend, cfg: JSONObject): JSONObject? {
        val root = remoteRoot(cfg)
        val remotePath = remoteIndexPath(root)
        if (!bk.fileExists(remotePath)) return null
        val tmp = File(StoragePaths.dataDir(ctx), ".remote-index.json")
        try {
            if (!bk.downloadFile(remotePath, tmp)) throw SyncError("远端清单下载失败")
            return JSONObject(tmp.readText())
        } finally {
            tmp.delete()
        }
    }

    private fun writeTempIndex(ctx: Context, data: JSONObject): File {
        val tmp = File(StoragePaths.dataDir(ctx), ".local-index.json")
        tmp.writeText(data.toString())
        return tmp
    }

    private fun applyRemoteCollections(ctx: Context, data: JSONObject) {
        val db = MemeDb.get(ctx)
        val arr = data.optJSONArray("collections")
        if (arr == null) return
        for (i in 0 until arr.length()) {
            val node = arr.optJSONObject(i) ?: continue
            val name = node.optString("name", "")
            if (name.isEmpty()) continue
            val cid = db.createCollection(name)
            if (cid < 0) continue
            val fnames = node.optJSONArray("filenames")
            if (fnames != null) {
                for (j in 0 until fnames.length()) {
                    val fname = fnames.optString(j, "")
                    val row = db.getByFilename(fname)
                    if (row != null) db.addToCollection(row.id, cid)
                }
            }
        }
    }

    internal fun applyRemoteOrder(ctx: Context, data: JSONObject) {
        val db = MemeDb.get(ctx)
        val orderedIds = mutableListOf<Long>()
        val arr = data.optJSONArray("memes")
        if (arr != null) {
            for (i in 0 until arr.length()) {
                val m = arr.optJSONObject(i) ?: continue
                val fname = m.optString("filename", "")
                if (!isSafeRemoteFname(fname)) continue
                val row = db.getByFilename(fname)
                if (row != null) orderedIds.add(row.id)
            }
        }
        if (orderedIds.isNotEmpty()) db.reorderMemes(orderedIds)
    }

    internal fun isSafeRemoteFname(name: String): Boolean {
        return name.isNotEmpty() &&
            name != "." && name != ".." &&
            !name.startsWith(".") && !name.startsWith("/") &&
            !name.startsWith("\\") && !name.startsWith("~") &&
            !name.startsWith("..") &&
            "/" !in name && "\\" !in name
    }

    private fun readDimensions(stor: StorFile): Pair<Int, Int> {
        return try {
            val opts = BitmapFactory.Options()
            opts.inJustDecodeBounds = true
            stor.openInputStream().use { BitmapFactory.decodeStream(it, null, opts) }
            opts.outWidth to opts.outHeight
        } catch (e: Exception) {
            0 to 0
        }
    }
}
