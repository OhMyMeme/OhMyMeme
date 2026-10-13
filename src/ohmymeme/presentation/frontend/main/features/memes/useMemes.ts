import { reactive } from 'vue'
import { api, bridgeReady } from '../../shared/bridge'
import type { Meme } from '../../shared/types'

// 每页抓取数量（后端接口默认 limit=200、get_init_data 初始化 200 条保持不变）
const MEME_PAGE = 200
// 连续已加载槽位窗口的常规预算（软上限；受保护视口范围可超出）
const CACHE_BUDGET = 2000
// 桥接失败退避重试上限（1s/2s/3s；成功或新需求时重置）
const RETRY_LIMIT = 3

// 滚动方向提示：决定预算裁剪时丢弃哪一侧
type CacheDirection = 'forward' | 'backward' | 'jump'

// 查询快照：页请求必须捕获发起时的筛选条件，await 后不得重读活动状态
type QuerySnapshot = {
  keyword: string
  tags: string[]
  collectionId: number | null
}

// 一次窗口需求：缺失页全部有结果（成功或失败）后统一结算提交
// 提交语义在 settleDemand 按「最终可用页是否与已提交窗口相连」重新判定，注册时不固化
type WindowDemand = {
  gen: number
  life: number
  queryGen: number
  epoch: number
  snapshot: QuerySnapshot
  targetLo: number
  targetHi: number
  protectLo: number
  protectHi: number
  direction: CacheDirection
  pages: number[]
  pending: Set<number>
  results: Map<number, Meme[] | null>
  active: boolean
  resolve: (ok: boolean) => void
  promise: Promise<boolean>
}

// pin 令牌：区分冻结提交与扩展许可（释放幂等，且不跨代次操作新集合）
type PinToken = {
  kind: 'freeze' | 'extension'
  life: number
  released: boolean
}

// 提交模式：extension 只允许相邻连续扩展（禁止远跳接管与预算裁剪）
type PinMode = 'normal' | 'extension'

const state = reactive({
  collections: [] as any[],
  activeCollection: null as number | null,
  activeTags: new Set<string>(),
  selectedIds: new Set<number>(),
  allTags: [] as string[],
  searchQuery: '',
  total: 0,
  slots: [] as (Meme | undefined)[],
  lo: 0,
  hi: 0,
  loading: false,
  rangeLoading: false,
  loadError: false,
  ready: false,
  queryGen: 0,
  rangeGen: 0,
  showStartupAnimation: true,
  startupBgColor: '#000000',
})

let disposed = false
// 生命周期代次：dispose / 显式新查询推进，卸载后旧异步写入一律拒绝
let lifeGen = 0
// 页 offset 代次：查询/总数变更与销毁时推进，旧页响应不得复用
let pageEpoch = 0
// 失效代次：invalidateRangeRequests 推进；在途种子/计数结果与退避续排必须校验，失效后一律丢弃
let rangeInvalidationGen = 0
// 已提交窗口对应的查询快照（同查询刷新失败时的回退判据）
let windowSnapshot: QuerySnapshot | null = null
let selectAllBusy = false
let retryTimer: ReturnType<typeof setTimeout> | null = null
let retryCount = 0
let retryAction: (() => void) | null = null
let collectionsRetryTimer: ReturnType<typeof setTimeout> | null = null
let collectionsRetryCount = 0
let activeDemand: WindowDemand | null = null
// pin 期间暂缓的提交（只保留当前代次的最新需求）
let deferredCommit: WindowDemand | null = null
// 冻结 pin 集合：settle 一律暂缓提交（S2 pin 语义）
const freezePins = new Set<PinToken>()
// 扩展 pin 集合：允许相邻连续补页立即提交，禁止裁剪与远跳接管
const extensionPins = new Set<PinToken>()
let lastFailed: { demand: WindowDemand; refreshCount: boolean } | null = null
let lastSpec: { targetLo: number; targetHi: number; direction: CacheDirection } | null = null
// 非分页失败描述：seed/init/count 的失败重放目标；描述捕获发起上下文，重放前按 life/查询代次/快照校验
type NonRangeFailureKind = 'seed' | 'init' | 'count'
type NonRangeFailure = {
  kind: NonRangeFailureKind
  queryGen: number
  life: number
  snapshot: QuerySnapshot
}
let nonRangeFailure: NonRangeFailure | null = null
// 同 offset 代次+查询+页的在途请求：并发需求复用同一 Promise
const pageWaiters = new Map<string, Promise<Meme[] | null>>()

