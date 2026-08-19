package com.ohmymeme.app

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import javax.imageio.ImageIO

/**
 * 隐写 GIF 解码单测。fixture 由桌面端 D:\code\OhMyMeme\src\gif_stego.py 生成。
 */
class GifStegoTest {

    private val res = File("src/test/resources")

    private fun read(name: String): ByteArray = File(res, name).readBytes()

    private fun gifData(name: String): ByteArray {
        val data = read("$name.gif")
        val pos = data.rfindStego()
        assertTrue("STG3 not found in $name", pos >= 0)
        return data.copyOfRange(0, pos)
    }

    private fun ByteArray.rfindStego(): Int {
        val magic = byteArrayOf(0x53, 0x54, 0x47, 0x33)
        for (i in size - magic.size downTo 0) {
            var ok = true
            for (j in magic.indices) {
                if (this[i + j] != magic[j]) { ok = false; break }
            }
            if (ok) return i
        }
        return -1
    }

    private fun pngToRgba(png: ByteArray): ByteArray {
        val img = ImageIO.read(java.io.ByteArrayInputStream(png))
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

    private fun lumaOf(rgb: ByteArray): ByteArray {
        val n = rgb.size / 3
        val l = ByteArray(n)
        for (i in 0 until n) {
            l[i] = (((rgb[i * 3].toInt() and 0xFF) * 299 +
                (rgb[i * 3 + 1].toInt() and 0xFF) * 587 +
                (rgb[i * 3 + 2].toInt() and 0xFF) * 114 + 500) / 1000).toByte()
        }
        return l
    }

    @Test
    fun gifFrameRenderMatchesPillow() {
        val fixtures = listOf(
            "stego_rgb_lzma", "stego_rgb_webp", "stego_rgba_lzma", "stego_rgba_webp",
            "stego_l_lzma", "stego_l_webp"
        )
        for (name in fixtures) {
            val result = GifFrameDecoder.decode(gifData(name))
            assertNotNull("GIF 解码失败: $name", result)
            val expectedRgb = read("${name}_basergb.raw")
            assertEquals("$name RGB 尺寸不符", expectedRgb.size, result!!.rgb.size)
            assertArrayEquals("$name GIF 首帧 RGB 与 Pillow 不一致", expectedRgb, result.rgb)
            if (name.startsWith("stego_l_")) {
                val expectedL = read("${name}_basel.raw")
                assertArrayEquals("$name GIF 首帧 L 与 Pillow 不一致", expectedL, lumaOf(result.rgb))
            }
        }
    }

    @Test
    fun hasStegoDetects() {
        assertTrue(GifStego.hasStego(read("stego_rgb_full.gif")))
        val plain = byteArrayOf(1, 2, 3)
        assertTrue(!GifStego.hasStego(plain))
    }

    @Test
    fun decodeFullMode() {
        val result = GifStego.decode(read("stego_rgb_full.gif"), { null })
        assertNotNull(result)
        val expected = read("stego_rgb_full_expected.png")
        assertEquals("png", result!!.ext)
        assertArrayEquals("MODE_FULL 还原字节不一致", expected, result.bytes)
    }

    @Test
    fun decodeDeltaLzmaModes() {
        val cases = listOf("stego_rgb_lzma", "stego_rgba_lzma", "stego_l_lzma")
        for (name in cases) {
            val result = GifStego.decode(read("$name.gif"), { null })
            assertNotNull("$name 解码失败", result)
            assertEquals("$name 扩展名", "png", result!!.ext)
            val expected = read("${name}_expected.raw")
            assertArrayEquals("$name 像素与 Pillow 不一致", expected, pngToRgba(result.bytes))
        }
    }

    @Test
    fun decodeDeltaWebpModes() {
        val cases = listOf("stego_rgb_webp", "stego_rgba_webp", "stego_l_webp")
        for (name in cases) {
            val stored = read("${name}_stored.raw")
            val w = when (name) {
                "stego_rgb_webp" -> 64
                "stego_rgba_webp" -> 32
                else -> 40
            }
            val h = when (name) {
                "stego_rgb_webp" -> 48
                "stego_rgba_webp" -> 32
                else -> 30
            }
            val webpToRgba: (ByteArray) -> GifStego.PixelImage? = { GifStego.PixelImage(w, h, stored) }
            val result = GifStego.decode(read("$name.gif"), webpToRgba)
            assertNotNull("$name 解码失败", result)
            assertEquals("$name 扩展名", "png", result!!.ext)
            val expected = read("${name}_expected.raw")
            assertArrayEquals("$name 像素与 Pillow 不一致", expected, pngToRgba(result.bytes))
        }
    }

    @Test
    fun decodeFailsOnPlainGif() {
        val plain = byteArrayOf(0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0x00)
        assertNull(GifStego.decode(plain, { null }))
    }

    @Test
    fun pngEncoderRoundTrips() {
        val w = 7
        val h = 5
        val rgba = ByteArray(w * h * 4)
        for (i in rgba.indices) rgba[i] = (i % 251).toByte()
        val png = GifStego.encodePng(w, h, rgba)
        assertArrayEquals(rgba, pngToRgba(png))
    }
}
