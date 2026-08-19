package com.ohmymeme.app

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase

class MemeDb(context: Context) {

    private val db: SQLiteDatabase

    companion object {
        private const val TAG = "OhMyMeme/MemeDb"

        @Volatile
        private var instance: MemeDb? = null

        fun get(context: Context): MemeDb {
            return instance ?: synchronized(this) {
                instance ?: MemeDb(context.applicationContext).also { instance = it }
            }
        }

        fun close() {
            synchronized(this) {
                instance?.let {
                    android.util.Log.d(TAG, "closing database")
                    it.db.close()
                    instance = null
                }
            }
        }
    }

    init {
        db = try {
            SQLiteDatabase.openDatabase(
                StoragePaths.dbPath(context).absolutePath,
                null,
                SQLiteDatabase.OPEN_READWRITE or SQLiteDatabase.CREATE_IF_NECESSARY
            )
        } catch (e: android.database.sqlite.SQLiteException) {
            android.util.Log.w(TAG, "open DB failed, resetting dataDir to default: $e")
            StoragePaths.resetDataDir(context)
            SQLiteDatabase.openDatabase(
                StoragePaths.dbPath(context).absolutePath,
                null,
                SQLiteDatabase.OPEN_READWRITE or SQLiteDatabase.CREATE_IF_NECESSARY
            )
        }
        db.enableWriteAheadLogging()
        initSchema()
        android.util.Log.d(TAG, "opened ${db.path}")
    }

    private fun initSchema() {
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS memes (" +
                "id INTEGER PRIMARY KEY AUTOINCREMENT," +
                "filename TEXT NOT NULL," +
                "file_hash TEXT NOT NULL DEFAULT ''," +
                "original_name TEXT NOT NULL DEFAULT ''," +
                "width INTEGER DEFAULT 0," +
                "height INTEGER DEFAULT 0," +
                "file_size INTEGER DEFAULT 0," +
                "mime_type TEXT DEFAULT 'image/png'," +
                "sort_order INTEGER DEFAULT 0," +
                "stego_of_hash TEXT DEFAULT NULL," +
                "from_stego INTEGER DEFAULT 0," +
                "image_phash TEXT NOT NULL DEFAULT ''," +
                "ai_description TEXT NOT NULL DEFAULT ''," +
                "ai_ocr_text TEXT NOT NULL DEFAULT ''," +
                "created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))," +
                "updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))" +
                ")"
        )
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS tags (" +
                "id INTEGER PRIMARY KEY AUTOINCREMENT," +
                "name TEXT NOT NULL UNIQUE COLLATE NOCASE" +
                ")"
        )
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS meme_tags (" +
                "meme_id INTEGER NOT NULL REFERENCES memes(id) ON DELETE CASCADE," +
                "tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE," +
                "PRIMARY KEY (meme_id, tag_id)" +
                ")"
        )
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS collections (" +
                "id INTEGER PRIMARY KEY AUTOINCREMENT," +
                "name TEXT NOT NULL COLLATE NOCASE," +
                "parent_id INTEGER DEFAULT NULL REFERENCES collections(id) ON DELETE CASCADE," +
                "sort_order INTEGER DEFAULT 0" +
                ")"
        )
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS meme_collections (" +
                "meme_id INTEGER NOT NULL REFERENCES memes(id) ON DELETE CASCADE," +
                "collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE," +
                "sort_order INTEGER DEFAULT 0," +
                "PRIMARY KEY (meme_id, collection_id)" +
                ")"
        )
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS favorites (" +
                "meme_id INTEGER PRIMARY KEY REFERENCES memes(id) ON DELETE CASCADE," +
                "added_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))" +
                ")"
        )
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS recent_uses (" +
                "meme_id INTEGER NOT NULL REFERENCES memes(id) ON DELETE CASCADE," +
                "used_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))," +
                "PRIMARY KEY (meme_id)" +
                ")"
        )
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_memes_hash ON memes(file_hash)")
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_memes_name ON memes(filename)")
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_recent_uses_at ON recent_uses(used_at)")
        migrateColumns()
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_memes_stego ON memes(stego_of_hash)")
    }

