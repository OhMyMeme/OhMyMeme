package com.ohmymeme.app

import android.app.AlertDialog
import android.content.ClipData
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.result.PickVisualMediaRequest
import androidx.core.content.FileProvider
import androidx.documentfile.provider.DocumentFile
import android.text.Spannable
import android.text.SpannableString
import android.text.style.ForegroundColorSpan
import android.view.View
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.PopupMenu
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.ItemTouchHelper
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import java.io.File
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {

    private val TAG = "OhMyMeme/MainActivity"

    private data class CollectionEntry(
        val id: Long,
        val name: String,
        val count: Int,
        val hasChildren: Boolean = false
    )

    private data class CollectionNode(
        val entry: CollectionEntry,
        val children: List<CollectionNode>
    )

    private data class AiReviewItem(
        val meme: Meme,
        var tags: String,
        var collection: String,
        var description: String,
        var ocrText: String
    )

    private val executor = Executors.newSingleThreadExecutor()
    private val syncExecutor = Executors.newSingleThreadExecutor()
    private var currentKeyword = ""
    private var activeCollectionId: Long? = null
    private val activeTags = linkedSetOf<String>()
    private var currentOffset = 0
    private var currentTotal = 0
    private var displayedMemes = emptyList<Meme>()
    private var latestReloadId = 0L
    private var pendingPackExportIds = emptyList<Long>()

    companion object {
        private const val PAGE_SIZE = 200
        private const val COLLECTION_FAVORITES = -2L
        private const val COLLECTION_RECENT = -3L
        private const val COLLECTION_UNCATEGORIZED = -4L
    }

    private val folderImportLauncher =
        registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
            if (uri != null) doImportFolder(uri)
        }

    private val importLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            handlePickResult(result.resultCode, result.data)
        }
    private val galleryLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            handlePickResult(result.resultCode, result.data)
        }
    private val packImportLauncher =
        registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
            if (uri != null) doImportPack(uri)
        }
    private val packExportLauncher =
        registerForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
            if (uri != null) doExportPack(uri, pendingPackExportIds)
        }
    private val photoPickerLauncher =
        registerForActivityResult(ActivityResultContracts.PickMultipleVisualMedia()) { uris ->
            if (uris.isNotEmpty()) doImport(uris)
        }
    private val pickDirLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            handlePickDirResult(result.resultCode, result.data)
        }
    private val settingsLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode == RESULT_OK) reloadData()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        setupLogo()
        setupTitleButtons()
        setupBars()
        setupSearch()
        ensureFirstRunSetup()
        autoSyncIfConfigured()
        handleIncomingIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingIntent(intent)
    }

    @Suppress("DEPRECATION")
    private fun handleIncomingIntent(intent: Intent) {
        if (intent.action != Intent.ACTION_SEND && intent.action != Intent.ACTION_SEND_MULTIPLE) return
        val uris = mutableListOf<Uri>()
        when (intent.action) {
            Intent.ACTION_SEND -> intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)?.let { uris.add(it) }
            Intent.ACTION_SEND_MULTIPLE -> {
                intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)?.let { uris.addAll(it) }
            }
        }
        if (uris.isEmpty()) return
        doImport(uris)
    }

    private fun autoSyncIfConfigured() {
        if (StoragePaths.isFirstRun(this)) return
        val cfg = ConfigStore.get(this)
        val syncType = cfg.optString("sync_type", "")
        val autoFetch = cfg.optBoolean("sync_auto_fetch_index", false)
        val autoSync = cfg.optBoolean("sync_auto_sync", false)
        if (syncType.isEmpty() || (!autoFetch && !autoSync)) return
        executor.execute {
            try {
                if (autoSync) {
                    CloudSync.pull(this)
                } else if (autoFetch) {
                    CloudSync.checkSyncStatus(this)
                }
                runOnUiThread { reloadData() }
            } catch (e: Exception) {
                runOnUiThread { toast(e.message ?: getString(R.string.sync_failed)) }
            }
        }
    }

    private fun ensureFirstRunSetup() {
        if (!StoragePaths.isFirstRun(this)) {
            reloadData()
            return
        }
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.storage_title))
            .setMessage(getString(R.string.storage_message))
            .setCancelable(false)
            .setPositiveButton(getString(R.string.storage_use_default)) { _, _ ->
                StoragePaths.markSetupDone(this)
                reloadData()
            }
            .setNegativeButton(getString(R.string.storage_pick_custom)) { _, _ ->
                val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
                pickDirLauncher.launch(intent)
            }
            .show()
    }

    private fun setupLogo() {
        val logo = findViewById<TextView>(R.id.tv_logo)
        val spannable = SpannableString("OhMyMeme")
        spannable.setSpan(
            ForegroundColorSpan(getColor(R.color.accent)),
            4, 8, Spannable.SPAN_EXCLUSIVE_EXCLUSIVE
        )
        logo.text = spannable
    }

    private fun setupTitleButtons() {
        findViewById<TextView>(R.id.btn_import).setOnClickListener { showImportMenu(it) }
        findViewById<View>(R.id.btn_more).setOnClickListener { showMoreActionsMenu(it) }
        findViewById<View>(R.id.btn_settings).setOnClickListener {
            settingsLauncher.launch(Intent(this, SettingsActivity::class.java))
        }
    }

    private fun quickSync(isUpload: Boolean) {
        val cfg = ConfigStore.get(this)
        if (cfg.optString("sync_type", "").isEmpty()) {
            toast(getString(R.string.sync_not_configured))
            return
        }
        val showProgress = cfg.optBoolean(
            if (isUpload) "show_upload_progress" else "show_download_progress", true
        )
        val showDone = cfg.optBoolean(
            if (isUpload) "show_upload_done" else "show_download_done", true
        )
        val titleRes = if (isUpload) R.string.sync_pushing else R.string.sync_pulling
        val doneTitleRes = if (isUpload) R.string.sync_upload_done_title else R.string.sync_download_done_title

        val syncProgress = CloudSync.SyncProgress()
        var dialog: AlertDialog? = null
        var inBackground = false
        if (showProgress) {
            val view = layoutInflater.inflate(R.layout.dialog_sync_progress, null)
            view.findViewById<TextView>(R.id.sync_progress_title).text = getString(titleRes)
            val bar = view.findViewById<ProgressBar>(R.id.sync_progress_bar)
            val pct = view.findViewById<TextView>(R.id.sync_progress_pct)
            val file = view.findViewById<TextView>(R.id.sync_progress_file)
            view.findViewById<TextView>(R.id.btn_sync_bg).setOnClickListener {
                inBackground = true
                dialog?.dismiss()
                dialog = null
            }
            syncProgress.onProgress = { p ->
                runOnUiThread {
                    if (inBackground || dialog == null) return@runOnUiThread
                    val percent = if (p.filesTotal > 0) p.done() * 100 / p.filesTotal else 0
                    bar.progress = percent
                    pct.text = "$percent% · ${formatSpeed(p.bytesDone(), p.startTime)}"
                    file.text = p.currentFile
                }
            }
            dialog = AlertDialog.Builder(this)
                .setView(view)
                .setCancelable(false)
                .create()
            dialog?.window?.setBackgroundDrawable(android.graphics.drawable.ColorDrawable(android.graphics.Color.TRANSPARENT))
            dialog?.show()
        }
        syncExecutor.execute {
            try {
                val result = if (isUpload) CloudSync.push(this, syncProgress)
                else CloudSync.pull(this, syncProgress)
                android.util.Log.d(TAG, "quickSync ${if (isUpload) "push" else "pull"} result=$result")
                runOnUiThread {
                    if (!isUpload) reloadData()
                    if (!inBackground && showDone) {
                        dialog?.dismiss()
                        dialog = null
                        showSyncDoneDialog(doneTitleRes, syncSummary(result))
                        return@runOnUiThread
                    }
                    dialog?.dismiss()
                    dialog = null
                    toast(syncSummary(result))
                }
            } catch (e: Exception) {
                android.util.Log.e(TAG, "quickSync ${if (isUpload) "push" else "pull"} failed: $e")
                runOnUiThread {
                    dialog?.dismiss()
                    dialog = null
                    toast(e.message ?: getString(R.string.sync_failed))
                }
            }
        }
    }

    private fun formatSpeed(bytesDone: Long, startTime: Long): String {
        val elapsedSec = (System.currentTimeMillis() - startTime) / 1000.0
        if (elapsedSec <= 0.0) return "0 KB/s"
        val bytesPerSec = bytesDone / elapsedSec
        return if (bytesPerSec >= 1024.0 * 1024.0) {
            String.format("%.1f MB/s", bytesPerSec / 1024.0 / 1024.0)
        } else {
            String.format("%.0f KB/s", bytesPerSec / 1024.0)
        }
    }

    private fun showSyncDoneDialog(titleRes: Int, detail: String) {
        val view = layoutInflater.inflate(R.layout.dialog_sync_done, null)
        view.findViewById<TextView>(R.id.sync_done_title).text = getString(titleRes)
        view.findViewById<TextView>(R.id.sync_done_detail).text = detail
        val dialog = AlertDialog.Builder(this)
            .setView(view)
            .setCancelable(false)
            .create()
        dialog.window?.setBackgroundDrawable(android.graphics.drawable.ColorDrawable(android.graphics.Color.TRANSPARENT))
        view.findViewById<TextView>(R.id.btn_sync_done_close).setOnClickListener { dialog.dismiss() }
        dialog.show()
    }

    private fun syncSummary(r: CloudSync.SyncResult): String {
        val parts = mutableListOf<String>()
        if (r.uploaded > 0) parts.add(getString(R.string.sync_uploaded, r.uploaded))
        if (r.downloaded > 0) parts.add(getString(R.string.sync_downloaded, r.downloaded))
        if (r.skipped > 0) parts.add(getString(R.string.sync_skipped, r.skipped))
        if (r.deleted > 0) parts.add(getString(R.string.sync_deleted, r.deleted))
        if (r.removedLocal > 0) parts.add(getString(R.string.sync_removed_local, r.removedLocal))
        if (r.errors > 0) parts.add(getString(R.string.sync_errors, r.errors))
        return if (parts.isEmpty()) getString(R.string.sync_done) else parts.joinToString("，")
    }

    private fun setupSearch() {
        findViewById<EditText>(R.id.et_search).addTextChangedListener(
            object : android.text.TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}

                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}

                override fun afterTextChanged(s: android.text.Editable?) {
                    currentKeyword = s?.toString() ?: ""
                    reloadData()
                }
            }
        )
    }

    private fun setupBars() {
        findViewById<RecyclerView>(R.id.rv_collections).let { rv ->
            rv.layoutManager = LinearLayoutManager(this, RecyclerView.HORIZONTAL, false)
            rv.adapter = ChipAdapter(emptyList<CollectionEntry>(), emptySet()) { it.name }
        }
        findViewById<RecyclerView>(R.id.rv_tags).let { rv ->
            rv.layoutManager = LinearLayoutManager(this, RecyclerView.HORIZONTAL, false)
            rv.adapter = ChipAdapter(emptyList<String>(), emptySet()) { it }
        }
        findViewById<TextView>(R.id.btn_clear_tags).setOnClickListener {
            activeTags.clear()
            reloadData()
        }
        findViewById<TextView>(R.id.btn_load_more).setOnClickListener {
            currentOffset += PAGE_SIZE
            reloadData(append = true)
        }
    }

    private fun reloadBars() {
        val db = MemeDb.get(this)
        val all = db.getCollections()
        fun buildTree(parentId: Long?): List<CollectionNode> {
            return all
                .filter { c -> if (parentId == null) c.parentId == null || c.parentId == 0L else c.parentId == parentId }
                .map { c ->
                    val kids = buildTree(c.id)
                    CollectionNode(
                        CollectionEntry(c.id, c.name, db.count(collectionId = c.id), kids.isNotEmpty()),
                        kids
                    )
                }
        }
        val top = buildTree(null)
        val activePath = computeActivePath(all)
        val display = mutableListOf<CollectionEntry>()
        val favoritesCount = db.count(favoriteOnly = true)
        if (favoritesCount > 0) {
            display.add(CollectionEntry(COLLECTION_FAVORITES, getString(R.string.collection_favorites), favoritesCount))
        }
        val recentCount = db.getRecent(10000).size
        if (recentCount > 0) {
            display.add(CollectionEntry(COLLECTION_RECENT, getString(R.string.collection_recent), recentCount))
        }
        if (ConfigStore.get(this).optBoolean("show_uncategorized", true)) {
            val uncategorizedCount = db.count(uncategorizedOnly = true)
            if (uncategorizedCount > 0) {
                display.add(
                    CollectionEntry(
                        COLLECTION_UNCATEGORIZED,
                        getString(R.string.collection_uncategorized),
                        uncategorizedCount
                    )
                )
            }
        }
        fun flatten(items: List<CollectionNode>, parentActive: Boolean) {
            items.forEach { node ->
                val entry = node.entry
                display.add(entry)
                if (parentActive || activeCollectionId == entry.id || activePath.contains(entry.id)) {
                    if (node.children.isNotEmpty()) flatten(node.children, activeCollectionId == entry.id)
                }
            }
        }
        flatten(top, false)
        val active = display.firstOrNull { it.id == activeCollectionId }
        if (activeCollectionId != null && active == null) {
            activeCollectionId = null
        }
        val activeSet = display.filter {
            it.id == activeCollectionId || activePath.contains(it.id)
        }.toSet()
        findViewById<RecyclerView>(R.id.rv_collections).let { rv ->
            rv.adapter = ChipAdapter(
                display,
                activeSet
            ) { entry ->
                var label = entry.name
                if (entry.count > 0) label += " (${entry.count})"
                if (entry.hasChildren) label += " \u25BC"
                label
            }.apply {
                onItemClick = { e -> toggleCollection(e) }
                onItemLongClick = { v, e -> showCollectionMenu(v, e) }
            }
        }
    }

    private fun reloadTagBar() {
        val tags = MemeDb.get(this).getAllTags()
        activeTags.retainAll(tags.toSet())
        findViewById<RecyclerView>(R.id.rv_tags).adapter = ChipAdapter(
            tags,
            activeTags
        ) { it }.apply {
            onItemClick = { tag ->
                if (!activeTags.add(tag)) activeTags.remove(tag)
                reloadData()
            }
        }
        findViewById<TextView>(R.id.btn_clear_tags).visibility =
            if (activeTags.isEmpty()) View.GONE else View.VISIBLE
        findViewById<View>(R.id.tagbar_container).visibility =
            if (tags.isEmpty()) View.GONE else View.VISIBLE
    }

    private fun computeActivePath(all: List<MemeDb.Collection>): Set<Long> {
        val path = mutableSetOf<Long>()
        var cur = activeCollectionId ?: return path
        var guard = 0
        while (cur > 0 && guard++ < 16) {
            val parent = all.firstOrNull { it.id == cur }?.parentId
            if (parent == null || parent == 0L) break
            path.add(parent)
            cur = parent
        }
        return path
    }

    private fun showCollectionMenu(anchor: View, entry: CollectionEntry) {
        if (entry.id == COLLECTION_RECENT) {
            showClearRecentMenu(anchor)
            return
        }
        if (entry.id <= 0) return
        val popup = PopupMenu(this, anchor)
        popup.menuInflater.inflate(R.menu.menu_collection, popup.menu)
        popup.menu.findItem(R.id.act_clear_recent).isVisible = false
        popup.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.act_new_subcollection -> promptCreateSubcollection(entry)
                R.id.act_rename_collection -> promptRenameCollection(entry)
                R.id.act_delete_collection -> promptDeleteCollection(entry)
            }
            true
        }
        popup.show()
    }

    private fun showClearRecentMenu(anchor: View) {
        val popup = PopupMenu(this, anchor)
        popup.menuInflater.inflate(R.menu.menu_collection, popup.menu)
        popup.menu.findItem(R.id.act_new_subcollection).isVisible = false
        popup.menu.findItem(R.id.act_rename_collection).isVisible = false
        popup.menu.findItem(R.id.act_delete_collection).isVisible = false
        popup.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.act_clear_recent -> promptClearRecent()
            }
            true
        }
        popup.show()
    }

    private fun promptRenameCollection(entry: CollectionEntry) {
        val input = EditText(this)
        input.setText(entry.name)
        input.hint = getString(R.string.rename_hint)
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.rename_collection_dialog_title))
            .setView(input)
            .setPositiveButton(getString(R.string.ok)) { _, _ ->
                val name = input.text.toString().trim()
                if (name.isEmpty()) {
                    toast(getString(R.string.input_empty))
                    return@setPositiveButton
                }
                executor.execute {
                    val db = MemeDb.get(this)
                    val current = db.getCollections().firstOrNull { it.id == entry.id }
                    val sameParent = current?.let { db.findCollection(name, it.parentId) }
                    if (sameParent != null && sameParent.id != entry.id) {
                        runOnUiThread { toast(getString(R.string.folder_exists)) }
                        return@execute
                    }
                    db.renameCollection(entry.id, name)
                    runOnUiThread {
                        toast(getString(R.string.collection_renamed))
                        reloadData()
                    }
                }
            }
            .setNegativeButton(getString(R.string.cancel), null)
            .show()
    }

    private fun promptDeleteCollection(entry: CollectionEntry) {
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.ctx_delete_collection))
            .setMessage(getString(R.string.delete_collection_confirm_message, entry.name))
            .setPositiveButton(getString(R.string.ok)) { _, _ ->
                executor.execute {
                    val db = MemeDb.get(this)
                    val parentId = db.getCollections().firstOrNull { it.id == entry.id }
                        ?.parentId?.takeIf { it != 0L }
                    val members = db.search(collectionId = entry.id, offset = 0, limit = 10000)
                    for (m in members) {
                        if (parentId != null) db.addToCollection(m.id, parentId)
                    }
                    db.deleteCollection(entry.id)
                    val nextActive = if (activeCollectionId == entry.id) parentId else activeCollectionId
                    runOnUiThread {
                        activeCollectionId = nextActive
                        toast(getString(R.string.collection_deleted))
                        reloadData()
                    }
                }
            }
            .setNegativeButton(getString(R.string.cancel), null)
            .show()
    }

    private fun promptClearRecent() {
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.clear_recent_confirm_title))
            .setMessage(getString(R.string.clear_recent_confirm_message))
            .setPositiveButton(getString(R.string.ok)) { _, _ ->
                executor.execute {
                    MemeDb.get(this).clearRecent()
                    runOnUiThread {
                        if (activeCollectionId == COLLECTION_RECENT) activeCollectionId = null
                        toast(getString(R.string.recent_cleared))
                        reloadData()
                    }
                }
            }
            .setNegativeButton(getString(R.string.cancel), null)
            .show()
    }

    private fun promptCreateSubcollection(entry: CollectionEntry) {
        val db = MemeDb.get(this)
        if (db.getCollectionDepth(entry.id) >= 1) {
            toast(getString(R.string.subcollection_depth_limit))
            return
        }
        val input = EditText(this)
        input.hint = getString(R.string.add_collection_hint)
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.new_subcollection_title))
            .setView(input)
            .setPositiveButton(getString(R.string.ok)) { _, _ ->
                val name = input.text.toString().trim()
                if (name.isEmpty()) {
                    toast(getString(R.string.input_empty))
                    return@setPositiveButton
                }
                executor.execute {
                    MemeDb.get(this).createCollection(name, entry.id)
                    runOnUiThread {
                        toast(getString(R.string.subcollection_created))
                        reloadData()
                    }
                }
            }
            .setNegativeButton(getString(R.string.cancel), null)
            .show()
    }

    private fun toggleCollection(entry: CollectionEntry) {
        activeCollectionId = if (activeCollectionId == entry.id) null else entry.id
        reloadData()
    }

    private fun promptAddToSubgroup(meme: Meme) {
        val targetCol = activeCollectionId ?: return
        if (targetCol <= 0) return
        val db = MemeDb.get(this)
        val children = db.getChildCollections(targetCol)
        val labels = mutableListOf(getString(R.string.new_subcollection_title))
        val ids = mutableListOf<Long?>(-1L)
        children.forEach { child ->
            labels.add(child.name)
            ids.add(child.id)
        }
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.ctx_add_subgroup))
            .setItems(labels.toTypedArray()) { _, which ->
                val pickedId = ids[which]
                if (pickedId == -1L) {
                    promptCreateSubcollectionFor(meme, targetCol)
                } else if (pickedId != null) {
                    executor.execute {
                        MemeDb.get(this).addToCollection(meme.id, pickedId)
                        runOnUiThread {
                            toast(getString(R.string.added_to_collection, labels[which]))
                            reloadData()
                        }
                    }
                }
            }
            .setNegativeButton(getString(R.string.cancel), null)
            .show()
    }

    private fun promptCreateSubcollectionFor(meme: Meme, parentId: Long) {
        val input = EditText(this)
        input.hint = getString(R.string.add_collection_hint)
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.new_subcollection_title))
            .setView(input)
            .setPositiveButton(getString(R.string.ok)) { _, _ ->
                val name = input.text.toString().trim()
                if (name.isEmpty()) {
                    toast(getString(R.string.input_empty))
                    return@setPositiveButton
                }
                executor.execute {
                    val db = MemeDb.get(this)
                    if (db.getCollectionDepth(parentId) >= 1) {
                        runOnUiThread { toast(getString(R.string.subcollection_depth_limit)) }
                        return@execute
                    }
                    val cid = db.createCollection(name, parentId)
                    db.addToCollection(meme.id, cid)
                    runOnUiThread {
                        toast(getString(R.string.added_to_collection, name))
                        reloadData()
                    }
                }
            }
            .setNegativeButton(getString(R.string.cancel), null)
            .show()
    }

    private fun reloadData(append: Boolean = false) {
        if (!append) currentOffset = 0
        reloadBars()
        reloadTagBar()
        val keyword = currentKeyword
        val tags = activeTags.toList()
        val collectionId = activeCollectionId
        val offset = currentOffset
        latestReloadId += 1
        val reloadId = latestReloadId
        executor.execute {
            val db = MemeDb.get(this)
            val favoriteOnly = collectionId == COLLECTION_FAVORITES
            val recentOnly = collectionId == COLLECTION_RECENT
            val uncategorizedOnly = collectionId == COLLECTION_UNCATEGORIZED
            val realCollectionId = collectionId?.takeIf { it > 0 }
            val memes = db.search(
                keyword = keyword,
                tags = tags,
                collectionId = realCollectionId,
                favoriteOnly = favoriteOnly,
                recentOnly = recentOnly,
                uncategorizedOnly = uncategorizedOnly,
                offset = offset,
                limit = PAGE_SIZE
            )
            val total = db.count(
                keyword = keyword,
                tags = tags,
                collectionId = realCollectionId,
                favoriteOnly = favoriteOnly,
                recentOnly = recentOnly,
                uncategorizedOnly = uncategorizedOnly
            )
            android.util.Log.d(TAG, "reloadData got ${memes.size}/$total memes keyword='$keyword'")
            runOnUiThread {
                if (reloadId != latestReloadId) return@runOnUiThread
                currentTotal = total
                displayedMemes = if (append) displayedMemes + memes else memes
                val visibleMemes = displayedMemes
                findViewById<RecyclerView>(R.id.rv_memes).let { rv ->
                    rv.layoutManager = GridLayoutManager(this, ConfigStore.getInt(this, "grid_columns", 3).coerceIn(2, 6))
                    (rv.getTag(R.id.tag_sort_helper) as? ItemTouchHelper)?.attachToRecyclerView(null)
                    rv.setTag(R.id.tag_sort_helper, null)
                    val canOrder = offset == 0 && activeTags.isEmpty() && canOrderCards(keyword, collectionId, visibleMemes.size)
                    val adapter = MemeGridAdapter(this, visibleMemes, canOrder).apply {
                        onItemClick = { _, meme -> onMemeClick(meme) }
                        onMenuClick = { anchor, meme -> showMemeMenu(anchor, meme) }
                        onDragStart = { view, meme -> startGlobalDrag(view, meme) }
                        onDragFailed = { anchor, meme -> showMemeMenu(anchor, meme) }
                    }
                    rv.adapter = adapter
                    val helper = ItemTouchHelper(SortCallback(adapter, collectionId))
                    adapter.onReorderStart = { holder -> helper.startDrag(holder) }
                    helper.attachToRecyclerView(rv)
                    rv.setTag(R.id.tag_sort_helper, helper)
                }
                findViewById<View>(R.id.empty_state).visibility =
                    if (visibleMemes.isEmpty()) View.VISIBLE else View.GONE
                findViewById<TextView>(R.id.tv_page_status).apply {
                    visibility = if (total > PAGE_SIZE) View.VISIBLE else View.GONE
                    text = getString(R.string.page_status, offset + memes.size, total)
                }
                findViewById<TextView>(R.id.btn_load_more).visibility =
                    if (offset + memes.size < total) View.VISIBLE else View.GONE
            }
        }
    }

    private fun showMemeMenu(anchor: View, meme: Meme) {
        val popup = PopupMenu(this, anchor)
        popup.menuInflater.inflate(R.menu.menu_meme, popup.menu)
        val favorited = MemeDb.get(this).isFavorite(meme.id)
        popup.menu.findItem(R.id.act_favorite).setTitle(
            if (favorited) getString(R.string.ctx_unfavorite) else getString(R.string.ctx_favorite)
        )
        popup.menu.findItem(R.id.act_add_subgroup).isVisible =
            activeCollectionId != null && activeCollectionId!! > 0
        popup.menu.findItem(R.id.act_remove_collection).isVisible =
            activeCollectionId != null && activeCollectionId!! > 0
        popup.menu.findItem(R.id.act_remove_recent).isVisible =
            activeCollectionId == COLLECTION_RECENT
        popup.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.act_rename -> promptRename(meme)
                R.id.act_favorite -> toggleFavorite(meme)
                R.id.act_edit_tags -> promptEditTags(meme)
                R.id.act_ai_edit -> promptAiEdit(meme)
                R.id.act_export_pack -> exportPack(listOf(meme.id))
                R.id.act_add_collection -> promptAddCollection(meme)
                R.id.act_put_in_folder -> promptPutInFolder(meme)
                R.id.act_add_subgroup -> promptAddToSubgroup(meme)
                R.id.act_remove_collection -> removeFromCollection(meme)
                R.id.act_remove_recent -> removeFromRecent(meme)
                R.id.act_delete -> confirmDelete(meme)
            }
            true
        }
        popup.show()
    }

    private fun promptEditTags(meme: Meme) {
        executor.execute {
            val db = MemeDb.get(this)
            val allTags = db.getAllTags()
            val selected = db.getMemeTags(meme.id).toMutableSet()
            runOnUiThread {
                val content = LinearLayout(this).apply {
                    orientation = LinearLayout.VERTICAL
                    setPadding(48, 12, 48, 0)
                }
                val input = EditText(this).apply {
                    hint = getString(R.string.tag_dialog_hint)
                    setSingleLine(true)
                }
                content.addView(input)
                val tagList = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
                content.addView(tagList)
                fun renderTags() {
                    tagList.removeAllViews()
                    val display = (allTags + selected).distinct().sorted()
                    if (display.isEmpty()) {
                        tagList.addView(TextView(this).apply {
                            text = getString(R.string.tag_empty)
                            setTextColor(getColor(R.color.muted))
                        })
                    } else {
                        display.forEach { tag ->
                            tagList.addView(CheckBox(this).apply {
                                text = tag
                                isChecked = selected.contains(tag)
                                setOnCheckedChangeListener { _, checked ->
                                    if (checked) selected.add(tag) else selected.remove(tag)
                                }
                            })
                        }
                    }
                }
                renderTags()
                AlertDialog.Builder(this)
                    .setTitle(R.string.tag_dialog_title)
                    .setView(content)
                    .setNeutralButton(R.string.tag_add, null)
                    .setPositiveButton(R.string.ok) { _, _ ->
                        executor.execute {
                            MemeDb.get(this).setMemeTags(meme.id, selected.toList())
                            runOnUiThread {
                                toast(getString(R.string.tags_updated))
                                reloadData()
                            }
                        }
                    }
                    .setNegativeButton(R.string.cancel, null)
                    .create()
                    .also { dialog ->
                        dialog.setOnShowListener {
                            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener {
                                val tag = input.text.toString().trim()
                                if (tag.isNotEmpty()) {
                                    selected.add(tag)
                                    input.text.clear()
                                    renderTags()
                                }
                            }
                        }
                    }
                    .show()
            }
        }
    }

    private fun promptAiEdit(meme: Meme) {
        val input = EditText(this)
        input.hint = getString(R.string.ai_edit_hint)
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.ai_edit_title))
            .setView(input)
            .setPositiveButton(getString(R.string.ok)) { _, _ ->
                val prompt = input.text.toString().trim()
                if (prompt.isEmpty()) {
                    toast(getString(R.string.input_empty))
                    return@setPositiveButton
                }
                executor.execute {
                    try {
                        val file = Thumbnailer.findMemeFile(this, meme.filename)
                            ?: throw IllegalArgumentException(getString(R.string.share_file_missing))
                        val result = AiUtil.edit(file.readBytes(), meme.filename, prompt, ConfigStore.get(this))
                        val imported = MemeImporter.importBytes(
                            this,
                            result,
                            meme.originalName.ifEmpty { meme.filename.substringBeforeLast('.') } + "-AI"
                        )
                        runOnUiThread {
                            toast(getString(if (imported) R.string.ai_imported else R.string.ai_no_results))
                            if (imported) reloadData()
                        }
                    } catch (e: Exception) {
                        runOnUiThread { toast(e.message ?: getString(R.string.ai_processing)) }
                    }
                }
            }
            .setNegativeButton(getString(R.string.cancel), null)
            .show()
    }

    private fun promptRename(meme: Meme) {
        val input = EditText(this)
        input.setText(meme.originalName)
        input.hint = getString(R.string.rename_hint)
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.rename_dialog_title))
            .setView(input)
            .setPositiveButton(getString(R.string.ok)) { _, _ ->
                val name = input.text.toString().trim()
                if (name.isEmpty()) {
                    toast(getString(R.string.input_empty))
                    return@setPositiveButton
                }
                executor.execute {
                    MemeDb.get(this).updateMeme(meme.id, mapOf("original_name" to name))
                    runOnUiThread {
                        toast(getString(R.string.renamed))
                        reloadData()
                    }
                }
            }
            .setNegativeButton(getString(R.string.cancel), null)
            .show()
    }

    private fun toggleFavorite(meme: Meme) {
        executor.execute {
            val db = MemeDb.get(this)
            val nowFavorite = db.toggleFavorite(meme.id)
            val favEmpty = activeCollectionId == COLLECTION_FAVORITES && db.count(favoriteOnly = true) == 0
            runOnUiThread {
                if (favEmpty) activeCollectionId = null
                toast(getString(if (nowFavorite) R.string.favorited else R.string.unfavorited))
                reloadData()
            }
        }
    }

    private fun removeFromCollection(meme: Meme) {
        val cid = activeCollectionId ?: return
        if (cid <= 0) return
        executor.execute {
            val db = MemeDb.get(this)
            db.removeFromCollection(meme.id, cid)
            val parentId = db.getCollections().firstOrNull { it.id == cid }
                ?.parentId?.takeIf { it != 0L }
            if (parentId != null) db.addToCollection(meme.id, parentId)
            val empty = db.count(collectionId = cid) == 0
            if (empty) db.deleteCollection(cid)
            val nextActive = if (empty) parentId else cid
            runOnUiThread {
                activeCollectionId = nextActive
                toast(getString(R.string.removed_from_collection))
                reloadData()
            }
        }
    }

    private fun promptCreateFolder() {
        val input = EditText(this)
        input.hint = getString(R.string.create_folder_hint)
        AlertDialog.Builder(this)
            .setTitle(R.string.create_folder_dialog_title)
            .setView(input)
            .setPositiveButton(R.string.ok) { _, _ ->
                val name = input.text.toString().trim()
                if (name.isEmpty()) {
                    toast(getString(R.string.input_empty))
                    return@setPositiveButton
                }
                executor.execute {
                    val db = MemeDb.get(this)
                    val created = if (db.findCollection(name, null) == null) {
                        db.createCollection(name) > 0
                    } else {
                        false
                    }
                    runOnUiThread {
                        if (created) {
                            toast(getString(R.string.folder_created))
                            reloadData()
                        } else {
                            toast(getString(R.string.folder_exists))
                        }
                    }
                }
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun promptPutInFolder(meme: Meme) {
        executor.execute {
            val folders = MemeDb.get(this).getCollections()
            val names = folders.map { folder ->
                val parent = folder.parentId?.let { pid -> folders.firstOrNull { it.id == pid }?.name }
                if (parent.isNullOrBlank()) folder.name else "$parent / ${folder.name}"
            }.toTypedArray()
            runOnUiThread {
                if (folders.isEmpty()) {
                    toast(getString(R.string.folder_action_empty))
                    return@runOnUiThread
                }
                AlertDialog.Builder(this)
                    .setTitle(R.string.folder_action_title)
                    .setItems(names) { _, which ->
                        promptFolderMode(meme, folders[which])
                    }
                    .setNegativeButton(R.string.cancel, null)
                    .show()
            }
        }
    }

    private fun promptFolderMode(meme: Meme, folder: MemeDb.Collection) {
        AlertDialog.Builder(this)
            .setTitle(folder.name)
            .setItems(arrayOf(getString(R.string.ctx_copy_to_folder), getString(R.string.ctx_move_to_folder))) { _, which ->
                putInFolder(meme, folder, move = which == 1)
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun putInFolder(meme: Meme, folder: MemeDb.Collection, move: Boolean) {
        executor.execute {
            val db = MemeDb.get(this)
            if (move) db.moveToCollection(meme.id, folder.id) else db.addToCollection(meme.id, folder.id)
            val tag = folder.name.trim()
            if (tag.isNotEmpty()) {
                val tags = db.getMemeTags(meme.id)
                if (tags.none { it.equals(tag, ignoreCase = true) }) {
                    db.setMemeTags(meme.id, tags + tag)
                }
            }
            runOnUiThread {
                toast(getString(if (move) R.string.folder_move_done else R.string.folder_copy_done, folder.name))
                reloadData()
            }
        }
    }

    private fun promptAddCollection(meme: Meme) {
        val input = EditText(this)
        input.hint = getString(R.string.add_collection_hint)
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.add_collection_dialog_title))
            .setView(input)
            .setPositiveButton(getString(R.string.ok)) { _, _ ->
                val name = input.text.toString().trim()
                if (name.isEmpty()) {
                    toast(getString(R.string.input_empty))
                    return@setPositiveButton
                }
                executor.execute {
                    val db = MemeDb.get(this)
                    val cid = db.findCollection(name, null)?.id ?: db.createCollection(name)
                    if (cid <= 0) {
                        runOnUiThread { toast(getString(R.string.folder_exists)) }
                        return@execute
                    }
                    db.addToCollection(meme.id, cid)
                    val tags = db.getMemeTags(meme.id)
                    if (tags.none { it.equals(name, ignoreCase = true) }) {
                        db.setMemeTags(meme.id, tags + name)
                    }
                    runOnUiThread {
                        toast(getString(R.string.folder_copy_done, name))
                        reloadData()
                    }
                }
            }
            .setNegativeButton(getString(R.string.cancel), null)
            .show()
    }

    private fun onMemeClick(meme: Meme) {
        recordUse(meme)
        shareMeme(meme)
    }

    private fun shareMeme(meme: Meme) {
        executor.execute {
            val file = Thumbnailer.findMemeFile(this, meme.filename)
            if (file == null) {
                runOnUiThread { toast(getString(R.string.share_file_missing)) }
                return@execute
            }
            try {
                val processed = MemeCopyProcessor.process(this, file)
                val cache = cacheDir
                val shareFile = if (processed != null) {
                    processed.file
                } else {
                    File(cache, "share_${meme.id}_${file.name}").also { file.copyTo(it) }
                }
                val mime = processed?.mimeType ?: meme.mimeType.ifEmpty { "image/*" }
                val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", shareFile)
                runOnUiThread {
                    val share = Intent(Intent.ACTION_SEND).apply {
                        type = mime
                        putExtra(Intent.EXTRA_STREAM, uri)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    startActivity(Intent.createChooser(share, getString(R.string.share_title)))
                }
            } catch (e: Exception) {
                android.util.Log.w(TAG, "share failed for ${meme.filename}: $e")
                runOnUiThread { toast(getString(R.string.share_failed)) }
            }
        }
    }

    private fun recordUse(meme: Meme) {
        executor.execute {
            MemeDb.get(this).recordUse(meme.id)
            val recentEmpty = activeCollectionId == COLLECTION_RECENT && MemeDb.get(this).getRecent(1).isEmpty()
            runOnUiThread {
                if (recentEmpty) activeCollectionId = null
                reloadData()
            }
        }
    }

    private fun removeFromRecent(meme: Meme) {
        executor.execute {
            val db = MemeDb.get(this)
            db.removeFromRecent(meme.id)
            val recentEmpty = activeCollectionId == COLLECTION_RECENT && db.getRecent(1).isEmpty()
            runOnUiThread {
                if (recentEmpty) activeCollectionId = null
                toast(getString(R.string.removed_from_recent))
                reloadData()
            }
        }
    }

    private fun confirmDelete(meme: Meme) {
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.delete_confirm_title))
            .setMessage(getString(R.string.delete_confirm_message, meme.originalName.ifEmpty { meme.filename }))
            .setPositiveButton(getString(R.string.ok)) { _, _ ->
                executor.execute {
                    try {
                        deleteMemeFiles(meme)
                        MemeDb.get(this).deleteMeme(meme.id)
                        runOnUiThread {
                            toast(getString(R.string.deleted))
                            reloadData()
                        }
                    } catch (e: Exception) {
                        runOnUiThread { toast(getString(R.string.delete_failed)) }
                    }
                }
            }
            .setNegativeButton(getString(R.string.cancel), null)
            .show()
    }

    private fun deleteMemeFiles(meme: Meme) {
        Thumbnailer.findMemeFile(this, meme.filename)?.delete()
        StoragePaths.thumbnailDir(this).listFiles()
            .filter { it.name.startsWith("${meme.id}_") }
            .forEach { it.delete() }
    }

    private fun pickImages() {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "image/*"
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
        }
        importLauncher.launch(intent)
    }

    private fun pickPack() {
        packImportLauncher.launch(arrayOf("application/zip", "application/octet-stream"))
    }

    private fun exportPack(memeIds: List<Long>) {
        if (memeIds.isEmpty()) return
        pendingPackExportIds = memeIds
        packExportLauncher.launch("OhMyMeme.ohmymeme-pack")
    }

    private fun exportAllPack() {
        executor.execute {
            val ids = MemeDb.get(this).getAll(limit = 10_000).map { it.id }
            runOnUiThread {
                if (ids.isEmpty()) {
                    toast(getString(R.string.empty_title))
                } else {
                    exportPack(ids)
                }
            }
        }
    }

    private fun doImportPack(uri: Uri) {
        executor.execute {
            val result = MemePack.import(this, uri)
            runOnUiThread {
                if (!result.ok) {
                    toast(result.error ?: getString(R.string.pack_operation_failed))
                    return@runOnUiThread
                }
                toast(getString(R.string.pack_import_done, result.imported, result.skipped))
                if (result.imported > 0) reloadData()
            }
        }
    }

    private fun doExportPack(uri: Uri, memeIds: List<Long>) {
        executor.execute {
            val result = MemePack.export(this, memeIds, uri)
            runOnUiThread {
                if (!result.ok) {
                    toast(result.error ?: getString(R.string.pack_operation_failed))
                    return@runOnUiThread
                }
                toast(getString(R.string.pack_export_done, result.imported))
            }
        }
    }

    private fun showImportMenu(anchor: View) {
        val popup = PopupMenu(this, anchor)
        popup.menuInflater.inflate(R.menu.menu_import, popup.menu)
        popup.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.act_import_files -> pickImages()
                R.id.act_import_album -> pickAlbumImages()
                R.id.act_import_pack -> pickPack()
                R.id.act_import_folder -> folderImportLauncher.launch(null)
                R.id.act_import_qq -> toast(getString(R.string.import_qq_pending))
            }
            true
        }
        popup.show()
    }

    private fun showMoreActionsMenu(anchor: View) {
        val popup = PopupMenu(this, anchor)
        popup.menuInflater.inflate(R.menu.menu_more_actions, popup.menu)
        popup.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.act_overlay -> OverlayMemeService.requestEnable(this)
                R.id.act_export_all_pack -> exportAllPack()
                R.id.act_create_folder -> promptCreateFolder()
                R.id.act_ai_organize -> confirmAiOrganize()
                R.id.act_ai_search -> promptAiSearch()
                R.id.act_ai_generate -> promptAiGenerate()
                R.id.act_sync_push -> quickSync(isUpload = true)
                R.id.act_sync_pull -> quickSync(isUpload = false)
                R.id.act_refresh -> rescanCache()
            }
            true
        }
        popup.show()
    }

    private fun confirmAiOrganize() {
        val batchSize = ConfigStore.getInt(this, "ai_organize_batch_size", 50).coerceIn(1, 500)
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.ai_organize_title))
            .setMessage(getString(R.string.ai_organize_confirm) + "\n\n" + getString(R.string.ai_organize_batch_size) + "：$batchSize")
            .setPositiveButton(getString(R.string.ok)) { _, _ -> runAiOrganize(batchSize) }
            .setNegativeButton(getString(R.string.cancel), null)
            .show()
    }

    private fun runAiOrganize(batchSize: Int) {
        val progress = ProgressBar(this).apply { isIndeterminate = false; max = 100 }
        val progressText = TextView(this).apply {
            setPadding(52, 0, 52, 12)
            setTextColor(getColor(R.color.fg_secondary))
            text = getString(R.string.ai_processing)
        }
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, 20, 0, 0)
            addView(progressText)
            addView(progress, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { setMargins(52, 0, 52, 20) })
        }
        val dialog = AlertDialog.Builder(this)
            .setTitle(R.string.ai_organize_title)
            .setView(content)
            .setCancelable(false)
            .create()
        dialog.show()
        executor.execute {
            try {
                val db = MemeDb.get(this)
                val candidates = db.search(uncategorizedOnly = true, limit = batchSize)
                if (candidates.isEmpty()) {
                    runOnUiThread {
                        dialog.dismiss()
                        toast(getString(R.string.ai_organize_empty))
                    }
                    return@execute
                }
                val cfg = ConfigStore.get(this)
                val suggestions = mutableListOf<AiReviewItem>()
                candidates.forEachIndexed { index, meme ->
                    val file = Thumbnailer.findMemeFile(this, meme.filename)
                    if (file != null) {
                        val suggestion = AiUtil.organize(file.readBytes(), cfg)
                        suggestions.add(
                            AiReviewItem(
                                meme = meme,
                                tags = suggestion.tags.joinToString("、"),
                                collection = suggestion.collection,
                                description = suggestion.description,
                                ocrText = suggestion.ocrText
                            )
                        )
                    }
                    val done = index + 1
                    runOnUiThread {
                        progress.progress = done * 100 / candidates.size
                        progressText.text = getString(R.string.ai_organize_progress, done, candidates.size)
                    }
                }
                runOnUiThread {
                    dialog.dismiss()
                    showAiOrganizeReview(suggestions)
                }
            } catch (e: Exception) {
                runOnUiThread {
                    dialog.dismiss()
                    toast(e.message ?: getString(R.string.ai_processing))
                }
            }
        }
    }

    private fun showAiOrganizeReview(suggestions: List<AiReviewItem>) {
        if (suggestions.isEmpty()) {
            toast(getString(R.string.ai_no_results))
            return
        }
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 0, 48, 0)
        }
        content.addView(TextView(this).apply {
            text = getString(R.string.ai_organize_review_note)
            setTextColor(getColor(R.color.fg_secondary))
            setPadding(0, 0, 0, 12)
        })
        val list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val fields = mutableMapOf<AiReviewItem, List<EditText>>()
        suggestions.forEach { item ->
            val name = item.meme.originalName.ifEmpty { item.meme.filename.substringBeforeLast('.') }
            list.addView(TextView(this).apply {
                text = name
                setTextColor(getColor(R.color.fg))
                setPadding(0, 10, 0, 2)
            })
            fun field(value: String, hint: String, lines: Int = 1): EditText {
                return EditText(this).apply {
                    setText(value)
                    this.hint = hint
                    minLines = lines
                    maxLines = if (lines == 1) 1 else 3
                    setSingleLine(lines == 1)
                    setTextColor(getColor(R.color.fg))
                    setHintTextColor(getColor(R.color.muted))
                    background = getDrawable(R.drawable.bg_input)
                    setPadding(12, 5, 12, 5)
                }
            }
            val itemFields = listOf(
                field(item.tags, getString(R.string.ctx_edit_tags)),
                field(item.collection, getString(R.string.create_folder)),
                field(item.description, "图片描述", 2),
                field(item.ocrText, "图片文字", 2)
            )
            itemFields.forEach { list.addView(it) }
            fields[item] = itemFields
        }
        val scroll = ScrollView(this).apply { addView(list) }
        content.addView(scroll, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            0,
            1f
        ))
        val dialog = AlertDialog.Builder(this)
            .setTitle(R.string.ai_organize_review_title)
            .setView(content)
            .setNegativeButton(R.string.ai_organize_discard, null)
            .setNeutralButton(R.string.cancel, null)
            .setPositiveButton(R.string.ai_organize_apply, null)
            .create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_NEGATIVE).setOnClickListener { dialog.dismiss() }
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener { dialog.dismiss() }
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                fields.forEach { (item, itemFields) ->
                    item.tags = itemFields[0].text.toString().trim()
                    item.collection = itemFields[1].text.toString().trim()
                    item.description = itemFields[2].text.toString().trim()
                    item.ocrText = itemFields[3].text.toString().trim()
                }
                dialog.dismiss()
                applyAiOrganize(suggestions)
            }
        }
        dialog.show()
    }

    private fun applyAiOrganize(suggestions: List<AiReviewItem>) {
        executor.execute {
            val db = MemeDb.get(this)
            suggestions.forEach { item ->
                val tags = item.tags.split(Regex("[、,，]"))
                    .map { it.trim() }
                    .filter { it.isNotEmpty() }
                    .distinct()
                db.setMemeTags(item.meme.id, tags)
                db.updateMeme(
                    item.meme.id,
                    mapOf("ai_description" to item.description, "ai_ocr_text" to item.ocrText)
                )
                if (item.collection.isNotBlank()) {
                    val collection = db.getCollections().firstOrNull { it.name.equals(item.collection, true) }
                    val collectionId = collection?.id ?: db.createCollection(item.collection)
                    if (collectionId > 0) db.addToCollection(item.meme.id, collectionId)
                }
            }
            runOnUiThread {
                toast(getString(R.string.ai_organize_done, suggestions.size))
                reloadData()
            }
        }
    }

    private fun promptAiGenerate() {
        val input = EditText(this)
        input.hint = getString(R.string.ai_generate_hint)
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.ai_generate_title))
            .setView(input)
            .setPositiveButton(getString(R.string.ok)) { _, _ ->
                val prompt = input.text.toString().trim()
                if (prompt.isBlank()) {
                    toast(getString(R.string.input_empty))
                    return@setPositiveButton
                }
                executor.execute {
                    try {
                        val image = AiUtil.generate(prompt, ConfigStore.get(this))
                        val imported = MemeImporter.importBytes(this, image, "AI-$prompt")
                        runOnUiThread {
                            toast(getString(if (imported) R.string.ai_imported else R.string.ai_no_results))
                            if (imported) reloadData()
                        }
                    } catch (e: Exception) {
                        runOnUiThread { toast(e.message ?: getString(R.string.ai_processing)) }
                    }
                }
            }
            .setNegativeButton(getString(R.string.cancel), null)
            .show()
    }

    private fun promptAiSearch() {
        val input = EditText(this)
        input.hint = getString(R.string.ai_search_hint)
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.ai_search_title))
            .setView(input)
            .setPositiveButton(getString(R.string.ok)) { _, _ ->
                val keyword = input.text.toString().trim()
                if (keyword.isBlank()) {
                    toast(getString(R.string.input_empty))
                    return@setPositiveButton
                }
                executor.execute {
                    try {
                        val urls = AiUtil.searchImages(keyword)
                        var imported = 0
                        for (url in urls) {
                            try {
                                if (MemeImporter.importBytes(this, AiUtil.downloadImage(url), keyword)) imported++
                            } catch (_: Exception) {
                            }
                        }
                        runOnUiThread {
                            toast(if (imported > 0) getString(R.string.import_done, imported) else getString(R.string.ai_no_results))
                            if (imported > 0) reloadData()
                        }
                    } catch (e: Exception) {
                        runOnUiThread { toast(e.message ?: getString(R.string.ai_processing)) }
                    }
                }
            }
            .setNegativeButton(getString(R.string.cancel), null)
            .show()
    }

    /** 相册式跨应用拖拽：长按卡片直接拖入聊天软件，SAF 模式先物化到 cacheDir 再经 FileProvider 暴露 */
    private fun startGlobalDrag(itemView: View, meme: Meme) {
        executor.execute {
            val file = materializeDragFile(meme)
            runOnUiThread {
                if (file == null) {
                    toast(getString(R.string.drag_file_missing))
                    return@runOnUiThread
                }
                val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", file)
                val label = meme.originalName.ifEmpty { meme.filename.substringBeforeLast('.') }
                val data = ClipData.newUri(contentResolver, label, uri)
                val shadow = itemView.findViewById<View>(R.id.img_meme) ?: itemView
                itemView.startDragAndDrop(
                    data,
                    View.DragShadowBuilder(shadow),
                    meme,
                    View.DRAG_FLAG_GLOBAL or View.DRAG_FLAG_GLOBAL_URI_READ
                )
                recordUse(meme)
            }
        }
    }

    /** 拖拽源文件物化：真实路径/SAF 统一复制到内部 cacheDir，保证 FileProvider 路径一致 */
    private fun materializeDragFile(meme: Meme): File? {
        return try {
            val stor = Thumbnailer.findMemeFile(this, meme.filename) ?: return null
            val ext = meme.filename.substringAfterLast('.', "img")
            val tmp = File(cacheDir, "drag_${meme.id}_${System.nanoTime()}.$ext")
            stor.copyTo(tmp)
            tmp
        } catch (e: Exception) {
            android.util.Log.w(TAG, "materializeDragFile failed: $e")
            null
        }
    }

    private fun pickAlbumImages() {
        if (ActivityResultContracts.PickVisualMedia.isPhotoPickerAvailable(this)) {
            photoPickerLauncher.launch(
                PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
            )
        } else {
            val intent = Intent(Intent.ACTION_GET_CONTENT).apply {
                type = "image/*"
                putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
            }
            galleryLauncher.launch(intent)
        }
    }

    private fun rescanCache() {
        executor.execute {
            val added = CacheScanner.scan(this)
            runOnUiThread {
                toast(getString(R.string.scan_done, added))
                reloadData()
            }
        }
    }

    private fun handlePickResult(resultCode: Int, data: Intent?) {
        if (resultCode != RESULT_OK || data == null) return
        val uris = mutableListOf<Uri>()
        if (data.clipData != null) {
            for (i in 0 until data.clipData!!.itemCount) {
                data.clipData!!.getItemAt(i).uri?.let { uris.add(it) }
            }
        } else {
            data.data?.let { uris.add(it) }
        }
        if (uris.isEmpty()) return
        doImport(uris)
    }

    private fun doImport(uris: List<Uri>) {
        executor.execute {
            val imported = MemeImporter.importUris(this, uris)
            runOnUiThread {
                toast(getString(R.string.import_done, imported))
                reloadData()
            }
        }
    }

    private fun doImportFolder(uri: Uri) {
        executor.execute {
            val root = DocumentFile.fromTreeUri(this, uri)
            if (root == null || !root.isDirectory) {
                runOnUiThread { toast(getString(R.string.storage_pick_not_writable)) }
                return@execute
            }
            val db = MemeDb.get(this)
            val collectionName = root.name?.trim().orEmpty().ifEmpty { "文件夹导入" }
            val collectionId = db.getOrCreateCollection(collectionName)
            var imported = 0
            var skipped = 0
            fun importFiles(dir: DocumentFile, targetId: Long, targetName: String, depth: Int) {
                dir.listFiles().forEach { child ->
                    if (child.isDirectory) {
                        val childName = child.name?.trim().orEmpty().ifEmpty { targetName }
                        val childId = if (depth == 0) {
                            db.getOrCreateCollection(childName, targetId)
                        } else {
                            targetId
                        }
                        importFiles(child, childId, childName, depth + 1)
                    } else if (child.isFile) {
                        try {
                            val bytes = contentResolver.openInputStream(child.uri)?.use { it.readBytes() }
                            if (bytes == null) {
                                skipped++
                                return@forEach
                            }
                            val meme = MemeImporter.importBytesResult(
                                this,
                                bytes,
                                child.name ?: "未命名"
                            )
                            if (meme == null) {
                                skipped++
                            } else {
                                db.addToCollection(meme.id, targetId)
                                db.setMemeTags(meme.id, db.getMemeTags(meme.id) + targetName)
                                imported++
                            }
                        } catch (e: Exception) {
                            android.util.Log.w(TAG, "folder import failed for ${child.uri}: $e")
                            skipped++
                        }
                    }
                }
            }
            importFiles(root, collectionId, collectionName, 0)
            runOnUiThread {
                toast(getString(R.string.import_folder_done, imported, skipped))
                if (imported > 0) reloadData()
            }
        }
    }

    private fun handlePickDirResult(resultCode: Int, data: Intent?) {
        val uri = data?.data
        if (resultCode == RESULT_OK && uri != null) {
            if (StoragePaths.persistDataTree(this, uri)) {
                StoragePaths.setDataTree(this, uri)
            } else {
                toast(getString(R.string.storage_pick_not_writable))
            }
        }
        StoragePaths.markSetupDone(this)
        ConfigStore.invalidate()
        reloadData()
    }

    private fun toast(msg: String) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
    }

    private inner class SortCallback(
        private val adapter: MemeGridAdapter,
        private val collectionId: Long?
    ) : ItemTouchHelper.Callback() {

        override fun getMovementFlags(
            recyclerView: RecyclerView,
            viewHolder: RecyclerView.ViewHolder
        ): Int = makeMovementFlags(
            ItemTouchHelper.UP or ItemTouchHelper.DOWN or
                ItemTouchHelper.LEFT or ItemTouchHelper.RIGHT,
            0
        )

        override fun onMove(
            recyclerView: RecyclerView,
            viewHolder: RecyclerView.ViewHolder,
            target: RecyclerView.ViewHolder
        ): Boolean {
            adapter.move(viewHolder.bindingAdapterPosition, target.bindingAdapterPosition)
            return true
        }

        override fun onSwiped(viewHolder: RecyclerView.ViewHolder, direction: Int) {}

        override fun isLongPressDragEnabled() = false

        override fun clearView(
            recyclerView: RecyclerView,
            viewHolder: RecyclerView.ViewHolder
        ) {
            super.clearView(recyclerView, viewHolder)
            val ids = adapter.currentIds()
            executor.execute {
                if (collectionId != null && collectionId > 0) {
                    MemeDb.get(this@MainActivity).reorderCollectionMembers(collectionId, ids)
                } else {
                    MemeDb.get(this@MainActivity).reorderMemes(ids)
                }
            }
        }
    }
}
