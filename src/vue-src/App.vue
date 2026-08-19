<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, nextTick } from 'vue'
import { useMemes } from './composables/useMemes'
import { useDragSort } from './composables/useDragSort'
import { useContextMenu, type MenuItem } from './composables/useContextMenu'
import ContextMenu from './components/ContextMenu.vue'
import CollectionTreeNode from './components/CollectionTreeNode.vue'
import ImportMenu from './components/ImportMenu.vue'
import InputDialog from './components/InputDialog.vue'
import Pager from './components/Pager.vue'
import SyncOverlay from './components/SyncOverlay.vue'
import TagEditor from './components/TagEditor.vue'
import UpdateDialog from './components/UpdateDialog.vue'
import type { Meme } from './types'

const { state, setMemes, search, goToPage, setSearch, toggleTag, setActiveCollection, refreshTags, refreshCollections, copyMeme, pasteMemeToChat, setTagbarCollapsed, addToFolder, batchAddToFolder, reorderMemes, canReorder, startNativeDrag, loadInitData } = useMemes()
const ctx = useContextMenu()
const tagEditor = ref<InstanceType<typeof TagEditor> | null>(null)
const updateDialog = ref<InstanceType<typeof UpdateDialog> | null>(null)
const inputDialog = ref<InstanceType<typeof InputDialog> | null>(null)

// 检查更新并弹窗（与原始实现一致）
async function checkUpdateAndPrompt() {
  try {
    const upd = await window.pywebview?.api?.check_update()
    if (upd && upd.has_update) {
      updateDialog.value?.show(upd.current, upd.latest, upd.download_url, upd.notes)
    }
  } catch (_) {}
}

const sortEnabled = ref(false)
const batchMode = ref(false)
const selectedMemeIds = ref(new Set<number>())
const selectedFolderIds = ref(new Set<number>())
const selectedTags = ref(new Set<string>())
const drag = useDragSort(
  () => state.memes,
  setMemes,
  canReorder,
  () => sortEnabled.value,
  reorderMemes,
  () => { showToast('排序保存失败'); search() },
)

const sidebarCollapsed = ref(false)
const dragOver = ref(false)
const folderDropTargetId = ref<number | null>(null)
const draggingMemeIds = ref(new Set<number>())
let dragCounter = 0
let nativeDragActive = false
let dragState: { sx: number; sy: number } | null = null
let updateInterval: ReturnType<typeof setInterval> | null = null

// 启动动画：仅页面首次加载（启动）时播放一次，快捷键呼出不重载页面故不重复播放
const startupAnim = ref(true)
const startupVideoReady = ref(false)
const startupVideoSrc = '/resources/OhMyMeme.mp4'
let startupAnimTimer: ReturnType<typeof setTimeout> | null = null
function dismissStartupAnim() {
  startupAnim.value = false
  if (startupAnimTimer) { clearTimeout(startupAnimTimer); startupAnimTimer = null }
}
onMounted(() => {
  // 兜底：视频加载失败或未触发 ended 时最多 6s 后移除遮罩，避免卡死界面
  startupAnimTimer = setTimeout(dismissStartupAnim, 6000)
})
const gridStyle = computed(() => ({
  gridTemplateColumns: `repeat(auto-fill, minmax(${state.gridScale}px, 1fr))`,
}))

// 根视图展示全部单层文件夹及未归档表情；进入文件夹后只展示其中的表情。
const folderCards = computed(() => {
  if (state.activeCollection !== null || state.searchQuery || state.activeTags.size) return []
  return state.collections.filter((item: any) => item.id > 0)
})

const breadcrumb = computed(() => {
  if (state.activeCollection === null) return []
  const current = state.collections.find((item: any) => item.id === state.activeCollection)
  return current ? [{ id: null, name: '根目录' }, current] : []
})

async function goToAllMemes() {
  // 不依赖可切换的集合选择器：无论当前状态如何都直接回到根视图。
  state.activeCollection = null
  state.searchQuery = ''
  state.activeTags.clear()
  await nextTick()
  await search()
}

function onBreadcrumbClick(id: number | null) {
  if (id === null) goToAllMemes()
}

function onFolderCardClick(folderId: number) {
  if (batchMode.value) {
    toggleFolderSelection(folderId)
    return
  }
  setActiveCollection(folderId)
}

function toggleFolderSelection(folderId: number) {
  const next = new Set(selectedFolderIds.value)
  if (next.has(folderId)) next.delete(folderId)
  else next.add(folderId)
  selectedFolderIds.value = next
}

function toggleTagSelection(tag: string) {
  const next = new Set(selectedTags.value)
  if (next.has(tag)) next.delete(tag)
  else next.add(tag)
  selectedTags.value = next
}

function onFolderCardContext(e: MouseEvent, folderId: number, folderName: string) {
  e.preventDefault()
  e.stopPropagation()
  ctx.show([
    { action: 'rename-folder', label: '重命名文件夹' },
    { action: 'delete-folder', label: '删除文件夹', danger: true },
  ], { folderId, folderName, isFolder: true }, e.clientX, e.clientY)
}

async function handleCopy(meme: Meme) {
  if (ignoreClick) { ignoreClick = false; return }
  if (batchMode.value) {
    toggleMemeSelection(meme.id)
    return
  }
  const ok = await copyMeme(meme.id)
  if (ok) showToast(`${meme.name} 已复制`)
  else showToast('复制失败')
}

function showToast(msg: string) {
  const el = document.getElementById('toast')
  if (!el) return
  el.textContent = msg
  el.classList.add('show')
  setTimeout(() => el.classList.remove('show'), 1600)
}

function onSearchInput(e: Event) {
  const q = (e.target as HTMLInputElement).value
  setSearch(q)
  debounceSearch()
}

let searchTimer: ReturnType<typeof setTimeout>
function debounceSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => search(), 300)
}

function openSettings() {
  try {
    window.pywebview?.api?.open_settings()
  } catch (_) {}
}

type AiReviewSuggestion = {
  id: number
  tags: string[]
  collection: string
  description: string
  ocr_text: string
  tagsText: string
}

const aiReviewOpen = ref(false)
const aiTaskId = ref<string | null>(null)
const aiSuggestions = ref<AiReviewSuggestion[]>([])
const aiReviewMessage = ref('')
const aiReviewProgress = ref(0)
const aiReviewBusy = ref(false)
let aiReviewTimer: ReturnType<typeof setInterval> | null = null

function stopAiReviewPoll() {
  if (aiReviewTimer) {
    clearInterval(aiReviewTimer)
    aiReviewTimer = null
  }
}

async function loadAiSuggestions() {
  if (!aiTaskId.value) return
  const data = await window.pywebview?.api?.get_ai_suggestions(aiTaskId.value)
  aiSuggestions.value = Object.values(data || {}).map((item: any) => ({
    id: Number(item.id),
    tags: Array.isArray(item.tags) ? item.tags : [],
    collection: String(item.collection || ''),
    description: String(item.description || ''),
    ocr_text: String(item.ocr_text || ''),
    tagsText: Array.isArray(item.tags) ? item.tags.join('、') : '',
  }))
}

