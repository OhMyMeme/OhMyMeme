package com.ohmymeme.app

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Build
import java.io.ByteArrayOutputStream
import java.io.File

/**
 * 复制/分享前处理：对应桌面端 clipboard_util.py convert_image_mode_1/2/3。
 * - mode 1：静态图超限时缩放到 copy_resize_max 并存为 WebP（q90）
 * - mode 2：静态图超限时转为普通 GIF（256 色）
 * - mode 3：静态图超限时转为隐写 GIF（基座 GIF + STG3 原图数据，可无损还原）
 * 动图 / 未超限 / 处理失败均返回 null，调用方回退原图直发。
 */
object MemeCopyProcessor {

    private const val TAG = "OhMyMeme/MemeCopy"

    class Result(val file: File, val mimeType: String)

    fun process(context: Context, stor: StorFile): Result? {
        val cfg = ConfigStore.get(context)
        val mode = cfg.optInt("copy_resize_mode", 1)
        if (mode == 0) return null
        if (FileUtils.isAnimatedFile(stor)) return null
        val bounds = BitmapFactory.Options()
        bounds.inJustDecodeBounds = true
        stor.openInputStream().use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        val maxSide = cfg.optInt("copy_resize_max", 200)
        if (maxOf(bounds.outWidth, bounds.outHeight) <= maxSide) return null
        return when (mode) {
            1 -> toWebp(context, stor, bounds.outWidth, bounds.outHeight, maxSide)
            2 -> toGif(context, stor, bounds.outWidth, bounds.outHeight)
            3 -> toStegoGif(context, stor, bounds.outWidth, bounds.outHeight)
            else -> null
        }
    }

    private fun toWebp(context: Context, stor: StorFile, w: Int, h: Int, maxSide: Int): Result? {
        return try {
            var sample = 1
            while (w / sample > maxSide * 4 || h / sample > maxSide * 4) sample *= 2
            val src = decode(stor, sample) ?: return null
            val ratio = maxSide / maxOf(src.width, src.height).toFloat()
            val nw = maxOf(1, (src.width * ratio).toInt())
            val nh = maxOf(1, (src.height * ratio).toInt())
            val scaled = Bitmap.createScaledBitmap(src, nw, nh, true)
            if (scaled !== src) src.recycle()
            val out = File(context.cacheDir, "copy_${System.nanoTime()}.webp")
            out.outputStream().use { scaled.compress(Bitmap.CompressFormat.WEBP, 90, it) }
            scaled.recycle()
            Result(out, "image/webp")
        } catch (e: Exception) {
            android.util.Log.w(TAG, "toWebp failed: $e")
            null
        }
    }

    private fun toGif(context: Context, stor: StorFile, w: Int, h: Int): Result? {
        return try {
            val bmp = decodeFull(stor) ?: return null
            val rgba = bitmapToRgba(bmp)
            bmp.recycle()
            val gif = GifEncoder.encode(rgba, w, h)
            val out = File(context.cacheDir, "copy_${System.nanoTime()}.gif")
            out.writeBytes(gif)
            Result(out, "image/gif")
        } catch (e: Exception) {
            android.util.Log.w(TAG, "toGif failed: $e")
            null
        }
    }

