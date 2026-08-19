package com.ohmymeme.app

import org.tukaani.xz.LZMA2Options
import org.tukaani.xz.XZInputStream
import org.tukaani.xz.XZOutputStream
import java.io.ByteArrayOutputStream
import java.util.zip.CRC32
import java.util.zip.Deflater

/**
 * 隐写 GIF 解码，对应桌面端 gif_stego.py 的 decode + _try_decode_stego 检测。
 * 纯 JVM 依赖（LZMA 用 org.tukaani:xz），不含 android.graphics，可单测。
 */
object GifStego {

    private val MAGIC = byteArrayOf(0x53, 0x54, 0x47, 0x33) // "STG3"
    private const val MODE_FULL = 0
    private const val MODE_DELTA_LZMA = 1
    private const val MODE_DELTA_WEBP = 2
    private const val MODE_RGBA_LZMA = 3
    private const val MODE_RGBA_WEBP = 4
    private const val MODE_L_LZMA = 5
    private const val MODE_L_WEBP = 6

    class PixelImage(val width: Int, val height: Int, val rgba: ByteArray)

    class DecodeResult(val bytes: ByteArray, val ext: String)

    fun hasStego(data: ByteArray): Boolean {
        return indexOf(data, MAGIC) != -1
    }

    /**
     * @param webpToRgba 设备端 WebP 解码回调，返回 RGBA 像素；WebP 模式必用。
     */
    fun decode(data: ByteArray, webpToRgba: (ByteArray) -> PixelImage?): DecodeResult? {
        if (data.size < 4) return null
        val pos = lastIndexOf(data, MAGIC)
        if (pos < 0 || pos + MAGIC.size >= data.size) return null
        val gifData = data.copyOfRange(0, pos)
        val blob = data.copyOfRange(pos + MAGIC.size, data.size)
        val mode = blob[0].toInt() and 0xFF

        return try {
            when (mode) {
                MODE_FULL -> decodeFull(blob)
                MODE_DELTA_LZMA, MODE_RGBA_LZMA, MODE_L_LZMA -> decodeLzma(blob, mode, gifData)
                MODE_DELTA_WEBP, MODE_RGBA_WEBP, MODE_L_WEBP ->
                    decodeWebp(blob, mode, gifData, webpToRgba)
                else -> null
            }
        } catch (e: Exception) {
            null
        }
    }

