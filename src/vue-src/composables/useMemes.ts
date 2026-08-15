import { reactive, ref, readonly } from 'vue'
import { api } from '../utils/api'
import type { Meme } from '../types'

const MEME_PAGE = 200

const state = reactive({
  memes: [] as Meme[],
  collections: [] as any[],
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

export function useMemes() {
  async function waitForPywebview(): Promise<void> {
    while (typeof window.pywebview === 'undefined' || !window.pywebview.api) {
      await new Promise(r => setTimeout(r, 100))
    }
  }

  async function loadInitData() {
    await waitForPywebview()
    const data = await api('get_init_data')
    if (data) {
      state.memes = data.memes || []
      state.allTags = data.tags || []
      state.collections = data.collections || []
      state.page = 1
      state.total = await api('count_memes', '', [], state.activeCollection) || state.memes.length
      state.pageCount = Math.max(1, Math.ceil(state.total / MEME_PAGE))
    }
  }

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

  function setSearch(q: string) { state.searchQuery = q }
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
  async function refreshTags() { try { state.allTags = (await api('get_tags')) || [] } catch { state.allTags = [] } }
  async function refreshCollections() { try { state.collections = (await api('get_collections')) || [] } catch { state.collections = [] } }
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
  function setMemes(newMemes: Meme[]) { state.memes = newMemes }

  function canReorder(): boolean {
    const q = state.searchQuery.trim()
    if (q || state.activeTags.size > 0) return false
    return state.activeCollection === null || state.activeCollection > 0
  }

  async function startNativeDrag(memeId: number): Promise<boolean> {
    try { return !!await api('start_native_drag', memeId) } catch { return false }
  }

  return {
    state,
    setMemes,
    search,
    goToPage,
    setSearch,
    toggleTag,
    setActiveCollection,
    refreshTags,
    refreshCollections,
    copyMeme,
    reorderMemes,
    canReorder,
    startNativeDrag,
    loadInitData,
    waitForPywebview,
    MEME_PAGE,
  }
}

const dragSortEnabled = ref(false)
const dragState = reactive({
  active: false,
  memeId: null as number | null,
  card: null as HTMLElement | null,
  offX: 0,
  offY: 0,
  base: null as DOMRect | null,
  startX: 0,
  startY: 0,
  originalOrder: [] as Meme[],
})

export function useDragSort(
  getMemes: () => Meme[],
  setMemesFn: (m: Meme[]) => void,
  canReorderFn: () => boolean,
  getSortEnabled: () => boolean,
  startNativeDragFn: (id: number) => Promise<boolean>,
) {
  function enable() { dragSortEnabled.value = true }
  function disable() { dragSortEnabled.value = false }
  function toggle() { dragSortEnabled.value = !dragSortEnabled.value }

  function onPointerDown(e: PointerEvent, memeId: number, card: HTMLElement) {
    if (e.button !== 0 || !getSortEnabled() || !canReorderFn()) return
    const rect = card.getBoundingClientRect()
    dragState.active = false
    dragState.memeId = memeId
    dragState.card = card
    dragState.offX = e.clientX - rect.left
    dragState.offY = e.clientY - rect.top
    dragState.base = rect
    dragState.startX = e.clientX
    dragState.startY = e.clientY
    dragState.originalOrder = [...getMemes()]
  }

  function onPointerMove(e: PointerEvent) {
    const d = dragState
    if (!d.memeId || !d.card) return
    if (!d.active) {
      const dist = Math.hypot(e.clientX - d.startX, e.clientY - d.startY)
      if (dist <= 8) return
      d.active = true
      d.card.classList.add('dragging')
    }
    const dx = e.clientX - d.offX - d.base!.left
    const dy = e.clientY - d.offY - d.base!.top
    d.card.style.transform = `translate(${dx}px, ${dy}px) scale(0.90)`
    d.card.style.zIndex = '10'
  }

  function onPointerUp() {
    const d = dragState
    if (!d.memeId) return
    if (d.card) {
      d.card.classList.remove('dragging')
      d.card.style.transform = ''
      d.card.style.zIndex = ''
    }
    d.active = false
    d.memeId = null
    d.card = null
  }

  return {
    dragSortEnabled: readonly(dragSortEnabled),
    dragState: readonly(dragState),
    enable,
    disable,
    toggle,
    onPointerDown,
    onPointerMove,
    onPointerUp,
  }
}