    private fun migrateColumns() {
        val migrations = listOf(
            Triple("memes", "sort_order", "INTEGER DEFAULT 0"),
            Triple("memes", "stego_of_hash", "TEXT DEFAULT NULL"),
            Triple("memes", "from_stego", "INTEGER DEFAULT 0"),
            Triple("memes", "image_phash", "TEXT NOT NULL DEFAULT ''"),
            Triple("memes", "ai_description", "TEXT NOT NULL DEFAULT ''"),
            Triple("memes", "ai_ocr_text", "TEXT NOT NULL DEFAULT ''"),
            Triple(
                "collections",
                "parent_id",
                "INTEGER DEFAULT NULL REFERENCES collections(id) ON DELETE CASCADE"
            ),
            Triple("collections", "sort_order", "INTEGER DEFAULT 0"),
            Triple("meme_collections", "sort_order", "INTEGER DEFAULT 0")
        )
        for ((table, column, definition) in migrations) {
            try {
                db.execSQL("ALTER TABLE $table ADD COLUMN $column $definition")
            } catch (e: Exception) {
                // 列已存在
            }
        }
    }

    fun addMeme(
        filename: String,
        fileHash: String = "",
        width: Int = 0,
        height: Int = 0,
        fileSize: Long = 0,
        mimeType: String = "image/png",
        originalName: String = "",
        tags: List<String>? = null,
        stegoOfHash: String? = null,
        fromStego: Int = 0,
        aiDescription: String = "",
        aiOcrText: String = ""
    ): Long {
        val values = ContentValues().apply {
            put("filename", filename)
            put("file_hash", fileHash)
            put("width", width)
            put("height", height)
            put("file_size", fileSize)
            put("mime_type", mimeType)
            put("original_name", originalName)
            if (stegoOfHash != null) put("stego_of_hash", stegoOfHash)
            put("from_stego", fromStego)
            put("ai_description", aiDescription)
            put("ai_ocr_text", aiOcrText)
        }
        val id = db.insert("memes", null, values)
        if (id != -1L && tags != null) {
            setMemeTags(id, tags)
        }
        android.util.Log.d(TAG, "addMeme id=$id filename=$filename")
        return id
    }

    fun deleteMeme(memeId: Long) {
        db.delete("memes", "id=?", arrayOf(memeId.toString()))
        pruneOrphanTags()
        android.util.Log.d(TAG, "deleteMeme id=$memeId")
    }

    fun updateMeme(memeId: Long, updates: Map<String, Any>) {
        val allowed = setOf(
            "filename", "file_hash", "width", "height", "file_size",
            "mime_type", "original_name", "stego_of_hash", "from_stego",
            "image_phash", "ai_description", "ai_ocr_text"
        )
        val values = ContentValues()
        for ((k, v) in updates) {
            if (k !in allowed) continue
            when (v) {
                is String -> values.put(k, v)
                is Int -> values.put(k, v)
                is Long -> values.put(k, v)
                is Boolean -> values.put(k, if (v) 1 else 0)
            }
        }
        if (values.size() == 0) return
        db.update("memes", values, "id=?", arrayOf(memeId.toString()))
    }

    fun applyRemoteAiText(filename: String, description: String, ocrText: String) {
        val values = ContentValues().apply {
            put("ai_description", description)
            put("ai_ocr_text", ocrText)
        }
        db.update("memes", values, "filename=?", arrayOf(filename))
    }

