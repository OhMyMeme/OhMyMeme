package com.ohmymeme.app

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import java.io.ByteArrayInputStream
import javax.imageio.ImageIO

/**
 * 隐写 GIF 编码单测：GifEncoder 生成基座 GIF → GifStego.encode 写入 → GifStego.decode 还原，
 * 验证 RGB/L/RGBA 三种差值模式与 FULL 全图模式都能逐字节还原原图。
 */
class GifStegoEncodeTest {

    private fun gradientRgba(w: Int, h: Int, alphaMode: Int): ByteArray {
        val n = w * h
        val out = ByteArray(n * 4)
        val dw = (w - 1).coerceAtLeast(1)
        val dh = (h - 1).coerceAtLeast(1)
        for (i in 0 until n) {
            val x = i % w
            val y = i / w
            val r = (x * 255 / dw).toByte()
            val g = (y * 255 / dh).toByte()
            val b = ((x * 3 + y * 5) % 256).toByte()
            val a = when (alphaMode) {
                0 -> 0xFF
                1 -> ((x * 255 / w) % 256).toByte()
                else -> (i % 256).toByte()
            }
            out[i * 4] = r
            out[i * 4 + 1] = g
            out[i * 4 + 2] = b
            out[i * 4 + 3] = a.toByte()
        }
        return out
    }

    private fun rgbOf(rgba: ByteArray): ByteArray {
        val n = rgba.size / 4
        val out = ByteArray(n * 3)
        for (i in 0 until n) {
            out[i * 3] = rgba[i * 4]
            out[i * 3 + 1] = rgba[i * 4 + 1]
            out[i * 3 + 2] = rgba[i * 4 + 2]
        }
        return out
    }

    private fun grayOf(rgba: ByteArray): ByteArray {
        val n = rgba.size / 4
        val out = ByteArray(n)
        for (i in 0 until n) out[i] = rgba[i * 4]
        return out
    }

    private fun pngToRgba(png: ByteArray): ByteArray {
        val img = ImageIO.read(ByteArrayInputStream(png))
        val w = img.width
        val h = img.height
        val rgba = ByteArray(w * h * 4)
        for (y in 0 until h) {
            for (x in 0 until w) {
                val rgb = img.getRGB(x, y)
                val i = (y * w + x) * 4
                rgba[i] = (rgb ushr 16 and 0xFF).toByte()
                rgba[i + 1] = (rgb ushr 8 and 0xFF).toByte()
                rgba[i + 2] = (rgb and 0xFF).toByte()
                rgba[i + 3] = (rgb ushr 24 and 0xFF).toByte()
            }
        }
        return rgba
    }

    private fun roundtrip(rgba: ByteArray, kind: String, origBytes: ByteArray = pngOf(rgba)) {
        val w = 40
        val h = 30
        val base = GifEncoder.encode(rgba, w, h)
        val origPixels = when (kind) {
            "RGBA" -> rgba
            "L" -> grayOf(rgba)
            else -> rgbOf(rgba)
        }
        val stego = GifStego.encode(base, origBytes, "png", origPixels, kind, w, h)
        val res = GifStego.decode(stego) { null }
        assertNotNull("$kind 解码失败", res)
        assertEquals("$kind 扩展名", "png", res!!.ext)
        assertArrayEquals("$kind 还原像素不一致", rgba, pngToRgba(res.bytes))
    }

    private fun pngOf(rgba: ByteArray): ByteArray = GifStego.encodePng(40, 30, rgba)

    @Test
    fun rgbRoundtrip() {
        roundtrip(gradientRgba(40, 30, 0), "RGB")
    }

    @Test
    fun lRoundtrip() {
        val rgba = gradientRgba(40, 30, 0)
        for (i in rgba.indices step 4) {
            val v = rgba[i]
            rgba[i + 1] = v
            rgba[i + 2] = v
        }
        roundtrip(rgba, "L")
    }

    @Test
    fun rgbaRoundtrip() {
        roundtrip(gradientRgba(40, 30, 2), "RGBA")
    }

    @Test
    fun fullModeRoundtrip() {
        val w = 120
        val h = 90
        val n = w * h
        val rnd = java.util.Random(5)
        val rgba = ByteArray(n * 4)
        for (i in 0 until n) {
            rgba[i * 4] = rnd.nextInt(256).toByte()
            rgba[i * 4 + 1] = rnd.nextInt(256).toByte()
            rgba[i * 4 + 2] = rnd.nextInt(256).toByte()
            rgba[i * 4 + 3] = 0xFF.toByte()
        }
        val base = GifEncoder.encode(rgba, w, h)
        // 原始文件字节很小且差值巨大 → FULL 候选必然最小
        val origBytes = byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x01, 0x02, 0x03)
        val stego = GifStego.encode(base, origBytes, "png", rgbOf(rgba), "RGB", w, h)
        val res = GifStego.decode(stego) { null }
        assertNotNull("FULL 解码失败", res)
        assertEquals("png", res!!.ext)
        assertArrayEquals("FULL 应还原原始文件字节", origBytes, res.bytes)
    }

    @Test
    fun hasStegoAfterEncode() {
        val rgba = gradientRgba(16, 16, 0)
        val base = GifEncoder.encode(rgba, 16, 16)
        val stego = GifStego.encode(base, byteArrayOf(1, 2, 3), "png", rgbOf(rgba), "RGB", 16, 16)
        assertEquals(true, GifStego.hasStego(stego))
    }
}