    /**
     * 写入隐写数据（对应 gif_stego.py _candidates + encode）：生成 全图/差值 候选并取最小。
     *
     * @param gifData 与原始图同分辨率的基座 GIF（GifEncoder 生成）
     * @param origBytes 原始文件字节（FULL 模式用）
     * @param origExt 原始扩展名（不含点）
     * @param origPixels 原始像素，按 kind 布局：RGB(3/px)/RGBA(4/px)/L(1/px)
     * @param kind "RGB" | "RGBA" | "L"
     * @param webpLossless 设备端无损 WebP 编码器，接收 +128 偏移后的 RGB 灰度，返回 WebP 字节或 null；
     *                     null 或返回 null 时跳过 WebP 候选（仅 LZMA + FULL）
     */
    fun encode(
        gifData: ByteArray,
        origBytes: ByteArray,
        origExt: String,
        origPixels: ByteArray,
        kind: String,
        w: Int,
        h: Int,
        webpLossless: ((shiftedRgb: ByteArray, w: Int, h: Int) -> ByteArray?)? = null
    ): ByteArray {
        val gif = GifFrameDecoder.decode(gifData)
            ?: throw IllegalArgumentException("base gif decode failed")
        if (gif.width != w || gif.height != h) throw IllegalArgumentException("size mismatch")
        val n = w * h
        val gifRgb = gif.rgb

        data class Candidate(val mode: Int, val payload: ByteArray)

        val cands = ArrayList<Candidate>()

        val extBytes = origExt.toByteArray(Charsets.UTF_8)
        require(extBytes.size <= 255) { "ext too long" }
        val rawFull = ByteArray(1 + extBytes.size + origBytes.size)
        rawFull[0] = extBytes.size.toByte()
        System.arraycopy(extBytes, 0, rawFull, 1, extBytes.size)
        System.arraycopy(origBytes, 0, rawFull, 1 + extBytes.size, origBytes.size)
        cands.add(Candidate(MODE_FULL, be32(rawFull.size) + lzmaCompress(rawFull)))

        val head = be32(w) + be32(h)

        when (kind) {
            "RGB" -> {
                val delta = ByteArray(n * 3)
                for (i in 0 until n * 3) {
                    delta[i] = ((origPixels[i].toInt() and 0xFF) - (gifRgb[i].toInt() and 0xFF) and 0xFF).toByte()
                }
                cands.add(Candidate(MODE_DELTA_LZMA, be32(head.size + delta.size) + lzmaCompress(head + delta)))
                if (webpLossless != null) {
                    val shifted = ByteArray(n * 3)
                    for (i in 0 until n * 3) shifted[i] = ((delta[i].toInt() and 0xFF) + 128 and 0xFF).toByte()
                    val webp = webpLossless(shifted, w, h)
                    if (webp != null) cands.add(Candidate(MODE_DELTA_WEBP, head + webp))
                }
            }
            "L" -> {
                val delta = ByteArray(n)
                for (i in 0 until n) {
                    val g = luma(gifRgb[i * 3].toInt() and 0xFF, gifRgb[i * 3 + 1].toInt() and 0xFF, gifRgb[i * 3 + 2].toInt() and 0xFF)
                    delta[i] = ((origPixels[i].toInt() and 0xFF) - g and 0xFF).toByte()
                }
                cands.add(Candidate(MODE_L_LZMA, be32(head.size + delta.size) + lzmaCompress(head + delta)))
                if (webpLossless != null) {
                    val grayRgb = ByteArray(n * 3)
                    for (i in 0 until n) {
                        val v = ((delta[i].toInt() and 0xFF) + 128 and 0xFF).toByte()
                        grayRgb[i * 3] = v
                        grayRgb[i * 3 + 1] = v
                        grayRgb[i * 3 + 2] = v
                    }
                    val webp = webpLossless(grayRgb, w, h)
                    if (webp != null) cands.add(Candidate(MODE_L_WEBP, head + webp))
                }
            }
            "RGBA" -> {
                val delta = ByteArray(n * 3)
                val alpha = ByteArray(n)
                for (i in 0 until n) {
                    delta[i * 3] = ((origPixels[i * 4].toInt() and 0xFF) - (gifRgb[i * 3].toInt() and 0xFF) and 0xFF).toByte()
                    delta[i * 3 + 1] = ((origPixels[i * 4 + 1].toInt() and 0xFF) - (gifRgb[i * 3 + 1].toInt() and 0xFF) and 0xFF).toByte()
                    delta[i * 3 + 2] = ((origPixels[i * 4 + 2].toInt() and 0xFF) - (gifRgb[i * 3 + 2].toInt() and 0xFF) and 0xFF).toByte()
                    alpha[i] = origPixels[i * 4 + 3]
                }
                cands.add(Candidate(MODE_RGBA_LZMA, be32(head.size + delta.size + alpha.size) + lzmaCompress(head + delta + alpha)))
            }
            else -> throw IllegalArgumentException("bad kind $kind")
        }

        val best = cands.minByOrNull { it.payload.size }
            ?: throw IllegalArgumentException("no candidates")
        val out = ByteArrayOutputStream()
        out.write(gifData)
        out.write(MAGIC)
        out.write(best.mode)
        out.write(best.payload)
        return out.toByteArray()
    }

    private fun lzmaCompress(data: ByteArray): ByteArray {
        val bos = ByteArrayOutputStream()
        val xz = XZOutputStream(bos, LZMA2Options(6))
        xz.write(data)
        xz.finish()
        return bos.toByteArray()
    }

    private fun be32(v: Int): ByteArray {
        return byteArrayOf(
            (v ushr 24).toByte(),
            (v ushr 16).toByte(),
            (v ushr 8).toByte(),
            v.toByte()
        )
    }

    private fun decodeFull(blob: ByteArray): DecodeResult? {
        if (blob.size < 5) return null
        val rawLen = be32(blob, 1)
        val raw = lzmaDecompress(blob, 5)
        if (raw == null || raw.size != rawLen) return null
        val extLen = raw[0].toInt() and 0xFF
        if (extLen > raw.size - 1) return null
        val ext = String(raw, 1, extLen, Charsets.UTF_8)
        val origBytes = raw.copyOfRange(1 + extLen, raw.size)
        return DecodeResult(origBytes, ext)
    }

    private fun decodeLzma(blob: ByteArray, mode: Int, gifData: ByteArray): DecodeResult? {
        if (blob.size < 5) return null
        val rawLen = be32(blob, 1)
        val raw = lzmaDecompress(blob, 5)
        if (raw == null || raw.size != rawLen || raw.size < 8) return null
        val w = be32(raw, 0)
        val h = be32(raw, 4)
        val body = raw.copyOfRange(8, raw.size)
        if (w <= 0 || h <= 0) return null
        val isRgba = mode == MODE_RGBA_LZMA
        val delta = if (isRgba) body.copyOfRange(0, w * h * 3) else body
        val alpha = if (isRgba) body.copyOfRange(w * h * 3, body.size) else null
        return restore(w, h, delta, alpha, gifData)
    }

