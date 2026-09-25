import { reactive, ref, readonly } from 'vue'
import { api } from '../utils/api'
import type { Meme } from '../types'

const MEME_PAGE = 200

const state = reactive({
  memes: [] as Meme[],
  collections: [] as any[],
  activeCollection: null as number | null,
  activeTags: new Set<string>(),
  selectedIds: new Set<number>(),
  allTags: [] as string[],
  searchQuery: '',
  total: 0,
  page: 1,
  pageCount: 1,
  loading: false,
  showStartupAnimation: true,
  startupBgColor: '#000000',
  guideOk: true,
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
      state.showStartupAnimation = data.show_startup_animation !== false
      state.startupBgColor = data.startup_bg_color || '#000000'
      state.guideOk = data.guide_ok !== false
    }
  }

  async function search(resetPage = true) {
    const gen = ++searchGen
    if (resetPage) state.page = 1
    state.loading = true
    // 换页/筛选/切分组即清空选择（「全选当前页」语义）
    state.selectedIds = new Set()
    const offset = (state.page - 1) * MEME_PAGE
    try {
      const [countResult, memesResult] = await Promise.all([
        api('count_memes', state.searchQuery, [...state.activeTags], state.activeCollection),
        api('search_memes', state.searchQuery, [...state.activeTags], state.activeCollection, offset, MEME_PAGE),
      ])
      if (gen !== searchGen) return
      // 桥接失败（null/非数组）时保留当前分页与结果，避免暂时性故障触发空页回退或清空网格
      if (!Array.isArray(memesResult) || typeof countResult !== 'number') return
      state.total = countResult
      state.pageCount = Math.max(1, Math.ceil(state.total / MEME_PAGE))
      state.memes = memesResult
      // 删除等操作使当前页变空时回退到可用末页，避免停留在空页显示「没有表情包」
      if (!resetPage && state.memes.length === 0 && state.page > 1) {
        const target = Math.max(1, Math.min(state.page, state.pageCount))
        if (target !== state.page) { state.page = target; return search(false) }
      }
    } catch (e) {
      if (gen !== searchGen) return
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
  async function refreshTags() {
    let tags: string[] | null = null
    try { tags = await api('get_tags') } catch { return }
    // 桥接失败（null/非数组）时保留现有标签与筛选，避免暂时性故障清掉用户筛选
    if (!Array.isArray(tags)) return
    state.allTags = tags
    // 清理已不存在的激活标签（如删除标签下最后一张图后孤儿标签被清理），否则筛选永久卡死
    let pruned = false
    for (const t of [...state.activeTags]) {
      if (!state.allTags.includes(t)) { state.activeTags.delete(t); pruned = true }
    }
    if (pruned) await search()
  }
  async function refreshCollections() {
    let items: any[] | null = null
    try { items = await api('get_collections') } catch { return }
    // 桥接失败（null/非数组）时保留现有分组树与筛选，避免暂时性故障复位用户分组
    if (!Array.isArray(items)) return
    state.collections = items
    // 当前分组已被后端隐式删除（如同步 push 时 manifest 清理空分组）时复位到「全部」，避免筛选永久空显
    const ac = state.activeCollection
    if (ac && ac > 0 && !_collectionExists(state.collections, ac)) {
      state.activeCollection = null
      await search()
    }
  }
  async function copyMeme(id: number): Promise<boolean> {
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

  function selectAllVisible() { state.selectedIds = new Set(state.memes.map(m => m.id)) }

  function _collectionExists(items: any[], id: number): boolean {
    for (const c of items) {
      if (c.id === id) return true
      if (c.children && _collectionExists(c.children, id)) return true
    }
    return false
  }
  function clearSelection() { state.selectedIds = new Set() }

  function canReorder(): boolean {
    const q = state.searchQuery.trim()
    if (q || state.activeTags.size > 0) return false
    // 全部/未分类/正 ID 分组可排序；收藏夹/最近使用（-2/-3）不可排
    return state.activeCollection === null || state.activeCollection === -4 || state.activeCollection > 0
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
    selectAllVisible,
    clearSelection,
    loadInitData,
    waitForPywebview,
    MEME_PAGE,
  }
}