async function pollAiReviewProgress() {
  if (!aiTaskId.value) return
  const progress = await window.pywebview?.api?.get_ai_progress()
  if (!progress || progress.task_id !== aiTaskId.value) return
  aiReviewProgress.value = Number(progress.progress || 0)
  aiReviewMessage.value = progress.message || ''
  if (progress.status === 'running') return

  stopAiReviewPoll()
  aiReviewBusy.value = false
  if (progress.status === 'done') {
    await loadAiSuggestions()
    aiReviewMessage.value = aiSuggestions.value.length
      ? `已生成 ${aiSuggestions.value.length} 条建议，请确认后应用。`
      : '没有需要补全的表情，或 AI 未生成可用建议。'
    showToast(aiSuggestions.value.length ? 'AI 整理完成，等待审核' : 'AI 整理完成，没有待审核建议')
  } else {
    aiReviewMessage.value = progress.message || (progress.status === 'cancelled' ? 'AI 整理已取消' : 'AI 整理失败')
    showToast(aiReviewMessage.value)
  }
}

async function startAiOrganize() {
  if (aiReviewBusy.value) {
    aiReviewOpen.value = true
    showToast('AI 整理正在进行中')
    return
  }
  const result = await window.pywebview?.api?.ai_organize(state.aiOrganizeBatchSize)
  if (!result?.ok || !result.task_id) {
    showToast('AI 整理启动失败，请检查 AI 设置')
    return
  }
  stopAiReviewPoll()
  aiTaskId.value = String(result.task_id)
  aiSuggestions.value = []
  aiReviewProgress.value = 0
  aiReviewMessage.value = 'AI 正在分析表情；完成后请在这里审核。'
  aiReviewBusy.value = true
  aiReviewOpen.value = true
  await pollAiReviewProgress()
  aiReviewTimer = setInterval(pollAiReviewProgress, 500)
}

function openAiReview() {
  if (!aiTaskId.value && !aiSuggestions.value.length) {
    showToast('当前没有待审核的 AI 建议')
    return
  }
  aiReviewOpen.value = true
}

async function saveAiSuggestion(item: AiReviewSuggestion) {
  if (!aiTaskId.value) return
  const tags = item.tagsText.split(/[、,，]/).map(tag => tag.trim()).filter(Boolean)
  const result = await window.pywebview?.api?.adjust_ai_suggestion(
    aiTaskId.value, item.id, tags, item.collection.trim(), item.description.trim(), item.ocr_text.trim(),
  )
  if (!result?.ok) {
    showToast(result?.error || '保存建议失败')
    return
  }
  item.tags = tags
  item.tagsText = tags.join('、')
}

async function discardAiSuggestions() {
  if (!aiTaskId.value || !aiSuggestions.value.length) return
  if (!window.confirm(`确认丢弃当前 ${aiSuggestions.value.length} 条 AI 建议？不会修改表情库。`)) return
  const result = await window.pywebview?.api?.discard_ai_suggestions(aiTaskId.value)
  if (!result?.ok) {
    showToast(result?.error || '丢弃失败')
    return
  }
  aiSuggestions.value = []
  aiTaskId.value = null
  aiReviewOpen.value = false
  showToast(`已丢弃 ${result.discarded || 0} 条建议`)
}

async function applyAiSuggestions() {
  if (!aiTaskId.value || !aiSuggestions.value.length) return
  if (!window.confirm(`确认把当前 ${aiSuggestions.value.length} 条建议写入标签、文件夹和搜索描述？`)) return
  for (const item of aiSuggestions.value) await saveAiSuggestion(item)
  const result = await window.pywebview?.api?.apply_ai_suggestions(aiTaskId.value)
  if (!result?.ok) {
    showToast(result?.error || '应用失败')
    return
  }
  aiSuggestions.value = []
  aiTaskId.value = null
  aiReviewOpen.value = false
  await Promise.all([search(), refreshTags(), refreshCollections()])
  showToast(`已应用 ${result.applied || 0} 条建议`)
}

async function openFloatingSearch() {
  const result = await window.pywebview?.api?.toggle_floating_window()
  if (!result) showToast('快速搜索窗口启动失败')
}

async function setAiOrganizeBatchSize(value: number) {
  state.aiOrganizeBatchSize = Math.min(500, Math.max(1, Math.round(value) || 50))
  try {
    await window.pywebview?.api?.save_ai_organize_batch_size(state.aiOrganizeBatchSize)
  } catch (_) {}
}

function toggleSidebar() { sidebarCollapsed.value = !sidebarCollapsed.value }

function toggleTagbar() {
  setTagbarCollapsed(!state.tagbarCollapsed)
}

async function setGridScale(value: number) {
  state.gridScale = Math.max(48, Math.min(120, Math.round(value / 4) * 4))
  try {
    await window.pywebview?.api?.save_settings({ grid_scale: state.gridScale })
  } catch (_) {}
}

function toggleSort() {
  if (batchMode.value) return
  sortEnabled.value = !sortEnabled.value
  drag.toggle()
}

function toggleBatchMode() {
  batchMode.value = !batchMode.value
  clearSelection()
}

function toggleMemeSelection(memeId: number) {
  const next = new Set(selectedMemeIds.value)
  if (next.has(memeId)) next.delete(memeId)
  else next.add(memeId)
  selectedMemeIds.value = next
}

function selectCurrentPage() {
  selectedMemeIds.value = new Set(state.memes.map(meme => meme.id))
}

function selectAllFolders() {
  selectedFolderIds.value = new Set(folderCards.value.map((folder: any) => folder.id))
}

function selectAllTags() {
  selectedTags.value = new Set(state.allTags)
}

function clearSelection() {
  selectedMemeIds.value = new Set()
  selectedFolderIds.value = new Set()
  selectedTags.value = new Set()
}

async function favoriteMemeIds(ids: Iterable<number>) {
  const uniqueIds = [...new Set(ids)]
  if (!uniqueIds.length) return false
  const result = await window.pywebview?.api?.batch_set_favorite(uniqueIds, true)
  if (!result?.ok) {
    showToast(result?.error || '收藏失败')
    return false
  }
  await Promise.all([refreshCollections(), search()])
  showToast(`已收藏 ${result.count || uniqueIds.length} 张表情`)
  return true
}

async function favoriteMemes(memes: Meme[]) {
  return favoriteMemeIds(memes.map(meme => meme.id))
}

async function favoriteSelectedMemes() {
  await favoriteMemeIds(selectedMemeIds.value)
}

