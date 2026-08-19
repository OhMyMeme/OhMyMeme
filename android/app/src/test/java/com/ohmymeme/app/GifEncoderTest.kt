package com.ohmymeme.app

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Random

/**
 * GIF 编码器单测：GifEncoder 输出的 GIF 用 GifFrameDecoder 解码验证。
 * 256 色以内逐字节精确；超过 256 色验证尺寸与重编码稳定性（跨 LZW 码长边界）。
 */
class GifEncoderTest {

    private fun opaqueRgba(w: Int, h: Int, colors: IntArray, fn: (Int, Int) -> Int): ByteArray {
        val n = w * h
        val out = ByteArray(n * 4)
        for (i in 0 until n) {
            val c = colors[fn(i, n)]
            out[i * 4] = (c ushr 16 and 0xFF).toByte()
            out[i * 4 + 1] = (c ushr 8 and 0xFF).toByte()
            out[i * 4 + 2] = (c and 0xFF).toByte()
            out[i * 4 + 3] = 0xFF.toByte()
        }
        return out
    }

    @Test
    fun encodesSmallImageExact() {
        val w = 8
        val h = 8
        val colors = intArrayOf(0xFF0000, 0x00FF00, 0x0000FF, 0xFFFFFF, 0x000000, 0xFFFF00, 0xFF00FF, 0x00FFFF)
        val rgba = opaqueRgba(w, h, colors) { i, _ -> (i * 7) % colors.size }
        val gif = GifEncoder.encode(rgba, w, h)
        val dec = GifFrameDecoder.decode(gif)
        assertNotNull(dec)
        assertEquals(w, dec!!.width)
        assertEquals(h, dec.height)
        val exp = ByteArray(w * h * 3)
        for (i in 0 until w * h) {
            val c = colors[(i * 7) % colors.size]
            exp[i * 3] = (c ushr 16 and 0xFF).toByte()
            exp[i * 3 + 1] = (c ushr 8 and 0xFF).toByte()
            exp[i * 3 + 2] = (c and 0xFF).toByte()
        }
        assertArrayEquals("256 色以内应逐字节精确", exp, dec.rgb)
    }

    @Test
    fun encodesGrayscaleExact() {
        val w = 16
        val h = 16
        val rgba = ByteArray(w * h * 4)
        for (i in 0 until w * h) {
            val v = (i * 15 % 256).toByte()
            rgba[i * 4] = v
            rgba[i * 4 + 1] = v
            rgba[i * 4 + 2] = v
            rgba[i * 4 + 3] = 0xFF.toByte()
        }
        val gif = GifEncoder.encode(rgba, w, h)
        val dec = GifFrameDecoder.decode(gif)!!
        val exp = ByteArray(w * h * 3)
        for (i in 0 until w * h) {
            exp[i * 3] = rgba[i * 4]
            exp[i * 3 + 1] = rgba[i * 4 + 1]
            exp[i * 3 + 2] = rgba[i * 4 + 2]
        }
        assertArrayEquals("灰度像素应逐字节一致", exp, dec.rgb)
    }

    @Test
    fun encodesLargeImageAcrossBoundaries() {
        // 随机噪声 >256 色：LZW 表必然跨 512/1024/2048 码长边界与表满
        val rnd = Random(42)
        val w = 200
        val h = 150
        val n = w * h
        val rgba = ByteArray(n * 4)
        for (i in 0 until n) {
            rgba[i * 4] = rnd.nextInt(256).toByte()
            rgba[i * 4 + 1] = rnd.nextInt(256).toByte()
            rgba[i * 4 + 2] = rnd.nextInt(256).toByte()
            rgba[i * 4 + 3] = 0xFF.toByte()
        }
        val gif = GifEncoder.encode(rgba, w, h)
        val dec = GifFrameDecoder.decode(gif)
        assertNotNull("跨边界 GIF 应可解码", dec)
        assertEquals(w, dec!!.width)
        assertEquals(h, dec.height)
        assertTrue(dec.rgb.size == n * 3)
        // 重编码稳定性：解码结果再编码再解码应逐字节一致
        val rgba2 = ByteArray(n * 4)
        for (i in 0 until n) {
            rgba2[i * 4] = dec.rgb[i * 3]
            rgba2[i * 4 + 1] = dec.rgb[i * 3 + 1]
            rgba2[i * 4 + 2] = dec.rgb[i * 3 + 2]
            rgba2[i * 4 + 3] = 0xFF.toByte()
        }
        val gif2 = GifEncoder.encode(rgba2, w, h)
        val dec2 = GifFrameDecoder.decode(gif2)
        assertNotNull(dec2)
        assertArrayEquals("重编码应稳定", dec.rgb, dec2!!.rgb)
    }
}