    private fun decodeWebp(
        blob: ByteArray,
        mode: Int,
        gifData: ByteArray,
        webpToRgba: (ByteArray) -> PixelImage?
    ): DecodeResult? {
        if (blob.size < 9) return null
        val w = be32(blob, 1)
        val h = be32(blob, 5)
        if (w <= 0 || h <= 0) return null
        val stored = webpToRgba(blob.copyOfRange(9, blob.size)) ?: return null
        if (stored.width != w || stored.height != h) return null
        val rgba = stored.rgba
        val n = w * h
        val delta: ByteArray
        val alpha: ByteArray?
        when (mode) {
            MODE_DELTA_WEBP -> {
                delta = ByteArray(n * 3)
                var j = 0
                for (i in 0 until n) {
                    delta[j] = ((rgba[i * 4] - 128) and 0xFF).toByte()
                    delta[j + 1] = ((rgba[i * 4 + 1] - 128) and 0xFF).toByte()
                    delta[j + 2] = ((rgba[i * 4 + 2] - 128) and 0xFF).toByte()
                    j += 3
                }
                alpha = null
            }
            MODE_L_WEBP -> {
                delta = ByteArray(n)
                for (i in 0 until n) {
                    delta[i] = ((luma(
                        rgba[i * 4].toInt() and 0xFF,
                        rgba[i * 4 + 1].toInt() and 0xFF,
                        rgba[i * 4 + 2].toInt() and 0xFF
                    ) - 128) and 0xFF).toByte()
                }
                alpha = null
            }
            else -> {
                delta = ByteArray(n * 3)
                alpha = ByteArray(n)
                var j = 0
                for (i in 0 until n) {
                    delta[j] = ((rgba[i * 4] - 128) and 0xFF).toByte()
                    delta[j + 1] = ((rgba[i * 4 + 1] - 128) and 0xFF).toByte()
                    delta[j + 2] = ((rgba[i * 4 + 2] - 128) and 0xFF).toByte()
                    alpha[i] = rgba[i * 4 + 3]
                    j += 3
                }
            }
        }
        return restore(w, h, delta, alpha, gifData)
    }

    /**
     * 对应 gif_stego.py _restore：GIF 渲染像素 + 残差 (mod 256) 还原，输出 RGBA PNG。
     */
    private fun restore(
        w: Int,
        h: Int,
        delta: ByteArray,
        alpha: ByteArray?,
        gifData: ByteArray
    ): DecodeResult? {
        val gif = GifFrameDecoder.decode(gifData) ?: return null
        if (gif.width != w || gif.height != h) return null
        val rgb = gif.rgb
        val isGray = alpha == null && delta.size == w * h
        val out = ByteArray(w * h * 4)

        if (isGray) {
            if (rgb.size != w * h * 3) return null
            for (i in 0 until w * h) {
                val g = luma(rgb[i * 3].toInt() and 0xFF, rgb[i * 3 + 1].toInt() and 0xFF, rgb[i * 3 + 2].toInt() and 0xFF)
                val v = (g + (delta[i].toInt() and 0xFF)) and 0xFF
                out[i * 4] = v.toByte()
                out[i * 4 + 1] = v.toByte()
                out[i * 4 + 2] = v.toByte()
                out[i * 4 + 3] = 0xFF.toByte()
            }
        } else if (alpha == null) {
            if (rgb.size != w * h * 3 || delta.size != w * h * 3) return null
            var j = 0
            for (i in 0 until w * h) {
                out[i * 4] = ((rgb[j].toInt() and 0xFF) + (delta[j].toInt() and 0xFF) and 0xFF).toByte()
                out[i * 4 + 1] = ((rgb[j + 1].toInt() and 0xFF) + (delta[j + 1].toInt() and 0xFF) and 0xFF).toByte()
                out[i * 4 + 2] = ((rgb[j + 2].toInt() and 0xFF) + (delta[j + 2].toInt() and 0xFF) and 0xFF).toByte()
                out[i * 4 + 3] = 0xFF.toByte()
                j += 3
            }
        } else {
            if (rgb.size != w * h * 3 || delta.size != w * h * 3 || alpha.size != w * h) return null
            var j = 0
            for (i in 0 until w * h) {
                out[i * 4] = ((rgb[j].toInt() and 0xFF) + (delta[j].toInt() and 0xFF) and 0xFF).toByte()
                out[i * 4 + 1] = ((rgb[j + 1].toInt() and 0xFF) + (delta[j + 1].toInt() and 0xFF) and 0xFF).toByte()
                out[i * 4 + 2] = ((rgb[j + 2].toInt() and 0xFF) + (delta[j + 2].toInt() and 0xFF) and 0xFF).toByte()
                out[i * 4 + 3] = alpha[i]
                j += 3
            }
        }
        return DecodeResult(encodePng(w, h, out), "png")
    }

