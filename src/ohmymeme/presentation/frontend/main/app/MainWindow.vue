<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted, computed, h, watch, nextTick } from 'vue'
import { Virtualizer } from 'virtua/vue'
import type { VirtualizerHandle } from 'virtua/vue'
import { useMemes } from '../features/memes/useMemes'
import { useDragSort, type DragDirection, type DragDropResult, type PointerSample, type ScrollFrame } from '../features/sorting/useDragSort'
import { applyMarqueeSelection, gridSlotIndex, normalizeMarqueeRect, rectIntersects, slotOrigin, type GridGeometry, type RectLike } from '../features/sorting/gridInteraction'
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
import { ArrowUpDown, ArrowUp, PanelLeft, X, Heart, Folder, ImagePlus, Check, Ellipsis, CloudUpload, CloudDownload, RefreshCw, Settings } from '@lucide/vue'
import { lanConfirmVisible, lanConfirmDevice, confirmLanDevice, onLanConfirmShowChange } from '../features/lan/showLanDeviceConfirm'

// 后端 evaluate_js 刷新入口（与 main.ts 声明一致；main.ts 不在类型检查范围）
declare global {
  interface Window {
    refreshMemes: () => void
    refreshTags: () => void
    refreshCollections: () => void
  }
}

const { state, search, ensureRange, slot, loadedSlice, setLoadedSlice, pinLoadedRange, invalidateRangeRequests, dispose, setSearch, toggleTag, setActiveCollection, refreshTags, refreshCollections, copyMeme, reorderMemes, canReorder, startNativeDrag, selectAll, clearSelection, loadInitData, retryRange, MEME_PAGE } = useMemes()
const ctx = useContextMenu()
const cb = useCollectionBuilder()
const message = useMessage()

// ── 虚拟网格：固定卡片尺寸 + 行级 Virtualizer（folder-grid 不虚拟化，作为头块计入 startMargin） ──
// 卡片等宽等高：列数由容器宽按最小卡宽 112px / 间隙 10px 推导，卡高先用几何推导再由真实卡尺寸校准
const MEME_GAP = 10
const MEME_MIN_WIDTH = 112
const CARD_FRAME = 28 // 边框 2px×2 + 单行名称（16px 行高 + 上下 padding 12px）
const RANGE_BUFFER = 200 // 与 Virtualizer bufferSize 一致的视口外缓冲像素

const gridWrapRef = ref<HTMLElement | null>(null)
const folderGridRef = ref<HTMLElement | null>(null)
const virtualizerRef = ref<VirtualizerHandle | null>(null)
const virtualReady = ref(true)
const cols = ref(4)
const cardHeight = ref(0)
const startMargin = ref(0)
const layoutKey = ref(0)
let layoutEpoch = 0
let layoutRaf = 0
let rangeRaf = 0
// 组件级卸载门禁：卸载后的异步续体不得再调用 search/ensureRange 等模型操作
let windowUnmounted = false
let gridResizeObserver: ResizeObserver | null = null
let folderResizeObserver: ResizeObserver | null = null
// 「回到顶部」按钮显隐：仅由真实滚动位置驱动（两屏阈值）
const showBackToTop = ref(false)
// 底部错误重试：本地单飞与票号（查询换代/卸载后旧 Promise 不得覆盖新的点击状态）
const retryPending = ref(false)
let retryTicket = 0

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
    const name = card.querySelector<HTMLElement>('.meme-name')
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

// 回顶按钮显示：滚动容器真实滚动超过两屏（恰两屏不显示；0 视口不显示）
function syncBackToTopVisibility() {
  const wrap = gridWrapRef.value
  const visible = !!wrap && wrap.clientHeight > 0 && wrap.scrollTop > 2 * wrap.clientHeight
  if (showBackToTop.value !== visible) showBackToTop.value = visible
}

// 按钮消失时的焦点归宿：按钮曾持有焦点、且焦点确实随按钮丢失（未被用户移走）才交还网格
function restoreFocusFromRemovedButton(button: HTMLElement | null, hadFocus: boolean) {
  if (!hadFocus) return
  void nextTick(() => {
    if (windowUnmounted) return
    if (button && button.isConnected) return
    // 结算期间用户已把焦点移到别处（按钮移除后 activeElement 不再是 body）：不抢焦点
    const active = document.activeElement
    if (active !== null && active !== document.body) return
    gridWrapRef.value?.focus({ preventScroll: true })
  })
}

// 回到顶部：优先 handle.scrollTo(0)（保留 folder 头块）；handle 缺失/异常时只归零仍挂载的滚动容器
function backToTop() {
  if (windowUnmounted || gridActionBusy.value || !virtualReady.value) return
  const wrap = gridWrapRef.value
  if (!wrap || !wrap.isConnected) return
  const button = document.getElementById('back-to-top')
  const handle = virtualizerRef.value
  if (handle) {
    try {
      handle.scrollTo(0)
    } catch (_) {
      wrap.scrollTop = 0
    }
  } else {
    wrap.scrollTop = 0
  }
  syncBackToTopVisibility()
  restoreFocusFromRemovedButton(button, button !== null && document.activeElement === button)
  requestVisibleRange()
}

