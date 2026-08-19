package com.ohmymeme.app

import android.content.Context
import org.json.JSONObject

object ConfigStore {

    private const val TAG = "OhMyMeme/ConfigStore"

    private val SECRET_KEYS = setOf(
        "s3_access_key",
        "s3_secret_key",
        "r2_access_key_id",
        "r2_secret_access_key",
        "ftp_password",
        "webdav_password",
        "lan_secret",
        "ai_chat_api_key",
        "ai_image_api_key"
    )

    val DEFAULTS: Map<String, Any> = mapOf(
        "version" to "",
        "hotkey" to "Ctrl+Alt+N",
        "auto_start" to false,
        "silent_start" to false,
        "language" to "zh-CN",
        "cache_max_size_mb" to 500,
        "thumbnail_size" to 150,
        "sync_auto_fetch_index" to false,
        "sync_auto_sync" to false,
        "sync_type" to "",
        "sync_interval_minutes" to 60,
        "sync_delete_remote" to false,
        "sync_remove_local" to false,
        "sync_hide_upload_warning" to false,
        "sync_threads" to 3,
        "show_upload_progress" to true,
        "show_upload_done" to true,
        "show_download_progress" to true,
        "show_download_done" to true,
        "ftp_host" to "",
        "ftp_port" to 21,
        "ftp_user" to "",
        "ftp_password" to "",
        "ftp_path" to "/",
        "s3_endpoint" to "",
        "s3_region" to "",
        "s3_bucket" to "",
        "s3_access_key" to "",
        "s3_secret_key" to "",
        "s3_path" to "",
        "r2_account_id" to "",
        "r2_access_key_id" to "",
        "r2_secret_access_key" to "",
        "r2_bucket" to "",
        "r2_path" to "",
        "webdav_url" to "",
        "webdav_user" to "",
        "webdav_password" to "",
        "webdav_path" to "",
        "webdav_timeout" to 30,
        "copy_resize_mode" to 1,
        "copy_resize_max" to 200,
        "show_uncategorized" to true,
        "theme" to "dark",
        "window_x" to -1,
        "window_y" to -1,
        "auto_play_gif" to true,
        "grid_columns" to 3,
        "try_original_image" to false,
        "lan_port" to 17852,
        "lan_secret" to "",
        "ai_chat_base_url" to "",
        "ai_chat_api_key" to "",
        "ai_chat_model" to "",
        "ai_organize_style" to "general",
        "ai_organize_batch_size" to 50,
        "ai_image_base_url" to "",
        "ai_image_api_key" to "",
        "ai_image_model" to "",
        "ai_search_source" to "bing",
        "overlay_enabled" to false,
        "overlay_button_x" to -1,
        "overlay_button_y" to -1,
        "overlay_paste_route" to "manual"
    )

    @Volatile
    private var data: JSONObject? = null

    fun get(context: Context): JSONObject {
        val cached = data
        if (cached != null) return cached
        synchronized(this) {
            data?.let { return it }
            val obj = load(context)
            data = obj
            return obj
        }
    }

    fun reload(context: Context): JSONObject {
        synchronized(this) {
            val obj = load(context)
            data = obj
            return obj
        }
    }

    fun invalidate() {
        synchronized(this) {
            data = null
        }
    }

    internal fun isSecretKey(key: String): Boolean = key in SECRET_KEYS

    private fun load(context: Context): JSONObject {
        val obj = JSONObject()
        for ((k, v) in DEFAULTS) {
            putDefault(obj, k, v)
        }
        val file = StoragePaths.configFile(context)
        if (file.exists()) {
            try {
                val raw = JSONObject(file.readText())
                for (k in DEFAULTS.keys) {
                    if (raw.has(k)) {
                        obj.put(k, raw.get(k))
                    }
                }
                // 解密密钥字段
                for (k in SECRET_KEYS) {
                    if (obj.has(k)) {
                        val v = obj.optString(k, "")
                        if (v.isNotEmpty()) obj.put(k, CryptoUtil.decrypt(v))
                    }
                }
            } catch (e: Exception) {
                android.util.Log.w(TAG, "config parse failed, fallback to defaults: $e")
            }
        } else {
            // 首次运行：落盘默认配置，确保 config.json 存在
            try {
                file.parentFile?.mkdirs()
                file.writeText(obj.toString(2))
                android.util.Log.d(TAG, "wrote default config to $file")
            } catch (e: Exception) {
                android.util.Log.w(TAG, "failed to write default config: $e")
            }
        }
        return obj
    }

    private fun putDefault(obj: JSONObject, key: String, value: Any) {
        when (value) {
            is Boolean -> obj.put(key, value)
            is Int -> obj.put(key, value)
            is String -> obj.put(key, value)
            else -> obj.put(key, value)
        }
    }

    fun getString(context: Context, key: String, default: String = ""): String {
        return get(context).optString(key, default)
    }

    fun getInt(context: Context, key: String, default: Int = 0): Int {
        return get(context).optInt(key, default)
    }

    fun getBoolean(context: Context, key: String, default: Boolean = false): Boolean {
        return get(context).optBoolean(key, default)
    }

    fun set(context: Context, key: String, value: Any) {
        val obj = get(context)
        when (value) {
            is Boolean -> obj.put(key, value)
            is Int -> obj.put(key, value)
            is String -> obj.put(key, value)
            else -> obj.put(key, value)
        }
    }

    fun save(context: Context) {
        synchronized(this) {
            val obj = get(context)
            // 加密密钥字段后再写入
            val copy = JSONObject()
            val keys = obj.keys()
            while (keys.hasNext()) {
                val k = keys.next()
                val v = obj.get(k)
                if (k in SECRET_KEYS && v is String && v.isNotEmpty()) {
                    copy.put(k, CryptoUtil.encrypt(v))
                } else {
                    copy.put(k, v)
                }
            }
            val file = StoragePaths.configFile(context)
            file.parentFile?.mkdirs()
            file.writeText(copy.toString(2))
            android.util.Log.d(TAG, "saved config to $file")
        }
    }

    fun reset(context: Context) {
        synchronized(this) {
            data = JSONObject()
            for ((k, v) in DEFAULTS) {
                putDefault(data!!, k, v)
            }
            save(context)
        }
    }
}
