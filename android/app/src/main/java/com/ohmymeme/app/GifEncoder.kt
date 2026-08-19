package com.ohmymeme.app

import java.io.ByteArrayOutputStream

/**
 * 最小 GIF 编码器：median cut 量化到 256 色 + LZW 压缩，输出单帧 GIF89a。
 * 对应桌面端 gif_stego.py make_stego_gif / clipboard_util.py _static_to_gif 中
 * Pillow convert("P", ADAPTIVE, 256).save(GIF) 的作用。
 *
 * LZW 码长升位时机与 GifFrameDecoder.lzwDecode 严格对应（已验证与 Pillow 解码逐字节一致）：
 * 每新增一条目后 nextCode 达 (1 shl codeSize) + 1 时升位。
 */
object GifEncoder {

    /** 将 RGBA 像素编码为 GIF89a 字节（丢弃 alpha，仅量化 RGB） */
    fun encode(rgba: ByteArray, width: Int, height: Int): ByteArray {
        val (palette, indices) = quantize(rgba, width, height)
        val out = ByteArrayOutputStream()
        out.write("GIF89a".toByteArray(Charsets.ISO_8859_1))
        writeLe16(out, width)
        writeLe16(out, height)
        out.write(0x80 or 0x70 or 0x07) // 全局色板、8 位分辨率、2^(7+1)=256 色
        out.write(0) // 背景色索引
        out.write(0) // 宽高比
        out.write(palette)
        out.write(0x2C)
        writeLe16(out, 0)
        writeLe16(out, 0)
        writeLe16(out, width)
        writeLe16(out, height)
        out.write(0) // 无局部色板、无交织
        out.write(8) // 最小 LZW 码长
        val lzw = lzwEncode(indices)
        var i = 0
        while (i < lzw.size) {
            val len = minOf(255, lzw.size - i)
            out.write(len)
            out.write(lzw, i, len)
            i += len
        }
        out.write(0)
        out.write(0x3B)
        return out.toByteArray()
    }