// 底部错误重试：只重放当前失败目标（不 search/不改选择/回顶），单飞并由票号拦截迟到结算
async function retryFailedRange() {
  if (windowUnmounted || retryDisabled.value) return
  retryPending.value = true
  const ticket = retryTicket
  const button = document.getElementById('grid-retry')
  const buttonHadFocus = button !== null && document.activeElement === button
  try {
    await retryRange()
  } finally {
    if (ticket === retryTicket && !windowUnmounted) {
      retryPending.value = false
      restoreFocusFromRemovedButton(button, buttonHadFocus)
    }
  }
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
  syncBackToTopVisibility()
  if (!layoutChanged && !marginChanged) return
  // 拖拽/框选期间几何变化：统一取消并回滚（旧坐标/索引全部失效），再按新几何重建
  if (drag.dragState.memeId != null) cancelGridDrag('layout')
  if (marqueeSession) cancelMarquee('layout')
  if (layoutChanged && state.total > 0) {
    // 先记录可见位置，再改变列数/卡高重建虚拟izer，nextTick 后恢复
    const anchor = captureScrollAnchor()
    cols.value = nextCols
    cardHeight.value = nextCardHeight
    startMargin.value = nextStartMargin
    layoutEpoch += 1
    layoutKey.value += 1
    void nextTick(() => {
      restoreScrollAnchor(anchor)
      requestVisibleRange()
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
  if (drag.dragState.saving) return
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
  if (drag.dragState.active) {
    // 拖拽中：统一走 ensureDragRange（单飞去重），避免普通视口请求取消预取需求
    if (slotEnd > state.hi) ensureDragRange('forward')
    else if (slotStart < state.lo) ensureDragRange('backward')
    return
  }
  void ensureRange(slotStart, slotEnd)
}

// 视口是否仍落在连续已加载路径内（滚动条远跳的取消判据）
function scrollWithinLoadedPath(): boolean {
  const wrap = gridWrapRef.value
  if (!wrap || !(rowPitch.value > 0) || state.hi <= state.lo) return true
  const width = Math.max(1, cols.value)
  const firstRow = Math.floor(state.lo / width)
  const lastRow = Math.ceil(state.hi / width) - 1
  const contentTop = startMargin.value + firstRow * rowPitch.value
  const contentBottom = startMargin.value + (lastRow + 1) * rowPitch.value
  return wrap.scrollTop + wrap.clientHeight > contentTop && wrap.scrollTop < contentBottom
}

function onVirtualScroll() {
  syncBackToTopVisibility()
  // 框选期间发生任意滚动立即取消（起手坐标失效，按语义恢复起手快照）
  if (marqueeSession) cancelMarquee('scroll')
  if (drag.dragState.memeId != null && !drag.dragState.saving) {
    // 越出连续已加载路径的远跳立即取消；路径内滚动按最新滚动位置重算目标
    if (!scrollWithinLoadedPath()) cancelGridDrag('far-scroll')
    else drag.onScroll()
  }
  requestVisibleRange()
}

function onVirtualScrollEnd() {
  requestVisibleRange()
}

function onVirtualResize() {
  syncBackToTopVisibility()
  requestVisibleRange()
}

// ── 自研可见区框选：空白起手 + 起手快照 XOR 已挂载真卡（滚动/取消按语义回滚） ──
// 会话 idle → armed → selecting：>8px 进入 selecting；单帧用「当前矩形 × 起手快照」重算预览，
// 只命中当前挂载且与模型一致的已加载真卡；滚动立即取消，不做跨视口连续框选与修饰键语义。

const MARQUEE_THRESHOLD = 8
// 旧 WebView 无 PointerEvent 时用 mouse 事件归一成同一会话（两套起手不会同时启动）
const MOUSE_POINTER_ID = 0

type MarqueeOrigin = 'pointer' | 'mouse'

type MarqueePhase = 'armed' | 'selecting'

type MarqueeSession = {
  phase: MarqueePhase
  origin: MarqueeOrigin
  pointerId: number
  startX: number
  startY: number
  lastX: number
  lastY: number
  context: { queryGen: number; browseKey: string; layoutEpoch: number }
  scrollTop: number
  baseSelected: Set<number>
  captured: boolean
  frame: number
}

let marqueeSession: MarqueeSession | null = null
const marqueeBusy = ref(false)
const marqueeBox = reactive({ active: false, x: 0, y: 0, width: 0, height: 0 })

// 工具栏统一忙碌态：活动框选/排序（含保存）期间禁用全选/取消选择/批量删除
const interactionBusy = computed(() => marqueeBusy.value || drag.dragState.active || drag.dragState.saving)

// 窄手势门禁：框选（含 armed）/排序（含保存）期间禁用重试与回顶
const gridActionBusy = computed(() => marqueeBusy.value || drag.dragState.memeId !== null || drag.dragState.saving)
// 重试按钮禁用：本地单飞、请求中与手势期间都不可再次触发
const retryDisabled = computed(() => retryPending.value || gridActionBusy.value || state.loading || state.rangeLoading)

// 两个选择集合是否同内容（避免每帧重复赋值）
function sameSelection(a: Set<number>, b: Set<number>): boolean {
  if (a.size !== b.size) return false
  for (const id of a) if (!b.has(id)) return false
  return true
}

// 骨架 pointer-events:none：用当前骨架矩形做点命中排除，不能只看 event.target
function pointHitsSkeleton(clientX: number, clientY: number): boolean {
  const grid = document.getElementById('meme-grid')
  if (!grid) return false
  for (const card of Array.from(grid.querySelectorAll<HTMLElement>('.meme-card.skeleton'))) {
    const rect = card.getBoundingClientRect()
    if (clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom) return true
  }
  return false
}

// 起手点校验：有效客户区（排除边框/滚动条/工具栏覆盖区）与网格内容右边界内，且不在骨架矩形上
function marqueePointAllowed(clientX: number, clientY: number): boolean {
  const frame = getScrollFrame()
  if (!frame) return false
  if (clientX < frame.left || clientX > frame.right || clientY < frame.top || clientY > frame.bottom) return false
  const geometry = interactionGeometry()
  if (geometry && clientX > geometry.originX + geometry.cols * geometry.pitchX) return false
  return !pointHitsSkeleton(clientX, clientY)
}

// 空白起手资格：仅整理模式、主按钮/主指针、非保存、无现有手势、虚拟化就绪且有数据
function marqueeStartable(target: EventTarget | null, button: number, isPrimary?: boolean): boolean {
  if (!sortEnabled.value || !virtualReady.value) return false
  if (drag.dragState.memeId != null || drag.dragState.saving || marqueeSession) return false
  if (button !== 0 || isPrimary === false) return false
  if (state.total <= 0) return false
  const element = target as HTMLElement | null
  if (element && typeof element.closest === 'function'
    && element.closest('.meme-card, .folder-grid, #organize-bar, .grid-foot, #empty, button, a, input, textarea, select, [contenteditable="true"]')) {
    return false
  }
  return true
}

// 旧 WebView 探测：支持 PointerEvent 时只用 pointer 路径
function pointerEventsSupported(): boolean {
  return typeof window !== 'undefined' && typeof window.PointerEvent === 'function'
}

// 会话校验：查询/浏览键/布局/滚动任一变化即取消（查询变化不恢复旧 Set）
function marqueeSessionValid(session: MarqueeSession): boolean {
  if (state.queryGen !== session.context.queryGen) return false
  if (browseKey.value !== session.context.browseKey) return false
  if (layoutEpoch !== session.context.layoutEpoch) return false
  const wrap = gridWrapRef.value
  if (wrap && wrap.scrollTop !== session.scrollTop) return false
  return true
}

// 命中集合：全局槽位窗口（允许一格余量）→ 当前挂载真卡 → 裁入客户区后与框矩形相交（渲染矩形为准）
function marqueeHits(rect: RectLike): Set<number> {
  const hits = new Set<number>()
  const geometry = interactionGeometry()
  const frame = getScrollFrame()
  if (!geometry || !frame) return hits
  if (!(rect.right > rect.left) || !(rect.bottom > rect.top)) return hits
  const width = Math.max(1, geometry.cols)
  const firstRow = Math.max(0, Math.floor((rect.top - geometry.originY) / geometry.pitchY) - 1)
  const lastRow = Math.max(firstRow, Math.floor((rect.bottom - 1 - geometry.originY) / geometry.pitchY) + 1)
  const firstCol = Math.max(0, Math.floor((rect.left - geometry.originX) / geometry.pitchX) - 1)
  const lastCol = Math.min(width - 1, Math.floor((rect.right - 1 - geometry.originX) / geometry.pitchX) + 1)
  const lo = Math.max(0, firstRow * width + firstCol)
  const hi = Math.min(state.total - 1, lastRow * width + lastCol)
  const clip: RectLike = { left: frame.left, top: frame.top, right: frame.right, bottom: frame.bottom }
  for (let index = lo; index <= hi; index++) {
    const card = document.querySelector<HTMLElement>('#meme-grid .meme-card[data-slot-index="' + index + '"]')
    if (!card || !card.isConnected) continue
    const record = slot(index)
    if (!record || card.dataset['memeId'] !== String(record.id)) continue
    const cardRect = card.getBoundingClientRect()
    const visible = normalizeMarqueeRect(cardRect.left, cardRect.top, cardRect.right, cardRect.bottom, clip)
    if (!rectIntersects(rect, visible)) continue
    hits.add(record.id)
  }
  return hits
}

// 单帧命中：当前矩形 × 起手快照做对称差并替换选择（不在上帧结果上累积）
function applyMarqueeFrame(session: MarqueeSession) {
  const frame = getScrollFrame()
  if (!frame) return
  const clip: RectLike = { left: frame.left, top: frame.top, right: frame.right, bottom: frame.bottom }
  const rect = normalizeMarqueeRect(session.startX, session.startY, session.lastX, session.lastY, clip)
  marqueeBox.x = rect.left
  marqueeBox.y = rect.top
  marqueeBox.width = rect.right - rect.left
  marqueeBox.height = rect.bottom - rect.top
  const next = applyMarqueeSelection(session.baseSelected, marqueeHits(rect))
  if (!sameSelection(next, state.selectedIds)) state.selectedIds = next
}

function scheduleMarqueeFrame(session: MarqueeSession) {
  if (session.frame) return
  session.frame = requestAnimationFrame(() => {
    session.frame = 0
    if (marqueeSession !== session || session.phase !== 'selecting') return
    applyMarqueeFrame(session)
  })
}

// 结束会话：清 overlay/帧/捕获；restore 时仅在同一查询内恢复起手快照（查询变化不回填旧 Set）
function endMarquee(restore: boolean): boolean {
  const session = marqueeSession
  if (!session) return false
  const active = session.phase === 'selecting'
  if (session.frame) { cancelAnimationFrame(session.frame); session.frame = 0 }
  marqueeSession = null
  marqueeBusy.value = false
  marqueeBox.active = false
  if (session.captured) {
    const element = getScrollFrame()?.element
    if (element) {
      try {
        if (typeof element.hasPointerCapture === 'function' && element.hasPointerCapture(session.pointerId)) {
          element.releasePointerCapture(session.pointerId)
        }
      } catch (_) {}
    }
  }
  if (restore && state.queryGen === session.context.queryGen && browseKey.value === session.context.browseKey) {
    state.selectedIds = new Set(session.baseSelected)
  }
  return active
}

// 取消（ESC/blur/cancel/滚动/布局/查询/关闭整理/卸载共用）：返回是否吞掉随后 click
function cancelMarquee(reason: string): boolean {
  void reason
  const active = endMarquee(true)
  if (active) ignoreClick = true
  return active
}

// 建立会话：空白起手只记录起点与起手快照（未过门槛不改选择、不画框）
function startMarqueeSession(clientX: number, clientY: number, pointerId: number, origin: MarqueeOrigin): boolean {
  if (marqueeSession) return false
  if (!marqueePointAllowed(clientX, clientY)) return false
  marqueeSession = {
    phase: 'armed',
    origin,
    pointerId,
    startX: clientX,
    startY: clientY,
    lastX: clientX,
    lastY: clientY,
    context: { queryGen: state.queryGen, browseKey: browseKey.value, layoutEpoch },
    scrollTop: gridWrapRef.value?.scrollTop ?? 0,
    baseSelected: new Set(state.selectedIds),
    captured: false,
    frame: 0,
  }
  marqueeBusy.value = true
  return true
}

function onGridBlankPointerDown(e: PointerEvent) {
  if (!marqueeStartable(e.target, e.button, e.isPrimary)) return
  startMarqueeSession(e.clientX, e.clientY, e.pointerId, 'pointer')
}

// 旧 WebView 无 PointerEvent：mousedown 起手（有 PointerEvent 时直接让位给 pointer 路径）
function onGridBlankMouseDown(e: MouseEvent) {
  if (pointerEventsSupported()) return
  if (!marqueeStartable(e.target, e.button)) return
  startMarqueeSession(e.clientX, e.clientY, MOUSE_POINTER_ID, 'mouse')
}

// 移动：过 8px 门槛进入 selecting（稳定 wrap 捕获指针），随后按需单帧重算
function applyMarqueeMove(session: MarqueeSession, clientX: number, clientY: number, preventDefault: () => void) {
  if (!marqueeSessionValid(session)) { cancelMarquee('invalid'); return }
  session.lastX = clientX
  session.lastY = clientY
  if (session.phase === 'armed') {
    if (Math.hypot(clientX - session.startX, clientY - session.startY) <= MARQUEE_THRESHOLD) return
    session.phase = 'selecting'
    marqueeBox.active = true
    preventDefault()
    if (session.origin === 'pointer') {
      const frame = getScrollFrame()
      if (frame) {
        try {
          frame.element.setPointerCapture(session.pointerId)
          session.captured = true
        } catch (_) {}
      }
    }
  }
  scheduleMarqueeFrame(session)
}

// 抬起：同步完成最后一次命中并保留预览为提交结果；已激活手势吞掉随后 click
function applyMarqueeUp(session: MarqueeSession, clientX: number, clientY: number) {
  // 会话已失效（查询/布局/滚动变化）：只清资源并按语义回滚，不提交
  if (!marqueeSessionValid(session)) { cancelMarquee('invalid'); return }
  session.lastX = clientX
  session.lastY = clientY
  const wasSelecting = session.phase === 'selecting'
  if (wasSelecting) applyMarqueeFrame(session)
  endMarquee(false)
  if (wasSelecting) ignoreClick = true
}

function onMarqueePointerMove(e: PointerEvent) {
  const session = marqueeSession
  if (!session || session.origin !== 'pointer') return
  if (e.pointerId !== session.pointerId) return
  if (e.buttons === 0) { cancelMarquee('buttons'); return }
  applyMarqueeMove(session, e.clientX, e.clientY, () => e.preventDefault())
}

function onMarqueePointerUp(e: PointerEvent) {
  const session = marqueeSession
  if (!session || session.origin !== 'pointer') return
  if (e.pointerId !== session.pointerId) return
  applyMarqueeUp(session, e.clientX, e.clientY)
}

function onMarqueeMouseMove(e: MouseEvent) {
  const session = marqueeSession
  if (!session || session.origin !== 'mouse') return
  if ((e.buttons & 1) === 0) { cancelMarquee('buttons'); return }
  applyMarqueeMove(session, e.clientX, e.clientY, () => e.preventDefault())
}

function onMarqueeMouseUp(e: MouseEvent) {
  const session = marqueeSession
  if (!session || session.origin !== 'mouse') return
  applyMarqueeUp(session, e.clientX, e.clientY)
}

// 指针捕获丢失（非本会话主动释放）：框选或拖拽都取消并清理资源；正常释放与 saving 结算不在此取消
function onGridLostPointerCapture(e: PointerEvent) {
  const marquee = marqueeSession
  if (marquee && marquee.origin === 'pointer' && e.pointerId === marquee.pointerId) {
    cancelMarquee('lost-capture')
    return
  }
  // saving：pointerup 的自动释放捕获不是取消（结算走 RPC 自己的上下文门禁）
  if (drag.dragState.saving) return
  if (drag.dragState.memeId != null && e.pointerId === drag.dragState.pointerId) cancelGridDrag('lost-capture')
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

// ── 整理拖拽接线：全局槽位数学 + 连续扩展窗口（引擎持有手势/基准/持久化门禁与 rAF） ──

// 指针事件 → 窄样本（引擎不接收 DOM 事件对象）
function toPointerSample(e: PointerEvent): PointerSample {
  return {
    pointerId: e.pointerId,
    button: e.button,
    buttons: e.buttons,
    clientX: e.clientX,
    clientY: e.clientY,
    isPrimary: e.isPrimary,
  }
}

// 客户区几何：唯一滚动容器 + 工具栏覆盖后的有效底边（自动滚动触发区）
function getScrollFrame(): ScrollFrame | null {
  const wrap = gridWrapRef.value
  if (!wrap) return null
  const rect = wrap.getBoundingClientRect()
  const top = rect.top + wrap.clientTop
  let bottom = rect.top + wrap.clientTop + wrap.clientHeight
  const bar = document.getElementById('organize-bar')
  if (bar) {
    const barRect = bar.getBoundingClientRect()
    // 底部工具栏有覆盖时把有效底边提升到工具栏顶部，避免必须穿过按钮才触发
    if (barRect.height > 0 && barRect.top < bottom && barRect.bottom > top) bottom = Math.min(bottom, barRect.top)
  }
  return {
    element: wrap,
    left: rect.left + wrap.clientLeft,
    right: rect.left + wrap.clientLeft + wrap.clientWidth,
    top,
    bottom,
    scrollTop: wrap.scrollTop,
    maxScrollTop: Math.max(0, wrap.scrollHeight - wrap.clientHeight),
  }
}

// 全局槽位几何：未变换卡宽/步距与滚动后的内容原点（scale/rotate 不进入数学）
function interactionGeometry(): GridGeometry | null {
  const wrap = gridWrapRef.value
  const grid = document.getElementById('meme-grid')
  if (!wrap || !grid || !(rowPitch.value > 0)) return null
  const wrapStyle = getComputedStyle(wrap)
  const paddingX = finiteNumber(wrapStyle.paddingLeft) + finiteNumber(wrapStyle.paddingRight)
  const width = Math.max(1, cols.value)
  const contentWidth = Math.max(0, wrap.clientWidth - paddingX)
  const sample = grid.querySelector<HTMLElement>('.meme-card[data-meme-id]')
  const measured = sample ? sample.offsetWidth : 0
  const cardWidth = measured > 0 ? measured : Math.max(1, (contentWidth - (width - 1) * MEME_GAP) / width)
  const gridRect = grid.getBoundingClientRect()
  const wrapRect = wrap.getBoundingClientRect()
  const gridStyle = getComputedStyle(grid)
  return {
    originX: gridRect.left + grid.clientLeft + finiteNumber(gridStyle.paddingLeft),
    originY: wrapRect.top + wrap.clientTop + startMargin.value - wrap.scrollTop,
    pitchX: cardWidth + MEME_GAP,
    pitchY: rowPitch.value,
    cols: width,
  }
}

// 当前落点：全局槽位 → 必须是有效客户区内当前挂载且与模型一致的已加载真卡
function getDragTarget(clientX: number, clientY: number): number | null {
  // 记录最近一次落点查询指针：自动滚动写入前用它校验建议滚动后的指针槽位
  lastTargetPointer = { x: clientX, y: clientY }
  const frame = getScrollFrame()
  if (frame && (clientX < frame.left || clientX > frame.right || clientY < frame.top || clientY > frame.bottom)) return null
  const geometry = interactionGeometry()
  if (!geometry) return null
  // 网格内容右边界之外（最后一列后的 pitch 间隙）不是有效目标
  if (clientX > geometry.originX + geometry.cols * geometry.pitchX) return null
  const target = gridSlotIndex(geometry, clientX, clientY, state.total)
  if (target === null) return null
  const card = document.querySelector<HTMLElement>('#meme-grid .meme-card[data-slot-index="' + target + '"]')
  if (!card || !card.isConnected || card.classList.contains('skeleton')) return null
  const record = slot(target)
  if (!record || card.dataset['memeId'] !== String(record.id)) return null
  return target
}

// 最近一次拖拽落点查询的指针位置（自动滚动前的指针槽位校验）
let lastTargetPointer: { x: number; y: number } | null = null

// 建议滚动增量后指针所在槽位是否已加载（未加载则不写该步 scrollTop，交由单飞扩页推进）
function pointerSlotLoadedAfter(delta: number): boolean {
  const pointer = lastTargetPointer
  const geometry = interactionGeometry()
  if (!pointer || !geometry) return true
  const shifted: GridGeometry = { ...geometry, originY: geometry.originY - delta }
  const index = gridSlotIndex(shifted, pointer.x, pointer.y, state.total)
  return index !== null && slot(index) !== undefined
}

// 已加载可推进边界：拖拽自动滚动不得把未加载行推进可见区（加载前沿门禁）
function loadedScrollFrontier(frame: ScrollFrame): { min: number; max: number } | null {
  if (!(rowPitch.value > 0) || state.total === 0 || state.hi <= state.lo) return null
  const width = Math.max(1, cols.value)
  const firstRow = Math.floor(state.lo / width)
  const lastRow = Math.ceil(state.hi / width) - 1
  return {
    min: startMargin.value + firstRow * rowPitch.value,
    max: startMargin.value + (lastRow + 1) * rowPitch.value - (frame.bottom - frame.top),
  }
}

// 拖拽滚动：只操作 #grid-wrap，clamp 到物理边界与加载前沿，返回实际滚动差值
function scrollDragBy(delta: number): number {
  const wrap = gridWrapRef.value
  if (!wrap) return 0
  const before = wrap.scrollTop
  const frame = getScrollFrame()
  if (!frame) return 0
  let next = before + delta
  const frontier = loadedScrollFrontier(frame)
  // 已越界：只阻止继续向未加载方向推进（不强制回跳）；未越界：按边界收口
  if (frontier) {
    if (delta > 0) next = before >= frontier.max ? before : Math.min(next, frontier.max)
    else if (delta < 0) next = before <= frontier.min ? before : Math.max(next, frontier.min)
  }
  next = Math.max(0, Math.min(frame.maxScrollTop, next))
  if (next === before) return 0
  // 建议滚动后指针不得落在未加载槽位：不写该步，交由单飞扩页推进
  if (!pointerSlotLoadedAfter(next - before)) return 0
  wrap.scrollTop = next
  return wrap.scrollTop - before
}

// 可见真卡的未变换槽位原点（按 data-slot-index 与当前几何计算，不读被 scale 影响的矩形）
function captureVisibleOrigins(): Map<number, { left: number; top: number }> {
  const origins = new Map<number, { left: number; top: number }>()
  const grid = document.getElementById('meme-grid')
  const geometry = interactionGeometry()
  if (!grid || !geometry) return origins
  for (const card of Array.from(grid.querySelectorAll<HTMLElement>('.meme-card[data-meme-id][data-slot-index]'))) {
    if (!card.isConnected) continue
    const id = Number(card.dataset['memeId'])
    const index = Number(card.dataset['slotIndex'])
    if (!Number.isFinite(id) || !Number.isInteger(index)) continue
    const origin = slotOrigin(geometry, index)
    if (origin) origins.set(id, origin)
  }
  return origins
}

let flipTimer: ReturnType<typeof setTimeout> | null = null
let flippedNodes: HTMLElement[] = []

// 清理上一批 FLIP 动效：清计时器并移除残留的 .drag-flip（保留仍在动画中的同批节点）
function clearFlipNodes(keep: HTMLElement[] = []) {
  if (flipTimer) { clearTimeout(flipTimer); flipTimer = null }
  const previous = flippedNodes
  flippedNodes = []
  for (const card of previous) {
    if (!keep.includes(card) && card.isConnected) card.classList.remove('drag-flip')
  }
}

// 可见卡局部 FLIP：仅更新前后均可见的非拖动真卡，终态回到普通卡 scale(0.95)
function playVisibleFlip(before: Map<number, { left: number; top: number }>, draggedId: number | null) {
  const grid = document.getElementById('meme-grid')
  const geometry = interactionGeometry()
  if (!grid || !geometry) return
  const flipped: HTMLElement[] = []
  for (const card of Array.from(grid.querySelectorAll<HTMLElement>('.meme-card[data-meme-id][data-slot-index]'))) {
    const id = Number(card.dataset['memeId'])
    if (id === draggedId) continue
    const previous = before.get(id)
    if (!previous) continue
    const index = Number(card.dataset['slotIndex'])
    const current = Number.isInteger(index) ? slotOrigin(geometry, index) : null
    if (!current) continue
    const dx = previous.left - current.left
    const dy = previous.top - current.top
    if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) continue
    card.style.transform = `translate(${dx}px, ${dy}px) scale(0.95)`
    card.classList.add('drag-flip')
    flipped.push(card)
  }
  if (!flipped.length) {
    clearFlipNodes()
    return
  }
  clearFlipNodes(flipped)
  // 读取一次布局强制刷新起始位移，再归零触发 transition
  void flipped[0]?.offsetWidth
  for (const card of flipped) card.style.transform = ''
  flippedNodes = flipped
  flipTimer = setTimeout(() => {
    flipTimer = null
    if (flippedNodes === flipped) flippedNodes = []
    for (const card of flipped) {
      if (card.isConnected) card.classList.remove('drag-flip')
    }
  }, 220)
}

// 引擎 setWindow：写入前后做可见 FLIP，并只在挂载期间冻结行 key
function applyWindowOrder(start: number, items: Meme[]): boolean {
  refreshFrozenRowKeys()
  const before = captureVisibleOrigins()
  const draggedId = drag.dragState.memeId
  const gen = state.queryGen
  if (!setLoadedSlice(start, items)) {
    refreshFrozenRowKeys()
    return false
  }
  void nextTick(() => {
    // 卸载或查询已换代：不播放旧会话的可见 FLIP
    if (windowUnmounted || state.queryGen !== gen) return
    playVisibleFlip(before, draggedId)
    refreshFrozenRowKeys()
  })
  return true
}

// 活动拖拽只为当前挂载行冻结 key（行离开挂载集合即清）：置换期间保持行节点身份但不无限累积
function refreshFrozenRowKeys() {
  if (!drag.dragState.active) {
    if (frozenRowKeys.size) frozenRowKeys.clear()
    return
  }
  const grid = document.getElementById('meme-grid')
  if (!grid) return
  const mounted = new Set<number>()
  for (const row of Array.from(grid.querySelectorAll<HTMLElement>('.virtual-meme-row'))) {
    const start = Number(row.dataset['rowStart'])
    if (!Number.isFinite(start)) continue
    const index = Math.floor(start / Math.max(1, cols.value))
    mounted.add(index)
    const key = row.dataset['rowKey']
    if (!frozenRowKeys.has(index) && key) frozenRowKeys.set(index, key)
  }
  for (const index of Array.from(frozenRowKeys.keys())) {
    if (!mounted.has(index)) frozenRowKeys.delete(index)
  }
}

// 单飞扩页：以已提交 hi/lo 为锚只扩一页；相同前沿不重复请求，失败不每帧重启（交给 useMemes 有限退避）
let dragRangeKey = ''
let dragRangePending = false
let dragRangeGen = 0

function resetDragRange() {
  dragRangeGen += 1
  dragRangeKey = ''
  dragRangePending = false
}

function ensureDragRange(direction: DragDirection) {
  if (windowUnmounted || !drag.dragState.active) return
  if (state.total === 0) return
  const anchor = direction === 'forward' ? state.hi : state.lo
  const key = state.queryGen + ':' + direction + ':' + anchor
  if (dragRangePending || dragRangeKey === key) return
  const start = direction === 'forward' ? anchor : Math.max(0, anchor - MEME_PAGE)
  const end = direction === 'forward' ? Math.min(state.total, anchor + MEME_PAGE) : anchor
  if (end <= start) return
  dragRangeKey = key
  dragRangePending = true
  const gen = dragRangeGen
  void ensureRange(start, end, direction).finally(() => {
    if (gen === dragRangeGen) dragRangePending = false
  })
}

const drag = useDragSort({
  getWindow: () => loadedSlice(),
  setWindow: applyWindowOrder,
  getContext: () => ({ queryGen: state.queryGen, total: state.total, layoutEpoch, browseKey: browseKey.value }),
  canReorder,
  getSortEnabled: () => sortEnabled.value,
  getTarget: getDragTarget,
  getScrollFrame,
  scrollBy: scrollDragBy,
  ensureDragRange,
  acquireExtensionPin: () => pinLoadedRange({ allowExtension: true }),
  freezeForPersist: () => pinLoadedRange(),
  invalidateRequests: invalidateRangeRequests,
  persistFn: (ids: number[]) => reorderMemes(ids),
  onPersistFail: () => {
    if (windowUnmounted) return
    showToast('排序保存失败')
    void search()
  },
})

// 手势结束后的预算恢复：发一次普通视口范围请求（数据层缓存命中分支会按视口裁剪超长窗口）
function restoreViewportBudget() {
  if (windowUnmounted) return
  void nextTick(() => {
    if (windowUnmounted) return
    requestVisibleRangeNow()
  })
}

// 统一取消拖拽：吞掉随后 click 并复位分页/冻结行 key；活动手势结束后补发视口请求恢复预算
function cancelGridDrag(reason: string): boolean {
  const active = drag.cancel(reason)
  if (active) ignoreClick = true
  resetDragRange()
  frozenRowKeys.clear()
  if (active) restoreViewportBudget()
  return active
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

// 卡片点击/回车：整理模式=勾选切换；普通模式=复制（拖拽/框选手势后的首次点击由 ignoreClick 吞掉）
function onCardClick(meme: Meme) {
  if (ignoreClick) { ignoreClick = false; return }
  if (marqueeSession) return
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
  else {
    cancelGridDrag('sort-off')
    // 关闭整理以 clearSelection 为最终结果（框选会话不再回滚起手快照）
    endMarquee(false)
    drag.disable()
    clearSelection()
  }
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
      if (tags == null) break
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
          if (removedFrom !== null && removedFrom > 0) await api('delete_collection', removedFrom)
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
function findParentCollection(items: any[], target: number | null): any | null {
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
function findCollectionNode(items: any[], target: number | null): any | null {
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
    if (result === true || (result !== null && typeof result === 'object' && result.ok)) {
      showToast(existingId ? '已保存到分组：' + name : '分组已创建')
      refreshCollections(); search()
    } else if (result !== null && typeof result === 'object') {
      showToast(result.error || '保存失败')
    } else {
      showToast('保存失败')
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
    if (img) { img.dataset['thumb'] = img.src; img.src = `/api/original/${meme.id}/${encodeURIComponent(meme.filename)}` }
  }, 150)
  hoverTimers.set(meme.id, timer)
}

function onCardMouseLeave(meme: Meme) {
  const timer = hoverTimers.get(meme.id)
  if (timer) { clearTimeout(timer); hoverTimers.delete(meme.id) }
  if (!meme.is_animated || !meme.hover_to_play) return
  const img = document.querySelector(`.meme-card[data-meme-id="${meme.id}"] img`) as HTMLImageElement
  const thumb = img?.dataset['thumb']
  if (img && thumb) img.src = thumb
}

let nativeDragStart: { x: number; y: number; memeId: number } | null = null
let ignoreClick = false

function onCardPointerDown(e: PointerEvent, meme: Meme, card: HTMLElement) {
  ignoreClick = false
  // 整理模式接管指针：只从当前挂载且已加载的真卡发起（源行卸载由独立预览承担）
  if (sortEnabled.value) {
    if (!canReorder()) return
    if (drag.dragState.saving || marqueeSession) return
    if (e.button !== 0 || e.isPrimary === false) return
    const slotIndex = Number(card.dataset['slotIndex'])
    const record = Number.isInteger(slotIndex) ? state.slots[slotIndex] : undefined
    if (!record || record.id !== meme.id) return
    const rect = card.getBoundingClientRect()
    drag.onPointerDown(toPointerSample(e), meme.id, {
      slot: slotIndex,
      width: card.offsetWidth || rect.width,
      height: card.offsetHeight || rect.height,
      rect: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
    })
    return
  }
  if (e.button !== 0) return
  nativeDragStart = { x: e.clientX, y: e.clientY, memeId: meme.id }
}

function onDocPointerMove(e: PointerEvent) {
  if (marqueeSession) { onMarqueePointerMove(e); return }
  if (drag.dragState.memeId != null) {
    if (drag.dragState.saving) return
    drag.onPointerMove(toPointerSample(e))
    if (drag.dragState.active) refreshFrozenRowKeys()
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
  if (marqueeSession) { onMarqueePointerUp(e); return }
  if (drag.dragState.saving) return
  if (drag.dragState.memeId != null) {
    let result: DragDropResult = { active: false, cancelled: false, failed: false, contextLive: true }
    try {
      result = await drag.onPointerUp(toPointerSample(e))
    } catch (_) {
      // 引擎结算异常：清掉手势状态，避免会话/门禁悬挂
      drag.cancel('up-error')
    }
    if (result.active) ignoreClick = true
    // 保存期间被取消：仅当原会话上下文仍有效时才按数据库重同步（旧代次不 search、不清空新查询）
    if (result.cancelled && !result.failed && result.contextLive && !windowUnmounted) void search()
    // 成功/取消结束都补一次视口请求，触发数据层缓存命中裁剪恢复预算
    restoreViewportBudget()
    return
  }
  nativeDragStart = null
}

function onDocPointerCancel() {
  if (marqueeSession) cancelMarquee('pointer-cancel')
  if (drag.dragState.memeId != null || drag.dragState.saving) cancelGridDrag('pointer-cancel')
  nativeDragStart = null
}

function onVisibilityChange() {
  if (!document.hidden) return
  if (marqueeSession) cancelMarquee('visibility')
  if (drag.dragState.memeId != null || drag.dragState.saving) cancelGridDrag('visibility')
}

// 页面内图片的默认 HTML5 拖拽会与整理/原生文件拖拽竞争：网格内图片的 dragstart 一律阻止
function onDocDragStart(e: DragEvent) {
  const target = e.target as HTMLElement | null
  if (target && typeof target.closest === 'function' && target.closest('#meme-grid img, .meme-card img')) e.preventDefault()
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

// ESC：LAN 确认 → 右键菜单 → 活动框选/排序手势 → 整理模式 → 隐藏窗口（第一次 ESC 取消手势不退出整理）
function onDocKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (lanConfirmVisible.value) { confirmLanDevice(false); return }
  if (ctx.visible.value) { ctx.hide(); return }
  if (marqueeSession) { cancelMarquee('esc'); return }
  if (drag.dragState.active || drag.dragState.saving) { cancelGridDrag('esc'); return }
  if (sortEnabled.value) { toggleSort(); return }
  hideWindow()
}

onMounted(() => {
  document.addEventListener('dragstart', onDocDragStart)
  document.addEventListener('dragenter', onDragEnter)
  document.addEventListener('dragover', onDragOver)
  document.addEventListener('dragleave', onDragLeave)
  document.addEventListener('drop', onDrop)
  document.addEventListener('mousemove', onWindowMouseMove)
  document.addEventListener('mouseup', onWindowMouseUp)
  document.addEventListener('pointermove', onDocPointerMove)
  document.addEventListener('pointerup', onDocPointerUp)
  document.addEventListener('pointercancel', onDocPointerCancel)
  // 旧 WebView 无 PointerEvent 时的框选 mouse 回退（有 PointerEvent 时不会启动）
  document.addEventListener('mousemove', onMarqueeMouseMove)
  document.addEventListener('mouseup', onMarqueeMouseUp)
  document.addEventListener('keydown', onDocKeydown)
  document.addEventListener('visibilitychange', onVisibilityChange)
  window.addEventListener('blur', onDocPointerCancel)
  // 框选/拖拽丢失指针捕获即取消（正常释放时状态已复位）
  gridWrapRef.value?.addEventListener('lostpointercapture', onGridLostPointerCapture)
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
    syncBackToTopVisibility()
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
  retryTicket += 1
  window.refreshMemes = () => {}
  window.refreshTags = () => {}
  window.refreshCollections = () => {}
  document.removeEventListener('dragstart', onDocDragStart)
  document.removeEventListener('dragenter', onDragEnter)
  document.removeEventListener('dragover', onDragOver)
  document.removeEventListener('dragleave', onDragLeave)
  document.removeEventListener('drop', onDrop)
  document.removeEventListener('mousemove', onWindowMouseMove)
  document.removeEventListener('mouseup', onWindowMouseUp)
  document.removeEventListener('pointermove', onDocPointerMove)
  document.removeEventListener('pointerup', onDocPointerUp)
  document.removeEventListener('pointercancel', onDocPointerCancel)
  document.removeEventListener('mousemove', onMarqueeMouseMove)
  document.removeEventListener('mouseup', onMarqueeMouseUp)
  document.removeEventListener('keydown', onDocKeydown)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  window.removeEventListener('blur', onDocPointerCancel)
  gridWrapRef.value?.removeEventListener('lostpointercapture', onGridLostPointerCapture)
  if (updateInterval) { clearInterval(updateInterval); updateInterval = null }
  hoverTimers.forEach(t => clearTimeout(t))
  hoverTimers.clear()
  drag.cancel('unmount')
  endMarquee(false)
  resetDragRange()
  frozenRowKeys.clear()
  clearFlipNodes()
  if (layoutRaf) { cancelAnimationFrame(layoutRaf); layoutRaf = 0 }
  if (rangeRaf) { cancelAnimationFrame(rangeRaf); rangeRaf = 0 }
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
    // 初始化失败时跳过后台 search：它会清掉 init 失败描述与错误入口，改为等待用户点击重试走 loadInitData
    if (initOk) await search()
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

// 切换分组/标签/搜索词时滚动复位（窗口/cache 代次变化不触发）
const browseKey = computed(() => (state.activeCollection ?? 'all') + '|' + state.searchQuery + '|' + [...state.activeTags].sort().join(','))
watch(browseKey, () => { if (gridWrapRef.value) gridWrapRef.value.scrollTop = 0 })

// 同查询显式 search 刷新：滚动复位；拖拽/框选中先取消手势（查询变化不回填旧选择）
watch(() => state.queryGen, () => {
  // 新查询立即复位重试 UI 状态，并让旧重试 Promise 的结算失效
  retryTicket += 1
  retryPending.value = false
  cancelGridDrag('query')
  cancelMarquee('query')
  if (gridWrapRef.value) gridWrapRef.value.scrollTop = 0
  syncBackToTopVisibility()
  hoverTimers.forEach(t => clearTimeout(t))
  hoverTimers.clear()
  void nextTick(() => { refreshLayout(); requestVisibleRange() })
})

// 活动拖拽结束（成功/取消）：复位单飞扩页门禁与冻结行 key
watch(() => drag.dragState.active, (now, was) => {
  if (was && !now) {
    resetDragRange()
    frozenRowKeys.clear()
  }
})

// 缓存填充（骨架→真卡）或总数变化：新头/尾页并入拖拽基准，并重算可见窗口
watch([() => state.lo, () => state.hi, () => state.total], () => {
  if (drag.dragState.active) drag.syncWindow()
  void nextTick(() => {
    requestVisibleRange()
    refreshFrozenRowKeys()
  })
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
          <NButton class="btn btn-sm" size="small" :disabled="state.total === 0 || interactionBusy" @click="selectAllResults">全选</NButton>
          <NButton class="btn btn-sm btn-secondary" size="small" :disabled="state.selectedIds.size === 0 || interactionBusy" @click="clearSelection">取消选择</NButton>
          <NButton class="btn btn-sm btn-danger" size="small" type="error" :disabled="state.selectedIds.size === 0 || interactionBusy" @click="batchDelete">批量删除</NButton>
          <span v-if="canReorder()" class="hint">拖动卡片调整顺序</span>
          <NButton class="bar-close" quaternary size="tiny" title="退出整理" aria-label="退出整理" @click="toggleSort">
            <template #icon>
              <X :size="14" />
            </template>
          </NButton>
        </div>

        <div id="grid-wrap" ref="gridWrapRef" tabindex="-1" @pointerdown="onGridBlankPointerDown" @mousedown="onGridBlankMouseDown">
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
            :class="{ 'sort-enabled': sortEnabled && canReorder(), 'select-enabled': sortEnabled, 'drag-active': drag.dragState.active }"
            :style="gridStyle"
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
              @scroll="onVirtualScroll"
              @resize="onVirtualResize"
              @scroll-end="onVirtualScrollEnd"
            >
              <template #default="{ item: row }">
                <TransitionGroup
                  :key="row.key"
                  tag="div"
                  name="meme-list"
                  :move-class="drag.dragState.active ? 'meme-list-move-disabled' : 'meme-list-move'"
                  class="virtual-meme-row"
                  :data-row-start="row.start"
                  :data-row-key="row.key"
                >
                  <template v-for="entry in rowSlots(row)" :key="entry.meme ? 'm' + entry.meme.id : 's' + entry.index">
                    <div
                      v-if="entry.meme"
                      class="meme-card"
                      :class="{ 'drag-placeholder': drag.dragState.active && drag.dragState.memeId === entry.meme.id, selected: state.selectedIds.has(entry.meme.id) }"
                      :data-slot-index="entry.index"
                      :data-meme-id="entry.meme.id"
                      role="button"
                      tabindex="0"
                      :aria-pressed="sortEnabled ? state.selectedIds.has(entry.meme.id) : undefined"
                      :aria-label="entry.meme.name"
                      @click="onCardClick(entry.meme)"
                      @contextmenu="onMemeRightClick($event, entry.meme)"
                      @pointerdown="onCardPointerDown($event, entry.meme, $event.currentTarget as HTMLElement)"
                      @mouseenter="onCardMouseEnter(entry.meme)"
                      @mouseleave="onCardMouseLeave(entry.meme)"
                      @keydown.enter.prevent="onCardClick(entry.meme)"
                      @keydown.space.prevent="onCardClick(entry.meme)"
                    >
                      <img :src="memeSrc(entry.meme)" :alt="entry.meme.name" loading="lazy" draggable="false">
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
                    <div v-else class="meme-card skeleton" aria-hidden="true"></div>
                  </template>
                </TransitionGroup>
              </template>
            </Virtualizer>
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

          <div v-if="virtualReady && (state.total > 0 || state.loadError || state.loading || state.rangeLoading)" class="grid-foot" aria-live="polite" role="status" aria-atomic="true">
            <template v-if="state.loading || state.rangeLoading">加载中…</template>
            <NButton v-else-if="state.loadError" id="grid-retry" class="grid-retry" text size="small" aria-label="重新加载表情包" :disabled="retryDisabled" @click="retryFailedRange">加载失败，点击重试</NButton>
            <template v-else>共 {{ state.total }} 项</template>
          </div>
        </div>

        <NButton
          v-if="virtualReady && state.total > 0 && showBackToTop"
          id="back-to-top"
          :class="{ 'with-organize-bar': sortEnabled }"
          :disabled="gridActionBusy"
          title="回到顶部"
          aria-label="回到顶部"
          @click="backToTop"
        >
          <template #icon>
            <ArrowUp :size="16" />
          </template>
        </NButton>
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

  <div
    v-if="drag.ghost.visible && drag.ghost.meme"
    class="drag-ghost meme-card dragging"
    aria-hidden="true"
    :style="{ width: drag.ghost.width + 'px', height: drag.ghost.height + 'px', transform: drag.ghost.transform }"
  >
    <img :src="memeSrc(drag.ghost.meme)" alt="" draggable="false">
    <span v-if="drag.ghost.meme.from_stego" class="gif-badge stego-badge">隐写导入</span>
    <span v-else-if="drag.ghost.meme.is_animated" class="gif-badge">{{ drag.ghost.meme.is_gif ? 'GIF' : 'WebP' }}</span>
    <span class="meme-name">{{ drag.ghost.meme.name }}</span>
  </div>

  <div
    v-if="marqueeBox.active"
    class="marquee-overlay"
    aria-hidden="true"
    :style="{ left: marqueeBox.x + 'px', top: marqueeBox.y + 'px', width: marqueeBox.width + 'px', height: marqueeBox.height + 'px' }"
  ></div>

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
