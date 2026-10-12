<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, h, watch, nextTick } from 'vue'
import { Virtualizer } from 'virtua/vue'
import { useMemes } from '../features/memes/useMemes'
import { useDragSort } from '../features/sorting/useDragSort'
import { useContextMenu, type MenuItem } from '../features/dialogs/useContextMenu'
import { useCollectionBuilder } from '../features/collections/useCollectionBuilder'
import ContextMenu from '../features/dialogs/ContextMenu.vue'
import CollectionBuilder from '../features/collections/CollectionBuilder.vue'
import CollectionTreeNode from '../features/collections/CollectionTreeNode.vue'
import ConfirmDialog from '../features/dialogs/ConfirmDialog.vue'
import ImportMenu from '../features/imports/ImportMenu.vue'
import InputDialog from '../features/dialogs/InputDialog.vue'
import SyncOverlay from '../features/sync/SyncOverlay.vue'
import TagEditor from '../features/tags/TagEditor.vue'
import UpdateDialog from '../features/updates/UpdateDialog.vue'
import type { Meme } from '../shared/types'
import { api } from '../shared/bridge'
import { NButton, NInput, NTag, NModal, NSpin, NDropdown, useMessage, type DropdownMixedOption } from 'naive-ui'
import { ArrowUpDown, PanelLeft, X, Heart, Folder, ImagePlus, Check, Ellipsis, CloudUpload, CloudDownload, RefreshCw, Settings } from '@lucide/vue'
import { lanConfirmVisible, lanConfirmDevice, confirmLanDevice, onLanConfirmShowChange } from '../features/lan/showLanDeviceConfirm'

// 后端 evaluate_js 刷新入口（与 main.ts 声明一致；main.ts 不在类型检查范围）
declare global {
  interface Window {
    refreshMemes: () => void
    refreshTags: () => void
    refreshCollections: () => void
  }
}

const { state, search, ensureRange, slot, loadedSlice, setLoadedSlice, pinLoadedRange, dispose, setSearch, toggleTag, setActiveCollection, refreshTags, refreshCollections, copyMeme, reorderMemes, canReorder, startNativeDrag, selectAll, clearSelection, loadInitData } = useMemes()
const ctx = useContextMenu()
const cb = useCollectionBuilder()
const message = useMessage()

// ── 虚拟网格：固定卡片尺寸 + 行级 Virtualizer（folder-grid 不虚拟化，作为头块计入 startMargin） ──
// 卡片等宽等高：列数由容器宽按最小卡宽 112px / 间隙 10px 推导，卡高先用几何推导再由真实卡尺寸校准
const MEME_GAP = 10
const MEME_MIN_WIDTH = 112
const CARD_FRAME = 28 // 边框 2px×2 + 单行名称（16px 行高 + 上下 padding 12px）
const RANGE_BUFFER = 200 // 与 Virtualizer bufferSize 一致的视口外缓冲像素
const SCROLL_END_CLEANUP_DELAY = 120

const gridWrapRef = ref<HTMLElement | null>(null)
const folderGridRef = ref<HTMLElement | null>(null)
const virtualizerRef = ref<any>(null)
const dragSelectRef = ref<any>(null)
const virtualReady = ref(true)
const cols = ref(4)
const cardHeight = ref(0)
const startMargin = ref(0)
const layoutKey = ref(0)
const scrolling = ref(false)
let layoutEpoch = 0
let layoutRaf = 0
let rangeRaf = 0
// 组件级卸载门禁：卸载后的异步续体不得再调用 search/ensureRange 等模型操作
let windowUnmounted = false
let gridResizeObserver: ResizeObserver | null = null
let folderResizeObserver: ResizeObserver | null = null

interface VirtualRow {
  start: number
  end: number
  key: string
}
interface RowSlot {
  index: number
  meme: Meme | undefined
}

const rowPitch = computed(() => cardHeight.value + MEME_GAP)
const rowCount = computed(() => (state.total > 0 ? Math.ceil(state.total / Math.max(1, cols.value)) : 0))

// 行 key：有数据用稳定锚（该行首个已加载记录 id），全占位行用查询/布局内复用的 opaque token
let tokenSeq = 0
let tokenEpoch = ''
const placeholderTokens = new Map<number, string>()
const frozenRowKeys = new Map<number, string>()

function placeholderToken(index: number): string {
  const epoch = state.queryGen + ':' + layoutEpoch
  if (epoch !== tokenEpoch) {
    tokenEpoch = epoch
    placeholderTokens.clear()
  }
  let token = placeholderTokens.get(index)
  if (!token) {
    token = 'p' + (++tokenSeq)
    placeholderTokens.set(index, token)
  }
  return token
}

function rowKey(index: number, start: number, end: number): string {
  const frozen = frozenRowKeys.get(index)
  if (frozen) return frozen
  let anchor: number | null = null
  for (let i = start; i < end; i++) {
    const record = slot(i)
    if (record) { anchor = record.id; break }
  }
  const base = 'r' + layoutEpoch + '-' + cols.value + '-q' + state.queryGen
  // key 字面不使用裸行号：锚 id 或查询/布局内分配的 opaque token
  return anchor !== null ? base + '-m' + anchor : base + '-' + placeholderToken(index)
}

const rows = computed<VirtualRow[]>(() => {
  const width = Math.max(1, cols.value)
  const count = rowCount.value
  const out: VirtualRow[] = []
  for (let index = 0; index < count; index++) {
    const start = index * width
    const end = Math.min(start + width, state.total)
    out.push({ start, end, key: rowKey(index, start, end) })
  }
  return out
})

// 单行槽位描述：只在本行渲染时构建，不为 total 复制记录
function rowSlots(row: VirtualRow): RowSlot[] {
  const list: RowSlot[] = []
  for (let i = row.start; i < row.end; i++) list.push({ index: i, meme: slot(i) })
  return list
}

// 行外壳高度 = 卡高 + 行距间隙（库只允许补充 style 属性，不能覆盖其 top/position）
function rowItemProps(): { style: { height: string } } {
  return { style: { height: rowPitch.value + 'px' } }
}

const gridStyle = computed(() => ({
  '--meme-cols': String(Math.max(1, cols.value)),
  ...(cardHeight.value > 0 ? { '--meme-card-height': cardHeight.value + 'px' } : {}),
}))

// 虚拟化前提：ResizeObserver 与元素滚动方法（缺失时显示不可用提示，不静默挂库）
const virtualCache = ref<any>(null)
const virtualCacheLength = ref(0)
const virtualCacheForRender = computed(() => {
  if (!virtualCache.value) return undefined
  return virtualCacheLength.value === rows.value.length ? virtualCache.value : undefined
})

function finiteNumber(value: string): number {
  const parsed = parseFloat(value)
  return Number.isFinite(parsed) ? parsed : 0
}

// startMargin：虚拟列表起点相对滚动容器的内容坐标（含顶部 padding、folder 头块与祖先布局）
function measureStartMargin(wrap: HTMLElement, grid: HTMLElement): number {
  return Math.max(0, grid.getBoundingClientRect().top - wrap.getBoundingClientRect().top - wrap.clientTop + wrap.scrollTop)
}

// 卡高校准：优先用已挂载真卡的图片 + 名称实际高度加边框推导；否则退回几何估算
function measureCardHeight(container: HTMLElement, fallback: number): number {
  for (const card of Array.from(container.querySelectorAll<HTMLElement>('.meme-card:not(.dragging)'))) {
    const img = card.querySelector('img')
    const name = card.querySelector('.meme-name')
    if (!img || !name) continue
    const style = getComputedStyle(card)
    const borderY = finiteNumber(style.borderTopWidth) + finiteNumber(style.borderBottomWidth)
    const content = img.offsetHeight + name.offsetHeight
    if (content > 0) return Math.round(content + borderY)
  }
  return fallback
}

// 记录首个可见槽位与行内像素偏移（布局重建后恢复位置）
function captureScrollAnchor(): { slot: number; offset: number } | null {
  const wrap = gridWrapRef.value
  const handle = virtualizerRef.value
  if (!wrap || !handle || !(rowPitch.value > 0)) return null
  const firstRow = Math.max(0, handle.findItemIndex(wrap.scrollTop))
  const rowOffset = handle.getItemOffset(firstRow)
  return { slot: firstRow * cols.value, offset: wrap.scrollTop - startMargin.value - rowOffset }
}

function restoreScrollAnchor(anchor: { slot: number; offset: number } | null) {
  const wrap = gridWrapRef.value
  if (!wrap || !anchor || !(rowPitch.value > 0)) return
  const row = Math.floor(anchor.slot / Math.max(1, cols.value))
  wrap.scrollTop = startMargin.value + row * rowPitch.value + anchor.offset
}