    fun setMemeTags(memeId: Long, tags: List<String>) {
        db.beginTransaction()
        try {
            db.delete("meme_tags", "meme_id=?", arrayOf(memeId.toString()))
            for (raw in tags) {
                val tag = raw.trim()
                if (tag.isEmpty()) continue
                db.execSQL("INSERT OR IGNORE INTO tags (name) VALUES (?)", arrayOf(tag))
                val cur = db.rawQuery("SELECT id FROM tags WHERE name=?", arrayOf(tag))
                val tagId: Long? = if (cur.moveToFirst()) cur.getLong(0) else null
                cur.close()
                if (tagId != null) {
                    db.execSQL(
                        "INSERT OR IGNORE INTO meme_tags (meme_id, tag_id) VALUES (?, ?)",
                        arrayOf(memeId, tagId)
                    )
                }
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
        pruneOrphanTags()
    }

    private fun pruneOrphanTags() {
        db.delete("tags", "NOT EXISTS (SELECT 1 FROM meme_tags mt WHERE mt.tag_id = tags.id)", null)
    }

    fun getMemeTags(memeId: Long): List<String> {
        val result = mutableListOf<String>()
        db.rawQuery(
            "SELECT t.name FROM tags t JOIN meme_tags mt ON mt.tag_id = t.id WHERE mt.meme_id = ?",
            arrayOf(memeId.toString())
        ).use { cur ->
            while (cur.moveToNext()) result.add(cur.getString(0))
        }
        return result
    }

    fun getAllTags(): List<String> {
        val result = mutableListOf<String>()
        db.rawQuery("SELECT name FROM tags ORDER BY name", null).use { cur ->
            while (cur.moveToNext()) result.add(cur.getString(0))
        }
        return result
    }

    fun toggleFavorite(memeId: Long): Boolean {
        val cur = db.rawQuery("SELECT 1 FROM favorites WHERE meme_id=?", arrayOf(memeId.toString()))
        val exists = cur.moveToFirst()
        cur.close()
        return if (exists) {
            db.delete("favorites", "meme_id=?", arrayOf(memeId.toString()))
            false
        } else {
            db.insert("favorites", null, ContentValues().apply { put("meme_id", memeId) })
            true
        }
    }

    fun isFavorite(memeId: Long): Boolean {
        db.rawQuery("SELECT 1 FROM favorites WHERE meme_id=?", arrayOf(memeId.toString()))
            .use { return it.moveToFirst() }
    }

    fun createCollection(name: String, parentId: Long? = null): Long {
        val values = ContentValues().apply {
            put("name", name)
            if (parentId != null) put("parent_id", parentId)
        }
        return db.insert("collections", null, values)
    }

    fun findCollection(name: String, parentId: Long?): Collection? {
        val selection = if (parentId == null) {
            "name=? AND parent_id IS NULL"
        } else {
            "name=? AND parent_id=?"
        }
        val args = if (parentId == null) arrayOf(name) else arrayOf(name, parentId.toString())
        db.rawQuery(
            "SELECT id, name, parent_id, sort_order FROM collections WHERE $selection LIMIT 1",
            args
        ).use { cur ->
            if (!cur.moveToFirst()) return null
            return Collection(
                cur.getLong(0),
                cur.getString(1),
                if (cur.isNull(2)) null else cur.getLong(2),
                cur.getInt(3)
            )
        }
    }

    fun getOrCreateCollection(name: String, parentId: Long? = null): Long {
        return findCollection(name, parentId)?.id ?: createCollection(name, parentId)
    }

    fun setCollectionSortOrder(collectionId: Long, sortOrder: Int) {
        db.execSQL(
            "UPDATE collections SET sort_order=? WHERE id=?",
            arrayOf<Any>(sortOrder, collectionId)
        )
    }

    fun addToCollection(memeId: Long, collectionId: Long) {
        db.insertWithOnConflict(
            "meme_collections",
            null,
            ContentValues().apply {
                put("meme_id", memeId)
                put("collection_id", collectionId)
            },
            SQLiteDatabase.CONFLICT_IGNORE
        )
    }

    fun moveToCollection(memeId: Long, collectionId: Long) {
        db.beginTransaction()
        try {
            db.delete("meme_collections", "meme_id=?", arrayOf(memeId.toString()))
            addToCollection(memeId, collectionId)
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun removeFromCollection(memeId: Long, collectionId: Long) {
        db.delete(
            "meme_collections",
            "meme_id=? AND collection_id=?",
            arrayOf(memeId.toString(), collectionId.toString())
        )
    }

    data class CollectionMembership(val collectionId: Long, val sortOrder: Int)

    fun getMemeCollections(memeId: Long): List<CollectionMembership> {
        val result = mutableListOf<CollectionMembership>()
        db.rawQuery(
            "SELECT collection_id, sort_order FROM meme_collections WHERE meme_id=?",
            arrayOf(memeId.toString())
        ).use { cur ->
            while (cur.moveToNext()) {
                result.add(CollectionMembership(cur.getLong(0), cur.getInt(1)))
            }
        }
        return result
    }

    fun setCollectionMemberSortOrder(memeId: Long, collectionId: Long, sortOrder: Int) {
        db.execSQL(
            "UPDATE meme_collections SET sort_order=? WHERE meme_id=? AND collection_id=?",
            arrayOf<Any>(sortOrder, memeId, collectionId)
        )
    }

    data class Collection(val id: Long, val name: String, val parentId: Long?, val sortOrder: Int)

    fun getCollections(): List<Collection> {
        val result = mutableListOf<Collection>()
        db.rawQuery(
            "SELECT id, name, parent_id, sort_order FROM collections ORDER BY sort_order ASC, name",
            null
        ).use { cur ->
            while (cur.moveToNext()) {
                val parentId = if (cur.isNull(2)) null else cur.getLong(2)
                result.add(Collection(cur.getLong(0), cur.getString(1), parentId, cur.getInt(3)))
            }
        }
        return result
    }

    fun getChildCollections(parentId: Long): List<Collection> {
        val result = mutableListOf<Collection>()
        db.rawQuery(
            "SELECT id, name, parent_id, sort_order FROM collections WHERE parent_id=? " +
                "ORDER BY sort_order ASC, name",
            arrayOf(parentId.toString())
        ).use { cur ->
            while (cur.moveToNext()) {
                result.add(Collection(cur.getLong(0), cur.getString(1), parentId, cur.getInt(3)))
            }
        }
        return result
    }

    fun getCollectionDepth(cid: Long): Int {
        var depth = 0
        var cur = cid
        while (true) {
            db.rawQuery("SELECT parent_id FROM collections WHERE id=?", arrayOf(cur.toString()))
                .use { c ->
                    if (!c.moveToFirst() || c.isNull(0)) break
                    val pid = c.getLong(0)
                    if (pid == 0L) break
                    cur = pid
                    depth++
                }
        }
        return depth
    }

    fun deleteCollection(collectionId: Long) {
        db.delete("meme_collections", "collection_id=?", arrayOf(collectionId.toString()))
        db.delete("collections", "id=?", arrayOf(collectionId.toString()))
    }

    fun renameCollection(collectionId: Long, newName: String) {
        db.execSQL("UPDATE collections SET name=? WHERE id=?", arrayOf(newName, collectionId))
    }

    fun search(
        keyword: String = "",
        tags: List<String>? = null,
        collectionId: Long? = null,
        favoriteOnly: Boolean = false,
        recentOnly: Boolean = false,
        uncategorizedOnly: Boolean = false,
        offset: Int = 0,
        limit: Int = 100
    ): List<Meme> {
        val where = mutableListOf("(m.stego_of_hash IS NULL OR m.stego_of_hash = '')")
        val params = mutableListOf<String>()

        if (keyword.isNotEmpty()) {
            where.add("(m.filename LIKE ? OR m.original_name LIKE ? OR m.ai_description LIKE ? OR m.ai_ocr_text LIKE ?)")
            val kw = "%$keyword%"
            params.add(kw)
            params.add(kw)
            params.add(kw)
            params.add(kw)
        }

        if (tags != null && tags.isNotEmpty()) {
            val placeholders = tags.joinToString(",") { "?" }
            where.add(
                "m.id IN (SELECT mt.meme_id FROM meme_tags mt JOIN tags t ON t.id = mt.tag_id " +
                    "WHERE t.name IN ($placeholders) GROUP BY mt.meme_id " +
                    "HAVING COUNT(DISTINCT t.id) = ?)"
            )
            params.addAll(tags)
            params.add(tags.size.toString())
        }

        if (collectionId != null) {
            where.add("m.id IN (SELECT mc.meme_id FROM meme_collections mc WHERE mc.collection_id = ?)")
            params.add(collectionId.toString())
        }

        if (favoriteOnly) {
            where.add("m.id IN (SELECT meme_id FROM favorites)")
        }

        if (recentOnly) {
            where.add("m.id IN (SELECT meme_id FROM recent_uses)")
        }

        if (uncategorizedOnly) {
            where.add("NOT EXISTS (SELECT 1 FROM meme_collections mc WHERE mc.meme_id = m.id)")
        }

        val orderBy: String
        if (collectionId != null) {
            orderBy = "ORDER BY (" +
                "SELECT mc.sort_order FROM meme_collections mc " +
                "WHERE mc.meme_id = m.id AND mc.collection_id = ?" +
                ") ASC, m.updated_at DESC"
            params.add(collectionId.toString())
        } else if (recentOnly) {
            orderBy = "ORDER BY (SELECT r.used_at FROM recent_uses r WHERE r.meme_id = m.id) DESC"
        } else {
            orderBy = "ORDER BY m.sort_order ASC, m.updated_at DESC"
        }
        val sql = "SELECT m.* FROM memes m WHERE " + where.joinToString(" AND ") +
            " $orderBy LIMIT ? OFFSET ?"
        params.add(limit.toString())
        params.add(offset.toString())

        val result = mutableListOf<Meme>()
        db.rawQuery(sql, params.toTypedArray()).use { result.addAll(cursorToMemes(it)) }
        return result
    }

    fun count(
        keyword: String = "",
        tags: List<String>? = null,
        collectionId: Long? = null,
        favoriteOnly: Boolean = false,
        recentOnly: Boolean = false,
        uncategorizedOnly: Boolean = false
    ): Int {
        val where = mutableListOf("(stego_of_hash IS NULL OR stego_of_hash = '')")
        val params = mutableListOf<String>()
        if (keyword.isNotEmpty()) {
            where.add("(filename LIKE ? OR original_name LIKE ? OR ai_description LIKE ? OR ai_ocr_text LIKE ?)")
            val kw = "%$keyword%"
            params.add(kw)
            params.add(kw)
            params.add(kw)
            params.add(kw)
        }
        if (tags != null && tags.isNotEmpty()) {
            val placeholders = tags.joinToString(",") { "?" }
            where.add(
                "id IN (SELECT mt.meme_id FROM meme_tags mt JOIN tags t ON t.id = mt.tag_id " +
                    "WHERE t.name IN ($placeholders) GROUP BY mt.meme_id " +
                    "HAVING COUNT(DISTINCT t.id) = ?)"
            )
            params.addAll(tags)
            params.add(tags.size.toString())
        }
        if (collectionId != null) {
            where.add("id IN (SELECT meme_id FROM meme_collections WHERE collection_id = ?)")
            params.add(collectionId.toString())
        }
        if (favoriteOnly) {
            where.add("id IN (SELECT meme_id FROM favorites)")
        }
        if (recentOnly) {
            where.add("id IN (SELECT meme_id FROM recent_uses)")
        }
        if (uncategorizedOnly) {
            where.add("NOT EXISTS (SELECT 1 FROM meme_collections mc WHERE mc.meme_id = id)")
        }
        val sql = "SELECT COUNT(*) FROM memes WHERE " + where.joinToString(" AND ")
        db.rawQuery(sql, params.toTypedArray()).use {
            return if (it.moveToFirst()) it.getInt(0) else 0
        }
    }

    fun getByHash(fileHash: String): Meme? {
        return queryOne("SELECT * FROM memes WHERE file_hash=? LIMIT 1", arrayOf(fileHash))
    }

    fun getByStegoOf(fileHash: String): Meme? {
        return queryOne("SELECT * FROM memes WHERE stego_of_hash=? LIMIT 1", arrayOf(fileHash))
    }

    fun getById(memeId: Long): Meme? {
        return queryOne("SELECT * FROM memes WHERE id=?", arrayOf(memeId.toString()))
    }

    fun getByFilename(filename: String): Meme? {
        return queryOne("SELECT * FROM memes WHERE filename=? LIMIT 1", arrayOf(filename))
    }

    fun getAll(offset: Int = 0, limit: Int = 100): List<Meme> {
        val result = mutableListOf<Meme>()
        db.rawQuery(
            "SELECT * FROM memes ORDER BY sort_order ASC, updated_at DESC LIMIT ? OFFSET ?",
            arrayOf(limit.toString(), offset.toString())
        ).use { result.addAll(cursorToMemes(it)) }
        return result
    }

    fun getRecent(limit: Int = 50): List<Meme> {
        val result = mutableListOf<Meme>()
        db.rawQuery(
            "SELECT m.* FROM memes m JOIN recent_uses r ON r.meme_id = m.id " +
                "WHERE (m.stego_of_hash IS NULL OR m.stego_of_hash = '') " +
                "ORDER BY r.used_at DESC LIMIT ?",
            arrayOf(limit.toString())
        ).use { result.addAll(cursorToMemes(it)) }
        return result
    }

    fun recordUse(memeId: Long) {
        db.execSQL(
            "INSERT OR REPLACE INTO recent_uses (meme_id, used_at) VALUES (?, datetime('now','localtime'))",
            arrayOf(memeId)
        )
        android.util.Log.d(TAG, "recordUse id=$memeId")
    }

    fun removeFromRecent(memeId: Long) {
        db.delete("recent_uses", "meme_id=?", arrayOf(memeId.toString()))
    }

    fun clearRecent() {
        db.delete("recent_uses", null, null)
    }

    fun deleteAll() {
        db.execSQL("DELETE FROM favorites")
        db.execSQL("DELETE FROM meme_collections")
        db.execSQL("DELETE FROM meme_tags")
        db.execSQL("DELETE FROM memes")
        db.execSQL("DELETE FROM collections")
        db.execSQL("DELETE FROM tags")
        android.util.Log.d(TAG, "deleteAll")
    }

    fun reorderMemes(memeIds: List<Long>) {
        db.beginTransaction()
        try {
            memeIds.forEachIndexed { i, mid ->
                db.execSQL("UPDATE memes SET sort_order=? WHERE id=?", arrayOf(i, mid))
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun reorderCollections(collectionIds: List<Long>) {
        db.beginTransaction()
        try {
            collectionIds.forEachIndexed { i, cid ->
                db.execSQL("UPDATE collections SET sort_order=? WHERE id=?", arrayOf(i, cid))
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun reorderCollectionMembers(collectionId: Long, memeIds: List<Long>) {
        db.beginTransaction()
        try {
            memeIds.forEachIndexed { i, mid ->
                db.execSQL(
                    "UPDATE meme_collections SET sort_order=? WHERE meme_id=? AND collection_id=?",
                    arrayOf(i, mid, collectionId)
                )
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    private fun queryOne(sql: String, args: Array<String>): Meme? {
        db.rawQuery(sql, args).use { cur ->
            return if (cur.moveToFirst()) cursorToMeme(cur) else null
        }
    }

    private fun cursorToMemes(cur: android.database.Cursor): List<Meme> {
        val result = mutableListOf<Meme>()
        while (cur.moveToNext()) result.add(cursorToMeme(cur))
        return result
    }

    private fun cursorToMeme(cur: android.database.Cursor): Meme {
        return Meme(
            id = cur.getLong(cur.getColumnIndexOrThrow("id")),
            filename = cur.getString(cur.getColumnIndexOrThrow("filename")),
            fileHash = cur.getString(cur.getColumnIndexOrThrow("file_hash")),
            originalName = cur.getString(cur.getColumnIndexOrThrow("original_name")),
            width = cur.getInt(cur.getColumnIndexOrThrow("width")),
            height = cur.getInt(cur.getColumnIndexOrThrow("height")),
            fileSize = cur.getLong(cur.getColumnIndexOrThrow("file_size")),
            mimeType = cur.getString(cur.getColumnIndexOrThrow("mime_type")),
            sortOrder = cur.getInt(cur.getColumnIndexOrThrow("sort_order")),
            stegoOfHash = if (cur.isNull(cur.getColumnIndexOrThrow("stego_of_hash"))) {
                null
            } else {
                cur.getString(cur.getColumnIndexOrThrow("stego_of_hash"))
            },
            fromStego = cur.getInt(cur.getColumnIndexOrThrow("from_stego")),
            aiDescription = cur.getString(cur.getColumnIndexOrThrow("ai_description")),
            aiOcrText = cur.getString(cur.getColumnIndexOrThrow("ai_ocr_text")),
            createdAt = cur.getString(cur.getColumnIndexOrThrow("created_at")),
            updatedAt = cur.getString(cur.getColumnIndexOrThrow("updated_at"))
        )
    }
}
