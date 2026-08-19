package com.ohmymeme.app

import android.graphics.BitmapFactory
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.security.SecureRandom

object AiUtil {

    private const val TIMEOUT_MS = 60_000
    private const val IMAGE_TIMEOUT_MS = 30_000

    data class OrganizeSuggestion(
        val tags: List<String>,
        val collection: String,
        val description: String,
        val ocrText: String
    )

    private fun baseUrl(value: String): String = value.trim().trimEnd('/')

    private fun requireConfig(baseUrl: String, model: String, action: String) {
        if (baseUrl.isBlank()) throw IllegalArgumentException("请先在设置中填写${action}服务地址")
        if (model.isBlank()) throw IllegalArgumentException("请先在设置中填写${action}模型")
    }

    private fun postJson(url: String, apiKey: String, payload: JSONObject): JSONObject {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = TIMEOUT_MS
            readTimeout = TIMEOUT_MS
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            if (apiKey.isNotBlank()) setRequestProperty("Authorization", "Bearer $apiKey")
        }
        try {
            conn.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
            val stream = if (conn.responseCode in 200..299) conn.inputStream else conn.errorStream
            val body = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (conn.responseCode !in 200..299) throw IllegalArgumentException("AI 请求失败：HTTP ${conn.responseCode} ${body.take(180)}")
            return JSONObject(body)
        } finally {
            conn.disconnect()
        }
    }

    private fun imageResult(data: JSONObject, action: String): ByteArray {
        val item = data.optJSONArray("data")?.optJSONObject(0)
            ?: throw IllegalArgumentException("${action}响应缺少图片数据")
        val b64 = item.optString("b64_json", "")
        if (b64.isNotBlank()) return Base64.decode(b64, Base64.DEFAULT)
        val url = item.optString("url", "")
        if (url.isNotBlank()) return downloadImage(url)
        throw IllegalArgumentException("${action}响应缺少图片数据")
    }

    private fun imageDataUri(bytes: ByteArray): String {
        val ext = FileUtils.detectExt(bytes.take(16).toByteArray()).ifEmpty { ".png" }
        val mime = when (ext) {
            ".jpg", ".jpeg" -> "image/jpeg"
            ".gif" -> "image/gif"
            ".webp" -> "image/webp"
            else -> "image/png"
        }
        return "data:$mime;base64," + Base64.encodeToString(bytes, Base64.NO_WRAP)
    }

    private fun extractJson(text: String): JSONObject? {
        val clean = text.trim()
        try {
            return JSONObject(clean)
        } catch (_: Exception) {
        }
        val codeBlock = Regex("```(?:json)?\\s*(\\{[\\s\\S]*?})\\s*```", RegexOption.IGNORE_CASE)
            .find(clean)?.groupValues?.getOrNull(1)
        if (codeBlock != null) {
            try {
                return JSONObject(codeBlock)
            } catch (_: Exception) {
            }
        }
        val start = clean.indexOf('{')
        val end = clean.lastIndexOf('}')
        if (start >= 0 && end > start) {
            try {
                return JSONObject(clean.substring(start, end + 1))
            } catch (_: Exception) {
            }
        }
        return null
    }

    fun organize(image: ByteArray, cfg: JSONObject): OrganizeSuggestion {
        val endpoint = cfg.optString("ai_chat_base_url", "")
        val model = cfg.optString("ai_chat_model", "")
        requireConfig(endpoint, model, "AI 整理")
        val style = when (cfg.optString("ai_organize_style", "general")) {
            "anime" -> "二次元"
            "work" -> "职场"
            "gaming" -> "游戏群"
            else -> "通用聊天"
        }
        val system = "你是表情包分类助手。分析图片内容，只返回 JSON：" +
            "{\"tags\":[\"标签1\"],\"collection\":\"分组名\",\"description\":\"图片描述\",\"ocr_text\":\"图片文字\"}。" +
            "标签为2到4个简短中文词；没有文字时 ocr_text 为空；整理风格为$style。"
        val content = JSONArray()
            .put(JSONObject().put("type", "text").put("text", "分析这张表情包并返回 JSON。"))
            .put(JSONObject().put("type", "image_url").put("image_url", JSONObject().put("url", imageDataUri(image))))
        val messages = JSONArray()
            .put(JSONObject().put("role", "system").put("content", system))
            .put(JSONObject().put("role", "user").put("content", content))
        val payload = JSONObject()
            .put("model", model)
            .put("messages", messages)
            .put("max_tokens", 1024)
        val response = postJson(baseUrl(endpoint) + "/v1/chat/completions", cfg.optString("ai_chat_api_key", ""), payload)
        val text = response.optJSONArray("choices")?.optJSONObject(0)
            ?.optJSONObject("message")?.optString("content", "").orEmpty()
        val parsed = extractJson(text) ?: throw IllegalArgumentException("AI 整理返回无法解析")
        val tags = buildList {
            val arr = parsed.optJSONArray("tags") ?: JSONArray()
            for (i in 0 until arr.length()) {
                val tag = arr.optString(i, "").trim()
                if (tag.isNotBlank()) add(tag.take(24))
            }
        }.distinct().take(8)
        return OrganizeSuggestion(
            tags = tags,
            collection = parsed.optString("collection", "").trim().take(48),
            description = parsed.optString("description", "").trim().take(500),
            ocrText = parsed.optString("ocr_text", "").trim().take(500)
        )
    }

    fun generate(prompt: String, cfg: JSONObject, size: String = "1024x1024"): ByteArray {
        val endpoint = cfg.optString("ai_image_base_url", "")
        val model = cfg.optString("ai_image_model", "")
        requireConfig(endpoint, model, "AI 生图")
        if (prompt.isBlank()) throw IllegalArgumentException("请输入生成提示词")
        val payload = JSONObject().put("model", model).put("prompt", prompt).put("n", 1).put("size", size)
        return imageResult(postJson(baseUrl(endpoint) + "/v1/images/generations", cfg.optString("ai_image_api_key", ""), payload), "AI 生图")
    }

    fun edit(image: ByteArray, filename: String, prompt: String, cfg: JSONObject, size: String = "1024x1024"): ByteArray {
        val endpoint = cfg.optString("ai_image_base_url", "")
        val model = cfg.optString("ai_image_model", "")
        requireConfig(endpoint, model, "AI 生图")
        if (prompt.isBlank()) throw IllegalArgumentException("请输入编辑提示词")
        val boundary = "----OhMyMeme${SecureRandom().nextLong().toString(16)}"
        val out = ByteArrayOutputStream()
        fun field(name: String, value: String) {
            out.write("--$boundary\r\nContent-Disposition: form-data; name=\"$name\"\r\n\r\n$value\r\n".toByteArray(Charsets.UTF_8))
        }
        field("model", model)
        field("prompt", prompt)
        field("n", "1")
        field("size", size)
        val ext = filename.substringAfterLast('.', "png").lowercase()
        val mime = if (ext == "jpg" || ext == "jpeg") "image/jpeg" else "image/$ext"
        out.write("--$boundary\r\nContent-Disposition: form-data; name=\"image\"; filename=\"$filename\"\r\nContent-Type: $mime\r\n\r\n".toByteArray(Charsets.UTF_8))
        out.write(image)
        out.write("\r\n--$boundary--\r\n".toByteArray(Charsets.UTF_8))
        val conn = (URL(baseUrl(endpoint) + "/v1/images/edits").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = TIMEOUT_MS
            readTimeout = TIMEOUT_MS
            doOutput = true
            setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
            val apiKey = cfg.optString("ai_image_api_key", "")
            if (apiKey.isNotBlank()) setRequestProperty("Authorization", "Bearer $apiKey")
        }
        try {
            conn.outputStream.use { it.write(out.toByteArray()) }
            val stream = if (conn.responseCode in 200..299) conn.inputStream else conn.errorStream
            val body = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (conn.responseCode !in 200..299) throw IllegalArgumentException("AI 图片编辑失败：HTTP ${conn.responseCode} ${body.take(180)}")
            return imageResult(JSONObject(body), "AI 图片编辑")
        } finally {
            conn.disconnect()
        }
    }

    fun searchImages(keyword: String, count: Int = 8): List<String> {
        if (keyword.isBlank()) throw IllegalArgumentException("请输入找图关键词")
        val encoded = URLEncoder.encode(keyword, "UTF-8")
        val conn = (URL("https://www.bing.com/images/search?q=$encoded&form=HDRSC2").openConnection() as HttpURLConnection).apply {
            connectTimeout = TIMEOUT_MS
            readTimeout = TIMEOUT_MS
            setRequestProperty("User-Agent", "Mozilla/5.0")
        }
        val html = try {
            if (conn.responseCode !in 200..299) return emptyList()
            conn.inputStream.bufferedReader().use { it.readText() }
        } finally {
            conn.disconnect()
        }
        val urls = Regex("\\\"murl\\\":\\\"(https?://[^\\\"]+)\\\"").findAll(html)
            .map { it.groupValues[1].replace("\\u002f", "/") }
            .distinct()
            .take(count)
            .toList()
        return urls
    }

    fun downloadImage(url: String): ByteArray {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = IMAGE_TIMEOUT_MS
            readTimeout = IMAGE_TIMEOUT_MS
            instanceFollowRedirects = true
            setRequestProperty("User-Agent", "Mozilla/5.0")
        }
        try {
            if (conn.responseCode !in 200..299) throw IllegalArgumentException("图片下载失败：HTTP ${conn.responseCode}")
            val bytes = conn.inputStream.use { it.readBytes() }
            if (bytes.isEmpty() || BitmapFactory.decodeByteArray(bytes, 0, bytes.size) == null) {
                throw IllegalArgumentException("下载内容不是可用图片")
            }
            return bytes
        } finally {
            conn.disconnect()
        }
    }
}
