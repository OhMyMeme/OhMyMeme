<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useMemes } from './composables/useMemes'
import type { Meme } from './types'

const { state, search, goToPage, setSearch, toggleTag, setActiveCollection, refreshTags, refreshCollections, copyMeme, reorderMemes } = useMemes()

const sidebarCollapsed = ref(false)
const sortEnabled = ref(false)
const settingsVisible = ref(false)
const dragOver = ref(false)
let dragCounter = 0
let nativeDragActive = false

async function handleCopy(meme: Meme) {
  const ok = await copyMemes(meme.id, meme.filename)
  if (ok) showToast(`${meme.original_name || meme.filename} 已复制`)
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
  settingsVisible.value = true
}

function closeSettings() {
  settingsVisible.value = false
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
}

function toggleSort() {
  sortEnabled.value = !sortEnabled.value
}

function showImportMenu() {
  showToast('导入功能开发中...')
}

function rescanCache() {
  showToast('缓存刷新中...')
  search()
  refreshCollections()
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
  if (dragCounter <= 0) {
    dragCounter = 0
    dragOver.value = false
  }
}

async function onDrop(e: DragEvent) {
  e.preventDefault()
  if (nativeDragActive) {
    dragCounter = 0
    dragOver.value = false
    return
  }
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
      if (dt.items && dt.items.length) {
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

  if (!uri) { try { if (dt.files && dt.files.length) file = dt.files[0] } catch (_) {} }
  if (!uri && !file) {
    try {
      if (dt.items && dt.items.length) {
        for (let i = 0; i < dt.items.length; i++) {
          const it = dt.items[i]
          if (it.kind === 'file') { file = it.getAsFile(); if (file) break }
        }
      }
    } catch (_) {}
  }

  if (uri) {
    try {
      const r = await window.pywebview?.api?.download_original_image(uri)
      if (r && r.ok) {
        showToast('导入成功')
        search()
        refreshCollections()
        return
      }
    } catch (_) {}
  }

  if (file) {
    try {
      const b64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve((reader.result as string).split(',')[1])
        reader.onerror = () => reject(reader.error)
        reader.readAsDataURL(file!)
      })
      const res = await fetch('/api/upload/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files: [{ name: file.name, data: b64 }] }),
      })
      if (res.ok) {
        showToast('导入成功')
        search()
        refreshCollections()
      }
    } catch (_) {}
  }
}

onMounted(() => {
  document.addEventListener('dragenter', onDragEnter)
  document.addEventListener('dragover', onDragOver)
  document.addEventListener('dragleave', onDragLeave)
  document.addEventListener('drop', onDrop)
})

onUnmounted(() => {
  document.removeEventListener('dragenter', onDragEnter)
  document.removeEventListener('dragover', onDragOver)
  document.removeEventListener('dragleave', onDragLeave)
  document.removeEventListener('drop', onDrop)
})

search()
refreshTags()
refreshCollections()
</script>

<template>
  <div id="app">
    <header id="titlebar">
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
        <button class="title-btn" @click="showImportMenu()">导入</button>
        <button class="title-btn" @click="rescanCache()">刷新</button>
        <button class="title-btn" @click="openSettings()">设置</button>
        <button class="title-btn close-btn" @click="window.pywebview?.api?.hide_window()">×</button>
      </div>
    </header>

    <div id="search-wrap">
      <input id="search" type="text" placeholder="搜索表情包..." :value="state.searchQuery" @input="onSearchInput" autofocus spellcheck="false">
    </div>

    <div id="content">
      <aside id="sidebar" :class="{ collapsed: sidebarCollapsed }">
        <div id="sidebar-header">
          <span v-if="!sidebarCollapsed">分组</span>
        </div>
        <div id="tree">
          <div
            v-for="c in state.collections"
            :key="c.id"
            class="tree-node"
          >
            <div class="tree-row" :class="{ active: state.activeCollection === c.id }" @click="setActiveCollection(c.id)">
              <span class="tree-icon">📁</span>
              <span v-if="!sidebarCollapsed" class="tree-label">{{ c.name }}</span>
              <span v-if="!sidebarCollapsed" class="tree-count">{{ c.count || 0 }}</span>
            </div>
          </div>
        </div>
      </aside>

      <div id="main">
        <div id="tagbar">
          <span v-for="tag in state.allTags" :key="tag" class="tag" :class="{ active: state.activeTags.has(tag) }" @click="toggleTag(tag)">
            {{ tag }}
          </span>
        </div>

        <div id="grid-wrap">
          <div id="meme-grid" :style="{ gridTemplateColumns: `repeat(${sidebarCollapsed ? 5 : 4}, 1fr)` }">
            <div
              v-for="meme in state.memes"
              :key="meme.id"
              class="meme-card"
              :draggable="sortEnabled"
              @click="handleCopy(meme)"
            >
              <img :src="`/api/thumb/${meme.id}/${encodeURIComponent(meme.filename)}`" :alt="meme.original_name || meme.filename" loading="lazy">
              <span class="meme-name">{{ meme.original_name || meme.filename }}</span>
            </div>
          </div>

          <div v-if="state.memes.length === 0 && !state.loading" id="empty">
            <div class="icon">_(:3 」∠)_</div>
            <div class="text">还没有表情包，点击「导入」添加</div>
          </div>
        </div>

        <div v-if="state.pageCount > 1" id="pager">
          <button :disabled="state.page <= 1" @click="goToPage(state.page - 1)">&lt;</button>
          <span class="pager-info">{{ state.page }} / {{ state.pageCount }}</span>
          <button :disabled="state.page >= state.pageCount" @click="goToPage(state.page + 1)">&gt;</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Settings Overlay -->
  <div v-if="settingsVisible" id="settings-overlay" @click.self="closeSettings">
    <div class="settings-panel">
      <div class="settings-header">
        <h2>设置</h2>
        <button class="icon-btn" @click="closeSettings">×</button>
      </div>
      <div class="settings-body">
        <div class="settings-section">
          <h3>全局快捷键</h3>
          <div class="settings-row">
            <label>呼出窗口</label>
            <input type="text" value="Ctrl+Alt+N" readonly>
          </div>
        </div>
        <div class="settings-section">
          <h3>复制处理</h3>
          <div class="settings-row">
            <label>处理模式</label>
            <select>
              <option>不处理</option>
              <option selected>WebP 缩放</option>
              <option>转 GIF</option>
              <option>GIF 隐写原图</option>
            </select>
          </div>
        </div>
        <div class="settings-section">
          <h3>导入</h3>
          <button class="btn btn-primary" style="width:100%">从抖音下载表情</button>
        </div>
      </div>
    </div>
  </div>

  <div id="drop-overlay" :class="{ 'drag-over': dragOver }">
    <div class="drop-content">
      <div class="drop-icon">📁</div>
      <div class="drop-text">拖放图片到此处导入</div>
    </div>
  </div>

  <div id="toast"></div>
  <div id="loading"><div class="spinner"></div></div>
</template>
