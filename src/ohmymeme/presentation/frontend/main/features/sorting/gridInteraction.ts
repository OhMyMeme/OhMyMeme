// 纯交互数学：框选矩形、槽位换算、边缘滚动速度与落点顺序；不依赖 Vue/DOM/Bridge 与全局状态

// 矩形边界（DOMRect 子集）：框选、卡矩形与客户区通用
export type RectLike = {
  left: number
  top: number
  right: number
  bottom: number
}

// 网格几何：未变换的内容原点、行列步距与列数（scale/rotate 不进入数学）
export type GridGeometry = {
  originX: number
  originY: number
  pitchX: number
  pitchY: number
  cols: number
}

// 基准窗口：绝对起始槽位与未重排的完整记录
export type SliceBaseline<T> = {
  start: number
  items: T[]
}

// 拖拽项最小约束：排序只依赖稳定 id
export type DraggableItem = {
  id: number
}

// 边缘自动滚动的触发宽度上限与最大速度
const EDGE_ZONE_MAX = 64
const EDGE_SPEED_MAX = 800

// 归一化框选矩形：起止点取正向并裁入客户区，允许零面积
export function normalizeMarqueeRect(x1: number, y1: number, x2: number, y2: number, clip: RectLike): RectLike {
  const left = Math.max(Math.min(x1, x2), clip.left)
  const top = Math.max(Math.min(y1, y2), clip.top)
  const right = Math.max(Math.min(Math.max(x1, x2), clip.right), left)
  const bottom = Math.max(Math.min(Math.max(y1, y2), clip.bottom), top)
  return { left, top, right, bottom }
}

// 两矩形是否有可见重叠：有面积框的擦边命中（非严格比较），零面积矩形（未激活框/裁后无可见面积的卡）不选
export function rectIntersects(a: RectLike, b: RectLike): boolean {
  if (!(a.right > a.left) || !(a.bottom > a.top)) return false
  if (!(b.right > b.left) || !(b.bottom > b.top)) return false
  return Math.min(a.right, b.right) >= Math.max(a.left, b.left)
    && Math.min(a.bottom, b.bottom) >= Math.max(a.top, b.top)
}

// 起手快照与命中集合的对称差（重复命中只翻转一次，不修改入参）
export function applyMarqueeSelection(base: ReadonlySet<number>, hits: Iterable<number>): Set<number> {
  const next = new Set<number>(base)
  for (const id of new Set(hits)) {
    if (next.has(id)) next.delete(id)
    else next.add(id)
  }
  return next
}

// 客户区坐标换算全局槽位：越界、末行空列与非法几何返回 null（不做 DOM 数量钳制）
export function gridSlotIndex(geometry: GridGeometry, clientX: number, clientY: number, total: number): number | null {
  const { originX, originY, pitchX, pitchY, cols } = geometry
  if (!Number.isInteger(cols) || cols < 1) return null
  if (!Number.isFinite(originX) || !Number.isFinite(originY)) return null
  if (!Number.isFinite(pitchX) || !Number.isFinite(pitchY) || pitchX <= 0 || pitchY <= 0) return null
  if (!Number.isInteger(total) || total < 1) return null
  if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) return null
  const col = Math.floor((clientX - originX) / pitchX)
  const row = Math.floor((clientY - originY) / pitchY)
  if (col < 0 || col >= cols || row < 0) return null
  const slot = row * cols + col
  return slot < total ? slot : null
}

// 全局槽位反算客户区原点：按未变换步距定位，不读 DOM 矩形也不含 scale
export function slotOrigin(geometry: GridGeometry, slot: number): { left: number; top: number } | null {
  const { originX, originY, pitchX, pitchY, cols } = geometry
  if (!Number.isInteger(cols) || cols < 1) return null
  if (!Number.isInteger(slot) || slot < 0) return null
  if (!Number.isFinite(originX) || !Number.isFinite(originY)) return null
  if (!Number.isFinite(pitchX) || !Number.isFinite(pitchY)) return null
  const col = slot % cols
  const row = Math.floor(slot / cols)
  return { left: originX + col * pitchX, top: originY + row * pitchY }
}

// 边缘自动滚动速度：有效客户区内按二次曲线，中心 0、最外 ±800（上负下正）
export function edgeScrollVelocity(pointerY: number, viewportTop: number, viewportBottom: number): number {
  if (!Number.isFinite(pointerY) || !Number.isFinite(viewportTop) || !Number.isFinite(viewportBottom)) return 0
  const height = viewportBottom - viewportTop
  if (height <= 0 || pointerY < viewportTop || pointerY > viewportBottom) return 0
  const zone = Math.min(EDGE_ZONE_MAX, height / 4)
  const bottomDepth = pointerY - (viewportBottom - zone)
  if (bottomDepth > 0) {
    const u = Math.min(bottomDepth / zone, 1)
    return EDGE_SPEED_MAX * u * u
  }
  const topDepth = viewportTop + zone - pointerY
  if (topDepth > 0) {
    const u = Math.min(topDepth / zone, 1)
    return -EDGE_SPEED_MAX * u * u
  }
  return 0
}

// 落点顺序：从基准窗口移除拖动项后按绝对目标槽位插入；源缺失/目标越界返回 null 且不改入参
export function buildDropOrder<T extends DraggableItem>(
  baseline: SliceBaseline<T>,
  draggedId: number,
  targetSlot: number,
): T[] | null {
  const items = baseline.items
  if (!items.length || !Number.isInteger(targetSlot)) return null
  const local = targetSlot - baseline.start
  if (local < 0 || local >= items.length) return null
  const index = items.findIndex(item => item.id === draggedId)
  if (index < 0) return null
  const record = items[index]
  if (record === undefined) return null
  const next = items.slice()
  next.splice(index, 1)
  next.splice(local, 0, record)
  return next
}