async function exportMemePack() {
  const ids = selectedMemeIds.value.size
    ? [...selectedMemeIds.value]
    : state.memes.map(meme => meme.id)
  if (!ids.length) {
    showToast('当前没有可导出的表情')
    return
  }
  const scope = selectedMemeIds.value.size ? `已选 ${ids.length} 张` : `当前列表 ${ids.length} 张`
  if (!window.confirm(`导出${scope}表情及其标签、文件夹归属和收藏状态为 OhMyMeme 分享包？`)) return
  const result = await window.pywebview?.api?.export_pack(ids)
  if (!result || result.cancelled) return
  if (!result.ok) {
    showToast(result.error || '分享包导出失败')
    return
  }
  showToast(`已导出分享包：${result.count || ids.length} 张表情`)
}

async function deleteSelectedFolders() {
  const ids = [...selectedFolderIds.value]
  if (!ids.length) return
  if (!window.confirm(`确定删除选中的 ${ids.length} 个文件夹？表情包和标签不会被删除。`)) return
  const result = await window.pywebview?.api?.delete_folders(ids)
  if (!result?.ok) { showToast(result?.error || '文件夹删除失败'); return }
  selectedFolderIds.value = new Set()
  if (state.activeCollection !== null && ids.includes(state.activeCollection)) await goToAllMemes()
  await refreshCollections()
  showToast(`已删除 ${result.deleted || 0} 个文件夹`)
}

async function deleteSelectedTags() {
  const tags = [...selectedTags.value]
  if (!tags.length) return
  if (!window.confirm(`确定删除选中的 ${tags.length} 个标签？只会移除标签关联，不会删除表情包。`)) return
  const result = await window.pywebview?.api?.delete_tags(tags)
  if (!result?.ok) { showToast(result?.error || '标签删除失败'); return }
  for (const tag of tags) state.activeTags.delete(tag)
  selectedTags.value = new Set()
  await Promise.all([refreshTags(), search()])
  showToast(`已删除 ${result.deleted || 0} 个标签`)
}

const importMenu = ref<InstanceType<typeof ImportMenu> | null>(null)

function showImportMenu() {
  importMenu.value?.open()
}

function onImportDone() {
  search()
  refreshTags()
  refreshCollections()
}

const syncOverlay = ref<InstanceType<typeof SyncOverlay> | null>(null)

function syncUpload() {
  syncOverlay.value?.start('sync_push', '上传中', 'show_upload_progress', 'show_upload_done')
}

function syncDownload() {
  syncOverlay.value?.start('sync_pull', '下载中', 'show_download_progress', 'show_download_done')
}

function onSyncDone() {
  search()
  refreshTags()
  refreshCollections()
}

function rescanCache() {
  showToast('缓存刷新中...')
  search()
  refreshCollections()
}

function hideWindow() {
  try { window.pywebview?.api?.hide_window() } catch (_) {}
}

async function onTitlebarMouseDown(e: MouseEvent) {
  if (e.button !== 0) return
  if ((e.target as HTMLElement).closest('.title-btn') || (e.target as HTMLElement).closest('.icon-btn') || (e.target as HTMLElement).closest('.sidebar-toggle')) return
  try {
    const nativeDrag = await window.pywebview?.api?.start_window_drag(e.button + 1, e.screenX, e.screenY)
    if (nativeDrag) return
  } catch (_) {}
  dragState = { sx: e.screenX, sy: e.screenY }
  e.preventDefault()
}

function onWindowMouseMove(e: MouseEvent) {
  if (!dragState) return
  const dx = e.screenX - dragState.sx
  const dy = e.screenY - dragState.sy
  if (dx !== 0 || dy !== 0) {
    try { window.pywebview?.api?.move_window(dx, dy) } catch (_) {}
    dragState.sx = e.screenX
    dragState.sy = e.screenY
  }
}

function onWindowMouseUp() { dragState = null }

function onMemeRightClick(e: MouseEvent, meme: Meme) {
  e.preventDefault()
  e.stopPropagation()
  const items: MenuItem[] = [
    { action: 'rename', label: '重命名' },
    { action: 'favorite', label: meme.favorited ? '取消收藏' : '收藏' },
    { action: 'tag', label: '打标签' },
    { action: 'put-in-folder', label: '放入文件夹' },
    { action: 'paste-to-chat', label: '复制并粘贴（不会发送）' },
  ]
  if (state.activeCollection && state.activeCollection > 0) {
    items.push({ action: 'remove-folder', label: '移出当前文件夹' })
  }
  if (state.activeCollection === -3) {
    items.push({ action: 'remove-recent', label: '从最近使用中删除' })
  }
  items.push({ action: 'delete', label: '删除', danger: true })
  ctx.show(items, { memeId: meme.id, filename: meme.filename, memeName: meme.name, favorited: meme.favorited }, e.clientX, e.clientY)
}

function onFolderRightClick(e: MouseEvent, folderId: number, folderName: string) {
  e.preventDefault()
  e.stopPropagation()
  const items: MenuItem[] = []
  if (folderId === -3) {
    items.push({ action: 'clear-recent', label: '清空最近使用', danger: true })
  } else if (folderId > 0) {
    items.push({ action: 'rename-folder', label: '重命名文件夹' })
    items.push({ action: 'delete-folder', label: '删除文件夹', danger: true })
  }
  ctx.show(items, { folderId, folderName, isFolder: true }, e.clientX, e.clientY)
}

async function onShowSubmenu(_items: any[], x: number, y: number) {
  const folders = state.collections.filter((item: any) => item.id > 0)
  const items: MenuItem[] = [{ action: 'new-folder', label: '新建文件夹并复制' }]
  for (const folder of folders) {
    items.push({ action: `copy-folder-${folder.id}`, label: `复制到：${folder.name}` })
    items.push({ action: `move-folder-${folder.id}`, label: `移动到：${folder.name}` })
  }
  ctx.showSubmenu(items, x, y)
}