    /** Pillow RGB→L：round((R*299+G*587+B*114)/1000)，round-half-up */
    private fun luma(r: Int, g: Int, b: Int): Int {
        return (r * 299 + g * 587 + b * 114 + 500) / 1000
    }

    private fun lzmaDecompress(data: ByteArray, offset: Int): ByteArray? {
        return try {
            val input = XZInputStream(java.io.ByteArrayInputStream(data, offset, data.size - offset))
            input.readBytes()
        } catch (e: Exception) {
            null
        }
    }

    private fun be32(data: ByteArray, offset: Int): Int {
        if (offset + 3 >= data.size) return 0
        return ((data[offset].toInt() and 0xFF) shl 24) or
            ((data[offset + 1].toInt() and 0xFF) shl 16) or
            ((data[offset + 2].toInt() and 0xFF) shl 8) or
            (data[offset + 3].toInt() and 0xFF)
    }

    private fun indexOf(data: ByteArray, target: ByteArray): Int {
        outer@ for (i in 0..data.size - target.size) {
            for (j in target.indices) {
                if (data[i + j] != target[j]) continue@outer
            }
            return i
        }
        return -1
    }

    private fun lastIndexOf(data: ByteArray, target: ByteArray): Int {
        for (i in data.size - target.size downTo 0) {
            var match = true
            for (j in target.indices) {
                if (data[i + j] != target[j]) {
                    match = false
                    break
                }
            }
            if (match) return i
        }
        return -1
    }

    /** 无损 PNG 编码（RGBA，bit depth 8），对应桌面端 im.save PNG */
    fun encodePng(width: Int, height: Int, rgba: ByteArray): ByteArray {
        val out = ByteArrayOutputStream()
        out.write(byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A))

        val ihdr = ByteArray(13)
        ihdr[0] = (width ushr 24).toByte()
        ihdr[1] = (width ushr 16).toByte()
        ihdr[2] = (width ushr 8).toByte()
        ihdr[3] = width.toByte()
        ihdr[4] = (height ushr 24).toByte()
        ihdr[5] = (height ushr 16).toByte()
        ihdr[6] = (height ushr 8).toByte()
        ihdr[7] = height.toByte()
        ihdr[8] = 8
        ihdr[9] = 6 // color type RGBA
        ihdr[10] = 0
        ihdr[11] = 0
        ihdr[12] = 0
        writeChunk(out, "IHDR".toByteArray(Charsets.US_ASCII), ihdr)

        val raw = ByteArray(height * (1 + width * 4))
        var dst = 0
        for (row in 0 until height) {
            raw[dst++] = 0
            System.arraycopy(rgba, row * width * 4, raw, dst, width * 4)
            dst += width * 4
        }
        val deflater = Deflater(Deflater.BEST_COMPRESSION)
        deflater.setInput(raw)
        deflater.finish()
        val idatBuf = ByteArray(raw.size + 1024)
        val n = deflater.deflate(idatBuf)
        deflater.end()
        writeChunk(out, "IDAT".toByteArray(Charsets.US_ASCII), idatBuf.copyOfRange(0, n))

        writeChunk(out, "IEND".toByteArray(Charsets.US_ASCII), ByteArray(0))
        return out.toByteArray()
    }

    private fun writeChunk(out: ByteArrayOutputStream, type: ByteArray, data: ByteArray) {
        out.write(byteArrayOf(
            (data.size ushr 24).toByte(),
            (data.size ushr 16).toByte(),
            (data.size ushr 8).toByte(),
            data.size.toByte()
        ))
        out.write(type)
        out.write(data)
        val crc = CRC32()
        crc.update(type)
        crc.update(data)
        val v = crc.value.toInt()
        out.write(byteArrayOf(
            (v ushr 24).toByte(),
            (v ushr 16).toByte(),
            (v ushr 8).toByte(),
            v.toByte()
        ))
    }
}