// 测量并更新列数/卡高/startMargin；布局变化时重建 Virtualizer 并恢复可见位置
function refreshLayout() {
  const wrap = gridWrapRef.value
  const grid = document.getElementById('meme-grid')
  if (!wrap || !grid) return
  const style = getComputedStyle(wrap)
  const paddingX = finiteNumber(style.paddingLeft) + finiteNumber(style.paddingRight)
  const contentWidth = Math.max(0, wrap.clientWidth - paddingX)
  const nextCols = Math.max(1, Math.floor((contentWidth + MEME_GAP) / (MEME_MIN_WIDTH + MEME_GAP)))
  const cellWidth = (contentWidth - (nextCols - 1) * MEME_GAP) / nextCols
  const estimate = Math.max(1, Math.round(cellWidth + CARD_FRAME))
  // 未切换列数时才信任实测卡高：旧列数下的卡高不能用于新布局
  const nextCardHeight = nextCols === cols.value ? measureCardHeight(grid, estimate) : estimate
  const nextStartMargin = measureStartMargin(wrap, grid)
  const layoutChanged = nextCols !== cols.value || nextCardHeight !== cardHeight.value
  const marginChanged = nextStartMargin !== startMargin.value
  if (!layoutChanged && !marginChanged) return
  // 拖拽期间几何变化：统一取消并回滚（旧坐标/索引全部失效），再按新几何重建
  if (visibleDragSession) cancelVisibleDrag()
  if (layoutChanged && state.total > 0) {
    // 先记录可见位置，再改变列数/卡高重建虚拟izer，nextTick 后恢复
    const anchor = captureScrollAnchor()
    cols.value = nextCols
    cardHeight.value = nextCardHeight
    startMargin.value = nextStartMargin
    layoutEpoch += 1
    virtualCache.value = null
    virtualCacheLength.value = 0
    layoutKey.value += 1
    void nextTick(() => {
      restoreScrollAnchor(anchor)
      requestVisibleRange()
      scheduleSelectionCheck()
      // 新列数/卡高落盘后按新布局校准一次
      scheduleLayoutRefresh()
    })
    return
  }
  cols.value = nextCols
  cardHeight.value = nextCardHeight
  startMargin.value = nextStartMargin
  requestVisibleRange()
}

function scheduleLayoutRefresh() {
  if (layoutRaf) return
  layoutRaf = requestAnimationFrame(() => {
    layoutRaf = 0
    refreshLayout()
  })
}

function clampRow(value: number, total: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(total - 1, Math.floor(value)))
}

// 视口 + 200px buffer 覆盖的槽位范围驱动 ensureRange；0 视口/空库/拖拽期间不请求
function requestVisibleRange() {
  if (windowUnmounted) return
  if (rangeRaf) return
  rangeRaf = requestAnimationFrame(() => {
    rangeRaf = 0
    requestVisibleRangeNow()
  })
}

function requestVisibleRangeNow() {
  if (visibleDragSession) return
  if (state.total === 0) return
  const wrap = gridWrapRef.value
  if (!wrap) return
  const pitch = rowPitch.value
  const width = Math.max(1, cols.value)
  const totalRows = rowCount.value
  if (!(pitch > 0) || totalRows <= 0) return
  const viewport = wrap.clientHeight
  // ResizeObserver 首帧可能为 0：不据 0 视口错误裁剪
  if (!(viewport > 0)) return
  const scrollTop = wrap.scrollTop
  const handle = virtualizerRef.value
  let firstRow = 0
  let lastRow = totalRows - 1
  if (handle) {
    // findItemIndex 内部已扣 startMargin：传滚动容器偏移即可
    firstRow = clampRow(handle.findItemIndex(scrollTop - RANGE_BUFFER), totalRows)
    lastRow = clampRow(handle.findItemIndex(scrollTop + viewport + RANGE_BUFFER), totalRows)
  } else {
    // 固定行距回退公式：容器内坐标 = 滚动偏移 − startMargin
    const start = scrollTop - startMargin.value - RANGE_BUFFER
    const end = scrollTop + viewport + RANGE_BUFFER - startMargin.value
    if (end <= 0) return
    firstRow = clampRow(Math.floor(start / pitch), totalRows)
    lastRow = clampRow(Math.floor(end / pitch), totalRows)
  }
  if (lastRow < firstRow) return
  const slotStart = firstRow * width
  const slotEnd = Math.min(state.total, (lastRow + 1) * width)
  if (slotEnd <= slotStart) return
  void ensureRange(slotStart, slotEnd)
}

function onVirtualScroll() {
  scrolling.value = true
  if (visibleDragSession) cancelVisibleDrag()
  requestVisibleRange()
}

function onVirtualScrollEnd() {
  scrolling.value = false
  requestVisibleRange()
  scheduleSelectionCheck()
}

function onVirtualResize() {
  requestVisibleRange()
}

// ── 框选 registry 受控清理（依赖未修改：卸载 option 不会自动出栈，停滚后重挂清理） ──
const selectionEpoch = ref(0)
let selectionCheckTimer: ReturnType<typeof setTimeout> | null = null
let mountedFingerprint = ''
let pendingSelectionReset = false

// 已挂载真卡指纹（布局代次 + 行 key + 行内真卡 id）；断开节点不计入
function mountedRealCardFingerprint(): string {
  const grid = document.getElementById('meme-grid')
  if (!grid) return ''
  const parts: string[] = ['l' + layoutEpoch]
  for (const row of Array.from(grid.querySelectorAll<HTMLElement>('.virtual-meme-row'))) {
    const ids: string[] = []
    for (const card of Array.from(row.querySelectorAll<HTMLElement>('.meme-card[data-meme-id]'))) {
      if (card.isConnected) ids.push(card.dataset.memeId || '')
    }
    parts.push((row.dataset.rowKey || row.dataset.rowStart || '') + ':' + ids.join(','))
  }
  return parts.join('|')
}

// drag-select 的命中用 option 的 offsetTop/offsetLeft 与框矩形比较；
// 虚拟化后 option 的 offsetParent 是绝对定位的行外壳（局部 top≈0），坐标不可比。
// 这里把每个已挂载 option 的 offsetTop/offsetLeft 改写为「相对 .drag-select 内容的坐标」，
// 即与库内部 areaRect 同一坐标系（不改依赖库源码，指针按下时安装以保证框选前生效）
const optionMetricsInstalled = new WeakSet<HTMLElement>()

function installOptionMetrics() {
  const grid = document.getElementById('meme-grid')
  if (!grid) return
  const content = grid.querySelector<HTMLElement>('.drag-select')
  if (!content) return
  for (const option of Array.from(grid.querySelectorAll<HTMLElement>('.drag-select-option'))) {
    if (optionMetricsInstalled.has(option)) continue
    optionMetricsInstalled.add(option)
    Object.defineProperty(option, 'offsetTop', {
      configurable: true,
      get() {
        return option.getBoundingClientRect().top - content.getBoundingClientRect().top + content.scrollTop
      },
    })
    Object.defineProperty(option, 'offsetLeft', {
      configurable: true,
      get() {
        return option.getBoundingClientRect().left - content.getBoundingClientRect().left + content.scrollLeft
      },
    })
  }
}

function onGridPointerDownCapture() {
  installOptionMetrics()
}

function boxSelecting(): boolean {
  return dragSelectRef.value?.isDragging === true
}

function scheduleSelectionCheck() {
  if (windowUnmounted) return
  if (selectionCheckTimer) return
  selectionCheckTimer = setTimeout(() => {
    selectionCheckTimer = null
    maybeResetSelectionRegistry(false)
  }, SCROLL_END_CLEANUP_DELAY)
}

// 重挂前保存指纹，新挂载相同指纹不再次触发；活跃排序/框选手势推迟清理
function maybeResetSelectionRegistry(force: boolean) {
  if (visibleDragSession || drag.dragState.active === true || boxSelecting()) {
    pendingSelectionReset = true
    return
  }
  const fingerprint = mountedRealCardFingerprint()
  if (!force && (fingerprint === mountedFingerprint || mountedFingerprint === '')) {
    mountedFingerprint = fingerprint
    return
  }
  const handle = virtualizerRef.value
  if (handle?.cache) {
    virtualCache.value = handle.cache
    virtualCacheLength.value = rows.value.length
  }
  mountedFingerprint = fingerprint
  selectionEpoch.value += 1
}

// 手势结束/拖拽释放后补做被推迟的 registry 清理
function flushPendingWork() {
  if (pendingSelectionReset) {
    pendingSelectionReset = false
    maybeResetSelectionRegistry(false)
  }
}

const dragSelectDisabled = computed(() => !sortEnabled.value || scrolling.value || drag.dragState.active === true)

// 框选回传的是 drag-select 计算出的全量选择：只应用当前已挂载且已连接的真卡 id，保留离屏 id
function onBoxSelection(next: unknown) {
  const incoming: Set<unknown> = next instanceof Set ? next : new Set(Array.isArray(next) ? next : [])
  const mounted = new Set<number>()
  const grid = document.getElementById('meme-grid')
  if (grid) {
    for (const card of Array.from(grid.querySelectorAll<HTMLElement>('.meme-card[data-meme-id]'))) {
      if (!card.isConnected) continue
      const id = Number(card.dataset.memeId)
      if (Number.isFinite(id)) mounted.add(id)
    }
  }
  const result = new Set(state.selectedIds)
  for (const id of mounted) {
    if (incoming.has(id)) result.add(id)
    else result.delete(id)
  }
  state.selectedIds = result
}