async function onCtxAction(action: string) {
  ctx.hide()
  const t = ctx.trigger.value
  switch (action) {
    case 'rename': {
      const name = await inputDialog.value?.open('重命名', t.memeName || '')
      if (name && name !== t.memeName) { await window.pywebview?.api?.rename_meme(t.memeId, name); search() }
      break
    }
    case 'favorite': {
      const ok = await window.pywebview?.api?.toggle_favorite(t.memeId)
      if (ok !== null) {
        await refreshCollections()
        if (!ok && state.activeCollection === -2) {
          const fav = state.collections.find((c: any) => c.id === -2)
          if (!fav || fav.count === 0) setActiveCollection(-4)
        }
        search()
      }
      break
    }
    case 'tag': {
      const tags = await tagEditor.value?.open(t.memeId)
      if (tags === null) break
      await window.pywebview?.api?.set_meme_tags(t.memeId, tags)
      // 同步已激活标签筛选，避免已删除标签继续筛
      refreshTags()
      search()
      break
    }
    case 'put-in-folder': {
      break
    }
    case 'new-folder': {
      const name = await inputDialog.value?.open('新建文件夹', '', '输入文件夹名称')
      if (!name) break
      const created = await window.pywebview?.api?.create_folder(name)
      if (!created?.ok) { showToast(created?.error || '创建文件夹失败'); break }
      const result = await addToFolder(t.memeId, created.id, 'copy')
      if (result?.ok) { await refreshCollections(); await search(); showToast('已复制到新文件夹') }
      else showToast(result?.error || '放入文件夹失败')
      break
    }
    case 'paste-to-chat': {
      const status = await pasteMemeToChat(t.memeId)
      if (status === 'pasted') showToast('已粘贴到聊天输入框，未发送')
      else if (status === 'manual_paste_required') showToast('已复制，请手动粘贴')
      else showToast('复制失败')
      break
    }
    case 'remove-folder': {
      if (state.activeCollection && state.activeCollection > 0) {
        const ok = await window.pywebview?.api?.remove_from_folder(t.memeId, state.activeCollection)
        if (ok) { await refreshCollections(); await search(); showToast('已移出当前文件夹') }
        else showToast('移出文件夹失败')
      }
      break
    }
    case 'remove-recent': {
      await window.pywebview?.api?.remove_from_recent(t.memeId)
      search()
      break
    }
    case 'delete': {
      if (confirm('确定删除这个表情包吗？')) { await window.pywebview?.api?.delete_meme(t.memeId); search(); refreshCollections() }
      break
    }
    case 'rename-folder': {
      const name = await inputDialog.value?.open('重命名文件夹', t.folderName || '')
      if (name && name !== t.folderName) {
        const ok = await window.pywebview?.api?.rename_folder(t.folderId, name)
        if (ok) { await refreshCollections(); showToast('文件夹已重命名') }
        else showToast('重命名失败')
      }
      break
    }
    case 'delete-folder': {
      if (confirm('确定删除文件夹「' + t.folderName + '」？表情包不会被删除。')) {
        const ok = await window.pywebview?.api?.delete_folder(t.folderId)
        if (ok) {
          if (state.activeCollection === t.folderId) setActiveCollection(null)
          await refreshCollections()
          await search()
        } else showToast('删除文件夹失败')
      }
      break
    }
    case 'clear-recent': {
      if (confirm('确定清空最近使用记录吗？')) {
        await window.pywebview?.api?.clear_recent()
        search()
      }
      break
    }
    default:
      if (/^(copy|move)-folder-\d+$/.test(action)) {
        const [, mode, id] = action.match(/^(copy|move)-folder-(\d+)$/) || []
        const result = await addToFolder(t.memeId, Number(id), mode as 'copy' | 'move')
        if (result?.ok) {
          await refreshCollections()
          await search()
          showToast(mode === 'move' ? '已移动到文件夹' : '已复制到文件夹')
        } else showToast(result?.error || '放入文件夹失败')
      } else {
        showToast(`${action} 功能开发中`)
      }
  }
}

const hoverTimers = new Map<number, ReturnType<typeof setTimeout>>()

// 与原始实现一致：auto_play_gif && !hover_to_play 时网格直接播原图；
// hover_to_play 开启时显示缩略图，悬停切原图
function memeSrc(meme: Meme): string {
  if (meme.is_animated && meme.auto_play_gif && !meme.hover_to_play) {
    return `/api/original/${meme.id}/${encodeURIComponent(meme.filename)}`
  }
  return `/api/thumb/${meme.id}/${encodeURIComponent(meme.filename)}`
}

function onCardMouseEnter(meme: Meme) {
  if (!meme.is_animated || !meme.hover_to_play) return
  const timer = setTimeout(() => {
    const img = document.querySelector(`.meme-card[data-meme-id="${meme.id}"] img`) as HTMLImageElement
    if (img) { img.dataset.thumb = img.src; img.src = `/api/original/${meme.id}/${encodeURIComponent(meme.filename)}` }
  }, 150)
  hoverTimers.set(meme.id, timer)
}

function onCardMouseLeave(meme: Meme) {
  const timer = hoverTimers.get(meme.id)
  if (timer) { clearTimeout(timer); hoverTimers.delete(meme.id) }
  if (!meme.is_animated || !meme.hover_to_play) return
  const img = document.querySelector(`.meme-card[data-meme-id="${meme.id}"] img`) as HTMLImageElement
  if (img && img.dataset.thumb) img.src = img.dataset.thumb
}

type DragPreview = {
  meme: Meme
  memeIds: number[]
  count: number
  x: number
  y: number
}

type NativeDragStart = {
  x: number
  y: number
  meme: Meme
  memeIds: number[]
}

const DRAG_THRESHOLD = 8
const DRAG_PREVIEW_OFFSET = 14
let nativeDragStart: NativeDragStart | null = null
const internalDrag = ref<DragPreview | null>(null)
const dragPreviewEl = ref<HTMLElement | null>(null)
const gridWrap = ref<HTMLElement | null>(null)
const folderDropChoice = ref<{ memeIds: number[]; folderId: number; folderName: string } | null>(null)
let dragPreviewFrame = 0
let dragPreviewPoint: { x: number; y: number } | null = null
let autoScrollFrame = 0
let autoScrollPoint: { x: number; y: number } | null = null
let ignoreClick = false

const AUTO_SCROLL_ZONE = 76
const AUTO_SCROLL_MAX_SPEED = 22

function stopDragAutoScroll() {
  if (autoScrollFrame) cancelAnimationFrame(autoScrollFrame)
  autoScrollFrame = 0
  autoScrollPoint = null
}

function updateDragAutoScrollPoint(x: number, y: number) {
  autoScrollPoint = { x, y }
  if (!autoScrollFrame) runDragAutoScroll()
}

function runDragAutoScroll() {
  autoScrollFrame = requestAnimationFrame(() => {
    autoScrollFrame = 0
    const wrap = gridWrap.value
    const point = autoScrollPoint
    if (!internalDrag.value || !wrap || !point) return
    const rect = wrap.getBoundingClientRect()
    let delta = 0
    if (point.y < rect.top + AUTO_SCROLL_ZONE) {
      const depth = Math.min(1, Math.max(0, (rect.top + AUTO_SCROLL_ZONE - point.y) / AUTO_SCROLL_ZONE))
      delta = -Math.ceil(4 + depth * AUTO_SCROLL_MAX_SPEED)
    } else if (point.y > rect.bottom - AUTO_SCROLL_ZONE) {
      const depth = Math.min(1, Math.max(0, (point.y - (rect.bottom - AUTO_SCROLL_ZONE)) / AUTO_SCROLL_ZONE))
      delta = Math.ceil(4 + depth * AUTO_SCROLL_MAX_SPEED)
    }
    if (delta) {
      const before = wrap.scrollTop
      wrap.scrollTop += delta
      if (wrap.scrollTop !== before) updateFolderDropTarget(point.x, point.y)
      runDragAutoScroll()
    }
  })
}

