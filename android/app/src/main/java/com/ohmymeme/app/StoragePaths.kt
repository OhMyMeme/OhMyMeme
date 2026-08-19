package com.ohmymeme.app

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Environment
import android.provider.DocumentsContract
import java.io.File

object StoragePaths {

    private const val TAG = "OhMyMeme/StoragePaths"
    private const val PREFS = "ohmymeme_prefs"
    private const val KEY_DATA_DIR = "data_dir"
    private const val KEY_DATA_TREE = "data_tree"
    private const val KEY_SETUP_DONE = "setup_done"

    fun isFirstRun(context: Context): Boolean {
        return !context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getBoolean(KEY_SETUP_DONE, false)
    }

    fun markSetupDone(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putBoolean(KEY_SETUP_DONE, true).apply()
    }

    /** config 所在根目录：Android/data/com.ohmymeme.app/（应用专属数据根） */
    fun configRoot(context: Context): File {
        val base = context.getExternalFilesDir(null) ?: context.filesDir
        return base.parentFile ?: base
    }

    /**
     * localdata 真实路径目录：默认 Android/data/com.ohmymeme.app/files/，可被用户以真实路径自定义覆盖。
     * memes.db 与云端临时清单始终保存在此（SQLite 需要真实文件路径）；
     * SAF 模式下 cache/thumbnails 经 [dataRoot] 走 content URI，DB 仍在本目录。
     */
    fun dataDir(context: Context): File {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val saved = prefs.getString(KEY_DATA_DIR, null)
        if (saved != null && saved.isNotEmpty()) {
            val dir = File(saved)
            if (isUsableDataDir(dir)) return dir
            android.util.Log.w(TAG, "saved dataDir not usable, resetting to default: $saved")
            prefs.edit().remove(KEY_DATA_DIR).apply()
        }
        val def = context.getExternalFilesDir(null) ?: context.filesDir
        def.mkdirs()
        return def
    }

    fun setDataDir(context: Context, dir: File) {
        dir.mkdirs()
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(KEY_DATA_DIR, dir.absolutePath).apply()
        android.util.Log.d(TAG, "setDataDir ${dir.absolutePath}")
    }

    /** 用户选择的 SAF 树 URI（content://.../tree/...），cache/thumbnails 的存放位置 */
    fun dataTreeUri(context: Context): Uri? {
        val s = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_DATA_TREE, null)
        return if (s != null && s.isNotEmpty()) Uri.parse(s) else null
    }

    fun useSaf(context: Context): Boolean = dataTreeUri(context) != null

    fun setDataTree(context: Context, uri: Uri) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(KEY_DATA_TREE, uri.toString()).apply()
        android.util.Log.d(TAG, "setDataTree $uri")
    }

    fun resetDataDir(context: Context) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        dataTreeUri(context)?.let {
            try {
                context.contentResolver.releasePersistableUriPermission(
                    it,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                )
            } catch (e: Exception) {
                // ignore
            }
        }
        prefs.edit().remove(KEY_DATA_DIR).remove(KEY_DATA_TREE).apply()
    }

    /**
     * 目录是否可被本应用以原始 File API 写入（mkdirs + 探针文件）。
     * 仅用于真实路径模式的历史兼容校验；用户经 SAF 选择的目录用 [persistDataTree] 校验。
     */
    fun isUsableDataDir(dir: File): Boolean {
        return try {
            if (!dir.isDirectory && !dir.mkdirs()) return false
            val probe = File(dir, ".ohmymeme_probe")
            probe.createNewFile()
            val ok = probe.isFile
            probe.delete()
            ok
        } catch (e: Exception) {
            false
        }
    }

    /**
     * 取得所选 SAF 树的持久化读写权限并校验可写（创建/删除探针文件）。
     * 必须在用户选择后立即调用，否则重启后权限丢失。
     */
    fun persistDataTree(context: Context, uri: Uri): Boolean {
        return try {
            context.contentResolver.takePersistableUriPermission(
                uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            )
            val root = StorFile.safRoot(context, uri)
            val probe = root.createFile(".ohmymeme_probe", "text/plain")
            val ok = probe.exists
            probe.delete()
            ok
        } catch (e: Exception) {
            android.util.Log.w(TAG, "persistDataTree failed: $e")
            false
        }
    }

    /**
     * 将 SAF 树 URI 解析为真实文件路径（仅用于展示）；无法解析时返回 null。
     * 支持 internal storage（primary:xxx）与 Downloads（home:xxx）。
     */
    fun resolveTreeUriPath(context: Context, uri: Uri): File? {
        return try {
            val docId = DocumentsContract.getTreeDocumentId(uri)
            val idx = docId.indexOf(':')
            val root = if (idx >= 0) docId.substring(0, idx) else docId
            val rel = if (idx >= 0) docId.substring(idx + 1) else ""
            val base = when (root) {
                "primary" -> Environment.getExternalStorageDirectory()
                "home" -> Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                else -> return null
            }
            if (rel.isEmpty()) base else File(base, rel)
        } catch (e: Exception) {
            null
        }
    }

    /** 数据根：SAF 模式下为用户选择的树；否则为真实路径 localdata 目录 */
    fun dataRoot(context: Context): StorFile {
        val tree = dataTreeUri(context)
        return if (tree != null) StorFile.safRoot(context, tree) else StorFile.real(context, dataDir(context))
    }

    fun cacheDir(context: Context): StorFile = dataRoot(context).childOrCreateDir("cache")

    fun thumbnailDir(context: Context): StorFile = dataRoot(context).childOrCreateDir("thumbnails")

    fun dbPath(context: Context): File {
        return File(dataDir(context), "memes.db")
    }

    /** 设置页展示：SAF 树解析为真实路径（仅展示），解析失败显示 URI */
    fun describeDataLocation(context: Context): String {
        val tree = dataTreeUri(context)
        if (tree != null) {
            return resolveTreeUriPath(context, tree)?.absolutePath ?: tree.toString()
        }
        return dataDir(context).absolutePath
    }

    fun configFile(context: Context): File {
        val f = File(configRoot(context), "config.json")
        f.parentFile?.mkdirs()
        return f
    }
}