const tagEditor = ref<InstanceType<typeof TagEditor> | null>(null)
const updateDialog = ref<InstanceType<typeof UpdateDialog> | null>(null)
const inputDialog = ref<InstanceType<typeof InputDialog> | null>(null)
const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)

// 统一确认对话框（替代原生 confirm，风格与重构主题一致）
async function confirmAsk(title: string, message: string): Promise<boolean> {
  return !!(await confirmDialog.value?.open(title, message))
}

// check_update 结果形状（桥接对象按运行时字段读取；卸载后不再弹窗）
interface UpdateInfo {
  pending?: boolean
  has_update?: boolean
  current?: string
  latest?: string
  download_url?: string
  notes?: string
}

function asUpdateInfo(value: unknown): UpdateInfo | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
  return value as UpdateInfo
}

// 检查更新并弹窗：首次 force 发起后台检查；pending 时以非 force 轮询取结果
async function checkUpdateAndPrompt() {
  const upd = asUpdateInfo(await api('check_update', false, true))
  if (windowUnmounted) return
  if (upd?.pending) {
    setTimeout(checkUpdateResult, 2000)
  } else {
    maybeShowUpdate(upd)
  }
}

// 轮询最近一次后台检查结果（非 force，避免重复触发新检查造成永久 pending）
async function checkUpdateResult() {
  if (windowUnmounted) return
  const upd = asUpdateInfo(await api('check_update', false, false))
  if (windowUnmounted) return
  if (upd?.pending) {
    setTimeout(checkUpdateResult, 2000)
  } else {
    maybeShowUpdate(upd)
  }
}

function maybeShowUpdate(upd: UpdateInfo | null) {
  try {
    if (upd && upd.has_update) {
      updateDialog.value?.show(upd.current ?? '', upd.latest ?? '', upd.download_url ?? '', upd.notes ?? '')
    }
  } catch (_) {}
}

const sortEnabled = ref(false)
const drag = useDragSort(
  () => (visibleDragSession ? visibleDragSession.segItems : []),
  applyVisibleSegment,
  canReorder,
  () => sortEnabled.value,
  persistVisibleOrder,
  () => { showToast('排序保存失败'); search() },
)

// ── 整理模式：可见已加载段拖拽（引擎不改，坐标/索引/跨行重挂在 MainWindow 适配） ──
interface VisibleDragSession {
  gen: number
  rangeGen: number
  layout: number
  memeId: number
  firstRow: number
  lastRow: number
  segStart: number
  segEnd: number
  segItems: Meme[]
  sliceStart: number
  sliceItems: Meme[]
  originalSlice: Meme[]
  deltaY: number
  rowPitch: number
  pointerId: number
  liveNode: HTMLElement | null
  liveCard: HTMLElement | null
  visual: { transform: string; zIndex: string }
  visualNodes: Set<HTMLElement>
  releasePin: (() => void) | null
  finished: boolean
}

let visibleDragSession: VisibleDragSession | null = null
// persist 进行中禁止发起新会话（引擎 cleanup 是全局的，重入会清掉新手势）
let persistInFlight = false
// 保存已发出后收到的取消：结算后按数据库权威顺序重同步，不回滚旧快照
let cancelDuringPersist = false

// 收集当前已挂载行：必须连续、全部槽位已加载、DOM 真卡顺序与槽位一致（含骨架一律拒绝）
function collectMountedSegment(grid: HTMLElement): {
  firstRow: number
  lastRow: number
  segStart: number
  segEnd: number
  items: Meme[]
  rows: HTMLElement[]
} | null {
  const rowEls = Array.from(grid.querySelectorAll<HTMLElement>('.virtual-meme-row'))
  if (!rowEls.length) return null
  const width = Math.max(1, cols.value)
  const total = state.total
  const totalRows = Math.ceil(total / width)
  const sorted: Array<{ index: number; el: HTMLElement }> = []
  for (const el of rowEls) {
    const start = Number(el.dataset.rowStart)
    if (!Number.isFinite(start) || start % width !== 0) return null
    const index = start / width
    if (index < 0 || index >= totalRows) return null
    sorted.push({ index, el })
  }
  sorted.sort((a, b) => a.index - b.index)
  for (let i = 0; i < sorted.length; i++) {
    const entry = sorted[i]
    const previous = sorted[i - 1]
    if (!entry) return null
    if (previous && entry.index !== previous.index + 1) return null
    const rowStart = entry.index * width
    const rowEnd = Math.min(rowStart + width, total)
    const cards = Array.from(entry.el.querySelectorAll<HTMLElement>('.meme-card[data-meme-id]'))
    if (cards.length !== rowEnd - rowStart) return null
    if (entry.el.querySelector('.meme-card.skeleton')) return null
    for (let k = 0; k < cards.length; k++) {
      const card = cards[k]
      const record = slot(rowStart + k)
      if (!card || !record || !card.isConnected || card.dataset.memeId !== String(record.id)) return null
    }
  }
  const firstEntry = sorted[0]
  const lastEntry = sorted[sorted.length - 1]
  if (!firstEntry || !lastEntry) return null
  const firstRow = firstEntry.index
  const lastRow = lastEntry.index
  const segStart = firstRow * width
  const segEnd = Math.min((lastRow + 1) * width, total)
  const items: Meme[] = []
  for (let i = segStart; i < segEnd; i++) {
    const record = slot(i)
    if (!record) return null
    items.push(record)
  }
  return { firstRow, lastRow, segStart, segEnd, items, rows: sorted.map(entry => entry.el) }
}

// live-card：跨视觉行重挂后仍转发到当前节点，避免在断开节点上写样式/捕获
const NOOP_CLASS_LIST = { add: () => {}, remove: () => {}, toggle: () => {}, contains: () => false }

// 查找当前真卡节点：跨行置换后可能同时存在退场副本，按模型当前所在行挑当前节点
function findMemeCardNode(session: VisibleDragSession): HTMLElement | null {
  const nodes = Array.from(document.querySelectorAll<HTMLElement>('#meme-grid .meme-card[data-meme-id="' + session.memeId + '"]'))
    .filter(node => node.isConnected)
  if (nodes.length <= 1) return nodes[0] ?? null
  const slice = loadedSlice()
  const offset = slice.items.findIndex(record => record.id === session.memeId)
  if (offset >= 0) {
    const width = Math.max(1, cols.value)
    const rowStart = Math.floor((slice.start + offset) / width) * width
    const expected = nodes.find(node => node.closest<HTMLElement>('.virtual-meme-row')?.dataset.rowStart === String(rowStart))
    if (expected) return expected
  }
  return nodes[nodes.length - 1] ?? null
}

function createLiveCard(session: VisibleDragSession): HTMLElement {
  const findEl = () => findMemeCardNode(session)
  const current = () => (session.liveNode && session.liveNode.isConnected ? session.liveNode : findEl())
  const styleProxy = new Proxy({} as CSSStyleDeclaration, {
    get(_target, prop) {
      const el = current()
      if (!el) return undefined
      const value = (el.style as unknown as Record<string | symbol, unknown>)[prop as string]
      return typeof value === 'function' ? (value as (...args: unknown[]) => unknown).bind(el.style) : value
    },
    set(_target, prop, value) {
      const el = current()
      if (el) {
        ;(el.style as unknown as Record<string, unknown>)[prop as string] = value
        session.visualNodes.add(el)
      }
      if (prop === 'transform') session.visual.transform = String(value)
      else if (prop === 'zIndex') session.visual.zIndex = String(value)
      return true
    },
  })
  return new Proxy({ __v_skip: true } as unknown as HTMLElement, {
    get(_target, prop) {
      // 阻止 Vue 对代理再次 reactive 包装（包装会破坏 DOMTokenList 等原生方法的 this）
      if (prop === '__v_skip') return true
      if (prop === 'style') return styleProxy
      if (prop === 'classList') {
        const el = current()
        return el ? el.classList : NOOP_CLASS_LIST
      }
      if (prop === 'getBoundingClientRect') {
        return () => {
          const el = current()
          const rect = el ? el.getBoundingClientRect() : new DOMRect(0, 0, 0, 0)
          // 归一化坐标下返回同样减 deltaY 的 rect，offY 仍是真实抓取偏移
          return {
            left: rect.left,
            top: rect.top - session.deltaY,
            right: rect.right,
            bottom: rect.bottom - session.deltaY,
            width: rect.width,
            height: rect.height,
            x: rect.x,
            y: rect.y - session.deltaY,
          } as DOMRect
        }
      }
      const el = current()
      if (!el) return undefined
      const value = (el as unknown as Record<string | symbol, unknown>)[prop as string]
      return typeof value === 'function' ? (value as (...args: unknown[]) => unknown).bind(el) : value
    },
    set(_target, prop, value) {
      const el = current()
      if (!el) return false
      ;(el as unknown as Record<string, unknown>)[prop as string] = value
      return true
    },
  })
}

