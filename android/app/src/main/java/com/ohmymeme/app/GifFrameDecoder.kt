package com.ohmymeme.app

import java.io.ByteArrayOutputStream

/**
 * 最小 GIF 解码器：只渲染首个图像块为 RGB 像素。
 * 对应桌面端 gif_stego.py 的 _render_gif（Pillow 打开 GIF 后 convert）。
 * 透明索引不做 alpha 合成，直接映射调色板 RGB，与 Pillow 逐字节一致。
 */
object GifFrameDecoder {

    class Result(val width: Int, val height: Int, val rgb: ByteArray)

    fun decode(data: ByteArray): Result? {
        if (data.size < 13) return null
        if (!isGifHeader(data)) return null
        var pos = 6
        val width = le16(data, pos).coerceAtLeast(1)
        val height = le16(data, pos + 2).coerceAtLeast(1)
        val packed = data[pos + 4].toInt() and 0xFF
        val gctFlag = packed and 0x80 != 0
        val gctSize = 1 shl ((packed and 0x07) + 1)
        pos += 7
        val globalPalette = if (gctFlag) readPalette(data, pos, gctSize) else null
        if (globalPalette != null) pos += gctSize * 3

        // 找到首个图像描述符
        while (pos < data.size) {
            when (data[pos].toInt() and 0xFF) {
                0x21 -> {
                    pos += 2
                    while (pos < data.size && data[pos].toInt() != 0) {
                        val subLen = data[pos].toInt() and 0xFF
                        pos += 1 + subLen
                    }
                    pos += 1
                }
                0x2C -> {
                    val left = le16(data, pos + 1)
                    val top = le16(data, pos + 3)
                    val imgW = le16(data, pos + 5).coerceAtLeast(1)
                    val imgH = le16(data, pos + 7).coerceAtLeast(1)
                    val imgPacked = data[pos + 9].toInt() and 0xFF
                    val lctFlag = imgPacked and 0x80 != 0
                    val interlace = imgPacked and 0x40 != 0
                    val lctSize = 1 shl ((imgPacked and 0x07) + 1)
                    pos += 10
                    val palette = if (lctFlag) readPalette(data, pos, lctSize) else globalPalette
                    if (lctFlag) pos += lctSize * 3
                    if (palette == null) return null
                    val minCodeSize = data[pos].toInt() and 0xFF
                    pos += 1
                    val lzwData = ByteArrayOutputStream()
                    while (pos < data.size && data[pos].toInt() != 0) {
                        val subLen = data[pos].toInt() and 0xFF
                        lzwData.write(data, pos + 1, subLen)
                        pos += 1 + subLen
                    }
                    val indices = lzwDecode(minCodeSize, lzwData.toByteArray())
                    return renderFrame(
                        indices, width, height, left, top, imgW, imgH, interlace, palette
                    )
                }
                0x3B -> return null
                else -> pos++
            }
        }
        return null
    }

    private fun isGifHeader(data: ByteArray): Boolean {
        if (data.size < 6) return false
        val s = String(data, 0, 6, Charsets.ISO_8859_1)
        return s == "GIF87a" || s == "GIF89a"
    }

    private fun renderFrame(
        indices: IntArray,
        canvasW: Int,
        canvasH: Int,
        left: Int,
        top: Int,
        imgW: Int,
        imgH: Int,
        interlace: Boolean,
        palette: ByteArray
    ): Result {
        val rgb = ByteArray(canvasW * canvasH * 3)
        var pixel = 0
        for (row in 0 until imgH) {
            val destRow = if (interlace) deinterlaceRow(row, imgH) else row
            for (col in 0 until imgW) {
                if (pixel >= indices.size) return Result(canvasW, canvasH, rgb)
                val idx = indices[pixel++]
                val src = idx * 3
                val dst = ((top + destRow) * canvasW + (left + col)) * 3
                if (src + 2 < palette.size && dst + 2 < rgb.size) {
                    rgb[dst] = palette[src]
                    rgb[dst + 1] = palette[src + 1]
                    rgb[dst + 2] = palette[src + 2]
                }
            }
        }
        return Result(canvasW, canvasH, rgb)
    }

    /** GIF 交织行序：pass1 隔 8 取 0,8.. / pass2 取 4,12.. / pass3 隔 4 取 2,6.. / pass4 隔 2 取 1,3.. */
    private fun deinterlaceRow(row: Int, height: Int): Int {
        val p1 = (height + 7) / 8
        if (row < p1) return row * 8
        val p2 = (height + 3) / 8
        if (row < p1 + p2) return (row - p1) * 8 + 4
        val p3 = (height + 1) / 4
        if (row < p1 + p2 + p3) return (row - p1 - p2) * 4 + 2
        return (row - p1 - p2 - p3) * 2 + 1
    }

    private fun readPalette(data: ByteArray, offset: Int, size: Int): ByteArray {
        val pal = ByteArray(size * 3)
        val n = minOf(size * 3, data.size - offset)
        System.arraycopy(data, offset, pal, 0, n.coerceAtLeast(0))
        return pal
    }

    private fun le16(data: ByteArray, offset: Int): Int {
        if (offset + 1 >= data.size) return 0
        return (data[offset].toInt() and 0xFF) or ((data[offset + 1].toInt() and 0xFF) shl 8)
    }

    private fun lzwDecode(minCodeSize: Int, data: ByteArray): IntArray {
        val clearCode = 1 shl minCodeSize
        val endCode = clearCode + 1
        var codeSize = minCodeSize + 1
        val dict = ArrayList<IntArray>()
        fun resetDict() {
            dict.clear()
            for (i in 0 until clearCode) dict.add(intArrayOf(i))
            dict.add(intArrayOf())
            dict.add(intArrayOf())
            codeSize = minCodeSize + 1
        }
        resetDict()
        val result = ArrayList<Int>(data.size * 2)
        var previousCode = -1
        var bitBuffer = 0
        var bitCount = 0
        var bytePos = 0
        while (true) {
            while (bitCount < codeSize) {
                if (bytePos >= data.size) return result.toIntArray()
                bitBuffer = bitBuffer or ((data[bytePos++].toInt() and 0xFF) shl bitCount)
                bitCount += 8
            }
            val code = bitBuffer and ((1 shl codeSize) - 1)
            bitBuffer = bitBuffer shr codeSize
            bitCount -= codeSize

            if (code == clearCode) {
                resetDict()
                previousCode = -1
                continue
            }
            if (code == endCode) break

            if (previousCode == -1) {
                if (code >= dict.size) break
                val entry = dict[code]
                result.addAll(entry.toList())
                previousCode = code
                continue
            }
            val prev = dict[previousCode]
            val entry: IntArray
            if (code < dict.size) {
                entry = dict[code]
                dict.add(prev + intArrayOf(entry[0]))
            } else if (code == dict.size) {
                entry = prev + intArrayOf(prev[0])
                dict.add(entry)
            } else {
                break
            }
            result.addAll(entry.toList())
            previousCode = code
            if (dict.size == (1 shl codeSize) && codeSize < 12) codeSize++
        }
        return result.toIntArray()
    }
}
