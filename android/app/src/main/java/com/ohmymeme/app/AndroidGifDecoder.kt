package com.ohmymeme.app

import android.graphics.BitmapFactory

/**
 * 设备端 WebP 解码：把无损 WebP 解为 RGBA 像素，供 GifStego 使用。
 * Android Bitmap 默认预乘 alpha，需手动反预乘还原像素（对应桌面 Pillow 无损解码）。
 */
object AndroidGifDecoder {

    fun webpToRgba(webpBytes: ByteArray): GifStego.PixelImage? {
        return try {
            val opts = BitmapFactory.Options()
            opts.inPreferredConfig = android.graphics.Bitmap.Config.ARGB_8888
            val bmp = BitmapFactory.decodeByteArray(webpBytes, 0, webpBytes.size, opts) ?: return null
            val w = bmp.width
            val h = bmp.height
            val pixels = IntArray(w * h)
            bmp.getPixels(pixels, 0, w, 0, 0, w, h)
            val rgba = ByteArray(w * h * 4)
            for (i in pixels.indices) {
                val p = pixels[i]
                val a = (p ushr 24) and 0xFF
                val r = (p ushr 16) and 0xFF
                val g = (p ushr 8) and 0xFF
                val b = p and 0xFF
                val base = i * 4
                if (a == 255) {
                    rgba[base] = r.toByte()
                    rgba[base + 1] = g.toByte()
                    rgba[base + 2] = b.toByte()
                    rgba[base + 3] = 0xFF.toByte()
                } else if (a == 0) {
                    rgba[base] = 0
                    rgba[base + 1] = 0
                    rgba[base + 2] = 0
                    rgba[base + 3] = 0
                } else {
                    rgba[base] = ((r * 255 + a / 2) / a).coerceAtMost(255).toByte()
                    rgba[base + 1] = ((g * 255 + a / 2) / a).coerceAtMost(255).toByte()
                    rgba[base + 2] = ((b * 255 + a / 2) / a).coerceAtMost(255).toByte()
                    rgba[base + 3] = a.toByte()
                }
            }
            bmp.recycle()
            GifStego.PixelImage(w, h, rgba)
        } catch (e: Exception) {
            null
        }
    }
}
