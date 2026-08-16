import { reactive, readonly, ref } from 'vue'
import type { Meme } from '../types'

const dragSortEnabled = ref(false)

interface DragState {
  active: boolean
  memeId: number | null
  card: HTMLElement | null
  offX: number
  offY: number
  startX: number
  startY: number
  curIndex: number
}

const dragState = reactive<DragState>({
  active: false,
  memeId: null,
  card: null,
  offX: 0,
  offY: 0,
  startX: 0,
  startY: 0,
  curIndex: -1,
})

interface GridMetrics {
  originX: number
  originY: number
  pitchX: number
  pitchY: number
  cols: number
}

function gridMetrics(grid: HTMLElement): GridMetrics | null {
  const gRect = grid.getBoundingClientRect()
  const cards = Array.from(grid.querySelectorAll('.meme-card'))
  if (!cards.length) return null
  const style = getComputedStyle(grid)
  const finite = (v: string) => {
    const p = parseFloat(v)
    return Number.isFinite(p) ? p : 0
  }
  const paddingLeft = finite(style.paddingLeft)
  const paddingRight = finite(style.paddingRight)
  const paddingTop = finite(style.paddingTop)
  const columnGap = finite(style.columnGap)
  const rowGap = finite(style.rowGap)
  const cardWidth = cards[0].offsetWidth
  const cardHeight = cards[0].offsetHeight
  const contentWidth = grid.clientWidth - paddingLeft - paddingRight
  return {
    originX: gRect.left + grid.clientLeft + paddingLeft,
    originY: gRect.top + grid.clientTop + paddingTop,
    pitchX: cardWidth + columnGap,
    pitchY: cardHeight + rowGap,
    cols: Math.max(1, Math.round((contentWidth + columnGap) / (cardWidth + columnGap))),
  }
}

function gridSlotIndex(grid: HTMLElement, x: number, y: number) {
  const m = gridMetrics(grid)
  if (!m) return 0
  const col = Math.max(0, Math.min(Math.floor((x - m.originX) / m.pitchX), m.cols - 1))
  const row = Math.max(0, Math.floor((y - m.originY) / m.pitchY))
  const all = Array.from(grid.querySelectorAll('.meme-card'))
  const absSlot = Math.min(row * m.cols + col, all.length - 1)
  return Math.max(0, absSlot)
}

/** 由网格几何直接计算槽位原点（不经 getBoundingClientRect，避免 Vue 批量更新导致的偏移） */
function slotOrigin(m: GridMetrics, slot: number) {
  const col = slot % m.cols
  const row = Math.floor(slot / m.cols)
  return {
    left: m.originX + col * m.pitchX,
    top: m.originY + row * m.pitchY,
  }
}

function moveInArray<T>(arr: T[], from: number, to: number) {
  const [item] = arr.splice(from, 1)
  arr.splice(to, 0, item)
}

export function useDragSort(
  getMemes: () => Meme[],
  setMemesFn: (m: Meme[]) => void,
  canReorderFn: () => boolean,
  getSortEnabled: () => boolean,
  persistFn: (ids: number[]) => Promise<boolean>,
  onPersistFail?: () => void,
) {
  function enable() { dragSortEnabled.value = true }
  function disable() { dragSortEnabled.value = false }
  function toggle() { dragSortEnabled.value = !dragSortEnabled.value }

  function onPointerDown(e: PointerEvent, memeId: number, card: HTMLElement) {
    if (e.button !== 0 || !getSortEnabled() || !canReorderFn()) return
    const rect = card.getBoundingClientRect()
    Object.assign(dragState, {
      active: false,
      memeId,
      card,
      offX: e.clientX - rect.left,
      offY: e.clientY - rect.top,
      startX: e.clientX,
      startY: e.clientY,
      curIndex: getMemes().findIndex(m => m.id === memeId),
    })
  }

  function onPointerMove(e: PointerEvent) {
    const d = dragState
    if (!d.memeId || !d.card) return

    // 未激活：超过阈值才激活
    if (!d.active) {
      const dist = Math.hypot(e.clientX - d.startX, e.clientY - d.startY)
      if (dist <= 8) return
      d.active = true
      d.card.classList.add('dragging')
      const grid = d.card.closest('#meme-grid')
      if (grid) grid.classList.add('drag-active')
      // 指针捕获：即使移出卡片/网格也继续接收事件
      try {
        if (e.pointerId != null) d.card.setPointerCapture(e.pointerId)
      } catch (_) {}
    }

    const grid = d.card.closest('#meme-grid') as HTMLElement
    if (!grid) return
    const m = gridMetrics(grid)
    if (!m) return

    const target = gridSlotIndex(grid, e.clientX, e.clientY)

    // 槽位变化时重排数组（Vue + TransitionGroup 自动 FLIP 让位动画）
    if (target !== d.curIndex) {
      const memes = [...getMemes()]
      moveInArray(memes, d.curIndex, target)
      setMemesFn(memes)
      d.curIndex = target
    }

    // 视觉位置：由网格几何直接算出槽位原点，避免读矩形产生偏移/卡顿
    const origin = slotOrigin(m, d.curIndex)
    const dragX = e.clientX - d.offX - origin.left
    const dragY = e.clientY - d.offY - origin.top
    d.card.style.transform = `translate(${dragX}px, ${dragY}px) scale(0.90)`
    d.card.style.zIndex = '10'
  }

  async function onPointerUp() {
    const d = dragState
    if (!d.memeId) return
    const wasActive = d.active
    if (wasActive) {
      const ids = getMemes().map(m => m.id)
      const ok = await persistFn(ids)
      if (!ok && onPersistFail) onPersistFail()
    }
    cleanup()
    return wasActive
  }

  function cancel() {
    cleanup()
  }

  function cleanup() {
    const d = dragState
    if (d.card) {
      d.card.classList.remove('dragging')
      d.card.style.transform = ''
      d.card.style.zIndex = ''
    }
    const grid = document.getElementById('meme-grid')
    if (grid) grid.classList.remove('drag-active')
    Object.assign(d, {
      active: false, memeId: null, card: null,
      offX: 0, offY: 0, startX: 0, startY: 0, curIndex: -1,
    })
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
    cancel,
  }
}
