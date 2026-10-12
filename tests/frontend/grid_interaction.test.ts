import { describe, expect, it } from 'vitest'
import {
  applyMarqueeSelection,
  buildDropOrder,
  edgeScrollVelocity,
  gridSlotIndex,
  normalizeMarqueeRect,
  rectIntersects,
  slotOrigin,
  type GridGeometry,
  type RectLike,
} from '../../src/ohmymeme/presentation/frontend/main/features/sorting/gridInteraction'

// 纯逻辑测试：不依赖 Vue/DOM/Bridge，槽位与几何全部由显式数学驱动

// 矩形夹具：仅需边界四值
function rect(left: number, top: number, right: number, bottom: number): RectLike {
  return { left, top, right, bottom }
}

// 网格几何夹具：未变换的内容原点与步距
function geometry(overrides: Partial<GridGeometry> = {}): GridGeometry {
  return { originX: 0, originY: 0, pitchX: 112, pitchY: 150, cols: 4, ...overrides }
}

describe('normalizeMarqueeRect', () => {
  it('marqueeFourDirections', () => {
    const clip = rect(0, 0, 480, 600)
    const expected = rect(100, 120, 300, 320)
    // 四方向拖拽得到同一正向矩形
    expect(normalizeMarqueeRect(100, 120, 300, 320, clip)).toEqual(expected)
    expect(normalizeMarqueeRect(300, 320, 100, 120, clip)).toEqual(expected)
    expect(normalizeMarqueeRect(300, 120, 100, 320, clip)).toEqual(expected)
    expect(normalizeMarqueeRect(100, 320, 300, 120, clip)).toEqual(expected)
    // 客户区 clip：越出客户区的部分被裁掉
    expect(normalizeMarqueeRect(-50, -40, 1000, 900, clip)).toEqual(rect(0, 0, 480, 600))
    expect(normalizeMarqueeRect(400, 500, 900, 700, clip)).toEqual(rect(400, 500, 480, 600))
    // 零面积框不产生任何命中
    const empty = normalizeMarqueeRect(200, 200, 200, 200, clip)
    expect(empty).toEqual(rect(200, 200, 200, 200))
    expect(rectIntersects(empty, rect(0, 0, 400, 400))).toBe(false)
  })
})

describe('rectIntersects', () => {
  it('marqueeTouchesAndMisses', () => {
    const box = rect(10, 10, 110, 110)
    // 有面积框的擦边命中（非严格比较）
    expect(rectIntersects(box, rect(105, 105, 200, 200))).toBe(true)
    expect(rectIntersects(box, rect(5, 5, 15, 15))).toBe(true)
    // 间隙不命中
    expect(rectIntersects(box, rect(130, 10, 200, 110))).toBe(false)
    // 仅共边（零面积重叠）按擦边命中
    expect(rectIntersects(box, rect(110, 10, 200, 110))).toBe(true)
    expect(rectIntersects(box, rect(10, 110, 110, 200))).toBe(true)
    // 零面积矩形（未激活框或裁后无可见面积的卡）不选
    expect(rectIntersects(rect(10, 10, 10, 110), rect(0, 0, 100, 100))).toBe(false)
    expect(rectIntersects(box, rect(0, 0, 0, 0))).toBe(false)
    const clip = rect(0, 0, 480, 600)
    const offscreen = normalizeMarqueeRect(-300, -300, -200, -200, clip)
    expect(rectIntersects(box, offscreen)).toBe(false)
  })
})

describe('applyMarqueeSelection', () => {
  it('marqueeSnapshotXor', () => {
    const base = new Set([1, 9])
    const first = applyMarqueeSelection(base, [1, 2])
    expect([...first].sort((a, b) => a - b)).toEqual([2, 9])
    // 框移开已选项：仍从同一快照重算，1 恢复
    const second = applyMarqueeSelection(base, [2])
    expect([...second].sort((a, b) => a - b)).toEqual([1, 2, 9])
    // 重复计算幂等且起手快照不被修改
    const again = applyMarqueeSelection(base, [1, 2])
    expect([...again].sort((a, b) => a - b)).toEqual([2, 9])
    expect([...base].sort((a, b) => a - b)).toEqual([1, 9])
    // 重复命中只翻转一次
    const deduped = applyMarqueeSelection(base, [1, 1, 2, 2])
    expect([...deduped].sort((a, b) => a - b)).toEqual([2, 9])
  })
})