function selectedDragIds(source: Meme): number[] {
  if (!batchMode.value) return [source.id]
  const ids = [...selectedMemeIds.value]
  return ids.length ? ids : [source.id]
}

function onCardPointerDown(e: PointerEvent, meme: Meme, _card: HTMLElement) {
  ignoreClick = false
  if (batchMode.value) {
    if (e.button !== 0) return
    // 未选中时立即选中；已选中时由 click 取消，避免一次点击被两个事件反转两次。
    if (!selectedMemeIds.value.has(meme.id)) {
      toggleMemeSelection(meme.id)
      ignoreClick = true
    }
    const memeIds = selectedDragIds(meme)
    nativeDragStart = { x: e.clientX, y: e.clientY, meme, memeIds }
    return
  }
  if (sortEnabled.value && canReorder()) {
    drag.onPointerDown(e, meme.id, _card)
    return
  }
  if (e.button !== 0) return
  nativeDragStart = { x: e.clientX, y: e.clientY, meme, memeIds: [meme.id] }
}

function updateFolderDropTarget(x: number, y: number) {
  const target = document.elementFromPoint(x, y)?.closest('[data-folder-id]') as HTMLElement | null
  const id = target ? Number(target.dataset.folderId) : null
  const nextId = Number.isFinite(id) ? id : null
  if (folderDropTargetId.value !== nextId) folderDropTargetId.value = nextId
}

function moveDragPreview(x: number, y: number) {
  const preview = dragPreviewEl.value
  if (!preview) return
  preview.style.transform = `translate3d(${x + DRAG_PREVIEW_OFFSET}px, ${y + DRAG_PREVIEW_OFFSET}px, 0) rotate(3deg) scale(1.04)`
}

function onFavoriteDragEnter(e: DragEvent) {
  if (!internalDrag.value) return
  e.preventDefault()
  folderDropTargetId.value = -2
}

function onFavoriteDragLeave(e: DragEvent) {
  const next = e.relatedTarget as Node | null
  if (!next || !(e.currentTarget as HTMLElement).contains(next)) {
    if (folderDropTargetId.value === -2) folderDropTargetId.value = null
  }
}

function onDocPointerMove(e: PointerEvent) {
  if (drag.dragState.memeId) {
    drag.onPointerMove(e)
    return
  }
  if ((!nativeDragStart && !internalDrag.value) || sortEnabled.value) return
  if (!internalDrag.value && nativeDragStart) {
    const dist = Math.hypot(e.clientX - nativeDragStart.x, e.clientY - nativeDragStart.y)
    if (dist <= DRAG_THRESHOLD) return
    // 预览首次渲染即放在当前指针旁，不再使用从卡片或视口坐标补间的动画。
    // 这样不会出现从左上角跳入的闪动。
    internalDrag.value = {
      meme: nativeDragStart.meme,
      memeIds: nativeDragStart.memeIds,
      count: nativeDragStart.memeIds.length,
      x: e.clientX,
      y: e.clientY,
    }
    draggingMemeIds.value = new Set(nativeDragStart.memeIds)
    nativeDragStart = null
    updateDragAutoScrollPoint(e.clientX, e.clientY)
    requestAnimationFrame(() => moveDragPreview(e.clientX, e.clientY))
  } else if (internalDrag.value) {
    updateDragAutoScrollPoint(e.clientX, e.clientY)
    dragPreviewPoint = { x: e.clientX, y: e.clientY }
    if (!dragPreviewFrame) {
      dragPreviewFrame = requestAnimationFrame(() => {
        dragPreviewFrame = 0
        if (!internalDrag.value || !dragPreviewPoint) return
        moveDragPreview(dragPreviewPoint.x, dragPreviewPoint.y)
        updateFolderDropTarget(dragPreviewPoint.x, dragPreviewPoint.y)
      })
    }
  }
  if (!dragPreviewFrame) updateFolderDropTarget(e.clientX, e.clientY)
}

async function onDocPointerUp() {
  if (drag.dragState.memeId) {
    const wasActive = await drag.onPointerUp()
    if (wasActive) ignoreClick = true
    return
  }
  const activeDrag = internalDrag.value
  if (activeDrag) {
    const folderId = folderDropTargetId.value
    const folder = state.collections.find((item: any) => item.id === folderId)
    if (folderId === -2) {
      await favoriteMemeIds(activeDrag.memeIds)
    } else if (folderId && folder) {
      folderDropChoice.value = { memeIds: activeDrag.memeIds, folderId, folderName: folder.name }
    }
    stopDragAutoScroll()
    if (dragPreviewFrame) cancelAnimationFrame(dragPreviewFrame)
    dragPreviewFrame = 0
    dragPreviewPoint = null
    internalDrag.value = null
    folderDropTargetId.value = null
    draggingMemeIds.value = new Set()
    ignoreClick = true
  }
  nativeDragStart = null
}

async function finishFolderDrop(mode: 'copy' | 'move') {
  const choice = folderDropChoice.value
  if (!choice) return
  folderDropChoice.value = null
  const result = await batchAddToFolder(choice.memeIds, choice.folderId, mode)
  if (!result?.ok) {
    showToast(result?.error || '放入文件夹失败')
    return
  }
  await Promise.all([refreshCollections(), refreshTags()])
  await search()
  const action = mode === 'copy' ? '复制到' : '移动到'
  showToast(`已${action}「${choice.folderName}」${result.count || choice.memeIds.length} 张`)
}

function cancelFolderDrop() {
  folderDropChoice.value = null
}

function onFolderDragOver(e: DragEvent, folderId: number) {
  if (!e.dataTransfer?.types.includes('Files')) return
  e.preventDefault()
  e.stopPropagation()
  e.dataTransfer.dropEffect = 'copy'
  folderDropTargetId.value = folderId
}

function onFolderDragLeave(e: DragEvent, folderId: number) {
  const next = e.relatedTarget as Node | null
  if (!next || !(e.currentTarget as HTMLElement).contains(next)) {
    if (folderDropTargetId.value === folderId) folderDropTargetId.value = null
  }
}

async function onFolderDrop(e: DragEvent, folderId: number) {
  e.preventDefault()
  e.stopPropagation()
  folderDropTargetId.value = null
  const files = Array.from(e.dataTransfer?.files || [])
  if (!files.length) return
  // 文件从系统拖入文件夹时按原有导入链路处理；导入成功后会刷新文件夹列表。
  await onDrop(e)
}

function onDocPointerCancel() {
  if (drag.dragState.memeId) drag.cancel()
  stopDragAutoScroll()
  if (dragPreviewFrame) cancelAnimationFrame(dragPreviewFrame)
  dragPreviewFrame = 0
  dragPreviewPoint = null
  nativeDragStart = null
  internalDrag.value = null
  folderDropTargetId.value = null
  draggingMemeIds.value = new Set()
}

