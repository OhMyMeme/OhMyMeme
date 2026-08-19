package com.ohmymeme.app

import java.io.File
import java.io.InputStream
import java.security.MessageDigest

object FileUtils {

    val ALLOWED_EXT = setOf(".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

    private val MAGIC_TYPES = listOf(
        Triple(byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47), ".png", null),
        Triple(byteArrayOf(0xFF.toByte(), 0xD8.toByte()), ".jpg", null),
        Triple(byteArrayOf(0x47, 0x49, 0x46, 0x38, 0x37, 0x61), ".gif", null),
        Triple(byteArrayOf(0x47, 0x49, 0x46, 0x38, 0x39, 0x61), ".gif", null),
        Triple(byteArrayOf(0x52, 0x49, 0x46, 0x46), ".webp", "WEBP"),
        Triple(byteArrayOf(0x42, 0x4D), ".bmp", null)
    )

    fun sha256(file: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(65536)
            while (true) {
                val n = input.read(buffer)
                if (n <= 0) break
                md.update(buffer, 0, n)
            }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }

    fun sha256(input: InputStream): String {
        val md = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(65536)
        while (true) {
            val n = input.read(buffer)
            if (n <= 0) break
            md.update(buffer, 0, n)
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }

    fun detectExt(head: ByteArray): String {
        for ((magic, ext, extra) in MAGIC_TYPES) {
            if (head.size >= magic.size && startsWith(head, magic)) {
                if (extra == "WEBP") {
                    if (head.size >= 12) {
                        val s = String(head, 8, 4, Charsets.ISO_8859_1)
                        if (s != "WEBP") continue
                    } else {
                        continue
                    }
                }
                return ext
            }
        }
        return ""
    }

    /** 对应桌面端 _is_animated：GIF89a 为动图；WebP 头含 ANIM chunk 为动图 */
    fun isAnimatedFile(file: File): Boolean {
        return try {
            val head = ByteArray(50)
            val n = file.inputStream().use { it.read(head) }
            isAnimatedHead(head, n)
        } catch (e: Exception) {
            false
        }
    }

    fun isAnimatedFile(stor: StorFile): Boolean {
        return try {
            val head = ByteArray(50)
            val n = stor.openInputStream().use { it.read(head) }
            isAnimatedHead(head, n)
        } catch (e: Exception) {
            false
        }
    }

    private fun isAnimatedHead(data: ByteArray, n: Int): Boolean {
        if (data.size >= 6 && String(data, 0, 6, Charsets.ISO_8859_1) == "GIF89a") return true
        if (data.size >= 12 &&
            String(data, 0, 4, Charsets.ISO_8859_1) == "RIFF" &&
            String(data, 8, 4, Charsets.ISO_8859_1) == "WEBP"
        ) {
            return String(data, 0, n, Charsets.ISO_8859_1).contains("ANIM")
        }
        return false
    }

    private fun startsWith(data: ByteArray, prefix: ByteArray): Boolean {
        for (i in prefix.indices) {
            if (data[i] != prefix[i]) return false
        }
        return true
    }
}