describe('edgeScrollVelocity', () => {
  it('edgeSpeedCurve', () => {
    const top = 100
    const bottom = 700
    // 高 600：触发宽度 min(64, 150) = 64
    expect(edgeScrollVelocity(400, top, bottom)).toBe(0)
    expect(edgeScrollVelocity(bottom - 64, top, bottom)).toBe(0)
    expect(edgeScrollVelocity(bottom - 32, top, bottom)).toBe(200)
    expect(edgeScrollVelocity(bottom, top, bottom)).toBe(800)
    expect(edgeScrollVelocity(top + 64, top, bottom)).toBe(0)
    expect(edgeScrollVelocity(top + 32, top, bottom)).toBe(-200)
    expect(edgeScrollVelocity(top, top, bottom)).toBe(-800)
    // 短 viewport 用 height/4 作触发宽度
    expect(edgeScrollVelocity(275, 100, 300)).toBe(200)
    expect(edgeScrollVelocity(300, 100, 300)).toBe(800)
    // 非法几何与有效客户区之外为 0
    expect(edgeScrollVelocity(200, 100, 100)).toBe(0)
    expect(edgeScrollVelocity(90, top, bottom)).toBe(0)
    expect(edgeScrollVelocity(710, top, bottom)).toBe(0)
    expect(edgeScrollVelocity(Number.NaN, top, bottom)).toBe(0)
    expect(edgeScrollVelocity(400, Number.NaN, bottom)).toBe(0)
  })
})

describe('gridSlotIndex', () => {
  it('globalNonZeroStart', () => {
    const pitchY = 150
    const scrollTop = 100 * pitchY
    const g = geometry({ originX: 0, originY: 100 - scrollTop, pitchX: 112, pitchY, cols: 4 })
    // 可视首行为第 100 行（lo=400）：客户点必须命中全局槽位而不是局部 0
    expect(gridSlotIndex(g, 5, 125, 5000)).toBe(400)
    expect(gridSlotIndex(g, 117, 125, 5000)).toBe(401)
    expect(gridSlotIndex(g, 5, 275, 5000)).toBe(404)
    // 不按 DOM 卡数做尾部钳制：总数不足时该槽位不成立
    expect(gridSlotIndex(g, 5, 125, 400)).toBeNull()
  })

  it('geometryMovesAndScrolls', () => {
    const pitchX = 112
    const pitchY = 150
    const baseX = 200
    const baseY = 100
    // 同一记录（3 行 1 列 → 绝对槽位 13）在侧栏偏移、wrap 边框内边距、文件夹头块与滚动偏移下都命中同一槽位
    const cases: Array<{ label: string; originX: number; originY: number; clientX: number; clientY: number }> = [
      { label: '基准', originX: baseX, originY: baseY, clientX: baseX + pitchX + 10, clientY: baseY + 3 * pitchY + 10 },
      { label: '侧栏偏移', originX: baseX + 180, originY: baseY, clientX: baseX + 180 + pitchX + 10, clientY: baseY + 3 * pitchY + 10 },
      { label: 'wrap边框内边距', originX: baseX + 2, originY: baseY + 8, clientX: baseX + 2 + pitchX + 10, clientY: baseY + 8 + 3 * pitchY + 10 },
      { label: '文件夹头块', originX: baseX, originY: baseY + 40, clientX: baseX + pitchX + 10, clientY: baseY + 40 + 3 * pitchY + 10 },
      { label: '滚动偏移', originX: baseX, originY: baseY - 300, clientX: baseX + pitchX + 10, clientY: baseY - 300 + 3 * pitchY + 10 },
    ]
    for (const item of cases) {
      const g = geometry({ originX: item.originX, originY: item.originY, pitchX, pitchY, cols: 4 })
      expect(gridSlotIndex(g, item.clientX, item.clientY, 4000), item.label).toBe(13)
    }
  })

  it('invalidAndLastRow', () => {
    const g = geometry({ originX: 0, originY: 0, pitchX: 100, pitchY: 150, cols: 4 })
    // 二维越界
    expect(gridSlotIndex(g, 400, 10, 1000)).toBeNull()
    expect(gridSlotIndex(g, -1, 10, 1000)).toBeNull()
    expect(gridSlotIndex(g, 10, -1, 1000)).toBeNull()
    // 末行空列与越过末行
    expect(gridSlotIndex(g, 10, 160, 5)).toBe(4)
    expect(gridSlotIndex(g, 110, 160, 5)).toBeNull()
    expect(gridSlotIndex(g, 10, 300, 5)).toBeNull()
    // 行内间隙归到前一格（卡宽 90 + 间隙 10）
    expect(gridSlotIndex(g, 95, 10, 1000)).toBe(0)
    expect(gridSlotIndex(g, 100, 10, 1000)).toBe(1)
    // 非法几何与参数
    expect(gridSlotIndex(geometry({ cols: 0 }), 10, 10, 1000)).toBeNull()
    expect(gridSlotIndex(geometry({ pitchX: 0 }), 10, 10, 1000)).toBeNull()
    expect(gridSlotIndex(geometry({ pitchY: Number.POSITIVE_INFINITY }), 10, 10, 1000)).toBeNull()
    expect(gridSlotIndex(geometry({ originX: Number.NaN }), 10, 10, 1000)).toBeNull()
    expect(gridSlotIndex(g, Number.NaN, 10, 1000)).toBeNull()
    expect(gridSlotIndex(g, Number.POSITIVE_INFINITY, 10, 1000)).toBeNull()
    expect(gridSlotIndex(g, 10, 10, 0)).toBeNull()
    expect(gridSlotIndex(g, 10, 10, 1.5)).toBeNull()
  })
})