export function useMemes() {
  // 等待 pywebview 桥接就绪（卸载/生命周期推进后不再等待）
  async function waitForPywebview(): Promise<void> {
    while (!bridgeReady()) {
      if (disposed) return
      await new Promise(r => setTimeout(r, 100))
    }
  }

  // 当前活动筛选的查询快照（tags 排序保证同一集合稳定比较）
  function snapshotQuery(): QuerySnapshot {
    return {
      keyword: state.searchQuery,
      tags: [...state.activeTags].sort(),
      collectionId: state.activeCollection,
    }
  }

  // 两个快照是否描述同一筛选
  function sameSnapshot(a: QuerySnapshot, b: QuerySnapshot): boolean {
    return a.keyword === b.keyword
      && a.collectionId === b.collectionId
      && a.tags.length === b.tags.length
      && a.tags.every((tag, index) => tag === b.tags[index])
  }

  // 快照是否仍是当前活动筛选
  function snapshotMatchesCurrent(snapshot: QuerySnapshot): boolean {
    return sameSnapshot(snapshot, snapshotQuery())
  }

  // 合法记录：对象且 id 为整数
  function isValidRecord(value: unknown): value is Meme {
    return !!value && typeof value === 'object' && Number.isInteger((value as Meme).id)
  }

  // 校验一页返回：必须为数组、元素合法、页内无重复 id
  function normalizeItems(value: unknown): Meme[] | null {
    if (!Array.isArray(value)) return null
    const ids = new Set<number>()
    for (const item of value) {
      if (!isValidRecord(item)) return null
      if (ids.has(item.id)) return null
      ids.add(item.id)
    }
    return value as Meme[]
  }

  // 抓取一页（按 offset 代次+查询+页号去重）：失败/非法返回 null
  function fetchPage(snapshot: QuerySnapshot, page: number): Promise<Meme[] | null> {
    const key = `${pageEpoch}:${state.queryGen}:${page}`
    const existing = pageWaiters.get(key)
    if (existing) return existing
    const tracked = (async () => {
      try {
        const result = await api('search_memes', snapshot.keyword, snapshot.tags, snapshot.collectionId, page * MEME_PAGE, MEME_PAGE)
        return normalizeItems(result)
      } catch {
        return null
      }
    })().then(items => {
      pageWaiters.delete(key)
      return items
    })
    pageWaiters.set(key, tracked)
    return tracked
  }

  // 某页在当前总数下的期望长度（末页允许短）
  function expectedLen(page: number, total: number): number {
    return Math.max(0, Math.min(MEME_PAGE, total - page * MEME_PAGE))
  }

  // 页完全落在已提交窗口内视为已加载
  function pageLoaded(page: number, total: number): boolean {
    return page * MEME_PAGE >= state.lo && Math.min((page + 1) * MEME_PAGE, total) <= state.hi
  }

  // 槽位范围换算为页范围（hiPage 为开区间）
  function pageRange(lo: number, hi: number): { loPage: number; hiPage: number } {
    return { loPage: Math.floor(lo / MEME_PAGE), hiPage: Math.ceil(hi / MEME_PAGE) }
  }

  // 两个页范围是否相交或相邻（按页判断，跨页间隙视为远跳）
  function rangesTouch(a: { loPage: number; hiPage: number }, b: { loPage: number; hiPage: number }): boolean {
    return a.loPage <= b.hiPage && b.loPage <= a.hiPage
  }

  // 页范围 outer 是否完整包含 inner
  function pageRangeContains(outer: { loPage: number; hiPage: number }, inner: { loPage: number; hiPage: number }): boolean {
    return outer.loPage <= inner.loPage && inner.hiPage <= outer.hiPage
  }

  // 规范化目标范围内缺失的页
  function neededPages(lo: number, hi: number, total: number): number[] {
    const pages: number[] = []
    for (let page = Math.floor(lo / MEME_PAGE); page < Math.ceil(hi / MEME_PAGE); page++) {
      if (!pageLoaded(page, total)) pages.push(page)
    }
    return pages
  }

  // 未显式给出方向时按目标相对当前窗口的位置推断
  function inferDirection(lo: number, hi: number): CacheDirection {
    if (lo >= state.hi) return 'forward'
    if (hi <= state.lo) return 'backward'
    return lo < state.lo ? 'backward' : 'forward'
  }

  // 清空当前退避重试状态
  function clearRetry() {
    if (retryTimer) {
      clearTimeout(retryTimer)
      retryTimer = null
    }
    retryAction = null
    retryCount = 0
  }

  // 登记非分页失败描述（失败发生时覆盖为最新目标）
  function registerNonRangeFailure(kind: NonRangeFailureKind, gen: number, life: number, snapshot: QuerySnapshot) {
    nonRangeFailure = { kind, queryGen: gen, life, snapshot }
  }

  // 清理指定 kind 的失败描述（成功路径；kind 不匹配时保留其他目标）
  function clearNonRangeFailure(kind: NonRangeFailureKind) {
    if (nonRangeFailure !== null && nonRangeFailure.kind === kind) nonRangeFailure = null
  }

  // 有限退避重试：1s/2s/3s，到顶仅保留 loadError 不再发请求（生命周期推进后旧计时器失效）
  function scheduleRetry(action: () => void, flagError = true) {
    if (disposed) return
    if (flagError) state.loadError = true
    if (retryCount >= RETRY_LIMIT) {
      state.loadError = true
      return
    }
    retryCount += 1
    retryAction = action
    const life = lifeGen
    if (retryTimer) clearTimeout(retryTimer)
    retryTimer = setTimeout(() => {
      retryTimer = null
      if (disposed || life !== lifeGen) return
      const run = retryAction
      retryAction = null
      if (run) run()
    }, 1000 * retryCount)
  }

  // rangeLoading 只在存在活动需求时为真
  function syncRangeLoading() {
    state.rangeLoading = !!activeDemand
  }

  // 是否存在冻结 pin（冻结优先于扩展 pin）
  function anyFreezePin(): boolean {
    return freezePins.size > 0
  }

  // 是否处于扩展许可：无冻结 pin 且有扩展 pin
  function extensionActive(): boolean {
    return freezePins.size === 0 && extensionPins.size > 0
  }

  // 是否存在任意 pin（缓存命中裁剪只在完全无 pin 时恢复预算）
  function anyPin(): boolean {
    return freezePins.size > 0 || extensionPins.size > 0
  }

  // 使全部 pin 令牌失效（查询/初始化接管/总数漂移/dispose）：旧 release 不得触碰新集合
  function invalidatePins() {
    freezePins.clear()
    extensionPins.clear()
  }

  // 撤销当前活动需求（旧结果不得提交）
  function supersedeDemand() {
    const demand = activeDemand
    if (!demand) return
    activeDemand = null
    demand.active = false
    syncRangeLoading()
    demand.resolve(false)
  }

  // 为需求补齐在途页抓取；全部页有结果后结算
  function ensureDemandFetches(demand: WindowDemand) {
    for (const page of demand.pages) {
      if (demand.results.has(page) || demand.pending.has(page)) continue
      demand.pending.add(page)
      void fetchPage(demand.snapshot, page).then(items => {
        demand.pending.delete(page)
        demand.results.set(page, items)
        if (demand.active && demand.pages.every(p => demand.results.has(p))) settleDemand(demand)
      })
    }
  }

  // 采纳/复用活动需求时更新其目标与保护范围（最新视口为准）
  function extendDemandSurface(demand: WindowDemand, lo: number, hi: number, direction: CacheDirection) {
    demand.targetLo = Math.min(demand.targetLo, lo)
    demand.targetHi = Math.max(demand.targetHi, hi)
    demand.protectLo = lo
    demand.protectHi = hi
    demand.direction = direction
  }

  // 注册新需求：推进窗口代次、清退旧需求、并发抓页
  function registerDemand(
    lo: number,
    hi: number,
    direction: CacheDirection,
    snapshot: QuerySnapshot,
    pages: number[],
    resetRetry: boolean,
  ): WindowDemand {
    supersedeDemand()
    if (resetRetry) clearRetry()
    state.rangeGen += 1
    const demand: WindowDemand = {
      gen: state.rangeGen,
      life: lifeGen,
      queryGen: state.queryGen,
      epoch: pageEpoch,
      snapshot,
      targetLo: lo,
      targetHi: hi,
      protectLo: lo,
      protectHi: hi,
      direction,
      pages: [...pages],
      pending: new Set(),
      results: new Map(),
      active: true,
      resolve: () => {},
      promise: Promise.resolve(false),
    }
    demand.promise = new Promise<boolean>(resolve => { demand.resolve = resolve })
    activeDemand = demand
    syncRangeLoading()
    ensureDemandFetches(demand)
    return demand
  }

  // 需求结算：代次有效才提交；pin 期间只暂缓，失败走有限退避重试
  function settleDemand(demand: WindowDemand) {
    if (!demand.active) return
    demand.active = false
    if (activeDemand === demand) activeDemand = null
    syncRangeLoading()
    const stale = disposed
      || demand.life !== lifeGen
      || demand.gen !== state.rangeGen
      || demand.epoch !== pageEpoch
      || demand.queryGen !== state.queryGen
      || !snapshotMatchesCurrent(demand.snapshot)
    if (stale) {
      demand.resolve(false)
      return
    }
    // 冻结 pin 一律暂缓（扩展 pin 不改变冻结语义）：只保留当前代次最新需求
    if (anyFreezePin()) {
      deferredCommit = demand
      demand.resolve(true)
      return
    }
    demand.resolve(commitDemand(demand, extensionActive() ? 'extension' : 'normal'))
  }

  // 重放失败需求（不经过 public search，不清选择、不推进查询代次）
  async function replayDemand(demand: WindowDemand, refreshCount: boolean): Promise<boolean> {
    if (disposed || demand.life !== lifeGen || demand.gen !== state.rangeGen) return false
    const snapshot = demand.snapshot
    if (!snapshotMatchesCurrent(snapshot)) return false
    if (refreshCount) {
      const countResult = await api('count_memes', snapshot.keyword, snapshot.tags, snapshot.collectionId)
      if (disposed || demand.life !== lifeGen || demand.gen !== state.rangeGen) return false
      if (typeof countResult === 'number' && Number.isInteger(countResult) && countResult >= 0 && countResult !== state.total) {
        applyTotalChange(countResult)
        return false
      }
    }
    if (disposed || demand.life !== lifeGen || demand.gen !== state.rangeGen) return false
    return issueRange(demand.protectLo, demand.protectHi, demand.direction, { resetRetry: false, snapshot })
  }

  // 扩展提交：头部/尾部只提交从旧边界连续成功的页，再按方向与预算裁剪（扩展许可下不裁剪）
  function applyExtension(demand: WindowDemand, allowTrim: boolean): { ok: boolean; drift: boolean } {
    const total = state.total
    const oldLo = state.lo
    const oldHi = state.hi
    let drift = false
    const writes: Array<{ page: number; items: Meme[]; from: number; to: number }> = []
    const staged = (page: number) => demand.results.get(page) ?? null
    let lo = oldLo
    let hi = oldHi
    // 头部：先补跨 lo 的页尾缺口（种子短页），再整页向前推进
    if (lo % MEME_PAGE !== 0) {
      const page = Math.floor(lo / MEME_PAGE)
      const items = staged(page)
      if (items) {
        if (items.length < expectedLen(page, total)) drift = true
        else {
          const pageEnd = Math.min(page * MEME_PAGE + items.length, total)
          if (pageEnd > lo) {
            writes.push({ page, items, from: page * MEME_PAGE, to: lo })
            lo = page * MEME_PAGE
          }
        }
      }
    }
    while (lo % MEME_PAGE === 0 && lo > 0) {
      const page = lo / MEME_PAGE - 1
      const items = staged(page)
      if (!items) break
      if (items.length < expectedLen(page, total)) { drift = true; break }
      writes.push({ page, items, from: page * MEME_PAGE, to: (page + 1) * MEME_PAGE })
      lo = page * MEME_PAGE
    }
    // 尾部：从覆盖末端连续向后推进（异常短页视为漂移，停止推进）
    while (hi < total) {
      const page = Math.floor(hi / MEME_PAGE)
      const items = staged(page)
      if (!items) break
      const expected = expectedLen(page, total)
      if (items.length < expected) { drift = true; break }
      const pageEnd = Math.min(page * MEME_PAGE + Math.min(items.length, expected), total)
      if (pageEnd <= hi) break
      writes.push({ page, items, from: hi, to: pageEnd })
      hi = pageEnd
    }
    // 结果漂移：本轮不提交，交由重试重读 count
    if (drift) return { ok: false, drift: true }
    const [wLo, wHi] = allowTrim ? trimWindow(lo, hi, demand) : [lo, hi]
    // 组装写入表并检查最终窗口是否密集、id 是否重复（跨页漂移）
    const covers: Array<{ page: number; from: number; to: number; items: Meme[] }> = []
    for (const write of writes) {
      const from = Math.max(write.from, wLo)
      const to = Math.min(write.to, wHi)
      if (from < to) covers.push({ page: write.page, from, to, items: write.items })
    }
    const freshAt = new Map<number, Meme>()
    for (const cover of covers) {
      for (let i = cover.from; i < cover.to; i++) {
        const record = cover.items[i - cover.page * MEME_PAGE]
        if (record) freshAt.set(i, record)
      }
    }
    const seen = new Set<number>()
    for (let i = wLo; i < wHi; i++) {
      const record = freshAt.get(i) ?? ((i >= oldLo && i < oldHi) ? state.slots[i] : undefined)
      if (!record) return { ok: false, drift }
      if (seen.has(record.id)) return { ok: false, drift: true }
      seen.add(record.id)
    }
    // 应用：清除窗口外的旧加载槽，写入新页（窗口内旧记录原样复用）
    for (let i = oldLo; i < wLo; i++) state.slots[i] = undefined
    for (let i = Math.max(wHi, oldLo); i < oldHi; i++) state.slots[i] = undefined
    for (const cover of covers) {
      for (let i = cover.from; i < cover.to; i++) {
        const record = cover.items[i - cover.page * MEME_PAGE]
        if (record) state.slots[i] = record
      }
    }
    state.lo = wLo
    state.hi = wHi
    return { ok: wLo <= Math.min(demand.protectLo, total) && wHi >= Math.min(demand.protectHi, total), drift: false }
  }

  // 远跳提交：目标页全部齐备后原子接管目标窗口并清空旧区间
  function applyJump(demand: WindowDemand): { ok: boolean; drift: boolean } {
    const total = state.total
    const pages = [...demand.pages].sort((a, b) => a - b)
    if (!pages.length) return { ok: false, drift: false }
    for (const page of pages) {
      const items = demand.results.get(page) ?? null
      if (!items) return { ok: false, drift: false }
      if (items.length < expectedLen(page, total)) return { ok: false, drift: true }
    }
    const first = pages[0] as number
    const last = pages[pages.length - 1] as number
    // 接管窗口必须页级密集：任何缺口都不得公布
    const stagedSet = new Set(pages)
    for (let page = first; page <= last; page++) {
      if (!stagedSet.has(page)) return { ok: false, drift: false }
    }
    const seen = new Set<number>()
    const stagedPages: Array<{ page: number; items: Meme[] }> = []
    for (const page of pages) {
      const items = demand.results.get(page) as Meme[]
      const len = Math.min(items.length, expectedLen(page, total))
      for (let i = 0; i < len; i++) {
        const record = items[i] as Meme
        if (seen.has(record.id)) return { ok: false, drift: true }
        seen.add(record.id)
      }
      stagedPages.push({ page, items })
    }
    const oldLo = state.lo
    const oldHi = state.hi
    for (let i = oldLo; i < oldHi; i++) state.slots[i] = undefined
    for (const entry of stagedPages) {
      const len = Math.min(entry.items.length, expectedLen(entry.page, total))
      const start = entry.page * MEME_PAGE
      for (let i = 0; i < len; i++) state.slots[start + i] = entry.items[i] as Meme
    }
    state.lo = first * MEME_PAGE
    state.hi = Math.min((last + 1) * MEME_PAGE, total)
    return { ok: true, drift: false }
  }

  // 提交时可用页：已提交窗口覆盖页 + 需求完整成功页（短页视为漂移）
  function availablePages(demand: WindowDemand): { set: Set<number>; drift: boolean } {
    const set = new Set<number>()
    const total = state.total
    for (let page = Math.floor(state.lo / MEME_PAGE); page < Math.ceil(state.hi / MEME_PAGE); page++) {
      if (page * MEME_PAGE >= state.lo && Math.min((page + 1) * MEME_PAGE, total) <= state.hi) set.add(page)
    }
    let drift = false
    for (const page of demand.pages) {
      const items = demand.results.get(page) ?? null
      if (!items) continue
      if (items.length < expectedLen(page, total)) {
        drift = true
        continue
      }
      set.add(page)
    }
    return { set, drift }
  }

  // 提交需求：按最终可用页与已提交窗口的关系重新判定语义（注册类型不再决定提交方式）
  // 合并后的远跳可能已连回旧窗口：此时只能按扩展提交并保留旧记录，绝不能清出孔洞
  // extension 模式只允许相邻连续扩展：远跳接管被拒绝（blocked）且不做预算裁剪
  function applyDemand(demand: WindowDemand, mode: PinMode): { ok: boolean; drift: boolean; blocked: boolean } {
    const total = state.total
    if (!(total > 0)) return { ok: false, drift: false, blocked: false }
    const { set, drift } = availablePages(demand)
    if (drift) return { ok: false, drift: true, blocked: false }
    // 受保护起点页不可用则本轮无法提交（旧窗口保留），避免把缺口公布成连续窗口
    const startPage = Math.floor(Math.max(0, Math.min(demand.protectLo, total - 1)) / MEME_PAGE)
    if (!set.has(startPage)) return { ok: false, drift: false, blocked: false }
    let runLo = startPage
    while (set.has(runLo - 1)) runLo--
    let runHi = startPage + 1
    while (set.has(runHi)) runHi++
    const oldPage = { loPage: Math.floor(state.lo / MEME_PAGE), hiPage: Math.ceil(state.hi / MEME_PAGE) }
    if (rangesTouch(oldPage, { loPage: runLo, hiPage: runHi })) {
      // 与旧窗口相连/重叠：扩展语义（只写缺失页、保留旧记录；扩展许可下不裁剪）
      const { ok, drift: extended } = applyExtension(demand, mode !== 'extension')
      return { ok, drift: extended, blocked: false }
    }
    if (mode === 'extension') return { ok: false, drift: false, blocked: true }
    // 远跳串：完整覆盖受保护范围才允许原子接管，否则保留旧窗口等待重试
    const covered = runLo * MEME_PAGE <= demand.protectLo
      && Math.min(runHi * MEME_PAGE, total) >= Math.min(demand.protectHi, total)
    if (!covered) return { ok: false, drift: false, blocked: false }
    const { ok, drift: jumped } = applyJump(demand)
    return { ok, drift: jumped, blocked: false }
  }

  // 需求提交：成功清分页类失败；扩展模式下被拒的远跳直接丢弃；失败记录并退避重放
  function commitDemand(demand: WindowDemand, mode: PinMode): boolean {
    const { ok, drift, blocked } = applyDemand(demand, mode)
    if (ok) {
      // 只清分页类失败：仍有未解决的非分页失败（seed/init/count）时保留错误入口
      if (nonRangeFailure === null) state.loadError = false
      lastFailed = null
      clearRetry()
      return true
    }
    if (blocked) return false
    lastFailed = { demand, refreshCount: drift }
    scheduleRetry(() => { void replayDemand(demand, drift) })
    return false
  }

  // 预算裁剪：受保护范围固定完整保留；先按方向从视口反方向释放整页，仍超预算时从另一端继续释放
  function trimWindow(lo: number, hi: number, hold: { direction: CacheDirection; protectLo: number; protectHi: number }): [number, number] {
    if (hi - lo <= CACHE_BUDGET) return [lo, hi]
    const protectLo = Math.max(lo, Math.min(hold.protectLo, hi))
    const protectHi = Math.max(protectLo, Math.min(hold.protectHi, hi))
    let wLo = lo
    let wHi = hi
    let steps = 0
    // 单侧被保护范围拉回（如视口回到窗口头部）时，从另一端按页释放直到回到预算或触及保护边界
    while (wHi - wLo > CACHE_BUDGET && steps < 4096) {
      steps += 1
      const trimHead = () => {
        const next = Math.min(Math.ceil((wLo + 1) / MEME_PAGE) * MEME_PAGE, protectLo)
        if (next <= wLo) return false
        wLo = next
        return true
      }
      const trimTail = () => {
        const next = Math.max(Math.floor((wHi - 1) / MEME_PAGE) * MEME_PAGE, protectHi)
        if (next >= wHi) return false
        wHi = next
        return true
      }
      const preferred = hold.direction === 'backward' ? trimTail : trimHead
      const fallback = hold.direction === 'backward' ? trimHead : trimTail
      if (!preferred() && !fallback()) break
    }
    if (wHi <= wLo) return [lo, hi]
    return [wLo, wHi]
  }

  // 总数变化：offset 可能整体漂移，旧窗口数据全部作废并重新加载活动目标
  function applyTotalChange(newTotal: number) {
    if (disposed || newTotal === state.total) return
    state.total = newTotal
    if (newTotal > state.slots.length) {
      for (let i = state.slots.length; i < newTotal; i++) state.slots.push(undefined)
    } else if (newTotal < state.slots.length) {
      state.slots.length = newTotal
    }
    // 前部插入/删除会让旧页拼到新后续页：推进 offset 代次并清空窗口，全部按新偏移重取
    for (let i = 0; i < newTotal; i++) if (state.slots[i] !== undefined) state.slots[i] = undefined
    state.lo = 0
    state.hi = 0
    pageEpoch += 1
    pageWaiters.clear()
    state.rangeGen += 1
    supersedeDemand()
    invalidatePins()
    deferredCommit = null
    lastFailed = null
    nonRangeFailure = null
    syncRangeLoading()
    const spec = lastSpec
    if (spec && state.total > 0) {
      const options: { resetRetry: boolean; snapshot?: QuerySnapshot } = { resetRetry: false }
      if (windowSnapshot !== null) options.snapshot = windowSnapshot
      void issueRange(spec.targetLo, spec.targetHi, spec.direction, options)
    }
  }

  // 规范化窗口请求：按页对齐、clamp 到 [0,total]；NaN/逆序/空库/加载中均 no-op
  function issueRange(
    start: number,
    end: number,
    directionHint: CacheDirection | undefined,
    options: { resetRetry: boolean; snapshot?: QuerySnapshot },
  ): Promise<boolean> {
    if (disposed) return Promise.resolve(false)
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return Promise.resolve(true)
    if (state.loading) return Promise.resolve(true)
    const total = state.total
    if (!(total > 0)) return Promise.resolve(true)
    const snapshot = options.snapshot ?? snapshotQuery()
    if (!snapshotMatchesCurrent(snapshot)) return Promise.resolve(true)
    const qLo = Math.max(0, Math.min(total, Math.floor(start / MEME_PAGE) * MEME_PAGE))
    const qHi = Math.max(0, Math.min(total, Math.ceil(end / MEME_PAGE) * MEME_PAGE))
    if (qHi <= qLo) return Promise.resolve(true)
    const direction = directionHint ?? inferDirection(qLo, qHi)
    lastSpec = { targetLo: qLo, targetHi: qHi, direction }
    const needed = neededPages(qLo, qHi, total)
    const active = activeDemand
    const activeUsable = !!active && active.active && active.gen === state.rangeGen
      && active.queryGen === state.queryGen && active.epoch === pageEpoch
    if (!needed.length) {
      // 全部命中缓存：该范围已满足，本次请求即最新权威。
      // 若在途需求、暂缓提交或退避重试的目标并不覆盖本次请求（含远跳失败结算后仅剩重试计时），
      // 说明用户已回到缓存区：撤销旧接管与重试并推进窗口代次，旧远跳（含其 1s 退避重放）不得再延迟接管
      const activeCovers = activeUsable
        && pageRangeContains(pageRange(active.targetLo, active.targetHi), pageRange(qLo, qHi))
      const deferred = deferredCommit
      const staleDeferred = !!deferred
        && !pageRangeContains(pageRange(deferred.targetLo, deferred.targetHi), pageRange(qLo, qHi))
      if (activeUsable && !activeCovers) {
        supersedeDemand()
        if (staleDeferred) deferredCommit = null
        lastFailed = null
        clearRetry()
        state.rangeGen += 1
        // 只清分页类失败：未解决的非分页失败（seed/init/count）保留错误入口
        if (nonRangeFailure === null) state.loadError = false
      } else if (lastFailed !== null || retryTimer !== null || staleDeferred) {
        if (staleDeferred) deferredCommit = null
        lastFailed = null
        clearRetry()
        state.rangeGen += 1
        if (nonRangeFailure === null) state.loadError = false
      }
      // 缓存命中同样恢复预算：无 pin 时按本次视口裁剪超长窗口（扩展 pin 释放后的长拖窗口回收）
      if (!anyPin() && state.hi - state.lo > CACHE_BUDGET) {
        const [wLo, wHi] = trimWindow(state.lo, state.hi, { direction, protectLo: qLo, protectHi: qHi })
        if (wLo > state.lo || wHi < state.hi) {
          for (let i = state.lo; i < wLo; i++) state.slots[i] = undefined
          for (let i = Math.max(wHi, state.lo); i < state.hi; i++) state.slots[i] = undefined
          state.lo = wLo
          state.hi = wHi
        }
      }
      return Promise.resolve(true)
    }
    if (activeUsable) {
      const covers = needed.every(page => active.pages.includes(page))
      const touches = rangesTouch(pageRange(active.targetLo, active.targetHi), pageRange(qLo, qHi))
      if (covers || touches) {
        // 命中/相邻：扩展既有需求，不重抓命中页
        extendDemandSurface(active, qLo, qHi, direction)
        if (!covers) {
          const fresh = needed.filter(page => !active.pages.includes(page))
          active.pages.push(...fresh)
          ensureDemandFetches(active)
        }
        return waitDemand(active, qLo, qHi)
      }
    }
    const demand = registerDemand(qLo, qHi, direction, snapshot, needed, options.resetRetry)
    return waitDemand(demand, qLo, qHi)
  }

  // 等待需求结算；失败时若当前窗口已覆盖该请求也视为成功
  function waitDemand(demand: WindowDemand, lo: number, hi: number): Promise<boolean> {
    return demand.promise.then(ok => {
      if (ok) return true
      if (disposed || state.queryGen !== demand.queryGen) return false
      const total = state.total
      return state.lo <= Math.min(lo, total) && state.hi >= Math.min(hi, total)
    })
  }

  // 窗口加载入口：视觉行换算出的槽位范围 [start,end)，end 为开区间
  function ensureRange(start: number, end: number, direction?: CacheDirection): Promise<boolean> {
    return issueRange(start, end, direction, { resetRetry: true })
  }

  // 读取槽位；区间外与越界一律 undefined
  function slot(index: number): Meme | undefined {
    if (!Number.isInteger(index) || index < 0 || index >= state.total) return undefined
    return state.slots[index]
  }

  // 当前已提交区间的密集有序副本（不 filter 孔洞、不改变绝对起点）
  function loadedSlice(): { start: number; items: Meme[] } {
    return { start: state.lo, items: state.slots.slice(state.lo, state.hi) as Meme[] }
  }

  // 整段置换已提交区间：长度与 id 集合必须一致，按绝对索引覆盖
  function setLoadedSlice(start: number, items: Meme[]): boolean {
    if (disposed) return false
    const lo = state.lo
    const hi = state.hi
    if (start !== lo || !Array.isArray(items) || items.length !== hi - lo || hi <= lo) return false
    const current = new Set<number>()
    for (let i = lo; i < hi; i++) {
      const record = state.slots[i]
      if (!record) return false
      current.add(record.id)
    }
    const incoming = new Set<number>()
    for (const item of items) {
      if (!isValidRecord(item) || !current.has(item.id) || incoming.has(item.id)) return false
      incoming.add(item.id)
    }
    if (incoming.size !== current.size) return false
    for (let i = 0; i < items.length; i++) state.slots[lo + i] = items[i]
    return true
  }

  // 执行一次种子加载：并发读取 count 与第 0 页；同查询刷新失败保留旧窗口
  async function runSeed(gen: number, snapshot: QuerySnapshot, life: number): Promise<boolean> {
    const invalidation = rangeInvalidationGen
    const [countResult, pageResult] = await Promise.all([
      api('count_memes', snapshot.keyword, snapshot.tags, snapshot.collectionId),
      fetchPage(snapshot, 0),
    ])
    if (disposed || life !== lifeGen || gen !== state.queryGen) return true
    // 失效（拖拽保存前 invalidateRangeRequests）后到达的种子结果整体丢弃：不提交窗口、不登记失败、不续排；
    // 此刻 loading 由本次种子持有（新查询会先经上一行代次校验），释放以恢复分页
    if (invalidation !== rangeInvalidationGen) {
      state.loading = false
      return true
    }
    if (!snapshotMatchesCurrent(snapshot)) {
      // 查询已改变但尚未触发新 search：丢弃本次结果，交给新的查询
      state.loading = false
      return false
    }
    const countOk = typeof countResult === 'number' && Number.isInteger(countResult) && countResult >= 0
    const seedTotal = countOk ? (countResult as number) : 0
    const shortSeed = countOk && seedTotal > 0 && pageResult !== null && pageResult.length < Math.min(MEME_PAGE, seedTotal)
    if (!countOk || pageResult === null || shortSeed) {
      state.loading = false
      const fallback = windowSnapshot !== null && sameSnapshot(windowSnapshot, snapshot)
      if (!fallback) {
        // 不同查询：清空活动缓存，旧记录不对外暴露
        windowSnapshot = null
        state.total = 0
        state.slots = []
        state.lo = 0
        state.hi = 0
      }
      state.loadError = true
      registerNonRangeFailure('seed', gen, life, snapshot)
      scheduleRetry(() => { void runSeed(gen, snapshot, life) })
      return false
    }
    const slots = new Array<Meme | undefined>(seedTotal).fill(undefined)
    const count = Math.min(pageResult.length, seedTotal)
    for (let i = 0; i < count; i++) slots[i] = pageResult[i]
    state.slots = slots
    state.total = seedTotal
    state.lo = 0
    state.hi = count
    state.loading = false
    state.loadError = false
    state.ready = true
    windowSnapshot = snapshot
    // 种子接管窗口：使在途/暂缓需求与旧页请求过期
    pageEpoch += 1
    pageWaiters.clear()
    state.rangeGen += 1
    supersedeDemand()
    invalidatePins()
    deferredCommit = null
    lastFailed = null
    clearRetry()
    clearNonRangeFailure('seed')
    return true
  }

  // 显式查询：推进代次、清选择与重试，清空不同查询的活动缓存后重新种子加载
  async function search(): Promise<boolean> {
    if (disposed) {
      // 重新挂载后的显式查询开启新生命周期；旧生命周期在途写入由 lifeGen 校验拒绝
      disposed = false
      lifeGen += 1
    }
    const life = lifeGen
    clearRetry()
    supersedeDemand()
    invalidatePins()
    deferredCommit = null
    lastFailed = null
    lastSpec = null
    nonRangeFailure = null
    pageEpoch += 1
    pageWaiters.clear()
    state.queryGen += 1
    state.rangeGen += 1
    state.selectedIds = new Set<number>()
    state.loading = true
    state.loadError = false
    syncRangeLoading()
    const snapshot = snapshotQuery()
    if (windowSnapshot !== null && !sameSnapshot(windowSnapshot, snapshot)) {
      windowSnapshot = null
      state.total = 0
      state.slots = []
      state.lo = 0
      state.hi = 0
    }
    return await runSeed(state.queryGen, snapshot, life)
  }

  // 初始化 count 失败的退避重读：成功后按总数变化处理（登记/清理/续排均须上下文与失效代次仍有效）
  async function refreshCountAfterInit(gen: number, snapshot: QuerySnapshot, life: number, invalidation: number): Promise<boolean> {
    if (disposed || life !== lifeGen || gen !== state.queryGen || invalidation !== rangeInvalidationGen || !snapshotMatchesCurrent(snapshot)) return false
    const countResult = await api('count_memes', snapshot.keyword, snapshot.tags, snapshot.collectionId)
    if (disposed || life !== lifeGen || gen !== state.queryGen || invalidation !== rangeInvalidationGen || !snapshotMatchesCurrent(snapshot)) return false
    if (typeof countResult === 'number' && Number.isInteger(countResult) && countResult >= 0) {
      clearRetry()
      applyTotalChange(countResult)
      // count 成功必须退出错误态：即使总数未变化也清错误与失败描述
      state.loadError = false
      clearNonRangeFailure('count')
      return true
    }
    registerNonRangeFailure('count', gen, life, snapshot)
    return false
  }

  // 安排 count 重读（与普通重试共用有限退避预算；首屏已有种子数据，不在重试期间报错）
  function scheduleCountRefresh(gen: number, snapshot: QuerySnapshot, life: number) {
    const invalidation = rangeInvalidationGen
    scheduleRetry(() => {
      void refreshCountAfterInit(gen, snapshot, life, invalidation).then(ok => {
        // 上下文与失效代次仍有效才续排：查询换代/失效后的旧链不得继续消耗退避预算并置位 loadError
        if (!ok && !disposed && life === lifeGen && gen === state.queryGen && invalidation === rangeInvalidationGen) {
          scheduleCountRefresh(gen, snapshot, life)
        }
      })
    }, false)
  }

  // 启动初始化：读取配置与首屏数据，种子接入同模型（异步期间查询/生命周期代次变化则丢弃）
  async function loadInitData(): Promise<boolean> {
    await waitForPywebview()
    // dispose 后不得复活：仅在当前生命周期内执行；显式 search 才开启新生命周期
    if (disposed) return false
    const life = lifeGen
    const gen = state.queryGen
    const snapshot = snapshotQuery()
    for (let attempt = 0; attempt < RETRY_LIMIT; attempt++) {
      const data = await api('get_init_data')
      if (disposed || life !== lifeGen) return false
      // 查询已换代/筛选已变：本次初始化响应整体丢弃（不读字段、不写状态、不登记失败）
      if (gen !== state.queryGen || !snapshotMatchesCurrent(snapshot)) return true
      const initMemes = data?.['memes']
      const initCollections = data?.['collections']
      if (data && Array.isArray(initMemes) && Array.isArray(initCollections)) {
        const seedItems = normalizeItems(initMemes) ?? []
        const countResult = await api('count_memes', snapshot.keyword, snapshot.tags, snapshot.collectionId)
        if (disposed || life !== lifeGen) return false
        // 异步返回后写状态前统一校验上下文：旧初始化不得写入新查询的元数据/窗口
        if (gen !== state.queryGen || !snapshotMatchesCurrent(snapshot)) return true
        const rawTags = data['tags']
        state.allTags = Array.isArray(rawTags)
          ? rawTags.filter((tag): tag is string => typeof tag === 'string')
          : []
        state.collections = [...initCollections]
        state.showStartupAnimation = data['show_startup_animation'] !== false
        state.startupBgColor = (data['startup_bg_color'] as string) || '#000000'
        const countOk = typeof countResult === 'number' && Number.isInteger(countResult) && countResult >= 0
        const total = countOk ? (countResult as number) : seedItems.length
        const slots = new Array<Meme | undefined>(total).fill(undefined)
        const count = Math.min(seedItems.length, total)
        for (let i = 0; i < count; i++) slots[i] = seedItems[i]
        state.slots = slots
        state.total = total
        state.lo = 0
        state.hi = count
        state.loading = false
        state.loadError = false
        state.ready = true
        windowSnapshot = snapshot
        pageEpoch += 1
        pageWaiters.clear()
        state.rangeGen += 1
        supersedeDemand()
        invalidatePins()
        deferredCommit = null
        lastFailed = null
        clearRetry()
        clearNonRangeFailure('init')
        if (!countOk) {
          registerNonRangeFailure('count', gen, life, snapshot)
          scheduleCountRefresh(gen, snapshot, life)
        }
        return true
      }
      if (disposed || life !== lifeGen) return false
      await new Promise(r => setTimeout(r, 500 * (attempt + 1)))
    }
    if (disposed || life !== lifeGen) return false
    // 仅当查询上下文仍有效才登记初始化失败：旧初始化的最终失败不得污染新查询的错误态
    if (gen !== state.queryGen || !snapshotMatchesCurrent(snapshot)) return true
    // 初始化最终失败：进入错误态，空库文案不得出现
    state.loading = false
    state.loadError = true
    registerNonRangeFailure('init', gen, life, snapshot)
    return false
  }

  // 手动重试入口：优先按 kind 重放非分页失败（seed/init/count），再重放最近失败需求，最后按最近目标重新请求
  async function retryRange(): Promise<boolean> {
    if (disposed) return false
    clearRetry()
    const failure = nonRangeFailure
    if (failure !== null) {
      nonRangeFailure = null
      const valid = failure.life === lifeGen
        && failure.queryGen === state.queryGen
        && snapshotMatchesCurrent(failure.snapshot)
      if (valid) {
        if (failure.kind === 'seed') {
          state.loading = true
          state.loadError = false
          return await runSeed(failure.queryGen, failure.snapshot, failure.life)
        }
        if (failure.kind === 'init') {
          state.loading = true
          state.loadError = false
          return await loadInitData()
        }
        return await refreshCountAfterInit(failure.queryGen, failure.snapshot, failure.life, rangeInvalidationGen)
      }
    }
    const failed = lastFailed
    if (failed) {
      lastFailed = null
      return await replayDemand(failed.demand, failed.refreshCount)
    }
    if (lastSpec) {
      return await issueRange(lastSpec.targetLo, lastSpec.targetHi, lastSpec.direction, { resetRetry: true })
    }
    return true
  }

  // 释放冻结 pin 后提交暂缓需求（代次失效则丢弃；扩展许可下禁止远跳接管）
  function applyDeferredCommit() {
    const demand = deferredCommit
    deferredCommit = null
    if (!demand || demand.life !== lifeGen) return
    const stale = demand.gen !== state.rangeGen
      || demand.epoch !== pageEpoch
      || demand.queryGen !== state.queryGen
      || !snapshotMatchesCurrent(demand.snapshot)
    if (stale) return
    commitDemand(demand, extensionActive() ? 'extension' : 'normal')
  }

  // 申请窗口 pin：缺省冻结提交；allowExtension 允许相邻连续补页立即提交（拖拽扩展期间）
  function pinLoadedRange(options?: { allowExtension?: boolean }): () => void {
    const kind: 'freeze' | 'extension' = options?.allowExtension ? 'extension' : 'freeze'
    const token: PinToken = { kind, life: lifeGen, released: false }
    if (kind === 'freeze') freezePins.add(token)
    else extensionPins.add(token)
    return () => {
      if (token.released) return
      token.released = true
      // 失效或已清理的 token 不属于当前集合：只标记释放，不触碰新会话
      const held = kind === 'freeze' ? freezePins.delete(token) : extensionPins.delete(token)
      if (!held || disposed || token.life !== lifeGen) return
      if (anyFreezePin()) return
      // 冻结全部释放：提交暂缓需求（扩展 pin 仍活动时按扩展语义）
      if (kind === 'freeze') applyDeferredCommit()
    }
  }

  // 失效在途页需求（拖拽保存前调用）：推进页/窗口/失效代次并清等待、暂缓、失败与重试，不动数据与选择
  function invalidateRangeRequests() {
    clearRetry()
    supersedeDemand()
    deferredCommit = null
    lastFailed = null
    lastSpec = null
    nonRangeFailure = null
    rangeInvalidationGen += 1
    pageEpoch += 1
    pageWaiters.clear()
    state.rangeGen += 1
  }

  // 卸载清理：清计时器、使在途请求过期（桥接无 Abort，只丢弃过期结果）
  function dispose() {
    disposed = true
    lifeGen += 1
    clearRetry()
    if (collectionsRetryTimer) {
      clearTimeout(collectionsRetryTimer)
      collectionsRetryTimer = null
    }
    collectionsRetryCount = 0
    pageEpoch += 1
    pageWaiters.clear()
    supersedeDemand()
    deferredCommit = null
    lastFailed = null
    nonRangeFailure = null
    invalidatePins()
    selectAllBusy = false
    state.queryGen += 1
    state.rangeGen += 1
    state.loading = false
    state.rangeLoading = false
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

  // 标签列表刷新（失败静默保留旧值；生命周期推进后丢弃结果）
  async function refreshTags() {
    const life = lifeGen
    const tags = await api('get_tags')
    if (disposed || life !== lifeGen) return
    if (Array.isArray(tags)) state.allTags = [...tags]
  }

  // 分组刷新：失败走独立有限退避重试，不无条件触发整库 search
  function scheduleCollectionsRetry() {
    if (disposed || collectionsRetryTimer || collectionsRetryCount >= RETRY_LIMIT) return
    collectionsRetryCount += 1
    const life = lifeGen
    collectionsRetryTimer = setTimeout(() => {
      collectionsRetryTimer = null
      if (disposed || life !== lifeGen) return
      void refreshCollections()
    }, 1000 * collectionsRetryCount)
  }

  async function refreshCollections(): Promise<boolean> {
    const life = lifeGen
    const collections = await api('get_collections')
    if (disposed || life !== lifeGen) return false
    if (!Array.isArray(collections)) {
      scheduleCollectionsRetry()
      return false
    }
    collectionsRetryCount = 0
    if (collectionsRetryTimer) {
      clearTimeout(collectionsRetryTimer)
      collectionsRetryTimer = null
    }
    state.collections = [...collections]
    return true
  }

  async function copyMeme(id: number): Promise<boolean> {
    const result = await api('copy_meme', id)
    return !!result?.['ok']
  }

  async function reorderMemes(orderedIds: number[]): Promise<boolean> {
    const collectionId = state.activeCollection && state.activeCollection > 0 ? state.activeCollection : null
    const result = collectionId
      ? await api('reorder_collection_members', collectionId, orderedIds)
      : await api('reorder_memes', orderedIds)
    return !!result
  }

  // 全选：按当前查询取全部结果 id（只写 id Set、不填 slots；旧代次/旧生命周期迟到结果不写入）
  async function selectAll(): Promise<boolean> {
    if (selectAllBusy) return false
    selectAllBusy = true
    const life = lifeGen
    const gen = state.queryGen
    const snapshot = snapshotQuery()
    try {
      const result = await api('search_memes', snapshot.keyword, snapshot.tags, snapshot.collectionId, 0, 999999)
      if (disposed || life !== lifeGen || gen !== state.queryGen || !snapshotMatchesCurrent(snapshot)) return false
      if (!Array.isArray(result)) return false
      const ids = new Set<number>()
      for (const item of result) {
        if (isValidRecord(item)) ids.add(item.id)
      }
      state.selectedIds = ids
      return true
    } finally {
      selectAllBusy = false
    }
  }
  function clearSelection() { state.selectedIds = new Set<number>() }

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
    search,
    ensureRange,
    slot,
    loadedSlice,
    setLoadedSlice,
    retryRange,
    pinLoadedRange,
    invalidateRangeRequests,
    dispose,
    setSearch,
    toggleTag,
    setActiveCollection,
    refreshTags,
    refreshCollections,
    copyMeme,
    reorderMemes,
    canReorder,
    startNativeDrag,
    selectAll,
    clearSelection,
    loadInitData,
    waitForPywebview,
    MEME_PAGE,
  }
}
