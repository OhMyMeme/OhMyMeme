package com.ohmymeme.app

import android.content.Context
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream

object MemePack {

    private const val FORMAT = "ohmymeme-pack"
    private const val VERSION = 1
    private const val MAX_MEMES = 500
    private const val MAX_MEMBERS = MAX_MEMES + 1
    private const val MAX_IMAGE_BYTES = 20L * 1024L * 1024L
    private const val MAX_TOTAL_BYTES = 200L * 1024L * 1024L
    private val allowedExtensions = setOf(".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

    data class Result(
        val ok: Boolean,
        val imported: Int = 0,
        val skipped: Int = 0,
        val error: String? = null
    )

    private data class ImageEntry(
        val file: String,
        val originalName: String,
        val tags: List<String>,
        val favorite: Boolean,
        val sortOrder: Int,
        val collections: List<Membership>
    )

    private data class Membership(val key: String, val sortOrder: Int)

    private data class CollectionEntry(
        val key: String,
        val name: String,
        val parentKey: String?,
        val sortOrder: Int
    )

    fun export(context: Context, memeIds: List<Long>, destination: Uri): Result {
        val db = MemeDb.get(context)
        val selected = memeIds.distinct().mapNotNull { db.getById(it) }
        if (selected.isEmpty()) return Result(false, error = "未选择有效表情")

        return try {
            val items = selected.mapNotNull { meme ->
                Thumbnailer.findMemeFile(context, meme.filename)?.let { meme to it }
            }
            if (items.isEmpty()) return Result(false, error = "未找到可导出的图片")
            context.contentResolver.openOutputStream(destination)?.use { raw ->
                ZipOutputStream(BufferedOutputStream(raw)).use { archive ->
                    val metadata = buildMetadata(db, items.map { it.first })
                    archive.putNextEntry(ZipEntry("metadata.json"))
                    archive.write(metadata.toString().toByteArray(Charsets.UTF_8))
                    archive.closeEntry()
                    items.forEachIndexed { index, (_, file) ->
                        val ext = extensionOf(file.name).ifEmpty { ".png" }
                        archive.putNextEntry(ZipEntry("images/$index$ext"))
                        file.openInputStream().use { input -> input.copyTo(archive) }
                        archive.closeEntry()
                    }
                }
            } ?: return Result(false, error = "无法写入分享包")
            Result(true, imported = items.size)
        } catch (e: Exception) {
            android.util.Log.w("OhMyMeme/MemePack", "export failed: $e")
            Result(false, error = "导出分享包失败")
        }
    }

    fun import(context: Context, source: Uri): Result {
        val entries = mutableListOf<ImageEntry>()
        val images = linkedMapOf<String, ByteArray>()
        val rawCollections = mutableListOf<CollectionEntry>()
        return try {
            context.contentResolver.openInputStream(source)?.use { raw ->
                ZipInputStream(BufferedInputStream(raw)).use { archive ->
                    var metadata: JSONObject? = null
                    var memberCount = 0
                    var totalSize = 0L
                    while (true) {
                        val entry = archive.nextEntry ?: break
                        memberCount++
                        if (memberCount > MAX_MEMBERS || !isSafeMember(entry.name)) {
                            return Result(false, error = "分享包内容无效")
                        }
                        val bytes = archive.readLimitedEntry(MAX_TOTAL_BYTES - totalSize)
                            ?: return Result(false, error = "分享包内容过大")
                        totalSize += bytes.size
                        if (totalSize > MAX_TOTAL_BYTES) return Result(false, error = "分享包内容过大")
                        when (entry.name) {
                            "metadata.json" -> metadata = parseMetadata(bytes, entries, rawCollections)
                                ?: return Result(false, error = "分享包元数据无效")
                            else -> {
                                if (!entry.name.startsWith("images/") ||
                                    extensionOf(entry.name) !in allowedExtensions ||
                                    bytes.size > MAX_IMAGE_BYTES
                                ) return Result(false, error = "分享包图片条目无效")
                                images[entry.name] = bytes
                            }
                        }
                        archive.closeEntry()
                    }
                    if (metadata == null) return Result(false, error = "分享包缺少元数据")
                }
            } ?: return Result(false, error = "无法读取分享包")

            if (entries.any { it.file !in images }) return Result(false, error = "分享包图片条目无效")
            val db = MemeDb.get(context)
            val imported = linkedMapOf<ImageEntry, Meme>()
            var skipped = 0
            entries.forEach { entry ->
                val meme = MemeImporter.importBytesResult(
                    context,
                    images.getValue(entry.file),
                    entry.originalName,
                    extensionOf(entry.file)
                )
                if (meme == null) skipped++ else imported[entry] = meme
            }
            restoreCollections(db, rawCollections)
            val collectionMap = buildCollectionMap(db, rawCollections)
            imported.forEach { (entry, meme) ->
                db.setMemeTags(meme.id, entry.tags.take(100))
                if (entry.favorite && !db.isFavorite(meme.id)) db.toggleFavorite(meme.id)
                entry.collections.forEach { membership ->
                    val collectionId = collectionMap[membership.key] ?: return@forEach
                    db.addToCollection(meme.id, collectionId)
                    db.setCollectionMemberSortOrder(meme.id, collectionId, membership.sortOrder)
                }
            }
            val ordered = imported.entries.sortedBy { it.key.sortOrder }.map { it.value.id }
            if (ordered.isNotEmpty()) db.reorderMemes(ordered)
            Result(true, imported = imported.size, skipped = skipped)
        } catch (e: Exception) {
            android.util.Log.w("OhMyMeme/MemePack", "import failed: $e")
            Result(false, error = "无法读取分享包")
        }
    }

    private fun buildMetadata(db: MemeDb, memes: List<Meme>): JSONObject {
        val collections = db.getCollections()
        val keys = collections.mapIndexed { index, collection -> collection.id to "c$index" }.toMap()
        val collectionJson = JSONArray()
        collections.forEach { collection ->
            collectionJson.put(JSONObject().apply {
                put("key", keys.getValue(collection.id))
                put("name", collection.name)
                put("parent", collection.parentId?.let { keys[it] })
                put("sort_order", collection.sortOrder)
            })
        }
        val memesJson = JSONArray()
        memes.forEachIndexed { index, meme ->
            val memberships = JSONArray()
            db.getMemeCollections(meme.id).forEach { membership ->
                keys[membership.collectionId]?.let { key ->
                    memberships.put(JSONObject().apply {
                        put("key", key)
                        put("sort_order", membership.sortOrder)
                    })
                }
            }
            val ext = extensionOf(meme.filename).ifEmpty { ".png" }
            memesJson.put(JSONObject().apply {
                put("file", "images/$index$ext")
                put("original_name", meme.originalName)
                put("tags", JSONArray(db.getMemeTags(meme.id)))
                put("favorite", db.isFavorite(meme.id))
                put("sort_order", meme.sortOrder)
                put("collections", memberships)
            })
        }
        return JSONObject().apply {
            put("format", FORMAT)
            put("version", VERSION)
            put("collections", collectionJson)
            put("memes", memesJson)
        }
    }

    private fun parseMetadata(
        bytes: ByteArray,
        entries: MutableList<ImageEntry>,
        collections: MutableList<CollectionEntry>
    ): JSONObject? {
        val data = try { JSONObject(bytes.toString(Charsets.UTF_8)) } catch (_: Exception) { return null }
        if (data.optString("format") != FORMAT || data.optInt("version", -1) != VERSION) return null
        val memes = data.optJSONArray("memes") ?: return null
        val collectionArray = data.optJSONArray("collections") ?: return null
        if (memes.length() > MAX_MEMES) return null
        for (i in 0 until collectionArray.length()) {
            val item = collectionArray.optJSONObject(i) ?: return null
            val key = item.optString("key")
            val name = item.optString("name").trim()
            val parent = if (item.isNull("parent")) null else item.optString("parent").takeIf { it.isNotEmpty() }
            if (key.isEmpty() || name.isEmpty()) return null
            collections.add(CollectionEntry(key, name, parent, item.optInt("sort_order", i)))
        }
        for (i in 0 until memes.length()) {
            val item = memes.optJSONObject(i) ?: return null
            val file = item.optString("file")
            if (!file.startsWith("images/") || !isSafeMember(file) || extensionOf(file) !in allowedExtensions) return null
            val tags = mutableListOf<String>()
            val tagArray = item.optJSONArray("tags") ?: JSONArray()
            for (j in 0 until minOf(tagArray.length(), 100)) {
                tagArray.optString(j).trim().takeIf { it.isNotEmpty() }?.let { tags.add(it) }
            }
            val memberships = mutableListOf<Membership>()
            val collectionItems = item.optJSONArray("collections") ?: JSONArray()
            for (j in 0 until collectionItems.length()) {
                val member = collectionItems.optJSONObject(j) ?: continue
                member.optString("key").takeIf { it.isNotEmpty() }?.let {
                    memberships.add(Membership(it, member.optInt("sort_order", 0)))
                }
            }
            entries.add(
                ImageEntry(
                    file,
                    item.optString("original_name"),
                    tags,
                    item.optBoolean("favorite", false),
                    item.optInt("sort_order", i),
                    memberships
                )
            )
        }
        return data
    }

    private fun restoreCollections(db: MemeDb, items: List<CollectionEntry>) {
        val remaining = items.toMutableList()
        val resolved = mutableMapOf<String, Long>()
        while (remaining.isNotEmpty()) {
            val progress = remaining.removeAll { item ->
                if (item.parentKey != null && item.parentKey !in resolved) return@removeAll false
                val id = db.getOrCreateCollection(item.name, item.parentKey?.let { resolved[it] })
                if (id <= 0) return@removeAll false
                db.setCollectionSortOrder(id, item.sortOrder)
                resolved[item.key] = id
                true
            }
            if (!progress) break
        }
    }

    private fun buildCollectionMap(db: MemeDb, items: List<CollectionEntry>): Map<String, Long> {
        val resolved = mutableMapOf<String, Long>()
        val remaining = items.toMutableList()
        while (remaining.isNotEmpty()) {
            val progress = remaining.removeAll { item ->
                if (item.parentKey != null && item.parentKey !in resolved) return@removeAll false
                val collection = db.findCollection(item.name, item.parentKey?.let { resolved[it] })
                    ?: return@removeAll false
                resolved[item.key] = collection.id
                true
            }
            if (!progress) break
        }
        return resolved
    }

    private fun isSafeMember(name: String): Boolean {
        if (name.isEmpty() || name.startsWith("/") || name.contains("\\")) return false
        return name.split('/').none { it.isEmpty() || it == "." || it == ".." }
    }

    private fun extensionOf(name: String): String {
        val index = name.lastIndexOf('.')
        return if (index < 0) "" else name.substring(index).lowercase()
    }

    private fun ZipInputStream.readLimitedEntry(limit: Long): ByteArray? {
        val output = ByteArrayOutputStream()
        val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
        var total = 0L
        while (true) {
            val count = read(buffer)
            if (count < 0) break
            total += count
            if (total > limit) return null
            output.write(buffer, 0, count)
        }
        return output.toByteArray()
    }
}
