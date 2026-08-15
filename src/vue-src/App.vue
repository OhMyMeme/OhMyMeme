<script setup lang="ts">
import { ref } from 'vue'
import { useMemes } from './composables/useMemes'
import type { Meme, Collection } from './types'

const { state, search, goToPage, setSearch, toggleTag, setActiveCollection, refreshTags, refreshCollections, copyMeme, reorderMemes } = useMemes()

const sidebarCollapsed = ref(false)
const sortEnabled = ref(false)

async function handleCopy(meme: Meme) {
  const ok = await copyMeme(meme.id, meme.filename)
  if (ok) showToast(`${meme.original_name || meme.filename} 已复制`)
  else showToast('复制失败')
}

async function handleReorder(memes: Meme[]) {
  const ok = await reorderMemes(memes.map(m => m.id))
  if (!ok) showToast('排序保存失败')
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
  window.pywebview?.api?.open_settings()
}

function hide() {
  window.pywebview?.api?.hide_window()
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
}

function toggleSort() {
  sortEnabled.value = !sortEnabled.value
}

search()
refreshTags()
refreshCollections()
</script>

<template>
  <div id="app">
    <header id="titlebar">
      <div class="logo">OhMy<span>Meme</span></div>
      <span class="spacer"></span>
      <button class="icon-btn" :class="{ 'sort-on': sortEnabled }" title="拖拽排序" @click="toggleSort">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
      </button>
      <button class="title-btn" @click="openSettings()">设置</button>
      <button class="title-btn close-btn" @click="hide()">×</button>
    </header>

    <div id="search-wrap">
      <input id="search" type="text" placeholder="搜索表情包..." :value="state.searchQuery" @input="onSearchInput" autofocus spellcheck="false">
    </div>

    <div id="content">
      <aside id="sidebar" :class="{ collapsed: sidebarCollapsed }">
        <div id="sidebar-header">
          <span>分组</span>
        </div>
        <div id="tree">
          <div
            v-for="c in state.collections"
            :key="c.id"
            class="tree-node"
          >
            <div class="tree-row" :class="{ active: state.activeCollection === c.id }" @click="setActiveCollection(c.id)">
              <span class="tree-label">{{ c.name }}</span>
              <span class="tree-count">{{ c.count || 0 }}</span>
            </div>
          </div>
        </div>
      </aside>
      <button id="sidebar-toggle" :class="{ collapsed: sidebarCollapsed }" @click="toggleSidebar()">
        {{ sidebarCollapsed ? '▶' : '◀' }}
      </button>

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

  <div id="toast"></div>
  <div id="loading"><div class="spinner"></div></div>
</template>
