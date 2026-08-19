package com.ohmymeme.app

import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import androidx.documentfile.provider.DocumentFile
import java.io.File
import java.io.InputStream
import java.io.OutputStream

/**
 * 统一数据目录文件句柄：真实路径模式（File）与 SAF 树模式（DocumentFile）双实现。
 * 作用域存储（Android 11+）下用户选择的目录只能经 content URI 读写，
 * cache/thumbnails 通过本抽象读写，memes.db 始终留在应用可真实写入的路径。
 */
class StorFile private constructor(
    private val ctx: Context,
    private val file: File?,
    private val doc: DocumentFile?
) {
    val realFile: File? get() = file

    val uri: Uri? get() = doc?.uri

    val name: String get() = file?.name ?: (doc?.name ?: "")

    val isDirectory: Boolean get() = file?.isDirectory ?: (doc?.isDirectory ?: false)

    val exists: Boolean get() = file?.exists() ?: (doc?.exists() ?: false)

    val length: Long get() = file?.length() ?: (doc?.length() ?: 0L)

    val lastModified: Long
        get() {
            if (file != null) return file.lastModified()
            // SAF 模式没有统一的 mtime 读取方式，返回 0（清单 mtime 仅作展示）
            return 0L
        }

    private val resolver: ContentResolver get() = ctx.contentResolver

    companion object {
        fun real(ctx: Context, dir: File): StorFile = StorFile(ctx, dir, null)

        fun safRoot(ctx: Context, treeUri: Uri): StorFile {
            val doc = DocumentFile.fromTreeUri(ctx, treeUri)
                ?: throw IllegalArgumentException("bad tree uri $treeUri")
            return StorFile(ctx, null, doc)
        }
    }

    /** 子项（可能不存在，需先检查 [exists]） */
    fun child(name: String): StorFile {
        return if (file != null) StorFile(ctx, File(file, name), null)
        else StorFile(ctx, null, doc?.findFile(name))
    }

    /** 子目录，不存在则创建 */
    fun childOrCreateDir(name: String): StorFile {
        return if (file != null) {
            val f = File(file, name)
            f.mkdirs()
            StorFile(ctx, f, null)
        } else {
            val d = doc?.findFile(name)
            if (d == null || !d.isDirectory) {
                val created = doc?.createDirectory(name)
                StorFile(ctx, null, created)
            } else {
                StorFile(ctx, null, d)
            }
        }
    }

    /** 创建文件（已存在则复用），用于写入新缓存/缩略图 */
    fun createFile(name: String, mime: String): StorFile {
        return if (file != null) {
            val f = File(file, name)
            f.parentFile?.mkdirs()
            StorFile(ctx, f, null)
        } else {
            var d = doc?.findFile(name)
            if (d == null) d = doc?.createFile(mime, name)
            StorFile(ctx, null, d)
        }
    }

    fun listFiles(): List<StorFile> {
        return if (file != null) (file.listFiles() ?: emptyArray()).map { StorFile(ctx, it, null) }
        else (doc?.listFiles() ?: emptyArray()).map { StorFile(ctx, null, it) }
    }

    /** 递归列出全部文件（不含目录），跳过名为 thumbnails 的目录 */
    fun listFilesRecursive(): List<StorFile> {
        val out = mutableListOf<StorFile>()
        fun walk(d: StorFile) {
            d.listFiles().forEach { e ->
                when {
                    e.isDirectory -> if (e.name != "thumbnails") walk(e)
                    else -> out.add(e)
                }
            }
        }
        walk(this)
        return out
    }

    /** 同名兄弟文件（用于 .webp 与 .gif 共存判断） */
    fun sibling(name: String): StorFile {
        return if (file != null) {
            val parent = file.parentFile
            StorFile(ctx, if (parent != null) File(parent, name) else null, null)
        } else {
            val parent = doc?.parentFile
            StorFile(ctx, null, parent?.findFile(name))
        }
    }

    fun openInputStream(): InputStream {
        return file?.inputStream() ?: resolver.openInputStream(doc!!.uri)!!
    }

    /** 输出流（SAF 模式用 "wt" 截断覆盖） */
    fun openOutputStream(): OutputStream {
        return if (file != null) file.outputStream()
        else resolver.openOutputStream(doc!!.uri, "wt")!!
    }

    fun readBytes(): ByteArray = openInputStream().use { it.readBytes() }

    fun writeBytes(bytes: ByteArray) {
        openOutputStream().use { it.write(bytes) }
    }

    fun delete(): Boolean = file?.delete() ?: (doc?.delete() ?: false)

    fun copyTo(dest: File) {
        dest.parentFile?.mkdirs()
        dest.outputStream().use { out -> openInputStream().use { inp -> inp.copyTo(out) } }
    }

    fun copyFrom(src: StorFile) {
        openOutputStream().use { out -> src.openInputStream().use { inp -> inp.copyTo(out) } }
    }

    fun writeFrom(src: File) {
        openOutputStream().use { out -> src.inputStream().use { inp -> inp.copyTo(out) } }
    }

    override fun toString(): String = file?.absolutePath ?: (doc?.uri?.toString() ?: "StorFile()")
}
