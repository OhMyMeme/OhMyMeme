import { reactive, ref, computed, readonly } from 'vue'
import { api } from '../utils/api'
import type { Meme, Collection } from './types'

export interface DragSortState {
  draggedId: number | null
  overId: number | null
}

const MEME_PAGE = 200

const state = reactive({
  memes: [] as Meme[],
  collections: [] as Collection[],
  activeCollection: null as number | null,
  activeTags: new Set<string>(),
  allTags: [] as string[],
  searchQuery: '',
  total: 0,
  page: 1,
  pageCount: 1,
  loading: false,
})

let searchGen = 0

const dragSort = reactive({
  draggedId: null as number | null,
  overId: null as number | null,
})

export function useMemes() {
  async function search(resetPage = true) {
    const gen = ++searchGen
    if (resetPage) state.page = 1
    state.loading = true

    const offset = (state.page - 1) * MEME_PAGE
    try {
      const [countResult, memesResult] = await Promise.all([
        api('count_memes', state.searchQuery, [...state.activeTags], state.activeCollection),
        api('search_memes', state.searchQuery, [...state.activeTags], state.activeCollection, offset, MEME_PAGE),
      ])
      if (gen !== searchGen) return
      state.total = countResult || 0
      state.pageCount = Math.max(1, Math.ceil(state.total / MEME_PAGE))
      state.memes = memesResult || []
    } catch (e) {
      if (gen !== searchGen) return
      state.memes = []
      state.total = 0
      state.pageCount = 1
    } finally {
      if (gen === searchGen) state.loading = false
    }
  }

  async function goToPage(p: number) {
    if (p < 1 || p > state.pageCount || p === state.page) return
    state.page = p
    await search(false)
    if (state.memes.length === 0 && state.page > 1) {
      state.page = Math.max(1, Math.min(state.page, state.pageCount))
      await search(false)
    }
  }

  function setSearch(q: string) {
    state.searchQuery = q
  }

  function toggleTag(tag: string) {
    if (state.activeTags.has(tag)) state.activeTags.delete(tag)
    else state.activeTags.add(tag)
    search()
  }

  function setActiveCollection(id: number | null) {
    if (state.activeCollection === id) state.activeCollection = null
    else state.activeCollection = id
    search()
  }

  async function refreshTags() {
    try {
      state.allTags = (await api('get_tags')) || []
    } catch (e) {
      state.allTags = []
    }
  }

  async function refreshCollections() {
    try {
      state.collections = (await api('get_collections')) || []
    } catch (e) {
      state.collections = []
    }
  }

  async function copyMeme(id: number, filename: string): Promise<boolean> {
    const result = await api('copy_meme', id)
    return !!result?.ok
  }

  async function reorderMemes(orderedIds: number[]): Promise<boolean> {
    const collectionId = state.activeCollection && state.activeCollection > 0 ? state.activeCollection : null
    const result = collectionId
      ? await api('reorder_collection_members', collectionId, orderedIds)
      : await api('reorder_memes', orderedIds)
    return !!result
  }

  function onSortDragStart(memeId: number) {
    dragSort.draggedId = memeId
  }

  function onSortDragOver(memeId: number) {
    if (dragSort.draggedId === memeId) return
    dragSort.overId = memeId
  }

  function onSortDragLeave() {
    dragSort.overId = null
  }

  async function onSortDrop(memeId: number) {
    const draggedId = dragSort.draggedId
    dragSort.draggedId = null
    dragSort.overId = null
    if (!draggedId || draggedId === memeId) return

    const memes = state.memes
    const fromIdx = memes.findIndex(m => m.id === draggedId)
    const toIdx = memes.findIndex(m => m.id === memeId)
    if (fromIdx < 0 || toIdx < 0) return

    const newMemes = [...memes]
    const [moved] = newMemes.splice(fromIdx, 1)
    newMemes.splice(toIdx, 0, moved)
    state.memes = newMemes

    const ok = await reorderMemes(newMemes.map(m => m.id))
    if (!ok) {
      state.memes = memes
    }
  }

  function onSortDragEnd() {
    dragSort.draggedId = null
    dragSort.overId = null
  }

  async function startNativeDrag(memeId: number, startX: number, startY: number): Promise<boolean> {
    try {
      const result = await api('start_native_drag', memeId)
      return !!result
    } catch {
      return false
    }
  }

  return {
    state: readonly(state),
    dragSort: readonly(dragSort),
    search,
    goToPage,
    setSearch,
    toggleTag,
    setActiveCollection,
    refreshTags,
    refreshCollections,
    copyMeme,
    reorderMemes,
    onSortDragStart,
    onSortDragOver,
    onSortDragLeave,
    onSortDrop,
    onSortDragEnd,
    startNativeDrag,
  }
}

export function useCollections() {
  const expandedNodes = ref(new Set<number>())

  function toggleExpand(id: number) {
    if (expandedNodes.value.has(id)) expandedNodes.value.delete(id)
    else expandedNodes.value.add(id)
  }

  function isExpanded(id: number): boolean {
    return expandedNodes.value.has(id)
  }

  return { expandedNodes: readonly(expandedNodes), toggleExpand, isExpanded }
}
