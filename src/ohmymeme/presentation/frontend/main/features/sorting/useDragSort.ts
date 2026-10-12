import { reactive, readonly, ref } from 'vue'
import { buildDropOrder, edgeScrollVelocity } from './gridInteraction'
import type { Meme } from '../../shared/types'

// 整理拖拽引擎：全局槽位/连续扩展窗口 + 独立固定预览 + rAF 边缘自动滚动 + 保存门禁
// 手势状态机：idle → armed → dragging → saving → idle（armed 未过 8px 门槛，saving 冻结事件与分页）

// 窄指针样本：引擎不接收 DOM 事件对象，便于 WebView 归一与测试驱动
export type PointerSample = {
  pointerId: number
  button: number
  buttons: number
  clientX: number
  clientY: number
  isPrimary?: boolean
}

// 拖动源卡：绝对槽位、未变换尺寸与当前视觉矩形（抓取比例映射到 0.90 预览）
export type DragSource = {
  slot: number
  width: number
  height: number
  rect: { left: number; top: number; width: number; height: number }
}

// 基准窗口：绝对起始槽位与未重排记录（每帧都从基准重建预览）
export type DragWindow = { start: number; items: Meme[] }

// 拖拽上下文：查询/总数/布局/浏览键任一变化即失效（普通补页推进不是失效条件）
export type DragContext = { queryGen: number; total: number; layoutEpoch: number; browseKey: string }

// 客户区滚动几何：element 为唯一滚动容器（稳定捕获目标），bottom 为工具栏覆盖后的有效底边
export type ScrollFrame = {
  element: HTMLElement
  left: number
  right: number
  top: number
  bottom: number
  scrollTop: number
  maxScrollTop: number
}

export type DragDirection = 'forward' | 'backward'

// 落点结果：active=发生过排序手势（调用方吞 click），cancelled=保存期间被取消（需重同步），
// failed=RPC 失败，contextLive=结算时原会话上下文仍有效（决定是否允许 toast/重同步）
export type DragDropResult = { active: boolean; cancelled: boolean; failed: boolean; contextLive: boolean }

export type DragSortOptions = {
  getWindow: () => DragWindow
  setWindow: (start: number, items: Meme[]) => boolean
  getContext: () => DragContext
  canReorder: () => boolean
  getSortEnabled: () => boolean
  getTarget: (clientX: number, clientY: number) => number | null
  getScrollFrame: () => ScrollFrame | null
  scrollBy: (delta: number) => number
  ensureDragRange: (direction: DragDirection) => void
  acquireExtensionPin: () => () => void
  freezeForPersist: () => () => void
  invalidateRequests: () => void
  persistFn: (ids: number[]) => Promise<boolean>
  onPersistFail?: () => void
}

// 激活门槛、ghost 缩放与单帧 dt 上限（后台恢复不大跳）
const DRAG_THRESHOLD = 8
const GHOST_SCALE = 0.9
const FRAME_MS = 32

type DragPhase = 'armed' | 'dragging' | 'saving'

type DragSession = {
  phase: DragPhase
  pointerId: number
  startX: number
  startY: number
  lastX: number
  lastY: number
  dragId: number
  sourceSlot: number
  sourceWidth: number
  sourceHeight: number
  sourceRect: DragSource['rect']
  grabX: number
  grabY: number
  context: DragContext
  baseline: DragWindow | null
  previewSlot: number | null
  releaseExtension: (() => void) | null
  releaseFreeze: (() => void) | null
  cancelledDuringPersist: boolean
  rafId: number
  lastFrameTs: number
}

// 同一位置点是否描述了同一筛选/布局上下文
function sameContext(a: DragContext, b: DragContext): boolean {
  return a.queryGen === b.queryGen && a.total === b.total
    && a.layoutEpoch === b.layoutEpoch && a.browseKey === b.browseKey
}