// 传给引擎的坐标：clientY 归一到挂载段基准（首行=0），其余字段原样保留
function normalizePointerEvent(e: PointerEvent, deltaY: number): PointerEvent {
  return {
    button: e.button,
    buttons: e.buttons,
    pointerId: e.pointerId,
    clientX: e.clientX,
    clientY: e.clientY - deltaY,
  } as unknown as PointerEvent
}

// 真实落点是否在本次可见已加载段内：二维落点须落在网格内容范围，
// 且按真实坐标解出的槽位属于挂载段（越界拖动不转发，避免引擎 clamp 误判尾部落点）
function insideVisibleSegment(clientX: number, clientY: number, session: VisibleDragSession): boolean {
  const grid = document.getElementById('meme-grid')
  if (!grid || !(session.rowPitch > 0)) return false
  const style = getComputedStyle(grid)
  const gridRect = grid.getBoundingClientRect()
  const gridTop = gridRect.top + grid.clientTop + finiteNumber(style.paddingTop)
  const gridLeft = gridRect.left + grid.clientLeft + finiteNumber(style.paddingLeft)
  const contentRight = gridLeft + grid.clientWidth - finiteNumber(style.paddingRight)
  const width = Math.max(1, cols.value)
  const sample = grid.querySelector<HTMLElement>('.meme-card[data-meme-id]')
  const pitchX = sample ? sample.offsetWidth + finiteNumber(style.columnGap) : 0
  if (!(pitchX > 0)) return false
  if (clientX < gridLeft || clientX > contentRight) return false
  const col = Math.min(width - 1, Math.max(0, Math.floor((clientX - gridLeft) / pitchX)))
  const row = session.firstRow + Math.floor((clientY - session.deltaY - gridTop) / session.rowPitch)
  if (row < session.firstRow || row > session.lastRow) return false
  const index = row * width + col
  return index >= session.segStart && index < session.segEnd
}

function sessionStillValid(session: VisibleDragSession): boolean {
  return state.queryGen === session.gen && state.rangeGen === session.rangeGen && layoutEpoch === session.layout
}

// 建立一次可见段拖拽会话：记录原连续 loadedSlice、挂载段绝对起点、布局与冻结行 key
function beginVisibleDragSession(e: PointerEvent, meme: Meme, card: HTMLElement): VisibleDragSession | null {
  const grid = document.getElementById('meme-grid')
  if (!grid) return null
  const segment = collectMountedSegment(grid)
  if (!segment) return null
  const slice = loadedSlice()
  if (segment.segStart < slice.start || segment.segEnd > slice.start + slice.items.length) return null
  if (!card.isConnected) return null
  const style = getComputedStyle(grid)
  const gridTop = grid.getBoundingClientRect().top + grid.clientTop + finiteNumber(style.paddingTop)
  const firstRowEl = segment.rows[0]
  if (!firstRowEl) return null
  const session: VisibleDragSession = {
    gen: state.queryGen,
    rangeGen: state.rangeGen,
    layout: layoutEpoch,
    memeId: meme.id,
    firstRow: segment.firstRow,
    lastRow: segment.lastRow,
    segStart: segment.segStart,
    segEnd: segment.segEnd,
    segItems: [...segment.items],
    sliceStart: slice.start,
    sliceItems: [...slice.items],
    originalSlice: [...slice.items],
    deltaY: firstRowEl.getBoundingClientRect().top - gridTop,
    rowPitch: rowPitch.value,
    pointerId: e.pointerId,
    liveNode: card,
    liveCard: null,
    visual: { transform: '', zIndex: '' },
    visualNodes: new Set(),
    releasePin: null,
    finished: false,
  }
  session.liveCard = createLiveCard(session)
  // 钉住既有 row key，避免置换/数据变化主动销毁拖动行
  for (let index = session.firstRow; index <= session.lastRow; index++) {
    const key = rows.value[index]?.key
    if (key) frozenRowKeys.set(index, key)
  }
  session.releasePin = pinLoadedRange()
  return session
}

// 恢复原 order（仅当前窗口代次仍有效）：新 query 不得被旧快照覆盖
function restoreSessionSlice(session: VisibleDragSession) {
  const slice = loadedSlice()
  if (slice.start !== session.sliceStart || slice.items.length !== session.originalSlice.length) return
  const current = new Set(slice.items.map(record => record.id))
  if (current.size !== session.originalSlice.length) return
  for (const record of session.originalSlice) {
    if (!current.has(record.id)) return
  }
  setLoadedSlice(session.sliceStart, session.originalSlice)
}

// 引擎 setter：仅置换已挂载密集子段，写回原 loadedSlice 的绝对槽位
async function applyVisibleSegment(items: Meme[]) {
  const session = visibleDragSession
  if (!session || session.finished || !sessionStillValid(session)) return
  if (items.length !== session.segEnd - session.segStart) return
  const offset = session.segStart - session.sliceStart
  const next = [...session.sliceItems]
  for (let i = 0; i < items.length; i++) next[offset + i] = items[i]
  if (!setLoadedSlice(session.sliceStart, next)) {
    cancelVisibleDrag()
    return
  }
  session.sliceItems = next
  session.segItems = [...items]
  await nextTick()
  reattachLiveCard(session)
}

// Vue 更新后确认拖动卡仍在预定挂载段；节点重建则恢复视觉/捕获，找不到立即取消并回滚
function reattachLiveCard(session: VisibleDragSession) {
  if (visibleDragSession !== session || session.finished) return
  const el = findMemeCardNode(session)
  if (!el || !el.isConnected) { cancelVisibleDrag(); return }
  const rowEl = el.closest<HTMLElement>('.virtual-meme-row')
  const start = rowEl ? Number(rowEl.dataset.rowStart) : NaN
  if (!Number.isFinite(start)) { cancelVisibleDrag(); return }
  const rowIndex = start / Math.max(1, cols.value)
  if (rowIndex < session.firstRow || rowIndex > session.lastRow) { cancelVisibleDrag(); return }
  if (el === session.liveNode) return
  // 跨行重挂：清理旧引用节点，转发到新节点并恢复拖拽视觉
  const previous = session.liveNode
  if (previous && previous !== el) {
    previous.classList.remove('dragging')
    previous.style.transform = ''
    previous.style.zIndex = ''
    session.visualNodes.delete(previous)
  }
  session.liveNode = el
  session.visualNodes.add(el)
  el.classList.add('dragging')
  el.style.transform = session.visual.transform
  el.style.zIndex = session.visual.zIndex
  if (drag.dragState.active) {
    try { el.setPointerCapture(session.pointerId) } catch (_) {}
  }
}

// 清理本会话写过的所有节点（含跨行重挂后的旧节点残留）
function cleanupVisualNodes(session: VisibleDragSession) {
  for (const el of session.visualNodes) {
    if (!el.isConnected) continue
    el.classList.remove('dragging')
    el.style.transform = ''
    el.style.zIndex = ''
  }
  session.visualNodes.clear()
}

// 引擎 persist：忽略可见子段 id，提交当前整个 loadedSlice 的有序 id（S1 位置置换语义）
async function persistVisibleOrder(): Promise<boolean> {
  const session = visibleDragSession
  if (!session) return false
  const slice = loadedSlice()
  const ids = slice.items.map(record => record.id)
  const ok = await reorderMemes(ids)
  if (!ok && sessionStillValid(session)) restoreSessionSlice(session)
  return ok
}

function finishVisibleDragSession(session: VisibleDragSession) {
  if (session.finished) return
  session.finished = true
  cleanupVisualNodes(session)
  session.releasePin?.()
  session.releasePin = null
  frozenRowKeys.clear()
  if (visibleDragSession === session) visibleDragSession = null
  flushPendingWork()
  // 排序结束后指纹（布局/行 key）可能已变化：安排一次受控 registry 清理
  scheduleSelectionCheck()
}

// 统一取消：恢复原顺序（代次有效时）→ 取消引擎手势 → 释放钉住，激活过的拖拽吞掉首次 click
function cancelVisibleDrag() {
  const session = visibleDragSession
  if (!session) return
  if (persistInFlight) {
    // 保存已发出：推迟到结算后按数据库权威顺序重同步，不在此恢复旧快照
    cancelDuringPersist = true
    return
  }
  visibleDragSession = null
  const wasActive = drag.dragState.active === true
  if (!session.finished && sessionStillValid(session)) restoreSessionSlice(session)
  drag.cancel()
  if (session.pointerId != null) {
    try { session.liveNode?.releasePointerCapture(session.pointerId) } catch (_) {}
  }
  if (!session.finished) cleanupVisualNodes(session)
  session.finished = true
  session.releasePin?.()
  session.releasePin = null
  frozenRowKeys.clear()
  if (wasActive) ignoreClick = true
  flushPendingWork()
  scheduleSelectionCheck()
}

