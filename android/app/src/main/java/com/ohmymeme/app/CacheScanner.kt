package com.ohmymeme.app

import android.content.Context
import android.graphics.BitmapFactory

object CacheScanner {

    private const val TAG = "OhMyMeme/CacheScanner"

    fun scan(context: Context): Int {
        val db = MemeDb.get(context)
        val cacheDir = StoragePaths.cacheDir(context)
        if (!cacheDir.exists) {
            android.util.Log.d(TAG, "cache dir missing, skipped")
            return 0
        }
        var added = 0
        cacheDir.listFilesRecursive().forEach { f ->
            val ext = f.name.substringAfterLast('.', "").lowercase().let { if (it.isEmpty()) "" else ".$it" }
            if (ext !in FileUtils.ALLOWED_EXT) return@forEach
            // 跳过由 WebP 动图自动生成的 GIF（同名 .webp 存在即为生成物）
            val stem = f.name.substringBeforeLast('.')
            if (ext == ".gif" && f.sibling("$stem.webp").exists) return@forEach
            if (db.getByFilename(f.name) != null) return@forEach
            val fhash = try {
                f.openInputStream().use { FileUtils.sha256(it) }
            } catch (e: Exception) {
                return@forEach
            }
            if (db.getByHash(fhash) != null) return@forEach
            val dims = decodeBounds(f)
            val mime = if (ext.isNotEmpty()) "image/${ext.substring(1)}" else "image/png"
            val oname = f.name.substringBeforeLast('.')
            db.addMeme(
                filename = f.name,
                fileHash = fhash,
                width = dims.first,
                height = dims.second,
                fileSize = f.length,
                mimeType = mime,
                originalName = oname
            )
            added++
        }
        android.util.Log.d(TAG, "scan finished, added=$added")
        return added
    }

    fun decodeBounds(file: StorFile): Pair<Int, Int> {
        return try {
            val opts = BitmapFactory.Options()
            opts.inJustDecodeBounds = true
            file.openInputStream().use { BitmapFactory.decodeStream(it, null, opts) }
            Pair(opts.outWidth, opts.outHeight)
        } catch (e: Exception) {
            Pair(0, 0)
        }
    }
}
