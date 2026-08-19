package com.ohmymeme.app

import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.IOException
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

object UpdateChecker {

    private const val TAG = "OhMyMeme/UpdateChecker"
    private const val REPO = "OhMyMeme/OhMyMeme-Android"
    private const val GITHUB_LATEST = "https://api.github.com/repos/$REPO/releases/latest"
    private const val GITHUB_LIST = "https://api.github.com/repos/$REPO/releases?per_page=5"
    private const val UA =
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"

    private val GH_MIRRORS = listOf(
        "https://github.dpik.top/",
        "https://gh.dpik.top/",
        "https://gh-proxy.org/",
        "https://proxy.starsfire.top/-----"
    )

    data class UpdateInfo(
        val latest: String,
        val downloadUrl: String,
        val hasUpdate: Boolean,
        val error: String
    )

    fun parseVersion(v: String): List<Int> {
        val parts = v.trim().trimStart('v', 'V').split(".")
        return parts.mapNotNull { it.toIntOrNull() }
    }

    /** 阻塞调用，须在后台线程执行 */
    fun checkLatest(currentVersion: String): UpdateInfo {
        val current = parseVersion(currentVersion)
        android.util.Log.d(TAG, "checkLatest current=$currentVersion")
        val parsed = fetchLatest()
        if (parsed == null) {
            android.util.Log.w(TAG, "fetchLatest failed")
            return UpdateInfo("", "", false, "无法连接到 GitHub，请检查网络设置")
        }
        val (tag, url) = parsed
        val latest = tag.trimStart('v', 'V')
        return UpdateInfo(
            latest = latest,
            downloadUrl = url,
            hasUpdate = compareVersions(parseVersion(latest), current) > 0,
            error = ""
        )
    }

    private fun compareVersions(a: List<Int>, b: List<Int>): Int {
        val n = maxOf(a.size, b.size)
        for (i in 0 until n) {
            val x = a.getOrElse(i) { 0 }
            val y = b.getOrElse(i) { 0 }
            if (x != y) return x - y
        }
        return 0
    }

    /** 对齐桌面端 check_latest：先 releases/latest，失败回退 releases 列表取最高版本 */
    private fun fetchLatest(): Pair<String, String>? {
        try {
            return parseRelease(fetchFirst(GITHUB_LATEST))
        } catch (e: Exception) {
            android.util.Log.w(TAG, "releases/latest failed: $e")
        }
        try {
            return pickHighestFromList(fetchFirst(GITHUB_LIST))
        } catch (e: Exception) {
            android.util.Log.w(TAG, "releases list failed: $e")
            return null
        }
    }

    /** 并发尝试所有镜像+直连，返回第一个成功响应的响应体（对齐桌面端 _urlopen_mirror） */
    private fun fetchFirst(url: String): String {
        val targets = GH_MIRRORS.map { it + url } + url
        val pool = Executors.newFixedThreadPool(targets.size)
        return try {
            pool.invokeAny(targets.map { Callable { fetchBody(it) } }, 20, TimeUnit.SECONDS)
        } finally {
            pool.shutdownNow()
        }
    }

    private fun fetchBody(url: String): String {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.requestMethod = "GET"
        conn.setRequestProperty("User-Agent", UA)
        conn.setRequestProperty("Accept", "application/vnd.github+json")
        conn.connectTimeout = 10000
        conn.readTimeout = 10000
        try {
            if (conn.responseCode != 200) throw IOException("HTTP ${conn.responseCode} for $url")
            return BufferedReader(InputStreamReader(conn.inputStream)).use { it.readText() }
        } finally {
            conn.disconnect()
        }
    }

    private fun parseRelease(body: String): Pair<String, String> {
        val json = JSONObject(body)
        val tag = json.optString("tag_name", "")
        if (tag.isEmpty()) throw IOException("no tag_name")
        val html = json.optString("html_url", "")
        return Pair(tag, pickApkUrl(json.optJSONArray("assets")).ifEmpty { html })
    }

    private fun pickHighestFromList(body: String): Pair<String, String> {
        val arr = JSONArray(body)
        var bestTag = ""
        var bestUrl = ""
        var bestVer = emptyList<Int>()
        for (i in 0 until arr.length()) {
            val rel = arr.optJSONObject(i) ?: continue
            val tag = rel.optString("tag_name", "")
            if (tag.isEmpty()) continue
            val ver = parseVersion(tag)
            if (bestTag.isEmpty() || compareVersions(ver, bestVer) > 0) {
                bestTag = tag
                bestVer = ver
                bestUrl = pickApkUrl(rel.optJSONArray("assets"))
            }
        }
        if (bestTag.isEmpty()) throw IOException("no releases in list")
        return Pair(bestTag, bestUrl)
    }

    private fun pickApkUrl(assets: JSONArray?): String {
        if (assets == null) return ""
        for (i in 0 until assets.length()) {
            val a = assets.optJSONObject(i) ?: continue
            val name = a.optString("name", "")
            if (name.endsWith(".apk")) {
                return a.optString("browser_download_url", "")
            }
        }
        return ""
    }

    /**
     * 依次探测镜像源，返回第一个可访问的下载地址；全部失败回退直连。
     * 桌面端 updater.py `_urlretrieve_mirror` 迁移：仅探测连通性（HEAD），
     * 实际下载交给系统下载管理器/浏览器。
     */
    fun mirrorDownloadUrl(url: String): String {
        if (url.isEmpty()) return url
        if (!url.startsWith("https://github.com/")) return url
        for (mirror in GH_MIRRORS) {
            val candidate = mirror + url
            if (reachable(candidate)) return candidate
        }
        return url
    }

    private fun reachable(url: String): Boolean {
        return try {
            val conn = URL(url).openConnection() as HttpURLConnection
            conn.requestMethod = "HEAD"
            conn.setRequestProperty("User-Agent", UA)
            conn.connectTimeout = 10000
            conn.readTimeout = 10000
            val code = conn.responseCode
            conn.disconnect()
            code in 200..399
        } catch (e: Exception) {
            false
        }
    }
}
