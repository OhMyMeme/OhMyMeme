package com.ohmymeme.app

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory

object Thumbnailer {

    private const val TAG = "OhMyMeme/Thumbnailer"

    fun getThumbBitmap(context: Context, memeId: Long, filename: String, size: Int = 150): Bitmap? {
        val thumbDir = StoragePaths.thumbnailDir(context)
        val thumb = thumbDir.child("${memeId}_${size}.png")
        if (thumb.exists) {
            decodeStorFile(thumb)?.let { return it }
            thumb.delete()
        }
        val memePath = findMemeFile(context, filename) ?: return null
        return try {
            val bitmap = decodeScaled(memePath, size) ?: return null
            val out = thumbDir.createFile("${memeId}_${size}.png", "image/png")
            out.openOutputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
            android.util.Log.d(TAG, "generated thumb for $filename")
            bitmap
        } catch (e: Exception) {
            android.util.Log.w(TAG, "thumb failed for $filename: $e")
            null
        }
    }

    fun findMemeFile(context: Context, filename: String): StorFile? {
        val cacheDir = StoragePaths.cacheDir(context)
        val direct = cacheDir.child(filename)
        if (direct.exists) return direct
        return cacheDir.listFilesRecursive().firstOrNull { !it.isDirectory && it.name == filename }
    }

    private fun decodeStorFile(stor: StorFile): Bitmap? {
        return try {
            stor.openInputStream().use { BitmapFactory.decodeStream(it, null, null) }
        } catch (e: Exception) {
            null
        }
    }

    private fun decodeScaled(stor: StorFile, size: Int): Bitmap? {
        val bounds = BitmapFactory.Options()
        bounds.inJustDecodeBounds = true
        stor.openInputStream().use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = 1
        while (bounds.outWidth / sample > size * 2 || bounds.outHeight / sample > size * 2) {
            sample *= 2
        }
        val opts = BitmapFactory.Options()
        opts.inSampleSize = sample
        val src = stor.openInputStream().use { BitmapFactory.decodeStream(it, null, opts) } ?: return null
        val scaled = Bitmap.createScaledBitmap(src, size, size, true)
        if (scaled !== src) src.recycle()
        return scaled
    }
}