    private fun quantize(rgba: ByteArray, width: Int, height: Int): Pair<ByteArray, IntArray> {
        val n = width * height
        val hist = HashMap<Int, Int>()
        val pixels = IntArray(n)
        var s = 0
        for (p in 0 until n) {
            val r = rgba[s].toInt() and 0xFF
            val g = rgba[s + 1].toInt() and 0xFF
            val b = rgba[s + 2].toInt() and 0xFF
            s += 4
            val c = (r shl 16) or (g shl 8) or b
            pixels[p] = c
            hist[c] = (hist[c] ?: 0) + 1
        }
        if (hist.size <= 256) {
            val palette = ByteArray(768)
            val map = HashMap<Int, Int>(hist.size)
            var idx = 0
            for ((c, _) in hist) {
                map[c] = idx
                palette[idx * 3] = ((c ushr 16) and 0xFF).toByte()
                palette[idx * 3 + 1] = ((c ushr 8) and 0xFF).toByte()
                palette[idx * 3 + 2] = (c and 0xFF).toByte()
                idx++
            }
            return palette to IntArray(n) { map[pixels[it]] ?: 0 }
        }
        // median cut：按最长颜色通道中位数反复分裂到 <=256 盒
        val boxColors = ArrayList<MutableList<Int>>()
        boxColors.add(hist.keys.toMutableList())
        val colorToBox = HashMap<Int, Int>(hist.size)
        for (c in hist.keys) colorToBox[c] = 0
        while (boxColors.size < 256) {
            var bestId = -1
            var bestScore = -1L
            for (id in boxColors.indices) {
                val list = boxColors[id]
                if (list.size <= 1) continue
                var minR = 255; var maxR = 0
                var minG = 255; var maxG = 0
                var minB = 255; var maxB = 0
                for (c in list) {
                    val r = c ushr 16 and 0xFF
                    val g = c ushr 8 and 0xFF
                    val b = c and 0xFF
                    if (r < minR) minR = r; if (r > maxR) maxR = r
                    if (g < minG) minG = g; if (g > maxG) maxG = g
                    if (b < minB) minB = b; if (b > maxB) maxB = b
                }
                val score = maxOf(maxR - minR, maxG - minG, maxB - minB).toLong() * list.size
                if (score > bestScore) { bestScore = score; bestId = id }
            }
            if (bestId == -1) break
            val list = boxColors[bestId]
            var minR = 255; var maxR = 0
            var minG = 255; var maxG = 0
            var minB = 255; var maxB = 0
            for (c in list) {
                val r = c ushr 16 and 0xFF
                val g = c ushr 8 and 0xFF
                val b = c and 0xFF
                if (r < minR) minR = r; if (r > maxR) maxR = r
                if (g < minG) minG = g; if (g > maxG) maxG = g
                if (b < minB) minB = b; if (b > maxB) maxB = b
            }
            val spreadR = maxR - minR
            val spreadG = maxG - minG
            val spreadB = maxB - minB
            when {
                spreadR >= spreadG && spreadR >= spreadB -> list.sortBy { it ushr 16 and 0xFF }
                spreadG >= spreadB -> list.sortBy { it ushr 8 and 0xFF }
                else -> list.sortBy { it and 0xFF }
            }
            val mid = list.size / 2
            val moved = ArrayList<Int>(list.subList(mid, list.size))
            boxColors[bestId] = ArrayList<Int>(list.subList(0, mid))
            val newId = boxColors.size
            for (c in moved) colorToBox[c] = newId
            boxColors.add(moved)
        }
        val palette = ByteArray(768)
        for (id in boxColors.indices) {
            var sr = 0L; var sg = 0L; var sb = 0L; var sc = 0L
            for (c in boxColors[id]) {
                val cnt = hist[c]!!
                sr += ((c ushr 16) and 0xFF) * cnt
                sg += ((c ushr 8) and 0xFF) * cnt
                sb += (c and 0xFF) * cnt
                sc += cnt
            }
            palette[id * 3] = (sr / sc).toByte()
            palette[id * 3 + 1] = (sg / sc).toByte()
            palette[id * 3 + 2] = (sb / sc).toByte()
        }
        return palette to IntArray(n) { colorToBox[pixels[it]] ?: 0 }
    }

    /** GIF LZW 编码：LSB-first，clear/end 各占 1 码，码长升位时机与 GifFrameDecoder 一致 */
    private fun lzwEncode(indices: IntArray): ByteArray {
        val clear = 256
        val end = 257
        var nextCode = 258
        var codeSize = 9
        val dict = HashMap<Int, Int>(4096)
        val out = ByteArrayOutputStream()
        var acc = 0
        var nbits = 0
        fun emit(code: Int) {
            acc = acc or (code shl nbits)
            nbits += codeSize
            while (nbits >= 8) {
                out.write(acc and 0xFF)
                acc = acc ushr 8
                nbits -= 8
            }
        }
        emit(clear)
        if (indices.isEmpty()) {
            emit(end)
        } else {
            var prefix = indices[0]
            for (i in 1 until indices.size) {
                val k = indices[i]
                val key = (prefix shl 8) or k
                val existing = dict[key]
                if (existing != null) {
                    prefix = existing
                } else {
                    emit(prefix)
                    if (nextCode < 4096) {
                        dict[key] = nextCode
                        nextCode++
                        if (nextCode == (1 shl codeSize) + 1 && codeSize < 12) codeSize++
                    }
                    prefix = k
                }
            }
            emit(prefix)
            emit(end)
        }
        if (nbits > 0) out.write(acc and 0xFF)
        return out.toByteArray()
    }

    private fun writeLe16(out: ByteArrayOutputStream, v: Int) {
        out.write(v and 0xFF)
        out.write(v ushr 8 and 0xFF)
    }
}
