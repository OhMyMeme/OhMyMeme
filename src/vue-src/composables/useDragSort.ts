import { reactive, readonly } from 'vue'
import type { Meme } from '../types'

const dragSortEnabled = ref(false)
import { ref } from 'vue'

interface DragState {
  active: boolean
  memeId: number | null
  card: HTMLElement | null
  offX: number
  offY: number
  base: DOMRect | null
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
  base: null,
  startX: 0,
  startY: 0,
  curIndex: -1,
})

function gridMetrics(grid: HTMLElement) {
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
  const { originX, originY, pitchX, pitchY, cols } = m
  const col = Math.max(0, Math.min(Math.floor((x - originX) / pitchX), cols - 1))
  const row = Math.max(0, Math.floor((y - originY) / pitchY))
  const all = Array.from(grid.querySelectorAll('.meme-card'))
  const absSlot = Math.min(row * cols + col, all.length - 1)
  return Math.max(0, absSlot)
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
      base: rect,
      startX: e.clientX,
      startY: e.clientY,
      curIndex: getMemes().findIndex(m => m.id === memeId),
    })
  }

  function onPointerMove(e: PointerEvent) {
    const d = dragState
    if (!d.memeId || !d.card || !d.base) return

    // 未激活：超过阈值才激活
    if (!d.active) {
      const dist = Math.hypot(e.clientX - d.startX, e.clientY - d.startY)
      if (dist <= 8) return
      d.active = true
      d.card.classList.add('dragging')
    }

    const grid = d.card.closest('#meme-grid') as HTMLElement
    if (!grid) return

    // 视觉拖动：translate + scale
    const dragX = e.clientX - d.offX - d.base.left
    const dragY = e.clientY - d.offY - d.base.top
    d.card.style.transform = `translate(${dragX}px, ${dragY}px) scale(0.90)`
    d.card.style.zIndex = '10'

    // 计算目标槽位并重排数组（TransitionGroup 自动 FLIP 动画）
    const cur = d.curIndex
    const target = gridSlotIndex(grid, e.clientX, e.clientY)
    if (target === cur) return

    const memes = [...getMemes()]
    moveInArray(memes, cur, target)
    setMemesFn(memes)

    // 更新 curIndex 和 base（卡片位置变化后重新定位）
    d.curIndex = target
    const prevTf = d.card.style.transform
    d.card.style.transform = ''
    d.base = d.card.getBoundingClientRect()
    d.card.style.transform = prevTf
    const updatedDragX = e.clientX - d.offX - d.base.left
    const updatedDragY = e.clientY - d.offY - d.base.top
    d.card.style.transform = `translate(${updatedDragX}px, ${updatedDragY}px) scale(0.90)`
  }

  async function onPointerUp() {
    const d = dragState
    if (!d.memeId) return
    if (d.active) {
      const ids = getMemes().map(m => m.id)
      const ok = await persistFn(ids)
      if (!ok && onPersistFail) onPersistFail()
    }
    cleanup()
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
    Object.assign(d, {
      active: false, memeId: null, card: null,
      offX: 0, offY: 0, base: null, startX: 0, startY: 0, curIndex: -1,
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