    private fun toStegoGif(context: Context, stor: StorFile, w: Int, h: Int): Result? {
        return try {
            val bmp = decodeFull(stor) ?: return null
            val rgba = bitmapToRgba(bmp)
            val hasAlpha = bmp.hasAlpha()
            bmp.recycle()
            val n = w * h
            val kind: String
            val origPixels: ByteArray
            if (hasAlpha) {
                kind = "RGBA"
                origPixels = rgba
            } else {
                var isGray = true
                var i = 0
                while (i < n) {
                    val r = rgba[i * 4].toInt() and 0xFF
                    if (r != (rgba[i * 4 + 1].toInt() and 0xFF) || r != (rgba[i * 4 + 2].toInt() and 0xFF)) {
                        isGray = false
                        break
                    }
                    i++
                }
                if (isGray) {
                    kind = "L"
                    origPixels = ByteArray(n)
                    for (j in 0 until n) origPixels[j] = rgba[j * 4]
                } else {
                    kind = "RGB"
                    origPixels = ByteArray(n * 3)
                    for (j in 0 until n) {
                        origPixels[j * 3] = rgba[j * 4]
                        origPixels[j * 3 + 1] = rgba[j * 4 + 1]
                        origPixels[j * 3 + 2] = rgba[j * 4 + 2]
                    }
                }
            }
            val baseGif = GifEncoder.encode(rgba, w, h)
            val stego = GifStego.encode(
                baseGif, stor.readBytes(), stor.name.substringAfterLast('.', ""),
                origPixels, kind, w, h, ::encodeLosslessWebp
            )
            val out = File(context.cacheDir, "copy_${System.nanoTime()}.gif")
            out.writeBytes(stego)
            Result(out, "image/gif")
        } catch (e: Exception) {
            android.util.Log.w(TAG, "toStegoGif failed: $e")
            null
        }
    }

    /** 无损 WebP 编码（WEBP_LOSSLESS，API 30+）；低版本返回 null 时跳过 WebP 候选 */
    private fun encodeLosslessWebp(rgb: ByteArray, w: Int, h: Int): ByteArray? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return null
        return try {
            val n = w * h
            val argb = IntArray(n)
            for (i in 0 until n) {
                argb[i] = (0xFF shl 24) or
                    ((rgb[i * 3].toInt() and 0xFF) shl 16) or
                    ((rgb[i * 3 + 1].toInt() and 0xFF) shl 8) or
                    (rgb[i * 3 + 2].toInt() and 0xFF)
            }
            val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
            bmp.setPixels(argb, 0, w, 0, 0, w, h)
            val bos = ByteArrayOutputStream()
            val ok = bmp.compress(Bitmap.CompressFormat.WEBP_LOSSLESS, 100, bos)
            bmp.recycle()
            if (ok) bos.toByteArray() else null
        } catch (e: Exception) {
            android.util.Log.w(TAG, "encodeLosslessWebp failed: $e")
            null
        }
    }

    private fun decode(stor: StorFile, sample: Int): Bitmap? {
        val opts = BitmapFactory.Options()
        opts.inSampleSize = sample
        opts.inPreferredConfig = Bitmap.Config.ARGB_8888
        return stor.openInputStream().use { BitmapFactory.decodeStream(it, null, opts) }
    }

    private fun decodeFull(stor: StorFile): Bitmap? {
        val bounds = BitmapFactory.Options()
        bounds.inJustDecodeBounds = true
        stor.openInputStream().use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        if (bounds.outWidth.toLong() * bounds.outHeight > 32_000_000L) return null
        return decode(stor, 1)
    }

    /** ARGB_8888 → 未预乘 RGBA 字节（反预乘，还原文件真实 RGB，对齐 Pillow） */
    private fun bitmapToRgba(bmp: Bitmap): ByteArray {
        val w = bmp.width
        val h = bmp.height
        val n = w * h
        val pixels = IntArray(n)
        bmp.getPixels(pixels, 0, w, 0, 0, w, h)
        val out = ByteArray(n * 4)
        var j = 0
        for (p in pixels) {
            var a = p ushr 24 and 0xFF
            var r = p ushr 16 and 0xFF
            var g = p ushr 8 and 0xFF
            var b = p and 0xFF
            if (a in 1..254) {
                r = (r * 255 / a).coerceAtMost(255)
                g = (g * 255 / a).coerceAtMost(255)
                b = (b * 255 / a).coerceAtMost(255)
            }
            out[j] = r.toByte()
            out[j + 1] = g.toByte()
            out[j + 2] = b.toByte()
            out[j + 3] = a.toByte()
            j += 4
        }
        return out
    }
}