const sidebarCollapsed = ref(false)
// 未分类没有成员时隐藏条目，保留其他集合的显示规则。
const visibleCollections = computed(() => state.collections.filter(c => c.id !== -4 || (c.count || 0) > 0))
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
  // 后端 evaluate_js 刷新入口（设置保存/同步后由 webui.py 调用）
  window.refreshMemes = () => { search() }
  window.refreshTags = refreshTags
  window.refreshCollections = refreshCollections
})

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
  const ok = await copyMeme(meme.id)
  if (ok) showToast(`${meme.name} 已复制`)
  else showToast('复制失败')
}

// 卡片点击/回车：整理模式=勾选切换；普通模式=复制（拖拽后的首次点击由 ignoreClick 吞掉）
function onCardClick(meme: Meme) {
  if (ignoreClick) { ignoreClick = false; return }
  if (sortEnabled.value) { toggleSelected(meme.id); return }
  void handleCopy(meme)
}

// 整理模式勾选：替换 Set 触发响应式（与 search 清空选择同一模式）
function toggleSelected(id: number) {
  const next = new Set(state.selectedIds)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  state.selectedIds = next
}

// 消息提示：走 Naive NMessage，保留原 toast 的 1600ms 时长
function showToast(msg: string) {
  message.info(msg, { duration: 1600 })
}

// 卡片悬停快速收藏（右键菜单外的一键入口）
async function quickFavorite(meme: Meme) {
  if (sortEnabled.value) return
  const ok = (await api('toggle_favorite', meme.id)) as boolean | null
  if (ok === null || ok === undefined) return
  meme.favorited = ok
  await refreshCollections()
  if (!ok && state.activeCollection === -2) {
    const fav = state.collections.find((c: any) => c.id === -2)
    if (!fav || fav.count === 0) setActiveCollection(-4)
  }
  showToast(ok ? '已收藏' : '已取消收藏')
}

// 搜索框输入：同步关键字并防抖触发搜索
function onSearchInput(value: string) {
  setSearch(value)
  debounceSearch()
}

function clearSearch() {
  setSearch('')
  search()
}

let searchTimer: ReturnType<typeof setTimeout>
function debounceSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => search(), 300)
}

async function openSettings() {
  try {
    const ok = await api('open_settings')
    if (!ok) showToast('无法打开设置窗口')
  } catch (_) {
    showToast('无法打开设置窗口')
  }
}
function toggleSidebar() { sidebarCollapsed.value = !sidebarCollapsed.value }

