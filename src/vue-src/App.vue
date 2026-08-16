<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useMemes } from './composables/useMemes'
import { useDragSort } from './composables/useDragSort'
import { useContextMenu, type MenuItem } from './composables/useContextMenu'
import { useCollectionBuilder } from './composables/useCollectionBuilder'
import ContextMenu from './components/ContextMenu.vue'
import CollectionBuilder from './components/CollectionBuilder.vue'
import CollectionTreeNode from './components/CollectionTreeNode.vue'
import ImportMenu from './components/ImportMenu.vue'
import InputDialog from './components/InputDialog.vue'
import Pager from './components/Pager.vue'
import SyncOverlay from './components/SyncOverlay.vue'
import TagEditor from './components/TagEditor.vue'
import UpdateDialog from './components/UpdateDialog.vue'
import type { Meme } from './types'

const { state, setMemes, search, goToPage, setSearch, toggleTag, setActiveCollection, refreshTags, refreshCollections, copyMeme, reorderMemes, canReorder, startNativeDrag, loadInitData } = useMemes()
const ctx = useContextMenu()
const cb = useCollectionBuilder()
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
// 网格列数随侧边栏即时切换（实时感）；性能由卡片 content-visibility 保证
const gridCols = computed(() => sidebarCollapsed.value ? 5 : 4)

// 当前分组（正 ID）下的子分组列表，用于网格顶部显示文件夹卡片
const folderCards = computed(() => {
  if (!state.activeCollection || state.activeCollection < 0) return []
  const find = (items: any[]): any[] => {
    for (const c of items) {
      if (c.id === state.activeCollection) return c.children || []
      if (c.children && c.children.length) {
        const r = find(c.children)
        if (r.length) return r
      }
    }
    return []
  }
  return find(state.collections)
})

// 面包屑：当前分组从「全部」到自身的祖先链
const breadcrumb = computed(() => {
  if (!state.activeCollection) return []
  const walk = (items: any[], target: number, trail: any[]): any[] | null => {
    for (const c of items) {
      if (c.id === target) return [...trail, c]
      if (c.children && c.children.length) {
        const r = walk(c.children, target, [...trail, c])
        if (r) return r
      }
    }
    return null
  }
  const path = walk(state.collections, state.activeCollection, [])
  if (path) return [{ id: null, name: '全部' }, ...path]
  const sys = state.collections.find(c => c.id === state.activeCollection)
  return sys ? [{ id: null, name: '全部' }, sys] : []
})

// 图标条祖先高亮：当前分组所属的顶层分组 id（用于折叠时高亮）
const activeTopLevel = computed(() => {
  if (!state.activeCollection || state.activeCollection < 0) return state.activeCollection
  const findTop = (items: any[], target: number, inherited: number | null): number | null => {
    for (const c of items) {
      const thisTop = inherited ?? c.id
      if (c.id === target) return thisTop
      if (c.children && c.children.length) {
        const r = findTop(c.children, target, thisTop)
        if (r != null) return r
      }
    }
    return null
  }
  const r = findTop(state.collections, state.activeCollection, null)
  return r != null ? r : state.activeCollection
})

function onBreadcrumbClick(id: number | null) {
  setActiveCollection(id)
}

function onFolderCardClick(childId: number) {
  setActiveCollection(childId)
}

function onFolderCardContext(e: MouseEvent, childId: number, childName: string) {
  e.preventDefault()
  e.stopPropagation()
  ctx.show([
    { action: 'delete-folder', label: '删除小分组', danger: true },
  ], { folderId: childId, folderName: childName, isFolder: true }, e.clientX, e.clientY)
}

