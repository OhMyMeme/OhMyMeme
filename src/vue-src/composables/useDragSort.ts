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
  pointerId: number | null
  originalOrder: Meme[]
  targetCard: HTMLElement | null
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
  pointerId: null,
  originalOrder: [],
  targetCard: null,
})

const AUTO_SCROLL_ZONE = 76
const AUTO_SCROLL_MAX_SPEED = 22
let autoScrollFrame = 0
let autoScrollPoint: { x: number; y: number } | null = null

function gridSlotIndex(grid: HTMLElement, x: number, y: number, dragged: HTMLElement | null) {
  // 使用真实卡片矩形计算“插入槽位”，而不是简单取当前格子。
  // 这样指针落在两张卡片之间时，会明确插入到前后两张卡片之间。
  const cards = Array.from(
    grid.querySelectorAll('.meme-card:not(.folder-card)'),
  ).filter(card => card !== dragged) as HTMLElement[]
  if (!cards.length) return { index: 0, targetCard: null as HTMLElement | null, before: true }

  const rects = cards.map(card => ({ card, rect: card.getBoundingClientRect() }))
  const rows: Array<typeof rects> = []
  for (const item of rects) {
    const row = rows.find(existing => Math.abs(existing[0].rect.top - item.rect.top) < 8)
    if (row) row.push(item)
    else rows.push([item])
  }
  rows.forEach(row => row.sort((a, b) => a.rect.left - b.rect.left))
  rows.sort((a, b) => a[0].rect.top - b[0].rect.top)

  // 先确定指针所在行：落在两行之间时归入下一行，符合手机图标的让位直觉。
  let row = rows[rows.length - 1]
  for (const candidate of rows) {
    const bottom = Math.max(...candidate.map(item => item.rect.bottom))
    if (y <= bottom) {
      row = candidate
      break
    }
  }
  const hitIndex = row.findIndex(item => x < item.rect.left + item.rect.width / 2)
  const targetCard = hitIndex >= 0 ? row[hitIndex].card : null
  const rowStart = cards.indexOf(row[0].card)
  const index = rowStart + (hitIndex >= 0 ? hitIndex : row.length)
  return {
    index: Math.max(0, index),
    targetCard,
    before: !!targetCard,
  }
}

/** 由网格几何直接计算槽位原点（不经 getBoundingClientRect，避免 Vue 批量更新导致的偏移） */
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
  function toggle() {
    dragSortEnabled.value = !dragSortEnabled.value
    if (!dragSortEnabled.value && dragState.memeId) cancel()
  }

  function stopAutoScroll() {
    if (autoScrollFrame) cancelAnimationFrame(autoScrollFrame)
    autoScrollFrame = 0
    autoScrollPoint = null
  }

  function updateAutoScrollPoint(x: number, y: number) {
    autoScrollPoint = { x, y }
    if (!autoScrollFrame) runAutoScroll()
  }

  function runAutoScroll() {
    autoScrollFrame = requestAnimationFrame(() => {
      autoScrollFrame = 0
      const d = dragState
      const point = autoScrollPoint
      const wrap = d.card?.closest('#grid-wrap') as HTMLElement | null
      if (!d.active || !point || !wrap) return
      const rect = wrap.getBoundingClientRect()
      let delta = 0
      if (point.y < rect.top + AUTO_SCROLL_ZONE) {
        const depth = Math.min(1, Math.max(0, (rect.top + AUTO_SCROLL_ZONE - point.y) / AUTO_SCROLL_ZONE))
        delta = -Math.ceil(4 + depth * AUTO_SCROLL_MAX_SPEED)
      } else if (point.y > rect.bottom - AUTO_SCROLL_ZONE) {
        const depth = Math.min(1, Math.max(0, (point.y - (rect.bottom - AUTO_SCROLL_ZONE)) / AUTO_SCROLL_ZONE))
        delta = Math.ceil(4 + depth * AUTO_SCROLL_MAX_SPEED)
      }
      if (delta) {
        wrap.scrollTop += delta
        runAutoScroll()
      }
    })
  }

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
      pointerId: e.pointerId ?? null,
      originalOrder: [...getMemes()],
      targetCard: null,
    })
  }

  function onPointerMove(e: PointerEvent) {
    const d = dragState
    if (!d.memeId || !d.card) return

    if (d.pointerId != null && e.pointerId != null && e.pointerId !== d.pointerId) return

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

    updateAutoScrollPoint(e.clientX, e.clientY)
    const grid = d.card.closest('#meme-grid') as HTMLElement
    if (!grid) return
    const slot = gridSlotIndex(grid, e.clientX, e.clientY, d.card)
    const current = getMemes().findIndex(meme => meme.id === d.memeId)

    // 先从数组中移除拖动项，再按“卡片之前/本行末尾”插入，避免向后移动时索引偏移。
    if (current < 0) return
    const memes = [...getMemes()]
    const [dragged] = memes.splice(current, 1)
    let insertAt = slot.targetCard
      ? memes.findIndex(meme => meme.id === Number(slot.targetCard?.dataset.memeId))
      : slot.index
    if (insertAt < 0) insertAt = memes.length
    insertAt = Math.max(0, Math.min(insertAt, memes.length))
    if (insertAt !== current || d.targetCard !== slot.targetCard) {
      if (d.targetCard) d.targetCard.classList.remove('sort-target-before')
      memes.splice(insertAt, 0, dragged)
      setMemesFn(memes)
      d.curIndex = insertAt
      d.targetCard = slot.targetCard
      if (d.targetCard) d.targetCard.classList.add('sort-target-before')
    } else {
      memes.splice(current, 0, dragged)
    }

    // 卡片自身通过 transform 跟随指针；其他卡片由 TransitionGroup 自动让位。
    // 先清除旧 transform 再测量，避免把上一次位移重复累加。
    d.card.style.transform = ''
    const cardRect = d.card.getBoundingClientRect()
    const dragX = e.clientX - d.offX - cardRect.left
    const dragY = e.clientY - d.offY - cardRect.top
    d.card.style.transform = `translate3d(${dragX}px, ${dragY}px, 0) scale(0.90)`
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
    const d = dragState
    if (d.active && d.originalOrder.length) setMemesFn([...d.originalOrder])
    cleanup()
  }

  function cleanup() {
    stopAutoScroll()
    const d = dragState
    if (d.card) {
      d.card.classList.remove('dragging')
      d.card.style.transform = ''
      d.card.style.zIndex = ''
    }
    if (d.targetCard) d.targetCard.classList.remove('sort-target-before')
    const grid = document.getElementById('meme-grid')
    if (grid) grid.classList.remove('drag-active')
    Object.assign(d, {
      active: false, memeId: null, card: null,
      offX: 0, offY: 0, startX: 0, startY: 0, curIndex: -1,
      pointerId: null, originalOrder: [], targetCard: null,
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