function toggleSort() {
  sortEnabled.value = !sortEnabled.value
  if (sortEnabled.value) drag.enable()
  else { cancelVisibleDrag(); drag.disable(); clearSelection() }
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

// 标题栏「更多」菜单：同步 / 维护 / 应用三类，非同类之间以分割线分隔
const titleMenuOptions: DropdownMixedOption[] = [
  { label: '上传到远端', key: 'sync_upload', icon: () => h(CloudUpload, { size: 16 }) },
  { label: '从远端下载', key: 'sync_download', icon: () => h(CloudDownload, { size: 16 }) },
  { type: 'divider', key: 'menu-divider-sync' },
  { label: '重新扫描', key: 'rescan', icon: () => h(RefreshCw, { size: 16 }) },
  { type: 'divider', key: 'menu-divider-rescan' },
  { label: '设置', key: 'settings', icon: () => h(Settings, { size: 16 }) },
]

function onTitleMenuSelect(key: string | number) {
  const action = String(key)
  if (action === 'sync_upload') syncUpload()
  else if (action === 'sync_download') syncDownload()
  else if (action === 'rescan') rescanCache()
  else if (action === 'settings') openSettings()
}

function hideWindow() {
  api('hide_window')
}

async function onTitlebarMouseDown(e: MouseEvent) {
  if (e.button !== 0) return
  if ((e.target as HTMLElement).closest('.title-btn') || (e.target as HTMLElement).closest('.icon-btn') || (e.target as HTMLElement).closest('.sidebar-toggle')) return
  try {
    const nativeDrag = await api('start_window_drag', e.button + 1, e.screenX, e.screenY)
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
    api('move_window', dx, dy)
    dragState.sx = e.screenX
    dragState.sy = e.screenY
  }
}

function onWindowMouseUp() { dragState = null }

// 右键子菜单项：加载当前分组（正 ID）下的子分组
async function buildSubgroupItems(): Promise<MenuItem[]> {
  const targetCol = state.activeCollection && state.activeCollection > 0 ? state.activeCollection : null
  const children = targetCol ? ((await api('get_child_collections', targetCol)) || []) : []
  const sub: MenuItem[] = []
  if (!targetCol) {
    sub.push({ action: '__new-subgroup__', label: '新建分组' })
  } else {
    sub.push({ action: '__new-subgroup__', label: '新建小分组' })
    for (const ch of children) {
      sub.push({ action: 'subgroup-' + ch.id, label: ch.name })
    }
  }
  return sub
}

async function onMemeRightClick(e: MouseEvent, meme: Meme) {
  e.preventDefault()
  e.stopPropagation()
  const posX = e.clientX
  const posY = e.clientY
  const items: MenuItem[] = [
    { action: 'rename', label: '重命名' },
    { action: 'favorite', label: meme.favorited ? '取消收藏' : '收藏' },
    { action: 'tag', label: '打标签' },
    { action: 'collection', label: '添加分组' },
  ]
  if (state.activeCollection && state.activeCollection > 0) {
    items.push({ action: 'add-to-subgroup', label: '加入小分组', children: await buildSubgroupItems() })
    items.push({ action: 'remove-collection', label: '移出该分组' })
  }
  if (state.activeCollection === -3) {
    items.push({ action: 'remove-recent', label: '从最近使用中删除' })
  }
  items.push({ action: 'delete', label: '删除', danger: true })
  ctx.show(items, { memeId: meme.id, filename: meme.filename, memeName: meme.name, favorited: meme.favorited }, posX, posY)
}

async function onFolderRightClick(e: MouseEvent, folderId: number, folderName: string) {
  e.preventDefault()
  e.stopPropagation()
  const posX = e.clientX
  const posY = e.clientY
  const items: MenuItem[] = [{ action: 'rename-collection', label: '重命名' }]
  if (folderId === -3) {
    items.push({ action: 'clear-recent', label: '清空最近使用', danger: true })
  } else if (folderId > 0) {
    items.push({ action: 'add-to-subgroup', label: '新建子分组', children: await buildSubgroupItems() })
    items.push({ action: 'delete-collection', label: '删除', danger: true })
  }
  ctx.show(items, { folderId, folderName, isFolder: true }, posX, posY)
}

async function onCtxAction(action: string) {
  ctx.hide()
  const t = ctx.trigger.value
  // 触发上下文可选字段统一窄化，避免把 undefined 传入桥接参数
  const memeId = t.memeId ?? 0
  const memeName = t.memeName ?? ''
  const folderId = t.folderId ?? 0
  const folderName = t.folderName ?? ''
  switch (action) {
    case 'rename': {
      const name = await inputDialog.value?.open('重命名', memeName)
      if (name && name !== memeName) { await api('rename_meme', memeId, name); search() }
      break
    }
    case 'favorite': {
      const ok = await api('toggle_favorite', memeId)
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
      const tags = await tagEditor.value?.open(memeId)
      if (tags === null) break
      await api('set_meme_tags', memeId, tags)
      // 同步已激活标签筛选，避免已删除标签继续筛
      refreshTags()
      search()
      break
    }
    case 'collection': { showCollectionBuilder(memeId); break }
    case 'add-to-subgroup': { /* 子菜单在 hover 时加载，点击走 subgroup-N / __new-subgroup__ */ break }
    case '__new-subgroup__': {
      const isSub = state.activeCollection && state.activeCollection > 0
      const name = await inputDialog.value?.open(isSub ? '新建小分组' : '新建分组', '', isSub ? '输入小分组名称' : '输入分组名称')
      if (!name) break
      const targetCol = state.activeCollection && state.activeCollection > 0 ? state.activeCollection : null
      let ok: any
      if (targetCol) {
        const r = (await api('create_subcollection', name, targetCol)) as { ok?: boolean; id?: number } | null
        if (r && r.ok && typeof r.id === 'number') ok = await api('add_to_existing_collection', memeId, r.id)
      } else {
        ok = await api('add_to_collection', memeId, name)
      }
      if (ok) { showToast('已添加'); refreshCollections(); search() }
      else showToast('添加分组失败')
      break
    }
    case 'remove-collection': {
      const removedFrom = state.activeCollection
      const ok = await api('remove_from_collection', memeId, removedFrom)
      if (ok) {
        // 从子分组移除时加回上层大分组
        const parent = findParentCollection(state.collections, removedFrom)
        if (parent) await api('add_to_existing_collection', memeId, parent.id)
        await refreshCollections()
        // 递归查找分组节点（子分组不在顶层），据此判断是否清空后再删
        const c = findCollectionNode(state.collections, removedFrom)
        if (!c || c.count === 0) {
          if (removedFrom > 0) await api('delete_collection', removedFrom)
          setActiveCollection(parent ? parent.id : -4)
        }
        search()
      }
      break
    }
    case 'remove-recent': {
      await api('remove_from_recent', memeId)
      search()
      break
    }
    case 'delete': {
      if (await confirmAsk('删除表情包', '确定删除这个表情包吗？')) { await api('delete_meme', memeId); search(); refreshCollections() }
      break
    }
    case 'rename-collection': {
      const name = await inputDialog.value?.open('重命名分组', folderName)
      if (name && name !== folderName) { await api('rename_collection', folderId, name); refreshCollections() }
      break
    }
    case 'delete-collection': {
      if (await confirmAsk('删除分组', '确定删除这个分组吗？')) {
        // 先移除组内表情到上层，再删组
        const parent = findParentCollection(state.collections, folderId)
        const members = (await api('search_memes', '', [], folderId, 0, 9999)) || []
        for (const mm of members) {
          if (parent) await api('add_to_existing_collection', mm.id, parent.id)
        }
        await api('delete_collection', folderId)
        if (state.activeCollection === folderId) setActiveCollection(parent ? parent.id : -4)
        refreshCollections(); search()
      }
      break
    }
    case 'delete-folder': {
      if (await confirmAsk('删除小分组', '确定删除小分组「' + folderName + '」？分组内表情包将移回上层分组。')) {
        const parent = findParentCollection(state.collections, folderId)
        const members = (await api('search_memes', '', [], folderId, 0, 9999)) || []
        for (const mm of members) {
          if (parent) await api('add_to_existing_collection', mm.id, parent.id)
        }
        await api('delete_collection', folderId)
        if (state.activeCollection === folderId) setActiveCollection(parent ? parent.id : -4)
        refreshCollections(); search()
      }
      break
    }
    case 'clear-recent': {
      if (await confirmAsk('清空最近使用', '确定清空最近使用记录吗？')) {
        await api('clear_recent')
        search()
      }
      break
    }
    default:
      if (action.startsWith('subgroup-')) {
        const cid = Number(action.slice('subgroup-'.length))
        const ok = await api('add_to_existing_collection', memeId, cid)
        if (ok) { showToast('已添加到分组'); refreshCollections(); search() }
        else showToast('添加失败')
      } else {
        showToast(`${action} 功能开发中`)
      }
  }
}

// 批量删除选中的表情包（整理模式操作栏）
async function batchDelete() {
  const ids = [...state.selectedIds]
  if (ids.length === 0) return
  if (!await confirmAsk('批量删除', `确定删除选中的 ${ids.length} 个表情包吗？此操作不可恢复。`)) return
  // 后端异常或 pywebview 不可用：报错即中止，不刷新以免 UI 与 DB 不一致
  let result: { ok?: boolean; deleted?: number } | null = null
  try {
    result = (await api('delete_memes', ids)) as { ok?: boolean; deleted?: number } | null
  } catch {
    showToast('批量删除失败')
    return
  }
  if (!result?.ok) {
    showToast('批量删除失败')
    return
  }
  if (result.deleted === 0) {
    // 后端一个都没删掉（所选 id 在库中已不存在），刷新以对齐 UI
    showToast('没有删除任何表情包')
    await search()
    refreshCollections()
    refreshTags()
    return
  }
  showToast(`已删除 ${result.deleted ?? ids.length} 个表情包`)
  await search() // search() 内已清空选择
  refreshCollections()
  refreshTags()
}

// 全选：按当前查询全量选择（仅取 id 集合，失败不改动现有选择）
async function selectAllResults() {
  if (state.total === 0) return
  const ok = await selectAll()
  if (ok) showToast(`已全选 ${state.selectedIds.size} 项`)
  else showToast('全选失败，请重试')
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

async function showCollectionBuilder(memeId?: number) {
  cb.open(async (confirm) => {
    const { name, memeIds, existingId } = confirm
    // 已选已有分组 → 更新其成员；否则新建分组
    const result = (existingId
      ? await api('set_collection_members', existingId, memeIds)
      : await api('set_collection_members_new', name, memeIds)) as { ok?: boolean; error?: string } | true | null
    if (result?.ok || result === true) {
      showToast(existingId ? '已保存到分组：' + name : '分组已创建')
      refreshCollections(); search()
    } else {
      showToast(result?.error || '保存失败')
    }
  }, memeId ? [memeId] : [])
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
  // 整理模式接管指针：可排视图走可见段拖拽；挂载段不全为已加载真卡时暂拒绝发起
  if (sortEnabled.value) {
    if (!canReorder()) return
    // 保存进行中禁止发起新会话：引擎 cleanup 是全局的，旧保存完成回调会清掉新手势
    if (persistInFlight) return
    const session = beginVisibleDragSession(e, meme, card)
    if (!session) return
    visibleDragSession = session
    const liveCard = session.liveCard
    if (!liveCard) { cancelVisibleDrag(); return }
    drag.onPointerDown(normalizePointerEvent(e, session.deltaY), meme.id, liveCard)
    if (drag.dragState.memeId !== meme.id) cancelVisibleDrag()
    return
  }
  if (e.button !== 0) return
  nativeDragStart = { x: e.clientX, y: e.clientY, memeId: meme.id }
}

function onDocPointerMove(e: PointerEvent) {
  if (drag.dragState.memeId) {
    // 保存挂起：不得再改动旧会话（显示顺序会偏离已提交的 ids）
    if (persistInFlight) return
    const session = visibleDragSession
    if (!session) { drag.cancel(); return }
    // 按键已释放（例如在窗口外抬起）时取消并回滚，避免会话/钉住悬挂
    if (e.buttons === 0) { cancelVisibleDrag(); return }
    // 真实落点越出已加载挂载段时不转发，避免引擎 clamp 误判尾部落点
    if (!insideVisibleSegment(e.clientX, e.clientY, session)) return
    drag.onPointerMove(normalizePointerEvent(e, session.deltaY))
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
  // 保存中收到重复抬起：忽略（旧会话的结算由首次 pointerup 负责）
  if (persistInFlight) return
  const session = visibleDragSession
  if (drag.dragState.memeId) {
    // 越界松手：取消并回滚，不提交（与 move 的越界拒绝一致）
    if (session && drag.dragState.active === true && !insideVisibleSegment(e.clientX, e.clientY, session)) {
      cancelVisibleDrag()
      return
    }
    persistInFlight = true
    cancelDuringPersist = false
    let wasActive = false
    try {
      wasActive = await drag.onPointerUp()
    } catch (_) {
      // 引擎结算异常：清理手势状态，保证 persist 标志必然释放（不死锁）
      drag.cancel()
    } finally {
      persistInFlight = false
    }
    const cancelled = cancelDuringPersist
    cancelDuringPersist = false
    if (wasActive) ignoreClick = true
    if (session) {
      finishVisibleDragSession(session)
      // 保存期间被取消：以数据库为准重同步，不保留本地快照（卸载后不再触碰模型）
      if (cancelled && !windowUnmounted) void search()
    }
    return
  }
  if (session) cancelVisibleDrag()
  nativeDragStart = null
}

function onDocPointerCancel() {
  if (visibleDragSession) cancelVisibleDrag()
  if (drag.dragState.memeId && !persistInFlight) drag.cancel()
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
          if (!item) continue
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
  if (!uri) { try { const picked = dt.files?.[0]; if (picked) file = picked } catch (_) {} }
  if (!uri && !file) {
    try {
      if (dt.items?.length) {
        for (let i = 0; i < dt.items.length; i++) {
          const it = dt.items[i]
          if (!it) continue
          if (it.kind === 'file') { file = it.getAsFile(); if (file) break }
        }
      }
    } catch (_) {}
  }
  if (uri) {
    try {
      const r = (await api('download_original_image', uri)) as { ok?: boolean; error?: string } | null
      if (r?.ok) { showToast('导入成功'); search(); refreshCollections(); return }
      showToast(r?.error || '导入失败')
      return
    } catch (_) {
      showToast('导入失败')
      return
    }
  }
  if (file) {
    let b64: string
    try {
      b64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => {
          const raw = typeof reader.result === 'string' ? reader.result : ''
          resolve(raw.split(',')[1] ?? '')
        }
        reader.onerror = () => reject(reader.error)
        reader.readAsDataURL(file!)
      })
    } catch (_) {
      showToast('导入失败：无法读取文件')
      return
    }
    try {
      const res = await fetch('/api/upload/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ files: [{ name: file.name, data: b64 }] }) })
      if (res.ok) { showToast('导入成功'); search(); refreshCollections() }
      else { showToast('导入失败：服务器返回错误') }
    } catch (_) {
      showToast('导入失败：网络或服务异常')
    }
    return
  }
  showToast('未识别到可导入的内容')
}

// ESC：右键菜单 → 整理模式 → 隐藏窗口
function onDocKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (lanConfirmVisible.value) { confirmLanDevice(false); return }
  if (ctx.visible.value) { ctx.hide(); return }
  if (sortEnabled.value) { toggleSort(); return }
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
  // 框选命中坐标适配：指针按下时把已挂载 option 的局部坐标改写为容器坐标
  gridWrapRef.value?.addEventListener('pointerdown', onGridPointerDownCapture, true)
  // 虚拟化前提：ResizeObserver + 元素滚动方法；缺失时显示不可用提示，不静默挂库
  const wrap = gridWrapRef.value
  const hasScrollMethods = !!wrap && typeof wrap.scrollTo === 'function' && typeof wrap.scrollBy === 'function'
  virtualReady.value = typeof ResizeObserver !== 'undefined' && hasScrollMethods
  if (virtualReady.value && wrap) {
    gridResizeObserver = new ResizeObserver(() => scheduleLayoutRefresh())
    gridResizeObserver.observe(wrap)
    observeFolderGrid()
    refreshLayout()
    requestVisibleRange()
  }
})