// 两个窗口是否持有同一 id 集合（顺序无关）
function sameIdSet(a: Meme[], b: Meme[]): boolean {
  if (a.length !== b.length) return false
  const ids = new Set<number>()
  for (const record of b) ids.add(record.id)
  if (ids.size !== b.length) return false
  for (const record of a) if (!ids.has(record.id)) return false
  return true
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value))
}

export function useDragSort(options: DragSortOptions) {
  const {
    getWindow,
    setWindow,
    getContext,
    canReorder,
    getSortEnabled,
    getTarget,
    getScrollFrame,
    scrollBy,
    ensureDragRange,
    acquireExtensionPin,
    freezeForPersist,
    invalidateRequests,
    persistFn,
  } = options
  const onPersistFail = options.onPersistFail

  const sortEnabled = ref(false)
  // 只读手势状态：active=活动拖拽，saving=保存门禁，pointerId=本会话指针（供捕获丢失判定）
  const dragState = reactive({ active: false, memeId: null as number | null, saving: false, pointerId: null as number | null })
  // 独立预览数据：固定未变换尺寸 + 最终 transform（translate(...) scale(0.90)），由 MainWindow 渲染
  const ghost = reactive({ visible: false, meme: null as Meme | null, width: 0, height: 0, transform: '' })
  // 实例私有会话：不再有跨实例共享的模块级 dragState
  let session: DragSession | null = null

  function enable() { sortEnabled.value = true }

  function disable() { sortEnabled.value = false }

  function toggle() { sortEnabled.value = !sortEnabled.value }

  // 上下文校验：查询/总数/布局/浏览键任一变化即失效
  function contextValid(s: DragSession): boolean {
    return sameContext(getContext(), s.context)
  }

  // 稳定容器捕获：不依赖源卡 DOM，行卸载/跨行重挂后仍接收指针事件
  function capturePointer(s: DragSession) {
    const frame = getScrollFrame()
    if (!frame) return
    try { frame.element.setPointerCapture(s.pointerId) } catch (_) {}
  }

  function releaseCapture(s: DragSession) {
    const element = getScrollFrame()?.element
    if (!element) return
    try {
      if (typeof element.hasPointerCapture === 'function' && element.hasPointerCapture(s.pointerId)) {
        element.releasePointerCapture(s.pointerId)
      }
    } catch (_) {}
  }

  // ghost 固定使用未变换卡宽/高，跟随同一抓取点（滚动后仍贴指针）
  function updateGhost(s: DragSession) {
    if (!ghost.visible) return
    const x = Math.round((s.lastX - s.grabX) * 100) / 100
    const y = Math.round((s.lastY - s.grabY) * 100) / 100
    ghost.transform = `translate(${x}px, ${y}px) scale(0.90)`
  }

  // 指针是否落在有效客户区（水平范围 + footer/工具栏之上的有效底边）
  function insideFrame(s: DragSession, frame: ScrollFrame | null): boolean {
    if (!frame) return false
    return s.lastX >= frame.left && s.lastX <= frame.right
      && s.lastY >= frame.top && s.lastY <= frame.bottom
  }

  // 指针样本 → 绝对槽位：越出有效客户区或暂未挂载真卡时返回 null（不沿用最后合法目标）
  function updatePointer(s: DragSession): number | null {
    updateGhost(s)
    const target = insideFrame(s, getScrollFrame()) ? getTarget(s.lastX, s.lastY) : null
    if (target === null) {
      s.previewSlot = null
      return null
    }
    if (target === s.previewSlot) return target
    const base = s.baseline
    if (!base) return null
    const order = buildDropOrder(base, s.dragId, target)
    if (!order) return null
    if (!setWindow(base.start, order)) {
      cancelSession(s, 'window-write')
      return null
    }
    s.previewSlot = target
    return target
  }

  // 单 rAF pump：指针静止也在边缘持续推进；dt clamp；前沿/物理边界暂停交由单飞扩页推进
  function frameStep(s: DragSession, ts: number) {
    if (session !== s || s.phase !== 'dragging') { s.rafId = 0; return }
    if (!contextValid(s) || !getSortEnabled() || !canReorder()) { cancel('frame-invalid'); return }
    const dt = s.lastFrameTs > 0 ? Math.min(FRAME_MS, Math.max(0, ts - s.lastFrameTs)) : 0
    s.lastFrameTs = ts
    const frame = getScrollFrame()
    if (frame && !(typeof document !== 'undefined' && document.hidden)) {
      const horizontal = s.lastX >= frame.left && s.lastX <= frame.right
      if (!horizontal) {
        // 水平越出有效客户区：速度/目标都置空，ghost 仍跟随指针
        updateGhost(s)
        s.previewSlot = null
      } else {
        const inside = s.lastY >= frame.top && s.lastY <= frame.bottom
        const velocity = inside ? edgeScrollVelocity(s.lastY, frame.top, frame.bottom) : 0
        if (velocity !== 0 && dt > 0) {
          const actual = scrollBy(velocity * (dt / 1000))
          // 已到物理边界或加载前沿：暂停穿越骨架，交由单飞扩页推进
          if (actual === 0) ensureDragRange(velocity > 0 ? 'forward' : 'backward')
        }
        const target = updatePointer(s)
        if (target === null && inside) {
          // 目标暂未挂载/未加载：按指针所在半区提前扩一页
          ensureDragRange(s.lastY < (frame.top + frame.bottom) / 2 ? 'backward' : 'forward')
        }
      }
    }
    // 帧内取消（窗口写失败等）后不得再排下一帧
    if (session !== s || s.phase !== 'dragging') { s.rafId = 0; return }
    s.rafId = requestAnimationFrame(next => frameStep(s, next))
  }

  function startPump(s: DragSession) {
    if (s.rafId) return
    s.lastFrameTs = 0
    s.rafId = requestAnimationFrame(ts => frameStep(s, ts))
  }

  function stopPump(s: DragSession) {
    if (!s.rafId) return
    cancelAnimationFrame(s.rafId)
    s.rafId = 0
  }

  // 清理会话：停止帧、先复位只读状态再释放捕获（正常释放的 lostpointercapture 不得再触发取消）
  function clearSession(s: DragSession) {
    stopPump(s)
    if (session === s) session = null
    dragState.active = false
    dragState.memeId = null
    dragState.saving = false
    dragState.pointerId = null
    ghost.visible = false
    ghost.meme = null
    ghost.transform = ''
    releaseCapture(s)
    s.releaseExtension?.()
    s.releaseExtension = null
    s.releaseFreeze?.()
    s.releaseFreeze = null
  }

  // 恢复基准顺序：仅当代次有效且窗口仍与基准同集合（新页保留、不回滚旧库）
  function restoreWindow(s: DragSession): boolean {
    const base = s.baseline
    if (!base || !contextValid(s)) return false
    const win = getWindow()
    if (win.start !== base.start || win.items.length !== base.items.length) return false
    if (!sameIdSet(win.items, base.items)) return false
    return setWindow(base.start, base.items)
  }

  // 取消会话：RPC 前可回滚基准；只清本会话资源
  function cancelSession(s: DragSession, reason?: string) {
    void reason
    if (s.phase === 'dragging') restoreWindow(s)
    clearSession(s)
  }

  // 激活：核验源仍在窗口内且上下文有效，建立基准/扩展 pin/稳定捕获/预览
  function activate(s: DragSession): boolean {
    const win = getWindow()
    const local = s.sourceSlot - win.start
    const record = local >= 0 && local < win.items.length ? win.items[local] : undefined
    if (!record || record.id !== s.dragId) { clearSession(s); return false }
    if (!contextValid(s)) { clearSession(s); return false }
    s.baseline = { start: win.start, items: [...win.items] }
    s.previewSlot = null
    s.phase = 'dragging'
    s.releaseExtension = acquireExtensionPin()
    const rect = s.sourceRect
    const relX = rect.width > 0 ? clamp01((s.startX - rect.left) / rect.width) : 0.5
    const relY = rect.height > 0 ? clamp01((s.startY - rect.top) / rect.height) : 0.5
    s.grabX = relX * s.sourceWidth * GHOST_SCALE
    s.grabY = relY * s.sourceHeight * GHOST_SCALE
    ghost.meme = record
    ghost.width = s.sourceWidth
    ghost.height = s.sourceHeight
    ghost.visible = true
    dragState.active = true
    capturePointer(s)
    updateGhost(s)
    startPump(s)
    return true
  }

  // 按下：只记录起点与源卡（id/绝对槽位已由 MainWindow 校验）；超过门槛才激活
  function onPointerDown(e: PointerSample, memeId: number, source: DragSource): boolean {
    if (e.button !== 0 || e.isPrimary === false) return false
    if (!getSortEnabled() || !canReorder()) return false
    if (dragState.saving || session) return false
    if (!Number.isInteger(e.pointerId)) return false
    if (!Number.isInteger(source.slot)) return false
    session = {
      phase: 'armed',
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      lastX: e.clientX,
      lastY: e.clientY,
      dragId: memeId,
      sourceSlot: source.slot,
      sourceWidth: Math.max(1, source.width),
      sourceHeight: Math.max(1, source.height),
      sourceRect: source.rect,
      grabX: 0,
      grabY: 0,
      context: getContext(),
      baseline: null,
      previewSlot: null,
      releaseExtension: null,
      releaseFreeze: null,
      cancelledDuringPersist: false,
      rafId: 0,
      lastFrameTs: 0,
    }
    // MainWindow 按 memeId 路由指针事件（armed/saving 期间同一路由）；pointerId 供捕获丢失/事件归属判定
    dragState.memeId = memeId
    dragState.active = false
    dragState.pointerId = e.pointerId
    return true
  }

  // 移动：armed 过门槛激活；dragging 立即重算 ghost 与目标（帧内同样重算）；只接受本会话指针
  function onPointerMove(e: PointerSample) {
    const s = session
    if (!s || s.phase === 'saving') return
    if (e.pointerId !== s.pointerId || e.isPrimary === false) return
    if (e.buttons === 0) { cancel('buttons'); return }
    s.lastX = e.clientX
    s.lastY = e.clientY
    if (s.phase === 'armed') {
      if (Math.hypot(e.clientX - s.startX, e.clientY - s.startY) <= DRAG_THRESHOLD) return
      if (!activate(s)) return
    }
    updatePointer(s)
  }

  // 滚动：armed 立即取消（起手坐标失效）；dragging 按最新坐标/滚动重算
  function onScroll() {
    const s = session
    if (!s) return
    if (s.phase === 'armed') { cancel('scroll'); return }
    if (s.phase !== 'dragging') return
    if (!contextValid(s)) { cancel('context'); return }
    updatePointer(s)
  }

  // 视口变化后的窗口同步：新头/尾页并入基准并重建预览；窗口被裁剪/远跳则取消
  function syncWindow() {
    const s = session
    if (!s || s.phase !== 'dragging') return
    if (!contextValid(s)) { cancel('context'); return }
    const base = s.baseline
    if (!base) return
    const win = getWindow()
    const baseEnd = base.start + base.items.length
    if (win.start === base.start && win.items.length === base.items.length) return
    // 只接受两侧密集增长：头/尾新增页，基准范围必须完整保留
    const headLen = base.start - win.start
    const tailLen = win.start + win.items.length - baseEnd
    if (headLen < 0 || tailLen < 0) { cancel('window-shrink'); return }
    const head = win.items.slice(0, headLen)
    const middle = win.items.slice(headLen, headLen + base.items.length)
    const tail = win.items.slice(headLen + base.items.length)
    if (middle.length !== base.items.length || !sameIdSet(middle, base.items)) { cancel('window-ids'); return }
    s.baseline = { start: win.start, items: [...head, ...base.items, ...tail] }
    // 新页并入基准后按当前目标重算预览；目标暂空时保留既有排列（不压缩 offset）
    let next = [...head, ...middle, ...tail]
    if (s.previewSlot !== null) {
      const order = buildDropOrder(s.baseline, s.dragId, s.previewSlot)
      if (order) next = order
      else s.previewSlot = null
    }
    if (!setWindow(s.baseline.start, next)) { cancel('window-write'); return }
  }

  // 抬起：归属/资格/上下文复核 → 同步重算并验证目标 → 冻结 pin + 失效在途请求 → 提交完整密集扩展窗口 id → saving
  async function onPointerUp(e?: PointerSample): Promise<DragDropResult> {
    const s = session
    if (!s) return { active: false, cancelled: false, failed: false, contextLive: true }
    // 非本会话指针（其他手指/次要指针）的抬起不得结算本会话
    if (e && (e.pointerId !== s.pointerId || e.isPrimary === false)) {
      return { active: false, cancelled: false, failed: false, contextLive: contextValid(s) }
    }
    if (e) { s.lastX = e.clientX; s.lastY = e.clientY }
    if (s.phase === 'armed') {
      clearSession(s)
      return { active: false, cancelled: false, failed: false, contextLive: true }
    }
    const live = contextValid(s)
    if (s.phase === 'saving') {
      return { active: true, cancelled: s.cancelledDuringPersist, failed: false, contextLive: live }
    }
    // drop 入口复核资格与上下文：已换代/降权时只取消本会话（不回滚旧库、不持久化、不 toast）
    if (!live || !getSortEnabled() || !canReorder()) {
      cancelSession(s, 'drop-invalid')
      return { active: true, cancelled: false, failed: false, contextLive: false }
    }
    // 无合法当前目标（越界/骨架/未挂载）或落点失效：取消全部预览，不等待网络后猜落点
    const target = insideFrame(s, getScrollFrame()) ? getTarget(s.lastX, s.lastY) : null
    if (target === null) {
      cancelSession(s, 'drop-target')
      return { active: true, cancelled: false, failed: false, contextLive: live }
    }
    if (target !== s.previewSlot) {
      const order = s.baseline ? buildDropOrder(s.baseline, s.dragId, target) : null
      if (!s.baseline || !order || !setWindow(s.baseline.start, order)) {
        cancelSession(s, 'drop-apply')
        return { active: true, cancelled: false, failed: false, contextLive: live }
      }
      s.previewSlot = target
    }
    const ids = getWindow().items.map(record => record.id)
    if (!ids.includes(s.dragId)) {
      cancelSession(s, 'drop-missing')
      return { active: true, cancelled: false, failed: false, contextLive: live }
    }
    stopPump(s)
    ghost.visible = false
    // 进入 saving：主动释放捕获并结束指针归属（正常 pointerup 的自动释放捕获不得当作取消）
    releaseCapture(s)
    dragState.pointerId = null
    s.phase = 'saving'
    dragState.active = false
    dragState.saving = true
    s.releaseFreeze = freezeForPersist()
    invalidateRequests()
    let ok = false
    try {
      ok = await persistFn(ids)
    } catch (_) {
      ok = false
    }
    // 结算副作用必须校验原会话上下文：旧代次只清本会话资源，不 toast、不重同步（避免清空新查询）
    const settledLive = contextValid(s)
    let failed = false
    if (!ok) {
      failed = true
      if (settledLive) {
        restoreWindow(s)
        onPersistFail?.()
      }
    }
    const cancelled = s.cancelledDuringPersist
    clearSession(s)
    return { active: true, cancelled, failed, contextLive: settledLive }
  }

  // 取消：返回是否吞掉随后的 click；saving 中只记录需重同步并立即停止视觉/帧
  function cancel(reason = ''): boolean {
    void reason
    const s = session
    if (!s) return false
    if (s.phase === 'saving') {
      s.cancelledDuringPersist = true
      stopPump(s)
      ghost.visible = false
      return true
    }
    const active = s.phase === 'dragging'
    cancelSession(s, reason)
    return active
  }

  return {
    dragSortEnabled: readonly(sortEnabled),
    dragState: readonly(dragState),
    ghost: readonly(ghost),
    enable,
    disable,
    toggle,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onScroll,
    syncWindow,
    cancel,
  }
}