async function handleCopy(meme: Meme) {
  if (ignoreClick) { ignoreClick = false; return }
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
function toggleSidebar() { sidebarCollapsed.value = !sidebarCollapsed.value }

function toggleSort() {
  sortEnabled.value = !sortEnabled.value
  drag.toggle()
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
    { action: 'collection', label: '添加分组' },
  ]
  if (state.activeCollection && state.activeCollection > 0) {
    items.push({ action: 'add-to-subgroup', label: '加入小分组' })
    items.push({ action: 'remove-collection', label: '移出该分组' })
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
  const items: MenuItem[] = [{ action: 'rename-collection', label: '重命名' }]
  if (folderId === -3) {
    items.push({ action: 'clear-recent', label: '清空最近使用', danger: true })
  } else if (folderId > 0) {
    items.push({ action: 'add-to-subgroup', label: '新建子分组' })
    items.push({ action: 'delete-collection', label: '删除', danger: true })
  }
  ctx.show(items, { folderId, folderName, isFolder: true }, e.clientX, e.clientY)
}

// 右键「加入小分组」子菜单：加载已有分组
async function onShowSubmenu(_items: any[], x: number, y: number) {
  // 只显示当前分组（正 ID）下的子分组；不在分组内时无子分组
  const targetCol = state.activeCollection && state.activeCollection > 0 ? state.activeCollection : null
  const children = targetCol ? ((await window.pywebview?.api?.get_child_collections(targetCol)) || []) : []
  const sub: { action: string; label: string }[] = []
  if (!targetCol) {
    sub.push({ action: '__new-subgroup__', label: '新建分组' })
  } else {
    sub.push({ action: '__new-subgroup__', label: '新建小分组' })
    for (const ch of children) {
      sub.push({ action: 'subgroup-' + ch.id, label: ch.name })
    }
  }
  ctx.showSubmenu(sub, x, y)
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
    case 'collection': { showCollectionBuilder(); break }
    case 'add-to-subgroup': { /* 子菜单在 hover 时加载，点击走 subgroup-N / __new-subgroup__ */ break }
    case '__new-subgroup__': {
      const isSub = state.activeCollection && state.activeCollection > 0
      const name = await inputDialog.value?.open(isSub ? '新建小分组' : '新建分组', '', isSub ? '输入小分组名称' : '输入分组名称')
      if (!name) break
      const targetCol = state.activeCollection && state.activeCollection > 0 ? state.activeCollection : null
      let ok: any
      if (targetCol) {
        const r = await window.pywebview?.api?.create_subcollection(name, targetCol)
        if (r && r.ok) ok = await window.pywebview?.api?.add_to_existing_collection(t.memeId, r.id)
      } else {
        ok = await window.pywebview?.api?.add_to_collection(t.memeId, name)
      }
      if (ok) { showToast('已添加'); refreshCollections(); search() }
      else showToast('添加分组失败')
      break
    }
    case 'remove-collection': {
      const removedFrom = state.activeCollection
      const ok = await window.pywebview?.api?.remove_from_collection(t.memeId, removedFrom)
      if (ok) {
        // 从子分组移除时加回上层大分组
        const parent = findParentCollection(state.collections, removedFrom)
        if (parent) await window.pywebview?.api?.add_to_existing_collection(t.memeId, parent.id)
        await refreshCollections()
        // 递归查找分组节点（子分组不在顶层），据此判断是否清空后再删
        const c = findCollectionNode(state.collections, removedFrom)
        if (!c || c.count === 0) {
          if (removedFrom > 0) await window.pywebview?.api?.delete_collection(removedFrom)
          setActiveCollection(parent ? parent.id : -4)
        }
        search()
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
    case 'rename-collection': {
      const name = await inputDialog.value?.open('重命名分组', t.folderName || '')
      if (name && name !== t.folderName) { await window.pywebview?.api?.rename_collection(t.folderId, name); refreshCollections() }
      break
    }
    case 'delete-collection': {
      if (confirm('确定删除这个分组吗？')) {
        // 先移除组内表情到上层，再删组
        const parent = findParentCollection(state.collections, t.folderId)
        const members = (await window.pywebview?.api?.search_memes('', [], t.folderId, 0, 9999)) || []
        for (const mm of members) {
          if (parent) await window.pywebview?.api?.add_to_existing_collection(mm.id, parent.id)
        }
        await window.pywebview?.api?.delete_collection(t.folderId)
        if (state.activeCollection === t.folderId) setActiveCollection(parent ? parent.id : -4)
        refreshCollections(); search()
      }
      break
    }
    case 'delete-folder': {
      if (confirm('确定删除小分组「' + t.folderName + '」？分组内表情包将移回上层分组。')) {
        const parent = findParentCollection(state.collections, t.folderId)
        const members = (await window.pywebview?.api?.search_memes('', [], t.folderId, 0, 9999)) || []
        for (const mm of members) {
          if (parent) await window.pywebview?.api?.add_to_existing_collection(mm.id, parent.id)
        }
        await window.pywebview?.api?.delete_collection(t.folderId)
        if (state.activeCollection === t.folderId) setActiveCollection(parent ? parent.id : -4)
        refreshCollections(); search()
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
      if (action.startsWith('subgroup-')) {
        const cid = Number(action.slice('subgroup-'.length))
        const ok = await window.pywebview?.api?.add_to_existing_collection(t.memeId, cid)
        if (ok) { showToast('已添加到分组'); refreshCollections(); search() }
        else showToast('添加失败')
      } else {
        showToast(`${action} 功能开发中`)
      }
  }
}

// 在 collections 树中查找 target 的父分组
function findParentCollection(items: any[], target: number): any | null {
  for (const c of items) {
    if (c.children) {
      for (const ch of c.children) {
        if (ch.id === target) return c
      }
      const r = findParentCollection(c.children, target)
      if (r) return r
    }
  }
  return null
}

// 递归查找分组节点（含子分组）
function findCollectionNode(items: any[], target: number): any | null {
  for (const c of items) {
    if (c.id === target) return c
    if (c.children && c.children.length) {
      const r = findCollectionNode(c.children, target)
      if (r) return r
    }
  }
  return null
}

async function showCollectionBuilder() {
  cb.open(async (confirm) => {
    const { name, memeIds, existingId } = confirm
    // 已选已有分组 → 更新其成员；否则新建分组
    const result = existingId
      ? await window.pywebview?.api?.set_collection_members(existingId, memeIds)
      : await window.pywebview?.api?.set_collection_members_new(name, memeIds)
    if (result?.ok || result === true) {
      showToast(existingId ? '已保存到分组：' + name : '分组已创建')
      refreshCollections(); search()
    } else {
      showToast(result?.error || '保存失败')
    }
  })
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
    startNativeDrag(id).then((ok) => {
      nativeDragActive = false
      ignoreClick = true
      if (!ok) showToast('拖拽失败：本地文件不存在')
    }).catch(() => { nativeDragActive = false })
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
        <button class="icon-btn" :class="{ 'sort-on': sortEnabled }" title="拖拽排序" @click="toggleSort">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
        </button>
        <button class="icon-btn" title="上传到远端" @click="syncUpload()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 19V5m-7 7l7-7 7 7"/></svg>
        </button>
        <button class="icon-btn" title="从远端下载" @click="syncDownload()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14m-7-7l7 7 7-7"/></svg>
        </button>
        <button class="title-btn" @click="showImportMenu()">导入</button>
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

        <div id="tagbar">
          <span v-for="tag in state.allTags" :key="tag" class="tag" :class="{ active: state.activeTags.has(tag) }" @click="toggleTag(tag)">{{ tag }}</span>
        </div>

        <div v-if="breadcrumb.length > 1" id="breadcrumb">
          <template v-for="(crumb, idx) in breadcrumb" :key="idx">
            <span v-if="idx > 0" class="crumb-sep">›</span>
            <button
              class="crumb"
              :class="{ current: idx === breadcrumb.length - 1 }"
              @click="onBreadcrumbClick(crumb.id)"
            >{{ crumb.name }}</button>
          </template>
        </div>

        <Pager
          v-if="state.pageCount > 1"
          :page="state.page"
          :page-count="state.pageCount"
          @go="goToPage"
        />

        <div id="grid-wrap">
          <div v-if="folderCards.length" class="meme-grid folder-grid" :style="{ gridTemplateColumns: `repeat(${gridCols}, 1fr)` }">
            <div
              v-for="child in folderCards"
              :key="'folder-' + child.id"
              class="meme-card folder-card"
              :data-folder-id="child.id"
              @click="onFolderCardClick(child.id)"
              @contextmenu="onFolderCardContext($event, child.id, child.name)"
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
            :style="{ gridTemplateColumns: `repeat(${gridCols}, 1fr)` }"
          >
            <div
              v-for="meme in state.memes"
              :key="meme.id"
              class="meme-card"
              :class="{ 'dragging': drag.dragState.active && drag.dragState.memeId === meme.id }"
              :data-meme-id="meme.id"
              @click="handleCopy(meme)"
              @contextmenu="onMemeRightClick($event, meme)"
              @pointerdown="onCardPointerDown($event, meme, $event.currentTarget as HTMLElement)"
              @mouseenter="onCardMouseEnter(meme)"
              @mouseleave="onCardMouseLeave(meme)"
            >
              <img :src="memeSrc(meme)" :alt="meme.name" loading="lazy">
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

  <CollectionBuilder />
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