// folder 头块高度变化（分组切换/子分组增删）时重测 startMargin
function observeFolderGrid() {
  folderResizeObserver?.disconnect()
  const folder = folderGridRef.value
  if (!virtualReady.value || !folder || typeof ResizeObserver === 'undefined') return
  if (!folderResizeObserver) folderResizeObserver = new ResizeObserver(() => scheduleLayoutRefresh())
  folderResizeObserver.observe(folder)
}

onUnmounted(() => {
  // 先置卸载门禁：阻止进行中的异步续体再触碰模型（search/ensureRange 会重建生命周期）
  windowUnmounted = true
  window.refreshMemes = () => {}
  window.refreshTags = () => {}
  window.refreshCollections = () => {}
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
  gridWrapRef.value?.removeEventListener('pointerdown', onGridPointerDownCapture, true)
  if (updateInterval) { clearInterval(updateInterval); updateInterval = null }
  hoverTimers.forEach(t => clearTimeout(t))
  hoverTimers.clear()
  cancelVisibleDrag()
  if (layoutRaf) { cancelAnimationFrame(layoutRaf); layoutRaf = 0 }
  if (rangeRaf) { cancelAnimationFrame(rangeRaf); rangeRaf = 0 }
  if (selectionCheckTimer) { clearTimeout(selectionCheckTimer); selectionCheckTimer = null }
  gridResizeObserver?.disconnect()
  gridResizeObserver = null
  folderResizeObserver?.disconnect()
  folderResizeObserver = null
  dispose()
})

// 桥接调用失败记录：控制台 + 后端日志（生产无 devtools，靠日志导出排查）
function logBridgeIssue(method: string, detail = '') {
  const msg = 'bridge ' + method + ' failed' + (detail ? ': ' + detail : '')
  console.error(msg)
  void api('log', msg, 'warning')
}