function onDragEnter(e: DragEvent) {
  e.preventDefault()
  if (nativeDragActive) return
  dragCounter++
  dragOver.value = true
}

function onDragOver(e: DragEvent) {
  e.preventDefault()
  if (nativeDragActive) return
}

function onDragLeave(e: DragEvent) {
  e.preventDefault()
  if (nativeDragActive) return
  dragCounter--
  if (dragCounter <= 0) { dragCounter = 0; dragOver.value = false }
}

async function onDrop(e: DragEvent) {
  e.preventDefault()
  if (nativeDragActive) { dragCounter = 0; dragOver.value = false; return }
  dragCounter = 0
  dragOver.value = false
  const dt = e.dataTransfer
  if (!dt) return
  let uri = ''
  let file: File | null = null
  if (!uri) { try { uri = dt.getData('text/uri-list') || '' } catch (_) {} }
  if (!uri) { try { uri = dt.getData('text/plain') || '' } catch (_) {} }
  uri = uri.trim()
  if (!uri) {
    try {
      if (dt.items?.length) {
        for (let i = 0; i < dt.items.length; i++) {
          const item = dt.items[i]
          if (item.kind === 'string' && item.type === 'text/html') {
            const html = await new Promise<string>(res => item.getAsString(res))
            if (!html) continue
            const text = html.replace(/<[^>]+>/g, '').trim()
            if (text.startsWith('file://')) { uri = text; break }
          }
        }
      }
    } catch (_) {}
  }
  if (!uri) { try { if (dt.files?.length) file = dt.files[0] } catch (_) {} }
  if (!uri && !file) {
    try {
      if (dt.items?.length) {
        for (let i = 0; i < dt.items.length; i++) {
          const it = dt.items[i]
          if (it.kind === 'file') { file = it.getAsFile(); if (file) break }
        }
      }
    } catch (_) {}
  }
  if (uri) {
    try { const r = await window.pywebview?.api?.download_original_image(uri); if (r?.ok) { showToast('导入成功'); search(); refreshCollections(); return } } catch (_) {}
  }
  if (file) {
    try {
      const b64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve((reader.result as string).split(',')[1])
        reader.onerror = () => reject(reader.error)
        reader.readAsDataURL(file!)
      })
      const res = await fetch('/api/upload/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ files: [{ name: file.name, data: b64 }] }) })
      if (res.ok) { showToast('导入成功'); search(); refreshCollections() }
    } catch (_) {}
  }
}

// ESC：有右键菜单时先关菜单，否则隐藏窗口
function onDocKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (ctx.visible.value) { ctx.hide(); return }
  if (aiReviewOpen.value) { aiReviewOpen.value = false; return }
  hideWindow()
}

onMounted(() => {
  document.addEventListener('dragenter', onDragEnter)
  document.addEventListener('dragover', onDragOver)
  document.addEventListener('dragleave', onDragLeave)
  document.addEventListener('drop', onDrop)
  document.addEventListener('mousemove', onWindowMouseMove)
  document.addEventListener('mouseup', onWindowMouseUp)
  document.addEventListener('pointermove', onDocPointerMove)
  document.addEventListener('pointerup', onDocPointerUp)
  document.addEventListener('pointercancel', onDocPointerCancel)
  document.addEventListener('keydown', onDocKeydown)
  window.addEventListener('blur', onDocPointerCancel)
})

onUnmounted(() => {
  document.removeEventListener('dragenter', onDragEnter)
  document.removeEventListener('dragover', onDragOver)
  document.removeEventListener('dragleave', onDragLeave)
  document.removeEventListener('drop', onDrop)
  document.removeEventListener('mousemove', onWindowMouseMove)
  document.removeEventListener('mouseup', onWindowMouseUp)
  document.removeEventListener('pointermove', onDocPointerMove)
  document.removeEventListener('pointerup', onDocPointerUp)
  document.removeEventListener('pointercancel', onDocPointerCancel)
  document.removeEventListener('keydown', onDocKeydown)
  window.removeEventListener('blur', onDocPointerCancel)
  if (updateInterval) { clearInterval(updateInterval); updateInterval = null }
  stopAiReviewPoll()
  stopDragAutoScroll()
  hoverTimers.forEach(t => clearTimeout(t))
  hoverTimers.clear()
})

;(async () => {
  await loadInitData()
  // 动画开启时：播放期间即加载后续内容（动画天然覆盖桥接稳定时间），去除 300ms 延时；
  // 动画关闭时：不播放动画，降级为 300ms 延时
  const runBackground = async () => {
    await window.pywebview?.api?.rescan_cache()
    await window.pywebview?.api?.run_auto_sync()
    await search()
    await refreshTags()
    await refreshCollections()
  }
  if (state.showStartupAnimation) {
    // 启动遮罩背景贴合视频边缘色（含 html/body 首次渲染）
    document.documentElement.style.background = state.startupBgColor
    document.body.style.background = state.startupBgColor
    startupVideoReady.value = true
    runBackground()
  } else {
    dismissStartupAnim()
    setTimeout(runBackground, 300)
  }
  // 每日更新检测（完整弹窗 + 下载安装，与原始实现一致）
  await checkUpdateAndPrompt()
  updateInterval = setInterval(checkUpdateAndPrompt, 24 * 60 * 60 * 1000)
})()
</script>

