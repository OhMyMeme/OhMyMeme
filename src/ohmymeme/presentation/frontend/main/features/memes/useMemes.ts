import { reactive, ref, readonly } from 'vue'
import { api, bridgeReady } from '../../shared/bridge'
import type { Meme } from '../../shared/types'

const MEME_PAGE = 200
// 桥接调用失败时的退避重试上限（失败不清空已有数据）
const RETRY_LIMIT = 3

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
})

let searchGen = 0
let retryTimer: ReturnType<typeof setTimeout> | null = null
let retryCount = 0

export function useMemes() {
  async function waitForPywebview(): Promise<void> {
    while (!bridgeReady()) {
      await new Promise(r => setTimeout(r, 100))
    }
  }

  // 桥接失败退避重试：搜索与分组恢复后复位计数，达上限后等待手动刷新
  function scheduleRetry() {
    if (retryTimer || retryCount >= RETRY_LIMIT) return
    retryCount += 1
    retryTimer = setTimeout(async () => {
      retryTimer = null
      const okSearch = await search(false)
      const okCollections = await refreshCollections()
      if (okSearch && okCollections) retryCount = 0
    }, 1000 * retryCount)
  }

  async function loadInitData(): Promise<boolean> {
    await waitForPywebview()
    for (let attempt = 0; attempt < RETRY_LIMIT; attempt++) {
      const data = await api('get_init_data')
      // 仅接受结构完整的响应：{} 等后端失败哨兵视为失败并重试
      if (data && Array.isArray(data.memes) && Array.isArray(data.collections)) {
        state.memes = data.memes
        state.allTags = Array.isArray(data.tags) ? data.tags : []
        state.collections = data.collections
        state.page = 1
        state.total = (await api('count_memes', '', [], state.activeCollection)) ?? state.memes.length
        state.pageCount = Math.max(1, Math.ceil(state.total / MEME_PAGE))
        state.showStartupAnimation = data.show_startup_animation !== false
        state.startupBgColor = data.startup_bg_color || '#000000'
        retryCount = 0
        return true
      }
      await new Promise(r => setTimeout(r, 500 * (attempt + 1)))
    }
    return false
  }

  async function search(resetPage = true): Promise<boolean> {
    const gen = ++searchGen
    if (resetPage) state.page = 1
    state.loading = true
    // 换页/筛选/切分组即清空选择（「全选当前页」语义）
    state.selectedIds = new Set()
    const offset = (state.page - 1) * MEME_PAGE
    let ok = false
    try {
      const [countResult, memesResult] = await Promise.all([
        api('count_memes', state.searchQuery, [...state.activeTags], state.activeCollection),
        api('search_memes', state.searchQuery, [...state.activeTags], state.activeCollection, offset, MEME_PAGE),
      ])
      // 过期响应用生成号丢弃，交给更新的请求
      if (gen !== searchGen) return true
      // 任一为 null 视为桥接失败：保留旧数据不覆盖，仅重试
      if (countResult !== null && memesResult !== null) {
        state.total = countResult
        state.pageCount = Math.max(1, Math.ceil(state.total / MEME_PAGE))
        state.memes = memesResult
        ok = true
      }
    } catch {
      if (gen !== searchGen) return true
    } finally {
      if (gen === searchGen) state.loading = false
    }
    if (!ok) scheduleRetry()
    return ok
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
    const tags = await api('get_tags')
    if (Array.isArray(tags)) state.allTags = tags
  }
  async function refreshCollections(): Promise<boolean> {
    const collections = await api('get_collections')
    if (!Array.isArray(collections)) {
      scheduleRetry()
      return false
    }
    state.collections = collections
    return true
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
