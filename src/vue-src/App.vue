<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useMemes } from './composables/useMemes'
import { useDragSort } from './composables/useDragSort'
import { useContextMenu } from './composables/useContextMenu'
import { useCollectionBuilder } from './composables/useCollectionBuilder'
import ContextMenu from './components/ContextMenu.vue'
import CollectionBuilder from './components/CollectionBuilder.vue'
import CollectionTreeNode from './components/CollectionTreeNode.vue'
import ImportMenu from './components/ImportMenu.vue'
import Pager from './components/Pager.vue'
import SyncOverlay from './components/SyncOverlay.vue'
import type { Meme } from './types'

const { state, setMemes, search, goToPage, setSearch, toggleTag, setActiveCollection, refreshTags, refreshCollections, copyMeme, reorderMemes, canReorder, startNativeDrag, loadInitData } = useMemes()
const ctx = useContextMenu()
const cb = useCollectionBuilder()

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
  onFolderRightClick(e, childId, childName)
}

async function handleCopy(meme: Meme) {
  if (ignoreClick) { ignoreClick = false; return }
  const ok = await copyMeme(meme.id, meme.filename)
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
  ctx.show([
    { action: 'rename', label: '重命名' },
    { action: 'favorite', label: '收藏' },
    { action: 'tag', label: '打标签' },
    { action: 'collection', label: '添加分组' },
    { action: 'delete', label: '删除', danger: true },
  ], { memeId: meme.id, filename: meme.filename, memeName: meme.name }, e.clientX, e.clientY)
}

function onFolderRightClick(e: MouseEvent, folderId: number, folderName: string) {
  e.preventDefault()
  e.stopPropagation()
  ctx.show([
    { action: 'rename-collection', label: '重命名' },
    { action: 'add-to-subgroup', label: '新建子分组' },
    { action: 'delete-collection', label: '删除', danger: true },
  ], { folderId, folderName, isFolder: true }, e.clientX, e.clientY)
}

async function onCtxAction(action: string) {
  ctx.hide()
  const t = ctx.trigger.value
  switch (action) {
    case 'rename': {
      const name = prompt('重命名', t.memeName || '')
      if (name && name !== t.memeName) { await window.pywebview?.api?.rename_meme(t.memeId, name); search() }
      break
    }
    case 'favorite': { await window.pywebview?.api?.toggle_favorite(t.memeId); search(); break }
    case 'tag': {
      const tag = prompt('输入标签（多个用逗号分隔）')
      if (tag) { await window.pywebview?.api?.set_meme_tags(t.memeId, tag.split(',').map((s: string) => s.trim()).filter(Boolean)); refreshTags(); search() }
      break
    }
    case 'collection': { showCollectionBuilder(); break }
    case 'delete': {
      if (confirm('确定删除这个表情包吗？')) { await window.pywebview?.api?.delete_meme(t.memeId); search(); refreshCollections() }
      break
    }
    case 'rename-collection': {
      const name = prompt('重命名分组', t.folderName || '')
      if (name && name !== t.folderName) { await window.pywebview?.api?.rename_collection(t.folderId, name); refreshCollections() }
      break
    }
    case 'delete-collection': {
      if (confirm('确定删除这个分组吗？')) { await window.pywebview?.api?.delete_collection(t.folderId); refreshCollections() }
      break
    }
    default: showToast(`${action} 功能开发中`)
  }
}

async function showCollectionBuilder() {
  cb.open(async (name, memeIds) => {
    const result = await window.pywebview?.api?.set_collection_members_new(name, memeIds)
    if (result?.ok) { showToast('分组已创建'); refreshCollections(); search() }
    else showToast(result?.error || '创建失败')
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
  if (dist > 8) { const id = nativeDragStart.memeId; nativeDragStart = null; startNativeDrag(id) }
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
  window.removeEventListener('blur', onDocPointerCancel)
})

;(async () => {
  await loadInitData()
  setTimeout(async () => {
    await window.pywebview?.api?.rescan_cache()
    await window.pywebview?.api?.run_auto_sync()
    await search()
    await refreshTags()
    await refreshCollections()
  }, 300)
})()
</script>

<template>
  <div id="app">
    <header id="titlebar" @mousedown="onTitlebarMouseDown">
      <div class="titlebar__left">
        <button class="sidebar-toggle" :class="{ collapsed: sidebarCollapsed }" @click="toggleSidebar" title="折叠/展开侧边栏">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
          </svg>
        </button>
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

    <div id="search-wrap">
      <input id="search" type="text" placeholder="搜索表情包..." :value="state.searchQuery" @input="onSearchInput" autofocus spellcheck="false">
    </div>

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

  <CollectionBuilder @confirm="showCollectionBuilder" />
  <ImportMenu ref="importMenu" @imported="onImportDone" />
  <SyncOverlay ref="syncOverlay" @synced="onSyncDone" />
  <ContextMenu
    :visible="ctx.visible.value" :x="ctx.x.value" :y="ctx.y.value"
    :items="ctx.items.value" :trigger="ctx.trigger.value"
    :submenu-visible="ctx.submenuVisible.value" :submenu-items="ctx.submenuItems.value"
    :submenu-x="ctx.submenuX.value" :submenu-y="ctx.submenuY.value"
    @action="onCtxAction" @close="ctx.hide"
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
</template>