<template>
  <div id="app">
    <header id="titlebar" @mousedown="onTitlebarMouseDown">
      <div class="titlebar__left">
        <div class="logo">OhMy<span>Meme</span></div>
        <button class="icon-btn floating-search-btn" title="打开独立快速搜索悬浮窗" @click="openFloatingSearch()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="6"/><path d="m20 20-4.2-4.2"/></svg>
        </button>
      </div>
      <span class="spacer"></span>
      <div class="titlebar__actions">
        <button class="title-btn primary-action" @click="showImportMenu()">导入</button>
        <button class="title-btn" :class="{ 'batch-on': batchMode }" @click="toggleBatchMode">{{ batchMode ? '完成选择' : '批量选择' }}</button>
        <details class="toolbar-menu more-menu" @mousedown.stop>
          <summary class="icon-btn" title="更多工具与显示选项">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="5" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="19" cy="12" r="1" fill="currentColor"/></svg>
          </summary>
          <div class="toolbar-popover more-popover">
            <div class="toolbar-popover__section">
              <strong>显示与排序</strong>
              <div class="toolbar-popover__row">
                <label for="grid-scale">图标大小 <b>{{ state.gridScale }}px</b></label>
                <input id="grid-scale" type="range" min="48" max="120" step="4" :value="state.gridScale" @input="setGridScale(Number(($event.target as HTMLInputElement).value))">
              </div>
              <button class="toolbar-popover__button" @click="toggleTagbar">{{ state.tagbarCollapsed ? '展开标签栏' : '折叠标签栏' }}</button>
              <button class="toolbar-popover__button" :class="{ active: sortEnabled }" @click="toggleSort">{{ sortEnabled ? '退出排序模式' : '进入排序模式' }}</button>
            </div>
            <div class="toolbar-popover__section">
              <strong>AI 整理</strong>
              <div class="toolbar-popover__row">
                <label for="ai-organize-batch-size">本次审核数量 <b>{{ state.aiOrganizeBatchSize }} 张</b></label>
                <input id="ai-organize-batch-size" type="number" min="1" max="500" step="1" :value="state.aiOrganizeBatchSize" @change="setAiOrganizeBatchSize(Number(($event.target as HTMLInputElement).value))">
              </div>
              <p class="toolbar-popover__hint">最多 500 张；数量越多，处理和审核时间越长。</p>
              <button class="toolbar-popover__button" @click="startAiOrganize()">开始 AI 整理</button>
              <button class="toolbar-popover__button" :disabled="!aiTaskId && !aiSuggestions.length" @click="openAiReview">打开 AI 审核</button>
            </div>
            <div class="toolbar-popover__section toolbar-popover__split-actions">
              <button class="toolbar-popover__button" @click="syncUpload">上传同步</button>
              <button class="toolbar-popover__button" @click="syncDownload">下载同步</button>
              <button class="toolbar-popover__button" @click="exportMemePack">导出当前列表为分享包</button>
              <button class="toolbar-popover__button" @click="rescanCache">刷新图库</button>
            </div>
          </div>
        </details>
        <button class="icon-btn" title="设置" @click="openSettings">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.1 2.1-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.56v.1h-3v-.1A1.7 1.7 0 0 0 10.7 18.64a1.7 1.7 0 0 0-1.88.34l-.06.06-2.1-2.1.06-.06A1.7 1.7 0 0 0 7.06 15 1.7 1.7 0 0 0 5.5 14H5.4v-3h.1a1.7 1.7 0 0 0 1.56-1.03 1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.1-2.1.06.06a1.7 1.7 0 0 0 1.88.34A1.7 1.7 0 0 0 11.73 4.8v-.1h3v.1a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.88-.34l.06-.06 2.1 2.1-.06.06a1.7 1.7 0 0 0-.34 1.88A1.7 1.7 0 0 0 21 11h.1v3H21A1.7 1.7 0 0 0 19.4 15Z"/></svg>
        </button>
        <button class="title-btn close-btn" title="隐藏窗口" @click="hideWindow">×</button>
      </div>
    </header>

    <div id="content">
      <aside id="sidebar" :class="{ collapsed: sidebarCollapsed }">
        <div id="sidebar-header"><span v-if="!sidebarCollapsed">分组</span></div>
        <div id="tree">
          <CollectionTreeNode
            v-for="c in state.collections"
            :key="c.id"
            :node="c"
            :active-id="state.activeCollection"
            :depth="0"
            :collapsed="sidebarCollapsed"
            :drop-target-id="folderDropTargetId"
            @select="setActiveCollection"
            @folder-context="onFolderRightClick"
            @favorite-drag-enter="onFavoriteDragEnter"
            @favorite-drag-leave="onFavoriteDragLeave"
          />
        </div>
      </aside>

      <div id="main">
        <div id="search-wrap">
          <button class="sidebar-toggle" :class="{ collapsed: sidebarCollapsed }" @click="toggleSidebar" title="折叠/展开侧边栏">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
            </svg>
          </button>
          <input id="search" type="text" placeholder="搜索表情包..." :value="state.searchQuery" @input="onSearchInput" autofocus spellcheck="false">
        </div>

        <div v-if="batchMode" id="batchbar">
          <span class="batchbar-summary">已选：表情 {{ selectedMemeIds.size }} · 文件夹 {{ selectedFolderIds.size }} · 标签 {{ selectedTags.size }}</span>
          <div class="batchbar-actions">
            <button class="tagbar-toggle" @click="selectCurrentPage">全选当前页表情</button>
            <button class="tagbar-toggle" :disabled="selectedMemeIds.size === 0" @click="favoriteSelectedMemes">收藏选中表情</button>
            <button class="tagbar-toggle" @click="exportMemePack">导出分享包</button>
            <button class="tagbar-toggle" @click="selectAllFolders">全选文件夹</button>
            <button class="tagbar-toggle" @click="selectAllTags">全选标签</button>
            <button class="tagbar-toggle danger" :disabled="selectedFolderIds.size === 0" @click="deleteSelectedFolders">删除文件夹</button>
            <button class="tagbar-toggle danger" :disabled="selectedTags.size === 0" @click="deleteSelectedTags">删除标签</button>
            <button class="tagbar-toggle" :disabled="selectedMemeIds.size + selectedFolderIds.size + selectedTags.size === 0" @click="clearSelection">取消全选</button>
          </div>
        </div>

        <div id="tagbar" :class="{ collapsed: state.tagbarCollapsed }">
          <button class="tagbar-toggle" @click="toggleTagbar" :title="state.tagbarCollapsed ? '展开标签栏' : '折叠标签栏'">
            {{ state.tagbarCollapsed ? '展开标签' : '收起标签' }}
          </button>
          <template v-if="!state.tagbarCollapsed">
            <span v-for="tag in state.allTags" :key="tag" class="tag" :class="{ active: state.activeTags.has(tag), selected: batchMode && selectedTags.has(tag) }" @click="batchMode ? toggleTagSelection(tag) : toggleTag(tag)">{{ tag }}</span>
          </template>
        </div>

        <nav v-if="state.activeCollection !== null" id="breadcrumb" aria-label="文件夹路径">
          <button class="crumb crumb-home" @click="goToAllMemes">← 根目录</button>
          <span class="crumb-sep">›</span>
          <span class="crumb-path">文件夹 / {{ breadcrumb[breadcrumb.length - 1]?.name || '当前文件夹' }}</span>
        </nav>

        <div ref="gridWrap" id="grid-wrap">
          <div v-if="folderCards.length" class="meme-grid folder-grid" :style="gridStyle">
            <div
              v-for="child in folderCards"
              :key="'folder-' + child.id"
              class="meme-card folder-card"
              :class="{ 'drop-target': folderDropTargetId === child.id, 'selected': batchMode && selectedFolderIds.has(child.id) }"
              :data-folder-id="child.id"
              @click="onFolderCardClick(child.id)"
              @contextmenu="onFolderCardContext($event, child.id, child.name)"
              @dragover="onFolderDragOver($event, child.id)"
              @dragleave="onFolderDragLeave($event, child.id)"
              @drop="onFolderDrop($event, child.id)"
            >
              <div class="folder-preview">
                <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="var(--accent)" stroke-width="1.5"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                <span class="folder-name">{{ child.name }}</span>
              </div>
            </div>
          </div>

          <TransitionGroup
            id="meme-grid"
            tag="div"
            name="meme-list"
            class="meme-grid"
            :class="{ 'sort-enabled': sortEnabled && canReorder() }"
            :style="gridStyle"
          >
            <div
              v-for="meme in state.memes"
              :key="meme.id"
              class="meme-card"
              :class="{
                'dragging': drag.dragState.active && drag.dragState.memeId === meme.id,
                'native-dragging': draggingMemeIds.has(meme.id),
                'selected': batchMode && selectedMemeIds.has(meme.id),
              }"
              :data-meme-id="meme.id"
              @click="handleCopy(meme)"
              @contextmenu="onMemeRightClick($event, meme)"
              @pointerdown="onCardPointerDown($event, meme, $event.currentTarget as HTMLElement)"
              @mouseenter="onCardMouseEnter(meme)"
              @mouseleave="onCardMouseLeave(meme)"
            >
              <img :src="memeSrc(meme)" :alt="meme.name" loading="lazy">
              <span v-if="batchMode" class="selection-check">{{ selectedMemeIds.has(meme.id) ? '✓' : '' }}</span>
              <span v-if="meme.from_stego" class="gif-badge stego-badge">隐写导入</span>
              <span v-else-if="meme.is_animated" class="gif-badge">{{ meme.is_gif ? 'GIF' : 'WebP' }}</span>
              <span class="meme-name">{{ meme.name }}</span>
            </div>
          </TransitionGroup>

          <div v-if="state.memes.length === 0 && !state.loading" id="empty">
            <div class="icon">_(:3 」∠)_</div>
            <div class="text">还没有表情包，点击「导入」添加</div>
          </div>

          <Pager
            v-if="state.pageCount > 1"
            :page="state.page"
            :page-count="state.pageCount"
            @go="goToPage"
          />
        </div>
      </div>
    </div>
  </div>

  <ImportMenu ref="importMenu" @imported="onImportDone" />
  <SyncOverlay ref="syncOverlay" @synced="onSyncDone" />
  <TagEditor ref="tagEditor" />
  <UpdateDialog ref="updateDialog" />
  <InputDialog ref="inputDialog" />
  <ContextMenu
    :visible="ctx.visible.value" :x="ctx.x.value" :y="ctx.y.value"
    :items="ctx.items.value" :trigger="ctx.trigger.value"
    :submenu-visible="ctx.submenuVisible.value" :submenu-items="ctx.submenuItems.value"
    :submenu-x="ctx.submenuX.value" :submenu-y="ctx.submenuY.value"
    @action="onCtxAction" @close="ctx.hide"
    @show-submenu="onShowSubmenu"
  />

  <div
    v-if="internalDrag"
    ref="dragPreviewEl"
    id="meme-drag-preview"
    :style="{
      transform: `translate3d(${internalDrag.x + DRAG_PREVIEW_OFFSET}px, ${internalDrag.y + DRAG_PREVIEW_OFFSET}px, 0) rotate(3deg) scale(1.04)`,
    }"
  >
    <img :src="memeSrc(internalDrag.meme)" :alt="internalDrag.meme.name">
    <span>{{ internalDrag.count > 1 ? `已选 ${internalDrag.count} 张表情` : internalDrag.meme.name }}</span>
  </div>

  <div v-if="folderDropChoice" class="folder-drop-dialog-overlay" @click.self="cancelFolderDrop">
    <div class="folder-drop-dialog">
      <div class="folder-drop-dialog__title">放入「{{ folderDropChoice.folderName }}」</div>
      <p>复制会保留原位置；移动会从原位置移除，并自动附加同名标签。</p>
      <div class="folder-drop-dialog__actions">
        <button class="btn btn-secondary" @click="cancelFolderDrop">取消</button>
        <button class="btn btn-secondary" @click="finishFolderDrop('copy')">复制进去</button>
        <button class="btn btn-primary" @click="finishFolderDrop('move')">移动进去</button>
      </div>
    </div>
  </div>

  <div v-if="aiReviewOpen" class="ai-review-overlay" @click.self="aiReviewOpen = false">
    <section class="ai-review-dialog" role="dialog" aria-modal="true" aria-label="AI 整理审核">
      <header class="ai-review-header">
        <div>
          <h2>AI 整理审核</h2>
          <p>确认应用前不会修改表情库。你可以先调整每条建议。</p>
        </div>
        <button class="icon-btn" title="关闭审核" @click="aiReviewOpen = false">×</button>
      </header>

      <div v-if="aiReviewBusy" class="ai-review-progress">
        <div class="ai-review-progress__line"><span>{{ aiReviewMessage }}</span><strong>{{ aiReviewProgress }}%</strong></div>
        <div class="ai-review-progress__track"><i :style="{ width: aiReviewProgress + '%' }"></i></div>
      </div>
      <p v-else class="ai-review-status">{{ aiReviewMessage || '等待 AI 整理任务开始。' }}</p>

      <div v-if="!aiReviewBusy && aiSuggestions.length" class="ai-review-list">
        <article v-for="item in aiSuggestions" :key="item.id" class="ai-review-card">
          <div class="ai-review-id">表情 #{{ item.id }}</div>
          <div class="ai-review-fields">
            <input v-model="item.tagsText" @change="saveAiSuggestion(item)" placeholder="标签，以顿号或逗号分隔">
            <input v-model="item.collection" @change="saveAiSuggestion(item)" placeholder="建议文件夹">
            <input v-model="item.description" @change="saveAiSuggestion(item)" placeholder="图片描述（用于搜索）">
            <input v-model="item.ocr_text" @change="saveAiSuggestion(item)" placeholder="图片文字（用于搜索）">
          </div>
        </article>
      </div>

      <footer class="ai-review-actions">
        <button class="btn btn-secondary" @click="aiReviewOpen = false">稍后审核</button>
        <button v-if="!aiReviewBusy && aiSuggestions.length" class="btn btn-secondary" @click="discardAiSuggestions">全部丢弃</button>
        <button v-if="!aiReviewBusy && aiSuggestions.length" class="btn btn-primary" @click="applyAiSuggestions">确认应用</button>
      </footer>
    </section>
  </div>

  <div id="drop-overlay" :class="{ 'drag-over': dragOver }">
    <div class="drop-content">
      <div class="drop-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>
      </div>
      <div class="drop-text">拖放图片到此处导入</div>
    </div>
  </div>

  <div id="toast"></div>
  <div id="loading"><div class="spinner"></div></div>

  <Transition name="startup-fade">
    <div v-if="startupAnim" id="startup-anim" :style="{ background: state.startupBgColor }">
      <video v-if="startupVideoReady" :src="startupVideoSrc" autoplay muted playsinline @ended="dismissStartupAnim"></video>
    </div>
  </Transition>
</template>
