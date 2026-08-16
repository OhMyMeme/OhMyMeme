<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
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

const { state, setMemes, search, goToPage, setSearch, toggleTag, setActiveCollection, refreshTags, refreshCollections, copyMeme, pasteMemeToChat, setTagbarCollapsed, addToFolder, reorderMemes, canReorder, startNativeDrag, loadInitData } = useMemes()
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
const nativeDraggingMemeId = ref<number | null>(null)
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

// 根视图展示全部单层文件夹；进入文件夹后只展示其中的表情。
const folderCards = computed(() => {
  if (state.activeCollection !== null || state.searchQuery || state.activeTags.size) return []
  return state.collections.filter((item: any) => item.id > 0)
})

const breadcrumb = computed(() => {
  if (state.activeCollection === null) return []
  const current = state.collections.find((item: any) => item.id === state.activeCollection)
  return current ? [{ id: null, name: '全部' }, current] : []
})

function goToAllMemes() {
  if (state.activeCollection !== null) setActiveCollection(null)
}

function onBreadcrumbClick(id: number | null) {
  if (id === null) goToAllMemes()
}

function onFolderCardClick(folderId: number) {
  setActiveCollection(folderId)
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

async function startAiOrganize() {
  const result = await window.pywebview?.api?.ai_organize(50)
  showToast(result?.ok ? 'AI 整理已开始，结果将在旧版 AI 面板审核后应用' : 'AI 整理启动失败，请检查设置')
}

async function openFloatingSearch() {
  const result = await window.pywebview?.api?.toggle_floating_window()
  if (!result) showToast('快速搜索窗口启动失败')
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
  selectedMemeIds.value = new Set()
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

function clearSelection() {
  selectedMemeIds.value = new Set()
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

let nativeDragStart: { x: number; y: number; memeId: number } | null = null
let ignoreClick = false

function onCardPointerDown(e: PointerEvent, meme: Meme, card: HTMLElement) {
  ignoreClick = false
  if (batchMode.value) return
  if (sortEnabled.value && canReorder()) {
    drag.onPointerDown(e, meme.id, card)
    return
  }
  if (e.button !== 0) return
  nativeDragStart = { x: e.clientX, y: e.clientY, memeId: meme.id }
}

function onDocPointerMove(e: PointerEvent) {
  if (drag.dragState.memeId) {
    drag.onPointerMove(e)
    return
  }
  if (!nativeDragStart || sortEnabled.value) return
  const dist = Math.hypot(e.clientX - nativeDragStart.x, e.clientY - nativeDragStart.y)
  if (dist > 8) {
    const id = nativeDragStart.memeId
    nativeDragStart = null
    // 原生拖拽进行中置标志，回拖到窗口视为取消（不触发 drop 导入）
    nativeDragActive = true
    nativeDraggingMemeId.value = id
    startNativeDrag(id).then((ok) => {
      nativeDragActive = false
      nativeDraggingMemeId.value = null
      ignoreClick = true
      if (!ok) showToast('拖拽失败：本地文件不存在')
    }).catch(() => {
      nativeDragActive = false
      nativeDraggingMemeId.value = null
    })
  }
}

async function onDocPointerUp(e: PointerEvent) {
  if (drag.dragState.memeId) {
    const wasActive = await drag.onPointerUp()
    if (wasActive) ignoreClick = true
    return
  }
  nativeDragStart = null
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
  nativeDragStart = null
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
      </div>
      <span class="spacer"></span>
      <div class="titlebar__actions">
        <details class="toolbar-menu" @mousedown.stop>
          <summary class="icon-btn" title="界面布局与显示选项">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/><circle cx="9" cy="7" r="1.5" fill="currentColor"/><circle cx="15" cy="12" r="1.5" fill="currentColor"/><circle cx="11" cy="17" r="1.5" fill="currentColor"/></svg>
          </summary>
          <div class="toolbar-popover">
            <div class="toolbar-popover__row">
              <label for="grid-scale">图标大小 <strong>{{ state.gridScale }}px</strong></label>
              <input id="grid-scale" type="range" min="48" max="120" step="4" :value="state.gridScale" @input="setGridScale(Number(($event.target as HTMLInputElement).value))">
            </div>
            <button class="toolbar-popover__button" @click="toggleTagbar">
              {{ state.tagbarCollapsed ? '展开标签栏' : '折叠标签栏' }}
            </button>
          </div>
        </details>
        <button class="icon-btn" :class="{ 'sort-on': sortEnabled }" title="拖拽排序" @click="toggleSort">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
        </button>
        <button class="title-btn" :class="{ 'batch-on': batchMode }" @click="toggleBatchMode">{{ batchMode ? '完成选择' : '批量选择' }}</button>
        <button class="icon-btn" title="上传到远端" @click="syncUpload()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 19V5m-7 7l7-7 7 7"/></svg>
        </button>
        <button class="icon-btn" title="从远端下载" @click="syncDownload()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14m-7-7l7 7 7-7"/></svg>
        </button>
        <button class="title-btn" @click="showImportMenu()">导入</button>
        <button class="title-btn" @click="startAiOrganize()">AI 整理</button>
        <button class="title-btn" @click="openFloatingSearch()">快速搜索</button>
        <button class="title-btn" @click="rescanCache()">刷新</button>
        <button class="title-btn" @click="openSettings()">设置</button>
        <button class="title-btn close-btn" @click="hideWindow()">×</button>
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
            :active-id="sidebarCollapsed ? activeTopLevel : state.activeCollection"
            :depth="0"
            :collapsed="sidebarCollapsed"
            @select="setActiveCollection"
            @folder-context="onFolderRightClick"
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
          <span>已选 {{ selectedMemeIds.size }} 个</span>
          <button class="tagbar-toggle" @click="selectCurrentPage">全选当前页</button>
          <button class="tagbar-toggle" :disabled="selectedMemeIds.size === 0" @click="clearSelection">取消全选</button>
        </div>

        <div id="tagbar" :class="{ collapsed: state.tagbarCollapsed }">
          <button class="tagbar-toggle" @click="toggleTagbar" :title="state.tagbarCollapsed ? '展开标签栏' : '折叠标签栏'">
            {{ state.tagbarCollapsed ? '展开标签' : '收起标签' }}
          </button>
          <template v-if="!state.tagbarCollapsed">
            <span v-for="tag in state.allTags" :key="tag" class="tag" :class="{ active: state.activeTags.has(tag) }" @click="toggleTag(tag)">{{ tag }}</span>
          </template>
        </div>

        <nav v-if="state.activeCollection !== null" id="breadcrumb" aria-label="文件夹路径">
          <button class="crumb crumb-home" @click="goToAllMemes">← 所有表情</button>
          <span class="crumb-sep">›</span>
          <span class="crumb-path">文件夹 / {{ breadcrumb[breadcrumb.length - 1]?.name || '当前文件夹' }}</span>
        </nav>

        <Pager
          v-if="state.pageCount > 1"
          :page="state.page"
          :page-count="state.pageCount"
          @go="goToPage"
        />

        <div id="grid-wrap">
          <div v-if="folderCards.length" class="meme-grid folder-grid" :style="gridStyle">
            <div
              v-for="child in folderCards"
              :key="'folder-' + child.id"
              class="meme-card folder-card"
              :class="{ 'drop-target': folderDropTargetId === child.id }"
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
                'native-dragging': nativeDraggingMemeId === meme.id,
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