;(async () => {
  const initOk = await loadInitData()
  if (windowUnmounted) return
  if (!initOk) {
    logBridgeIssue('get_init_data', '初始化数据重试后仍失败')
    showToast('数据加载失败，可点击「刷新」重试')
  }
  // 动画开启时：播放期间即加载后续内容（动画天然覆盖桥接稳定时间），去除 300ms 延时；
  // 动画关闭时：不播放动画，降级为 300ms 延时
  const runBackground = async () => {
    if (windowUnmounted) return
    if ((await api('rescan_cache')) === null) logBridgeIssue('rescan_cache')
    const autoSync = await api('run_auto_sync')
    if (windowUnmounted) return
    if (autoSync && typeof autoSync === 'object' && !Array.isArray(autoSync)) {
      const error = (autoSync as Record<string, unknown>)['error']
      if (error) logBridgeIssue('run_auto_sync', String(error))
    }
    await search()
    if (windowUnmounted) return
    await refreshTags()
    if (windowUnmounted) return
    await refreshCollections()
  }
  const prefersReducedMotion = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  if (state.showStartupAnimation && !prefersReducedMotion) {
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
  if (windowUnmounted) return
  updateInterval = setInterval(checkUpdateAndPrompt, 24 * 60 * 60 * 1000)
})()

// 纯框选手势结束（无卡片拖拽）：补做被推迟的 registry 清理
watch(() => dragSelectRef.value?.isDragging === true, (now) => {
  if (now) return
  flushPendingWork()
  scheduleSelectionCheck()
})

// 切换分组/标签/搜索词时滚动复位（窗口/cache 代次变化不触发）
const browseKey = computed(() => (state.activeCollection ?? 'all') + '|' + state.searchQuery + '|' + [...state.activeTags].sort().join(','))
watch(browseKey, () => { if (gridWrapRef.value) gridWrapRef.value.scrollTop = 0 })

// 同查询显式 search 刷新：滚动复位、重挂框选 registry；拖拽中先取消手势
watch(() => state.queryGen, () => {
  cancelVisibleDrag()
  scrolling.value = false
  if (gridWrapRef.value) gridWrapRef.value.scrollTop = 0
  hoverTimers.forEach(t => clearTimeout(t))
  hoverTimers.clear()
  virtualCache.value = null
  virtualCacheLength.value = 0
  maybeResetSelectionRegistry(true)
  void nextTick(() => { refreshLayout(); requestVisibleRange() })
})

// 缓存填充（骨架→真卡）或总数变化后重算窗口与 registry
watch([() => state.lo, () => state.hi, () => state.total], () => {
  void nextTick(() => { requestVisibleRange(); scheduleSelectionCheck() })
}, { flush: 'post' })

// folder 头块出现/消失/改行数时重测 startMargin
watch(folderCards, () => {
  void nextTick(() => { observeFolderGrid(); refreshLayout() })
})
</script>

<template>
  <div id="app">
    <header id="titlebar" @mousedown="onTitlebarMouseDown">
      <div class="titlebar__left">
        <div class="logo">OhMy<span>Meme</span></div>
      </div>
      <span class="spacer"></span>
      <div class="titlebar__actions">
        <NButton class="icon-btn" :class="{ on: sortEnabled }" quaternary :type="sortEnabled ? 'primary' : 'default'" title="整理模式" aria-label="整理模式" :aria-pressed="sortEnabled" @click="toggleSort">
          <template #icon>
            <ArrowUpDown :size="16" />
          </template>
        </NButton>
        <NButton class="icon-btn" quaternary title="导入表情包" aria-label="导入表情包" @click="showImportMenu()">
          <template #icon>
            <ImagePlus :size="16" />
          </template>
        </NButton>
        <NDropdown trigger="click" placement="bottom-end" :options="titleMenuOptions" @select="onTitleMenuSelect">
          <NButton class="icon-btn" quaternary title="更多操作" aria-label="更多操作">
            <template #icon>
              <Ellipsis :size="16" />
            </template>
          </NButton>
        </NDropdown>
        <NButton class="title-btn close-btn" quaternary aria-label="隐藏窗口" @click="hideWindow()"><X :size="16" /></NButton>
      </div>
    </header>

    <div id="content">
      <aside id="sidebar" :class="{ collapsed: sidebarCollapsed }">
        <div id="sidebar-header"><span v-if="!sidebarCollapsed">分组</span></div>
        <div id="tree">
          <CollectionTreeNode
            v-for="c in visibleCollections"
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
          <NButton class="sidebar-toggle" :class="{ collapsed: sidebarCollapsed }" quaternary title="折叠/展开侧边栏" aria-label="折叠/展开侧边栏" :aria-expanded="!sidebarCollapsed" @click="toggleSidebar">
            <template #icon>
              <PanelLeft :size="18" />
            </template>
          </NButton>
          <NInput
            class="search-input"
            :value="state.searchQuery"
            :input-props="{ id: 'search', autocomplete: 'off', spellcheck: 'false', style: 'padding-right:32px' }"
            placeholder="搜索表情包..."
            autofocus
            @input="onSearchInput"
          />
          <NButton v-if="state.searchQuery" class="search-clear" quaternary circle size="tiny" title="清除搜索" aria-label="清除搜索" @click="clearSearch"><X :size="14" /></NButton>
        </div>

        <div id="tagbar">
          <NTag
            v-for="tag in state.allTags"
            :key="tag"
            class="tag"
            checkable
            round
            size="small"
            role="button"
            tabindex="0"
            :checked="state.activeTags.has(tag)"
            :aria-pressed="state.activeTags.has(tag)"
            @update:checked="toggleTag(tag)"
            @keydown.enter.prevent="toggleTag(tag)"
            @keydown.space.prevent="toggleTag(tag)"
          >{{ tag }}</NTag>
        </div>

        <div v-if="breadcrumb.length > 1" id="breadcrumb">
          <template v-for="(crumb, idx) in breadcrumb" :key="idx">
            <span v-if="idx > 0" class="crumb-sep">›</span>
            <NButton
              class="crumb"
              :class="{ current: idx === breadcrumb.length - 1 }"
              :strong="idx === breadcrumb.length - 1"
              quaternary
              size="tiny"
              @click="onBreadcrumbClick(crumb.id)"
            >{{ crumb.name }}</NButton>
          </template>
        </div>

        <div v-if="sortEnabled" id="organize-bar" role="toolbar" aria-label="整理模式工具栏">
          <span class="count">已选 {{ state.selectedIds.size }} 项</span>
          <NButton class="btn btn-sm" size="small" :disabled="state.total === 0" @click="selectAllResults">全选</NButton>
          <NButton class="btn btn-sm btn-secondary" size="small" :disabled="state.selectedIds.size === 0" @click="clearSelection">取消选择</NButton>
          <NButton class="btn btn-sm btn-danger" size="small" type="error" :disabled="state.selectedIds.size === 0" @click="batchDelete">批量删除</NButton>
          <span v-if="canReorder()" class="hint">拖动卡片调整顺序</span>
          <NButton class="bar-close" quaternary size="tiny" title="退出整理" aria-label="退出整理" @click="toggleSort">
            <template #icon>
              <X :size="14" />
            </template>
          </NButton>
        </div>

        <div id="grid-wrap" ref="gridWrapRef">
          <div v-if="folderCards.length" ref="folderGridRef" class="meme-grid folder-grid">
            <div
              v-for="child in folderCards"
              :key="'folder-' + child.id"
              class="meme-card folder-card"
              :data-folder-id="child.id"
              role="button"
              tabindex="0"
              :aria-label="'打开分组 ' + child.name"
              @click="onFolderCardClick(child.id)"
              @contextmenu="onFolderCardContext($event, child.id, child.name)"
              @keydown.enter.prevent="onFolderCardClick(child.id)"
              @keydown.space.prevent="onFolderCardClick(child.id)"
            >
              <div class="folder-preview">
                <Folder :size="32" :stroke-width="1.5" />
                <span class="folder-name">{{ child.name }}</span>
              </div>
            </div>
          </div>

          <div
            id="meme-grid"
            class="meme-grid"
            :class="{ 'sort-enabled': sortEnabled && canReorder(), 'select-enabled': sortEnabled }"
            :style="gridStyle"
          >
            <drag-select
              ref="dragSelectRef"
              :key="selectionEpoch"
              :model-value="state.selectedIds"
              @update:model-value="onBoxSelection"
              :disabled="dragSelectDisabled"
              :multiple="true"
              :click-option-to-select="false"
              :draggable-on-option="false"
              :click-blank-to-clear="false"
            >
              <Virtualizer
                v-if="virtualReady && state.total > 0 && gridWrapRef"
                ref="virtualizerRef"
                :key="layoutKey"
                :data="rows"
                :scroll-ref="gridWrapRef as HTMLElement"
                :start-margin="startMargin"
                :item-size="rowPitch"
                :buffer-size="200"
                :shift="false"
                :item-props="rowItemProps"
                :cache="virtualCacheForRender"
                @scroll="onVirtualScroll"
                @resize="onVirtualResize"
                @scroll-end="onVirtualScrollEnd"
              >
                <template #default="{ item: row }">
                  <TransitionGroup
                    :key="row.key"
                    tag="div"
                    name="meme-list"
                    class="virtual-meme-row"
                    :data-row-start="row.start"
                    :data-row-key="row.key"
                  >
                    <template v-for="entry in rowSlots(row)" :key="entry.meme ? 'm' + entry.meme.id : 's' + entry.index">
                      <drag-select-option v-if="entry.meme" :value="entry.meme.id" :disabled="!sortEnabled">
                        <div
                          class="meme-card"
                          :class="{ 'dragging': drag.dragState.active && drag.dragState.memeId === entry.meme.id, selected: state.selectedIds.has(entry.meme.id) }"
                          :data-meme-id="entry.meme.id"
                          role="button"
                          tabindex="0"
                          :aria-label="entry.meme.name"
                          @click="onCardClick(entry.meme)"
                          @contextmenu="onMemeRightClick($event, entry.meme)"
                          @pointerdown="onCardPointerDown($event, entry.meme, $event.currentTarget as HTMLElement)"
                          @mouseenter="onCardMouseEnter(entry.meme)"
                          @mouseleave="onCardMouseLeave(entry.meme)"
                          @keydown.enter.prevent="onCardClick(entry.meme)"
                          @keydown.space.prevent="onCardClick(entry.meme)"
                        >
                          <img :src="memeSrc(entry.meme)" :alt="entry.meme.name" loading="lazy">
                          <span v-if="state.selectedIds.has(entry.meme.id)" class="select-badge"><Check :size="12" /></span>
                          <NButton
                            v-if="!sortEnabled"
                            class="fav-btn"
                            :class="{ active: entry.meme.favorited }"
                            quaternary
                            circle
                            size="tiny"
                            :aria-label="entry.meme.favorited ? '取消收藏' : '收藏'"
                            :title="entry.meme.favorited ? '取消收藏' : '收藏'"
                            @click.stop="quickFavorite(entry.meme)"
                            @pointerdown.stop
                          >
                            <template #icon>
                              <Heart :size="14" />
                            </template>
                          </NButton>
                          <span v-if="entry.meme.from_stego" class="gif-badge stego-badge">隐写导入</span>
                          <span v-else-if="entry.meme.is_animated" class="gif-badge">{{ entry.meme.is_gif ? 'GIF' : 'WebP' }}</span>
                          <span class="meme-name">{{ entry.meme.name }}</span>
                        </div>
                      </drag-select-option>
                      <div v-else class="meme-card skeleton" aria-hidden="true"></div>
                    </template>
                  </TransitionGroup>
                </template>
              </Virtualizer>
            </drag-select>
          </div>

          <div v-if="!virtualReady" class="grid-foot">当前环境不支持虚拟滚动（需要 ResizeObserver 与元素滚动方法）</div>

          <div v-if="virtualReady && state.total === 0 && state.ready && !state.loading && !state.loadError" id="empty">
            <svg class="empty-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 7a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/>
              <path d="M8.5 13.5h7M8.5 16.5h4.5"/>
            </svg>
            <div class="text">还没有表情包</div>
            <NButton class="btn btn-primary" type="primary" @click="showImportMenu()">导入表情包</NButton>
          </div>

          <div v-if="virtualReady && (state.total > 0 || state.loadError)" class="grid-foot" aria-live="polite">
            <template v-if="state.loadError">加载失败</template>
            <template v-else-if="state.loading || state.rangeLoading">加载中…</template>
            <template v-else>共 {{ state.total }} 项</template>
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
  <ConfirmDialog ref="confirmDialog" />

  <NModal
    :show="lanConfirmVisible"
    :close-on-esc="false"
    :theme-overrides="{ boxShadow: 'none' }"
    transform-origin="center"
    @update:show="onLanConfirmShowChange"
  >
    <div class="lan-confirm-box" role="dialog" aria-modal="true" aria-labelledby="lan-confirm-title" @keydown.esc.stop="confirmLanDevice(false)">
      <h2 id="lan-confirm-title">设备连接请求</h2>
      <p>以下设备请求连接本机 OhMyMeme：</p>
      <div class="lan-confirm-info">
        <div><span class="k">设备：</span><b class="v">{{ lanConfirmDevice.name || '未知设备' }}</b></div>
        <div><span class="k">型号：</span><span class="v">{{ lanConfirmDevice.model || '-' }}</span></div>
        <div><span class="k">系统：</span><span class="v">{{ lanConfirmDevice.os || '-' }}</span></div>
        <div><span class="k">版本：</span><span class="v">{{ lanConfirmDevice.ver || '-' }}</span></div>
      </div>
      <p class="lan-confirm-note">允许后该设备可同步表情包与配置。请确认是你信任的设备。</p>
      <div class="lan-confirm-actions">
        <NButton @click="confirmLanDevice(false)">拒绝</NButton>
        <NButton type="primary" @click="confirmLanDevice(true)">允许连接</NButton>
      </div>
    </div>
  </NModal>

  <ContextMenu
    :visible="ctx.visible.value" :x="ctx.x.value" :y="ctx.y.value"
    :items="ctx.items.value" :trigger="ctx.trigger.value"
    @action="onCtxAction" @close="ctx.hide"
  />

  <div id="drop-overlay" :class="{ 'drag-over': dragOver }">
    <div class="drop-content">
      <div class="drop-icon">
        <ImagePlus :size="56" :stroke-width="1.5" />
      </div>
      <div class="drop-text">拖放图片到此处导入</div>
    </div>
  </div>

  <div id="loading" :class="{ show: state.loading }"><NSpin :size="32" /></div>

  <Transition name="startup-fade">
    <div v-if="startupAnim" id="startup-anim" :style="{ background: state.startupBgColor }" @click="dismissStartupAnim">
      <video v-if="startupVideoReady" :src="startupVideoSrc" autoplay muted playsinline @ended="dismissStartupAnim"></video>
    </div>
  </Transition>
</template>