describe('slotOrigin', () => {
  it('absoluteOrigin', () => {
    const g = geometry({ originX: 200, originY: 100, pitchX: 112, pitchY: 150, cols: 4 })
    expect(slotOrigin(g, 0)).toEqual({ left: 200, top: 100 })
    expect(slotOrigin(g, 3)).toEqual({ left: 200 + 3 * 112, top: 100 })
    expect(slotOrigin(g, 4)).toEqual({ left: 200, top: 250 })
    // 第 n 行 m 列原点 = origin + pitch（scale 不进入数学）
    expect(slotOrigin(g, 13)).toEqual({ left: 200 + 112, top: 100 + 3 * 150 })
    expect(slotOrigin(g, 14)).toEqual({ left: 200 + 2 * 112, top: 100 + 3 * 150 })
    expect(slotOrigin(g, -1)).toBeNull()
    expect(slotOrigin(geometry({ cols: 0 }), 0)).toBeNull()
  })
})

describe('buildDropOrder', () => {
  it('moveBothDirections', () => {
    const items = [401, 402, 403, 404, 405].map(id => ({ id }))
    const baseline = { start: 400, items }
    const before = items.map(item => item.id)
    // 非 0 start：前→后 / 后→前
    expect(buildDropOrder(baseline, 401, 403)?.map(item => item.id)).toEqual([402, 403, 404, 401, 405])
    expect(buildDropOrder(baseline, 405, 400)?.map(item => item.id)).toEqual([405, 401, 402, 403, 404])
    // 同槽不变
    expect(buildDropOrder(baseline, 403, 402)?.map(item => item.id)).toEqual(before)
    // 源缺失/目标越界/非整数目标拒绝
    expect(buildDropOrder(baseline, 999, 402)).toBeNull()
    expect(buildDropOrder(baseline, 401, 399)).toBeNull()
    expect(buildDropOrder(baseline, 401, 405)).toBeNull()
    expect(buildDropOrder(baseline, 401, 400.5)).toBeNull()
    // 入参不被 splice，返回新数组
    expect(items.map(item => item.id)).toEqual(before)
    const moved = buildDropOrder(baseline, 401, 403)
    expect(moved).not.toBe(items)
  })

  it('expandedWindowOrder', () => {
    // 前插新头页 + 追加新尾页后：跨旧边界移动必须按整段扩展窗口计算
    // 基准 9 项（start=398）：398,399,401,402,403,404,405,406,407；399 移到槽位 405（local=7）
    // → 移除 399 后插回索引 7 → [398,401,402,403,404,405,406,399,407]
    const expanded = { start: 398, items: [398, 399, 401, 402, 403, 404, 405, 406, 407].map(id => ({ id })) }
    const ids = expanded.items.map(item => item.id)
    const moved = buildDropOrder(expanded, 399, 405)
    expect(moved?.length).toBe(expanded.items.length)
    expect(new Set(moved?.map(item => item.id))).toEqual(new Set(ids))
    expect(moved?.map(item => item.id)).toEqual([398, 401, 402, 403, 404, 405, 406, 399, 407])
    expect(moved?.[405 - expanded.start]?.id).toBe(399)
    // 追加页项反向移动到旧边界：407（索引 8）移到槽位 400（local=2）
    // → 移除 407 后插回索引 2 → [398,399,407,401,402,403,404,405,406]
    const back = buildDropOrder(expanded, 407, 400)
    expect(back?.length).toBe(expanded.items.length)
    expect(new Set(back?.map(item => item.id))).toEqual(new Set(ids))
    expect(back?.map(item => item.id)).toEqual([398, 399, 407, 401, 402, 403, 404, 405, 406])
    expect(back?.[400 - expanded.start]?.id).toBe(407)
  })
})
