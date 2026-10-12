import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { h, nextTick } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import type { Meme } from '../../src/ohmymeme/presentation/frontend/main/shared/types'

// MainWindow 虚拟网格拖拽/框选接线桩：mock virtua 行窗口；jsdom 无布局，
// 滚动容器/行/卡矩形与滚动位置由可控 harness 提供；rAF 走显式队列（stepAnimationFrame），
// 不用 runAllTimers 驱动持续自排队的引擎 pump。
// 覆盖：全局槽位数学（非 0 起点）、越界取消、saving 冻结、旧查询不回滚、丢捕获取消、
// 静止指针自动滚动、加载前沿暂停与恢复、跨新页 drop、扩展窗口 drop、取消保留新页、
// 同代次失败重同步，以及自研框选（快照 XOR/四方向/离屏保留/骨架排除/取消回滚/关闭清空/键盘替代）。
// 覆盖边界：mock 的挂载行区间由每个用例显式给定（不随滚动动态挂载；真实 virtua 的
// 行卸载/重挂与 overscan 行为不在此桩覆盖），滚动通过设置 scrollTop 与选择匹配的区间模拟。

const mockVirtua = vi.hoisted(() => ({
  range: [0, 0] as [number, number],
  // 桩开关：false 时不 expose 滚动方法（模拟暂时重挂/暂未就绪的 handle）
  hasHandle: true,
  scrollToCalls: [] as number[],
  scrollToIndexCalls: [] as number[],
}))
const scrollState = vi.hoisted(() => ({ value: 0 }))
const rafQueue = vi.hoisted(() => ({
  callbacks: new Map<number, FrameRequestCallback>(),
  nextId: 1,
  now: 0,
}))
const geomCard = vi.hoisted(() => ({ width: 112, height: 141 }))

const GEOM_TOP = 100
const GEOM_WRAP_WIDTH = 480
const GEOM_WRAP_HEIGHT = 600
const GEOM_GAP = 10

vi.mock('virtua/vue', async () => {
  const { defineComponent, h, onMounted, onBeforeUnmount } = await import('vue')
  return {
    Virtualizer: defineComponent({
      name: 'Virtualizer',
      props: {
        data: { type: Array, default: () => [] },
        bufferSize: Number,
        itemSize: Number,
        shift: Boolean,
        startMargin: Number,
        scrollRef: Object,
        itemProps: Function,
        keepMounted: Array,
        cache: Object,
      },
      emits: ['scroll', 'scrollEnd', 'resize'],
      setup(props: any, { slots, expose, emit }: any) {
        // 转发滚动容器原生 scroll（真实行为：virtua 由 scrollRef 触发 @scroll）
        const forwardScroll = () => emit('scroll')
        const scrollElement = (): HTMLElement | null => {
          const raw = props.scrollRef as unknown
          if (raw && typeof (raw as HTMLElement).addEventListener === 'function') return raw as HTMLElement
          const inner = (raw as { value?: unknown } | null)?.value
          return inner && typeof (inner as HTMLElement).addEventListener === 'function' ? (inner as HTMLElement) : null
        }
        onMounted(() => { scrollElement()?.addEventListener('scroll', forwardScroll) })
        onBeforeUnmount(() => { scrollElement()?.removeEventListener('scroll', forwardScroll) })
        // 与真实 handle 同形的读数方法始终提供；滚动方法由 hasHandle 控制，
        // scrollTo(number) 写 scrollRef 元素并发送 scroll（不做真实的行卸载/测量伪装）
        const exposed: Record<string, unknown> = {
          cache: null,
          scrollOffset: 0,
          scrollSize: 0,
          viewportSize: 0,
          findItemIndex(offset: number) {
            const size = Number(props.itemSize) || 1
            const total = (props.data as unknown[]).length
            if (!total) return 0
            const margin = Number(props.startMargin) || 0
            return Math.max(0, Math.min(total - 1, Math.floor((offset - margin) / size)))
          },
          getItemOffset(index: number) {
            return (Number(props.startMargin) || 0) + index * (Number(props.itemSize) || 0)
          },
          getItemSize() {
            return Number(props.itemSize) || 0
          },
        }
        if (mockVirtua.hasHandle) {
          exposed['scrollTo'] = (offset: number) => {
            mockVirtua.scrollToCalls.push(offset)
            const element = scrollElement()
            if (element) {
              element.scrollTop = offset
              element.dispatchEvent(new Event('scroll'))
            }
          }
          exposed['scrollToIndex'] = (index: number) => { mockVirtua.scrollToIndexCalls.push(index) }
          exposed['scrollBy'] = () => {}
        }
        expose(exposed)
        return () => {
          const data = props.data as unknown[]
          const [from, to] = mockVirtua.range
          const rows = []
          for (let index = from; index <= Math.min(to, data.length - 1); index++) {
            rows.push(slots.default?.({ item: data[index], index }))
          }
          return h('div', { class: 'mock-virtualizer' }, rows)
        }
      },
    }),
  }
})

const CHILD_STUBS = {
  CollectionBuilder: true,
  CollectionTreeNode: true,
  ConfirmDialog: true,
  ContextMenu: true,
  ImportMenu: true,
  InputDialog: true,
  SyncOverlay: true,
  TagEditor: true,
  UpdateDialog: true,
}

type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void }

function deferred<T>(): Deferred<T> {
  let resolve: (value: T) => void = () => {}
  const promise = new Promise<T>(r => { resolve = r })
  return { promise, resolve }
}

function makeRange(startId: number, count: number): Meme[] {
  return Array.from({ length: count }, (_, index) => ({
    id: startId + index,
    filename: `f${startId + index}.png`,
    name: `meme ${startId + index}`,
    file_hash: `h${startId + index}`,
    width: 16,
    height: 16,
    mime_type: 'image/png',
  }))
}

type BridgeHandler = (args: unknown[]) => unknown
type Call = { method: string; args: unknown[] }

// 全局 pywebview 桩：bridge.ts 直接读 globalThis.pywebview，避免 mock 模块
function installBridge(handlers: Record<string, BridgeHandler>): Call[] {
  const calls: Call[] = []
  ;(globalThis as any).pywebview = {
    api: new Proxy(
      {},
      {
        get: (_target, method) => (...args: unknown[]) => {
          const name = String(method)
          calls.push({ method: name, args })
          const handler = handlers[name]
          return handler ? handler(args) : null
        },
      },
    ),
  }
  return calls
}

async function flush(rounds = 4): Promise<void> {
  for (let i = 0; i < rounds; i++) {
    await vi.advanceTimersByTimeAsync(32)
    await nextTick()
  }
}

// 可控 rAF：一次 step 只执行当前队列（引擎 pump 的自排队回调留给下一次 step）
async function stepAnimationFrame(ms = 16): Promise<void> {
  rafQueue.now += ms
  const pending = Array.from(rafQueue.callbacks.entries())
  rafQueue.callbacks.clear()
  for (const [, callback] of pending) callback(rafQueue.now)
  await nextTick()
}

function fakeRect(left: number, top: number, width: number, height: number): DOMRect {
  return {
    left,
    top,
    right: left + width,
    bottom: top + height,
    width,
    height,
    x: left,
    y: top,
    toJSON: () => ({}),
  } as DOMRect
}

interface Geometry {
  cols: number
  cardWidth: number
  cardHeight: number
  rowPitch: number
  colPitch: number
  startMargin: number
  rowTop: (index: number) => number
  colLeft: (index: number) => number
}

// 挂载后安装滚动几何：卡宽/列距分离（112 + 10），行/卡矩形随滚动位置动态计算
function installGeometry(): Geometry {
  const wrap = document.getElementById('grid-wrap') as HTMLElement
  const grid = document.getElementById('meme-grid') as HTMLElement
  const cols = Math.max(1, Number(grid.style.getPropertyValue('--meme-cols')) || 1)
  const cardHeight = Math.max(1, Math.round(parseFloat(grid.style.getPropertyValue('--meme-card-height')) || 141))
  const cardWidth = 112
  const rowPitch = cardHeight + GEOM_GAP
  const colPitch = cardWidth + GEOM_GAP
  geomCard.width = cardWidth
  geomCard.height = cardHeight
  Object.defineProperty(wrap, 'scrollTop', {
    configurable: true,
    get: () => scrollState.value,
    set: (value: number) => { scrollState.value = Math.max(0, value) },
  })
  const rowRect = (index: number) => fakeRect(0, GEOM_TOP + index * rowPitch - scrollState.value, GEOM_WRAP_WIDTH, rowPitch)
  const cardRect = (index: number, col: number) => fakeRect(col * colPitch, GEOM_TOP + index * rowPitch - scrollState.value, cardWidth, cardHeight)
  for (const row of Array.from(grid.querySelectorAll<HTMLElement>('.virtual-meme-row'))) {
    row.getBoundingClientRect = () => rowRect(Math.max(0, Math.floor(Number(row.dataset['rowStart']) / cols)))
    for (const card of Array.from(row.querySelectorAll<HTMLElement>('.meme-card'))) {
      card.getBoundingClientRect = () => {
        const slot = Number(card.dataset['slotIndex'])
        if (!Number.isInteger(slot)) return cardRect(Math.floor(Number(row.dataset['rowStart']) / cols), 0)
        return cardRect(Math.floor(slot / cols), slot % cols)
      }
    }
  }
  return {
    cols,
    cardWidth,
    cardHeight,
    rowPitch,
    colPitch,
    startMargin: GEOM_TOP,
    rowTop: (index: number) => GEOM_TOP + index * rowPitch - scrollState.value,
    colLeft: (index: number) => index * colPitch,
  }
}

function cardOf(id: number): HTMLElement {
  return document.querySelector<HTMLElement>(`#meme-grid .meme-card[data-meme-id="${id}"]`) as HTMLElement
}

function slotCard(slot: number): HTMLElement {
  return document.querySelector<HTMLElement>(`#meme-grid .meme-card[data-slot-index="${slot}"]`) as HTMLElement
}

function pointerEvent(type: string, init: Partial<MouseEventInit> & { pointerId?: number }): MouseEvent {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, ...init })
  Object.defineProperty(event, 'pointerId', { value: init.pointerId ?? 1 })
  return event
}

async function setupMainWindow(
  handlers: Record<string, BridgeHandler>,
  range: [number, number],
): Promise<{ wrapper: VueWrapper; state: any; model: any; calls: Call[] }> {
  mockVirtua.range = range
  const calls = installBridge(handlers)
  vi.resetModules()
  const model = (await import('../../src/ohmymeme/presentation/frontend/main/features/memes/useMemes')).useMemes()
  const MainWindow = (await import('../../src/ohmymeme/presentation/frontend/main/app/MainWindow.vue')).default
  const wrapper = mount(
    { render: () => h(NMessageProvider, null, { default: () => h(MainWindow as any) }) },
    {
      attachTo: document.body,
      global: {
        stubs: CHILD_STUBS,
      },
    },
  )
  // 启动流程：init 数据 → 300ms 降级后台（rescan → auto_sync → search）
  await vi.advanceTimersByTimeAsync(300)
  await flush()
  return { wrapper, state: model.state, model, calls }
}

function baseHandlers(items: () => Meme[], reorder?: BridgeHandler): Record<string, BridgeHandler> {
  return {
    get_init_data: () => ({
      memes: items(),
      tags: [],
      collections: [],
      show_startup_animation: false,
      startup_bg_color: '#000000',
    }),
    count_memes: () => items().length,
    search_memes: (args) => {
      const offset = args[3] as number
      const limit = args[4] as number
      return items().slice(offset, offset + limit)
    },
    get_tags: () => [],
    get_collections: () => [],
    rescan_cache: () => true,
    run_auto_sync: () => true,
    check_update: () => ({ pending: false, has_update: false }),
    reorder_memes: reorder ?? (() => true),
  }
}

// 分页挂起桩：按 offset 返回可手动 resolve 的 Promise
function holdPage() {
  const waits = new Map<number, Deferred<Meme[] | null>>()
  const get = (offset: number): Deferred<Meme[] | null> => {
    let wait = waits.get(offset)
    if (!wait) {
      wait = deferred<Meme[] | null>()
      waits.set(offset, wait)
    }
    return wait
  }
  return {
    handler: (args: unknown[]): Promise<Meme[] | null> => get(args[3] as number).promise,
    resolve: (offset: number, value: Meme[] | null): void => {
      const wait = get(offset)
      waits.delete(offset)
      wait.resolve(value)
    },
  }
}

// 分页请求的 offset 调用计数
function offsetCalls(calls: Call[], offset: number): number {
  return calls.filter(call => call.method === 'search_memes' && call.args[3] === offset).length
}

const wrappers: VueWrapper[] = []

describe('MainWindow 虚拟网格拖拽接线', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    document.body.innerHTML = ''
    mockVirtua.range = [0, 0]
    mockVirtua.hasHandle = true
    mockVirtua.scrollToCalls.length = 0
    mockVirtua.scrollToIndexCalls.length = 0
    scrollState.value = 0
    rafQueue.callbacks.clear()
    rafQueue.nextId = 1
    rafQueue.now = 0
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      const id = rafQueue.nextId++
      rafQueue.callbacks.set(id, callback)
      return id
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => { rafQueue.callbacks.delete(id) })
    ;(globalThis as any).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    // jsdom 无布局：挂载前就给出滚动容器/网格尺寸与矩形（startMargin 首测即得 100）
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
      configurable: true,
      get(this: HTMLElement) {
        return this.id === 'grid-wrap' || this.id === 'meme-grid' ? GEOM_WRAP_WIDTH : 0
      },
    })
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get(this: HTMLElement) {
        return this.id === 'grid-wrap' ? GEOM_WRAP_HEIGHT : 0
      },
    })
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
      configurable: true,
      get(this: HTMLElement) {
        return this.id === 'grid-wrap' ? 100000 : 0
      },
    })
    Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
      configurable: true,
      value(this: HTMLElement) {
        if (this.id === 'grid-wrap') return fakeRect(0, 0, GEOM_WRAP_WIDTH, GEOM_WRAP_HEIGHT)
        if (this.id === 'meme-grid') return fakeRect(0, GEOM_TOP - scrollState.value, GEOM_WRAP_WIDTH, 100000)
        // 重渲染后新建的卡：按 data-slot-index 与固定几何回放矩形（与 installGeometry 同一数学）
        if (this.classList && this.classList.contains('meme-card')) {
          const slot = Number(this.dataset['slotIndex'])
          const grid = document.getElementById('meme-grid')
          const cols = Math.max(1, Number(grid?.style.getPropertyValue('--meme-cols')) || 4)
          if (Number.isInteger(slot)) {
            const pitchX = geomCard.width + GEOM_GAP
            const pitchY = geomCard.height + GEOM_GAP
            return fakeRect(
              (slot % cols) * pitchX,
              GEOM_TOP + Math.floor(slot / cols) * pitchY - scrollState.value,
              geomCard.width,
              geomCard.height,
            )
          }
        }
        return fakeRect(0, 0, 0, 0)
      },
    })
    // 卡片的未变换布局尺寸：不依赖实例安装，重渲染后的新卡同样可用
    Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
      configurable: true,
      get(this: HTMLElement) {
        return this.classList && this.classList.contains('meme-card') ? geomCard.width : 0
      },
    })
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
      configurable: true,
      get(this: HTMLElement) {
        return this.classList && this.classList.contains('meme-card') ? geomCard.height : 0
      },
    })
    if (typeof Element.prototype.scrollTo !== 'function') (Element.prototype as any).scrollTo = () => {}
    if (typeof Element.prototype.scrollBy !== 'function') (Element.prototype as any).scrollBy = () => {}
    if (typeof Element.prototype.setPointerCapture !== 'function') (Element.prototype as any).setPointerCapture = () => {}
    if (typeof Element.prototype.releasePointerCapture !== 'function') (Element.prototype as any).releasePointerCapture = () => {}
    if (typeof Element.prototype.hasPointerCapture !== 'function') (Element.prototype as any).hasPointerCapture = () => false
  })

  afterEach(() => {
    for (const wrapper of wrappers.splice(0)) wrapper.unmount()
    delete (globalThis as any).pywebview
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  // 切到整理模式（可排视图）后才能发起拖拽
  async function enableSortMode(wrapper: VueWrapper) {
    const button = wrapper.find('button[title="整理模式"]')
    expect(button.exists()).toBe(true)
    await button.trigger('click')
    await nextTick()
  }

  it('moves a mounted card to an absolute slot and persists the full window', async () => {
    const items = () => makeRange(1, 40)
    const reorderCalls: number[][] = []
    const handlers = baseHandlers(items, (args) => {
      reorderCalls.push((args[0] as number[]).slice())
      return true
    })
    const { wrapper, state } = await setupMainWindow(handlers, [1, 2])
    wrappers.push(wrapper)
    expect(state.lo).toBe(0)
    expect(state.hi).toBe(40)
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    const dragged = cardOf(5)
    expect(dragged.dataset['slotIndex']).toBe('4')
    dragged.dispatchEvent(pointerEvent('pointerdown', { clientX: 56, clientY: geometry.rowTop(1) + 30, buttons: 1 }))
    // 目标 = 行 2 列 3 = 全局槽位 11（非局部偏移）
    document.dispatchEvent(pointerEvent('pointermove', {
      clientX: geometry.colLeft(3) + 20,
      clientY: geometry.rowTop(2) + geometry.rowPitch / 2,
      buttons: 1,
    }))
    await flush()
    expect(state.slots[3]?.id).toBe(4)
    expect(state.slots[4]?.id).toBe(6)
    expect(state.slots[10]?.id).toBe(12)
    expect(state.slots[11]?.id).toBe(5)
    expect(state.slots[12]?.id).toBe(13)
    // 源卡原位占位；预览 ghost 是独立固定层且不带 id/按钮/tabindex
    expect(document.querySelector<HTMLElement>('#meme-grid .meme-card.drag-placeholder')?.dataset['memeId']).toBe('5')
    expect(document.querySelectorAll('#meme-grid .meme-card.dragging').length).toBe(0)
    const ghost = document.querySelector<HTMLElement>('.drag-ghost')
    expect(ghost?.getAttribute('aria-hidden')).toBe('true')
    expect(ghost?.hasAttribute('data-meme-id')).toBe(false)
    expect(ghost?.querySelectorAll('button, [tabindex]').length).toBe(0)
    expect(ghost?.style.transform).toContain('scale(0.90)')
    document.dispatchEvent(pointerEvent('pointerup', {
      clientX: geometry.colLeft(3) + 20,
      clientY: geometry.rowTop(2) + geometry.rowPitch / 2,
      buttons: 0,
    }))
    await flush(8)
    expect(reorderCalls.length).toBe(1)
    const submitted = reorderCalls[0] ?? []
    expect(submitted.length).toBe(40)
    expect(submitted[3]).toBe(4)
    expect(submitted[11]).toBe(5)
    expect(submitted[12]).toBe(13)
    expect(document.querySelector('.drag-ghost')).toBeNull()
    expect(document.querySelector('#meme-grid .meme-card.drag-placeholder')).toBeNull()
  })

  it('cancels without persisting when the pointer up leaves the grid frame', async () => {
    const items = () => makeRange(1, 40)
    const reorderCalls: number[][] = []
    const handlers = baseHandlers(items, (args) => {
      reorderCalls.push((args[0] as number[]).slice())
      return true
    })
    const { wrapper, state } = await setupMainWindow(handlers, [0, 9])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    const previewAndDrop = async (upX: number, upY: number) => {
      cardOf(1).dispatchEvent(pointerEvent('pointerdown', { clientX: 56, clientY: geometry.rowTop(0) + 30, buttons: 1 }))
      document.dispatchEvent(pointerEvent('pointermove', {
        clientX: geometry.colLeft(1) + 20,
        clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
        buttons: 1,
      }))
      await flush()
      expect(state.slots[1]?.id).toBe(1)
      document.dispatchEvent(pointerEvent('pointerup', { clientX: upX, clientY: upY, buttons: 0 }))
      await flush(8)
    }
    // 纵向越界（有效客户区上方）
    await previewAndDrop(56, -10)
    expect(reorderCalls.length).toBe(0)
    expect(state.slots[0]?.id).toBe(1)
    expect(state.slots[1]?.id).toBe(2)
    expect(document.querySelector('.drag-ghost')).toBeNull()
    // 横向越界（有效客户区右侧）
    await previewAndDrop(900, geometry.rowTop(0) + geometry.rowPitch / 2)
    expect(reorderCalls.length).toBe(0)
    expect(state.slots[0]?.id).toBe(1)
    expect(state.slots[1]?.id).toBe(2)
  })

  it('freezes the session while the order persist is in flight', async () => {
    const items = () => makeRange(1, 40)
    const persist = deferred<boolean>()
    const reorderCalls: number[][] = []
    const handlers = baseHandlers(items, (args) => {
      reorderCalls.push((args[0] as number[]).slice())
      return persist.promise
    })
    const { wrapper, state } = await setupMainWindow(handlers, [0, 9])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    cardOf(1).dispatchEvent(pointerEvent('pointerdown', { clientX: 56, clientY: geometry.rowTop(0) + 30, buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointermove', {
      clientX: geometry.colLeft(1) + 20,
      clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
      buttons: 1,
    }))
    await flush()
    expect(state.slots[0]?.id).toBe(2)
    document.dispatchEvent(pointerEvent('pointerup', {
      clientX: geometry.colLeft(1) + 20,
      clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
      buttons: 0,
    }))
    await flush()
    expect(reorderCalls.length).toBe(1)
    const order = () => state.slots.slice(0, 4).map((record: Meme | undefined) => record?.id)
    const submitted = order()
    expect(submitted[0]).toBe(2)
    // saving：视觉与占位已收起，新的按压/移动不得改动已提交顺序
    expect(document.querySelector('.drag-ghost')).toBeNull()
    expect(document.querySelector('#meme-grid .meme-card.drag-placeholder')).toBeNull()
    cardOf(4).dispatchEvent(pointerEvent('pointerdown', { clientX: geometry.colLeft(3) + 20, clientY: geometry.rowTop(0) + 30, buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointermove', {
      clientX: geometry.colLeft(3) + 20,
      clientY: geometry.rowTop(3) + geometry.rowPitch / 2,
      buttons: 1,
    }))
    await flush(8)
    expect(order()).toEqual(submitted)
    persist.resolve(true)
    await flush(8)
    expect(order()).toEqual(submitted)
    expect(reorderCalls[0]?.length).toBe(40)
  })

  it('does not restore a stale snapshot over a newer generation', async () => {
    const orderA = makeRange(1, 40)
    const orderB = makeRange(101, 40)
    let current = orderA
    const persist = deferred<boolean>()
    const reorderCalls: number[][] = []
    const handlers = baseHandlers(() => current, (args) => {
      reorderCalls.push((args[0] as number[]).slice())
      return persist.promise
    })
    const { wrapper, state, calls } = await setupMainWindow(handlers, [0, 9])
    wrappers.push(wrapper)
    expect(state.slots[0]?.id).toBe(1)
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    cardOf(1).dispatchEvent(pointerEvent('pointerdown', { clientX: 56, clientY: geometry.rowTop(0) + 30, buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointermove', {
      clientX: geometry.colLeft(1) + 20,
      clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
      buttons: 1,
    }))
    await flush()
    document.dispatchEvent(pointerEvent('pointerup', {
      clientX: geometry.colLeft(1) + 20,
      clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
      buttons: 0,
    }))
    await flush()
    expect(reorderCalls.length).toBe(1)
    expect((reorderCalls[0] ?? [])[0]).toBe(2)
    // 保存期间发生新查询：新代次数据落地
    current = orderB
    ;(globalThis as unknown as { refreshMemes: () => void }).refreshMemes()
    await flush(8)
    expect(state.slots[0]?.id).toBe(101)
    // 保存失败结算：不得用旧快照覆盖新代次，也不得为旧会话触发新查询的 search/选择清空
    state.selectedIds = new Set([101])
    const countsBeforeResult = calls.filter(call => call.method === 'count_memes').length
    persist.resolve(false)
    await flush(8)
    expect(state.slots[0]?.id).toBe(101)
    expect(state.slots[4]?.id).toBe(105)
    expect(state.selectedIds.size).toBe(1)
    expect(state.selectedIds.has(101)).toBe(true)
    expect(calls.filter(call => call.method === 'count_memes').length).toBe(countsBeforeResult)
  })

  it('restores the baseline and re-syncs when a same-context persist fails', async () => {
    const items = () => makeRange(1, 40)
    const persist = deferred<boolean>()
    const reorderCalls: number[][] = []
    const handlers = baseHandlers(items, (args) => {
      reorderCalls.push((args[0] as number[]).slice())
      return persist.promise
    })
    const { wrapper, state, calls } = await setupMainWindow(handlers, [0, 9])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    cardOf(1).dispatchEvent(pointerEvent('pointerdown', { clientX: 56, clientY: geometry.rowTop(0) + 30, buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointermove', {
      clientX: geometry.colLeft(1) + 20,
      clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
      buttons: 1,
    }))
    await flush()
    document.dispatchEvent(pointerEvent('pointerup', {
      clientX: geometry.colLeft(1) + 20,
      clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
      buttons: 0,
    }))
    await flush()
    expect(reorderCalls.length).toBe(1)
    // 同代次失败：恢复基准顺序并按数据库重同步（count 重新读取）
    const countsBeforeResult = calls.filter(call => call.method === 'count_memes').length
    persist.resolve(false)
    await flush(8)
    expect(state.slots[0]?.id).toBe(1)
    expect(state.slots[1]?.id).toBe(2)
    expect(calls.filter(call => call.method === 'count_memes').length).toBeGreaterThan(countsBeforeResult)
  })

  it('keeps auto-scrolling while the pointer stays still in the bottom edge', async () => {
    const items = () => makeRange(1, 200)
    const handlers = baseHandlers(items, () => true)
    const { wrapper, state, calls } = await setupMainWindow(handlers, [0, 9])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    cardOf(1).dispatchEvent(pointerEvent('pointerdown', { clientX: 56, clientY: geometry.rowTop(0) + 30, buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointermove', { clientX: 56, clientY: 590, buttons: 1 }))
    await flush()
    // 目标为已挂载真卡：行 3 列 0 = 槽位 12
    expect(state.slots[12]?.id).toBe(1)
    const before = wrap.scrollTop
    const callsBefore = calls.length
    // 不再发送任何 pointermove：静止指针由 rAF pump 持续滚动（视口内仍在已加载路径）
    for (let i = 0; i < 10; i++) await stepAnimationFrame(16)
    expect(wrap.scrollTop).toBeGreaterThan(before)
    expect(calls.length).toBe(callsBefore)
    // 松手结束：pump 停止，后续帧不再滚动
    document.dispatchEvent(pointerEvent('pointerup', { clientX: 56, clientY: 590, buttons: 0 }))
    await flush(8)
    const settled = wrap.scrollTop
    for (let i = 0; i < 5; i++) await stepAnimationFrame(16)
    expect(wrap.scrollTop).toBe(settled)
  })

  // 尾部短窗口夹具：total 1040、已加载 [1000,1040)（10 行）、视口对齐已加载首行，backward 页挂起
  interface TailHarness {
    wrapper: VueWrapper
    state: any
    model: any
    calls: Call[]
    reorderCalls: number[][]
    pages: ReturnType<typeof holdPage>
    wrap: HTMLElement
    geometry: Geometry
  }

  async function setupTailHarness(): Promise<TailHarness> {
    const total = 1040
    const pages = holdPage()
    const reorderCalls: number[][] = []
    const handlers: Record<string, BridgeHandler> = {
      ...baseHandlers(() => makeRange(1, 200), (args) => {
        reorderCalls.push((args[0] as number[]).slice())
        return true
      }),
      count_memes: () => total,
      search_memes: (args) => {
        const offset = args[3] as number
        const limit = args[4] as number
        if (offset === 0) return makeRange(1, 200)
        if (offset === 800) return pages.handler(args)
        return makeRange(offset + 1, Math.max(0, Math.min(limit, total - offset)))
      },
    }
    const { wrapper, state, model, calls } = await setupMainWindow(handlers, [245, 260])
    wrappers.push(wrapper)
    await model.ensureRange(1000, 1040, 'jump')
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    scrollState.value = geometry.startMargin + 250 * geometry.rowPitch
    return { wrapper, state, model, calls, reorderCalls, pages, wrap, geometry }
  }

  // 按下已加载卡（行 250 列 1 = 槽位 1001）并把指针移到上边缘：起手即位于 backward 前沿
  async function startTailDrag(harness: TailHarness) {
    const { geometry } = harness
    const card = slotCard(1001)
    expect(card?.dataset['memeId']).toBe('1002')
    card.dispatchEvent(pointerEvent('pointerdown', { clientX: geometry.colLeft(1) + 20, clientY: geometry.rowTop(250) + 30, buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointermove', { clientX: 56, clientY: 10, buttons: 1 }))
    await flush()
  }

  it('pauses at the loaded frontier, extends one page, then resumes scrolling', async () => {
    const harness = await setupTailHarness()
    const { state, calls, pages, wrap } = harness
    await startTailDrag(harness)
    expect(state.lo).toBe(1000)
    expect(state.hi).toBe(1040)
    expect(state.slots[1000]?.id).toBe(1002)
    const anchor = wrap.scrollTop
    // 指针静止在上边缘：前沿暂停不越入未加载行，单飞扩页只请求一次
    for (let i = 0; i < 12; i++) await stepAnimationFrame(16)
    expect(wrap.scrollTop).toBe(anchor)
    expect(offsetCalls(calls, 800)).toBe(1)
    // 邻页提交：窗口向前扩展，预览保留，滚动恢复；未到下一前沿前不再请求更前一页
    pages.resolve(800, makeRange(801, 200))
    await flush(8)
    expect(state.lo).toBe(800)
    expect(state.hi).toBe(1040)
    expect(state.slots[800]?.id).toBe(801)
    expect(state.slots[1000]?.id).toBe(1002)
    expect(offsetCalls(calls, 600)).toBe(0)
    for (let i = 0; i < 10; i++) await stepAnimationFrame(16)
    expect(wrap.scrollTop).toBeLessThan(anchor)
    expect(offsetCalls(calls, 800)).toBe(1)
  })

  it('submits the full extended window when dropping across the loaded edge', async () => {
    const harness = await setupTailHarness()
    const { state, reorderCalls, pages, geometry } = harness
    await startTailDrag(harness)
    for (let i = 0; i < 6; i++) await stepAnimationFrame(16)
    pages.resolve(800, makeRange(801, 200))
    await flush(8)
    expect(state.lo).toBe(800)
    expect(state.hi).toBe(1040)
    // 落点 = 行 251 列 2 = 槽位 1006（扩展窗口内的当前挂载真卡）
    document.dispatchEvent(pointerEvent('pointermove', {
      clientX: geometry.colLeft(2) + 20,
      clientY: geometry.rowTop(251) + 30,
      buttons: 1,
    }))
    await flush()
    expect(state.slots[1006]?.id).toBe(1002)
    document.dispatchEvent(pointerEvent('pointerup', {
      clientX: geometry.colLeft(2) + 20,
      clientY: geometry.rowTop(251) + 30,
      buttons: 0,
    }))
    await flush(8)
    expect(reorderCalls.length).toBe(1)
    const submitted = reorderCalls[0] ?? []
    expect(submitted.length).toBe(240)
    expect(submitted[0]).toBe(801)
    expect(submitted[206]).toBe(1002)
    expect(submitted[239]).toBe(1040)
    expect(state.lo).toBe(800)
    expect(state.hi).toBe(1040)
  })

  it('cancels back to the extended baseline and keeps the newly loaded page', async () => {
    const harness = await setupTailHarness()
    const { state, reorderCalls, pages } = harness
    await startTailDrag(harness)
    for (let i = 0; i < 6; i++) await stepAnimationFrame(16)
    expect(state.lo).toBe(1000)
    pages.resolve(800, makeRange(801, 200))
    await flush(8)
    expect(state.lo).toBe(800)
    expect(state.slots[1000]?.id).toBe(1002)
    // 取消：恢复扩展后的基准顺序（新页保留），不提交
    document.dispatchEvent(pointerEvent('pointercancel', { buttons: 0 }))
    await flush(8)
    expect(state.lo).toBe(800)
    expect(state.hi).toBe(1040)
    expect(state.slots[800]?.id).toBe(801)
    expect(state.slots[1000]?.id).toBe(1001)
    expect(state.slots[1001]?.id).toBe(1002)
    expect(reorderCalls.length).toBe(0)
    expect(document.querySelector('.drag-ghost')).toBeNull()
    expect(document.querySelector('#meme-grid .meme-card.drag-placeholder')).toBeNull()
  })

  // ── 自研可见区框选：空白起手 + 起手快照 XOR + 取消回滚 ──

  // 框选区：行 0 两张卡（x 2..238 / y 96..244，起止点都落在卡间隙与行间隙内）
  const MARQUEE_BOX: [number, number, number, number] = [2, 96, 238, 244]

  function sorted(ids: Set<number>): number[] {
    return [...ids].sort((a, b) => a - b)
  }

  async function marqueeCommit(start: [number, number], end: [number, number]) {
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    wrap.dispatchEvent(pointerEvent('pointerdown', { clientX: start[0], clientY: start[1], buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointermove', { clientX: end[0], clientY: end[1], buttons: 1 }))
    await stepAnimationFrame(16)
    document.dispatchEvent(pointerEvent('pointerup', { clientX: end[0], clientY: end[1], buttons: 0 }))
    await flush()
  }

  it('selects mounted cards from a blank marquee and keeps off-screen ids', async () => {
    const items = () => makeRange(1, 40)
    const { wrapper, state } = await setupMainWindow(baseHandlers(items), [0, 9])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    installGeometry()
    // 框外离屏 id 保留：起手快照与命中集合做对称差
    state.selectedIds = new Set([999])
    await marqueeCommit([MARQUEE_BOX[0], MARQUEE_BOX[1]], [MARQUEE_BOX[2], MARQUEE_BOX[3]])
    expect(sorted(state.selectedIds)).toEqual([1, 2, 999])
    expect(wrapper.find('#organize-bar .count').text()).toContain('已选 3 项')
    expect(document.querySelector('.marquee-overlay')).toBeNull()
    // 已激活框选吞掉随后一次 click（抬起落在卡上也不误触勾选）
    cardOf(3).dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(sorted(state.selectedIds)).toEqual([1, 2, 999])
    // 同一区域再框一次：反选命中的 1/2，离屏 999 保留
    await marqueeCommit([2, 96], [238, 244])
    expect(sorted(state.selectedIds)).toEqual([999])
  })

  it('normalizes four marquee directions to the same selection', async () => {
    const items = () => makeRange(1, 40)
    const { wrapper, state } = await setupMainWindow(baseHandlers(items), [0, 9])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    installGeometry()
    const corners: Array<[number, number, number, number]> = [
      [2, 96, 238, 244],
      [238, 244, 2, 96],
      [238, 96, 2, 244],
      [2, 244, 238, 96],
    ]
    for (const [sx, sy, ex, ey] of corners) {
      state.selectedIds = new Set<number>()
      await marqueeCommit([sx, sy], [ex, ey])
      expect(sorted(state.selectedIds)).toEqual([1, 2])
    }
  })

  it('does not clear on a blank click and never starts a marquee from a card', async () => {
    const items = () => makeRange(1, 40)
    const { wrapper, state } = await setupMainWindow(baseHandlers(items), [0, 9])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    installGeometry()
    state.selectedIds = new Set([1])
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    // 空白点击（未过 8px 门槛）：不清空选择、不出现 overlay
    wrap.dispatchEvent(pointerEvent('pointerdown', { clientX: 2, clientY: 96, buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointermove', { clientX: 5, clientY: 99, buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointerup', { clientX: 5, clientY: 99, buttons: 0 }))
    await flush()
    expect(sorted(state.selectedIds)).toEqual([1])
    expect(document.querySelector('.marquee-overlay')).toBeNull()
    expect(document.querySelector('.drag-ghost')).toBeNull()
    // 卡片起手走拖拽仲裁：不出现框选 overlay，也不改动选择
    cardOf(1).dispatchEvent(pointerEvent('pointerdown', { clientX: 56, clientY: 130, buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointermove', { clientX: 300, clientY: 300, buttons: 1 }))
    await flush()
    expect(document.querySelector('.marquee-overlay')).toBeNull()
    expect(document.querySelector('.drag-ghost')).not.toBeNull()
    expect(sorted(state.selectedIds)).toEqual([1])
    document.dispatchEvent(pointerEvent('pointerup', { clientX: 300, clientY: 300, buttons: 0 }))
    await flush(8)
  })

  it('never selects skeleton slots inside the marquee', async () => {
    const total = 240
    const handlers: Record<string, BridgeHandler> = {
      ...baseHandlers(() => makeRange(1, 200)),
      count_memes: () => total,
      search_memes: (args) => {
        const offset = args[3] as number
        const limit = args[4] as number
        if (offset === 0) return makeRange(1, 200)
        return makeRange(offset + 1, Math.max(0, Math.min(limit, total - offset)))
      },
    }
    const { wrapper, state } = await setupMainWindow(handlers, [49, 51])
    wrappers.push(wrapper)
    expect(state.hi).toBe(200)
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    // 视口对齐第 49 行：其下两行为未加载骨架，框选不得命中
    scrollState.value = geometry.startMargin + 49 * geometry.rowPitch - 20
    const startY = geometry.rowTop(49) - 4
    const endY = geometry.rowTop(51) + geometry.cardHeight - 4
    await marqueeCommit([4, startY], [470, endY])
    expect(sorted(state.selectedIds)).toEqual([197, 198, 199, 200])
  })

  it('cancels the marquee on Escape, pointercancel and scroll with the start snapshot', async () => {
    const items = () => makeRange(1, 40)
    const { wrapper, state } = await setupMainWindow(baseHandlers(items), [0, 9])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    installGeometry()
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    const startGesture = async () => {
      state.selectedIds = new Set([3])
      wrap.dispatchEvent(pointerEvent('pointerdown', { clientX: 2, clientY: 96, buttons: 1 }))
      document.dispatchEvent(pointerEvent('pointermove', { clientX: 238, clientY: 244, buttons: 1 }))
      await stepAnimationFrame(16)
      expect(document.querySelector('.marquee-overlay')).not.toBeNull()
      expect(state.selectedIds.has(1)).toBe(true)
    }
    // ESC：取消手势并回滚起手快照，第一次不退出整理
    await startGesture()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flush()
    expect(sorted(state.selectedIds)).toEqual([3])
    expect(document.querySelector('.marquee-overlay')).toBeNull()
    expect(wrapper.find('#organize-bar').exists()).toBe(true)
    // pointercancel：同样回滚
    await startGesture()
    document.dispatchEvent(pointerEvent('pointercancel', { buttons: 0 }))
    await flush()
    expect(sorted(state.selectedIds)).toEqual([3])
    expect(document.querySelector('.marquee-overlay')).toBeNull()
    // blur：同样回滚
    await startGesture()
    window.dispatchEvent(new Event('blur'))
    await flush()
    expect(sorted(state.selectedIds)).toEqual([3])
    expect(document.querySelector('.marquee-overlay')).toBeNull()
    // 滚动：立即取消并回滚
    await startGesture()
    scrollState.value += 40
    wrap.dispatchEvent(new Event('scroll'))
    await flush()
    expect(sorted(state.selectedIds)).toEqual([3])
    expect(document.querySelector('.marquee-overlay')).toBeNull()
  })

  it('clears on sort-off and never restores an old set across queries', async () => {
    const items = () => makeRange(1, 40)
    const { wrapper, state } = await setupMainWindow(baseHandlers(items), [0, 9])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    installGeometry()
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    // 查询变化：取消手势且不回填旧 Set（search 自行清空选择）
    state.selectedIds = new Set([3])
    wrap.dispatchEvent(pointerEvent('pointerdown', { clientX: 2, clientY: 96, buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointermove', { clientX: 238, clientY: 244, buttons: 1 }))
    await stepAnimationFrame(16)
    expect(state.selectedIds.has(1)).toBe(true)
    ;(globalThis as unknown as { refreshMemes: () => void }).refreshMemes()
    await flush(8)
    expect(state.selectedIds.size).toBe(0)
    expect(document.querySelector('.marquee-overlay')).toBeNull()
    // 关闭整理：以 clearSelection 为最终结果，不保留框选会话
    state.selectedIds = new Set([2])
    wrap.dispatchEvent(pointerEvent('pointerdown', { clientX: 2, clientY: 96, buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointermove', { clientX: 238, clientY: 244, buttons: 1 }))
    await stepAnimationFrame(16)
    expect(document.querySelector('.marquee-overlay')).not.toBeNull()
    await wrapper.find('button[title="整理模式"]').trigger('click')
    await flush()
    expect(state.selectedIds.size).toBe(0)
    expect(document.querySelector('.marquee-overlay')).toBeNull()
    expect(wrapper.find('#organize-bar').exists()).toBe(false)
  })

  it('keeps Enter/Space as the keyboard toggle in sort mode', async () => {
    const items = () => makeRange(1, 40)
    const { wrapper, state } = await setupMainWindow(baseHandlers(items), [0, 9])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    installGeometry()
    const card = cardOf(1)
    card.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flush()
    expect(sorted(state.selectedIds)).toEqual([1])
    card.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }))
    await flush()
    expect(state.selectedIds.size).toBe(0)
  })

  it('ignores the capture release of a normal pointerup while saving', async () => {
    const items = () => makeRange(1, 40)
    const persist = deferred<boolean>()
    const reorderCalls: number[][] = []
    const handlers = baseHandlers(items, (args) => {
      reorderCalls.push((args[0] as number[]).slice())
      return persist.promise
    })
    const { wrapper, state, calls } = await setupMainWindow(handlers, [0, 9])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    cardOf(1).dispatchEvent(pointerEvent('pointerdown', { clientX: 56, clientY: geometry.rowTop(0) + 30, buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointermove', {
      clientX: geometry.colLeft(1) + 20,
      clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
      buttons: 1,
    }))
    await flush()
    document.dispatchEvent(pointerEvent('pointerup', {
      clientX: geometry.colLeft(1) + 20,
      clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
      buttons: 0,
    }))
    await flush()
    expect(reorderCalls.length).toBe(1)
    // 真实时序：pointerup 后浏览器自动释放捕获触发 lostpointercapture（RPC 仍挂起）
    state.selectedIds = new Set([5])
    const countsBeforeResult = calls.filter(call => call.method === 'count_memes').length
    const scrollBeforeResult = (document.getElementById('grid-wrap') as HTMLElement).scrollTop
    ;(document.getElementById('grid-wrap') as HTMLElement).dispatchEvent(pointerEvent('lostpointercapture', { pointerId: 1 }))
    await flush()
    // RPC 成功结算：不得 search、不清选择、不回顶，也不得重复提交
    persist.resolve(true)
    await flush(8)
    expect(reorderCalls.length).toBe(1)
    expect(state.selectedIds.size).toBe(1)
    expect(state.selectedIds.has(5)).toBe(true)
    expect(calls.filter(call => call.method === 'count_memes').length).toBe(countsBeforeResult)
    expect((document.getElementById('grid-wrap') as HTMLElement).scrollTop).toBe(scrollBeforeResult)
    expect(state.slots[0]?.id).toBe(2)
  })

  // ── 捕获丢失、跨新页 drop、前沿挂起与卸载清队列 ──

  it('cancels an active drag when its pointer capture is lost', async () => {
    const items = () => makeRange(1, 40)
    const reorderCalls: number[][] = []
    const handlers = baseHandlers(items, (args) => {
      reorderCalls.push((args[0] as number[]).slice())
      return true
    })
    const { wrapper, state } = await setupMainWindow(handlers, [0, 9])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    const dryRun = async () => {
      cardOf(1).dispatchEvent(pointerEvent('pointerdown', { clientX: 56, clientY: geometry.rowTop(0) + 30, buttons: 1 }))
      document.dispatchEvent(pointerEvent('pointermove', {
        clientX: geometry.colLeft(1) + 20,
        clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
        buttons: 1,
      }))
      await flush()
      expect(state.slots[0]?.id).toBe(2)
    }
    // 丢捕获：取消并回滚基准，清理预览/占位/帧，且不提交
    await dryRun()
    wrap.dispatchEvent(pointerEvent('lostpointercapture', { pointerId: 1 }))
    await flush()
    expect(state.slots[0]?.id).toBe(1)
    expect(state.slots[1]?.id).toBe(2)
    expect(document.querySelector('.drag-ghost')).toBeNull()
    expect(document.querySelector('#meme-grid .meme-card.drag-placeholder')).toBeNull()
    expect(reorderCalls.length).toBe(0)
    const scrollAfterCancel = wrap.scrollTop
    for (let i = 0; i < 4; i++) await stepAnimationFrame(16)
    expect(state.slots[0]?.id).toBe(1)
    expect(wrap.scrollTop).toBe(scrollAfterCancel)
    // 正常完成一次 drop 后再收到迟到的 lostpointercapture：不得误取消/回滚
    await dryRun()
    document.dispatchEvent(pointerEvent('pointerup', {
      clientX: geometry.colLeft(1) + 20,
      clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
      buttons: 0,
    }))
    await flush(8)
    expect(reorderCalls.length).toBe(1)
    const submitted = state.slots.slice(0, 2).map((record: Meme | undefined) => record?.id)
    expect(submitted).toEqual([2, 1])
    wrap.dispatchEvent(pointerEvent('lostpointercapture', { pointerId: 1 }))
    await flush(8)
    expect(state.slots.slice(0, 2).map((record: Meme | undefined) => record?.id)).toEqual([2, 1])
    expect(reorderCalls.length).toBe(1)
  })

  it('drops onto a slot from a page loaded during the same drag', async () => {
    const total = 400
    const reorderCalls: number[][] = []
    const handlers: Record<string, BridgeHandler> = {
      ...baseHandlers(() => makeRange(1, 200)),
      count_memes: () => total,
      search_memes: (args) => {
        const offset = args[3] as number
        const limit = args[4] as number
        return makeRange(offset + 1, Math.max(0, Math.min(limit, total - offset)))
      },
      reorder_memes: (args) => {
        reorderCalls.push((args[0] as number[]).slice())
        return true
      },
    }
    const { wrapper, state, calls } = await setupMainWindow(handlers, [48, 52])
    wrappers.push(wrapper)
    expect(state.hi).toBe(200)
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    // 视口停在向前前沿前 10px：行 49 的已加载卡可用，下方两行仍是骨架
    const frontierTop = geometry.startMargin + 50 * geometry.rowPitch - GEOM_WRAP_HEIGHT
    scrollState.value = frontierTop - 10
    cardOf(197).dispatchEvent(pointerEvent('pointerdown', {
      clientX: 56,
      clientY: geometry.rowTop(49) + 30,
      buttons: 1,
    }))
    document.dispatchEvent(pointerEvent('pointermove', { clientX: 56, clientY: 590, buttons: 1 }))
    await flush()
    for (let i = 0; i < 30; i++) await stepAnimationFrame(16)
    await flush(4)
    // 邻页自动加载：窗口扩到 400，前沿随之推进
    expect(offsetCalls(calls, 200)).toBe(1)
    expect(state.hi).toBe(400)
    expect(wrap.scrollTop).toBeGreaterThan(frontierTop)
    // 落到新页已加载真卡（行 51 列 0 = 槽位 204，≥ 旧窗口 hi）
    document.dispatchEvent(pointerEvent('pointermove', {
      clientX: 56,
      clientY: geometry.rowTop(51) + 30,
      buttons: 1,
    }))
    await flush()
    expect(state.slots[204]?.id).toBe(197)
    document.dispatchEvent(pointerEvent('pointerup', {
      clientX: 56,
      clientY: geometry.rowTop(51) + 30,
      buttons: 0,
    }))
    await flush(8)
    expect(reorderCalls.length).toBe(1)
    const submitted = reorderCalls[0] ?? []
    expect(submitted.length).toBe(400)
    expect(submitted[204]).toBe(197)
    expect(state.hi).toBe(400)
  })

  it('stops at the frontier and never drops onto skeleton slots while the next page is pending', async () => {
    const total = 400
    const pages = holdPage()
    const reorderCalls: number[][] = []
    const handlers: Record<string, BridgeHandler> = {
      ...baseHandlers(() => makeRange(1, 200)),
      count_memes: () => total,
      search_memes: (args) => {
        const offset = args[3] as number
        if (offset === 200) return pages.handler(args)
        const limit = args[4] as number
        return makeRange(offset + 1, Math.max(0, Math.min(limit, total - offset)))
      },
      reorder_memes: (args) => {
        reorderCalls.push((args[0] as number[]).slice())
        return true
      },
    }
    const { wrapper, state, calls } = await setupMainWindow(handlers, [48, 52])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    const frontierTop = geometry.startMargin + 50 * geometry.rowPitch - GEOM_WRAP_HEIGHT
    scrollState.value = frontierTop - 10
    cardOf(197).dispatchEvent(pointerEvent('pointerdown', {
      clientX: 56,
      clientY: geometry.rowTop(49) + 30,
      buttons: 1,
    }))
    document.dispatchEvent(pointerEvent('pointermove', { clientX: 56, clientY: 590, buttons: 1 }))
    await flush()
    for (let i = 0; i < 12; i++) await stepAnimationFrame(16)
    await flush(4)
    // 邻页挂起：前沿暂停（不越过骨架）且只请求一次，不自动填充
    expect(wrap.scrollTop).toBe(frontierTop)
    expect(state.hi).toBe(200)
    expect(offsetCalls(calls, 200)).toBe(1)
    for (let i = 0; i < 6; i++) await stepAnimationFrame(16)
    await flush(4)
    expect(wrap.scrollTop).toBe(frontierTop)
    expect(offsetCalls(calls, 200)).toBe(1)
    // 骨架槽位（行 50 = 槽位 200）不是合法目标：松手不提交、不改顺序
    document.dispatchEvent(pointerEvent('pointerup', { clientX: 56, clientY: 600, buttons: 0 }))
    await flush(8)
    expect(reorderCalls.length).toBe(0)
    expect(state.slots[0]?.id).toBe(1)
    expect(state.slots[196]?.id).toBe(197)
    expect(document.querySelector('.drag-ghost')).toBeNull()
    expect(document.querySelector('#meme-grid .meme-card.drag-placeholder')).toBeNull()
  })

  it('drops pending gesture frames and requests on unmount', async () => {
    const items = () => makeRange(1, 200)
    const handlers = baseHandlers(items, () => true)
    const { wrapper, state, calls } = await setupMainWindow(handlers, [0, 9])
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    await flush()
    const baselineFrames = rafQueue.callbacks.size
    cardOf(1).dispatchEvent(pointerEvent('pointerdown', { clientX: 56, clientY: geometry.rowTop(0) + 30, buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointermove', { clientX: 56, clientY: 590, buttons: 1 }))
    await flush()
    expect(state.slots[12]?.id).toBe(1)
    wrapper.unmount()
    // 卸载：手势帧被取消（不超过进入前的队列），不再新增请求或滚动
    expect(rafQueue.callbacks.size).toBeLessThanOrEqual(baselineFrames)
    const scrollAfterUnmount = wrap.scrollTop
    const callsAfterUnmount = calls.length
    for (let i = 0; i < 4; i++) await stepAnimationFrame(16)
    expect(wrap.scrollTop).toBe(scrollAfterUnmount)
    expect(calls.length).toBe(callsAfterUnmount)
    expect(rafQueue.callbacks.size).toBe(0)
  })

  // ── S4 体验收尾：footer 重试 / 回到顶部 ──

  // 分页失败/挂起夹具：offset 200/400 由 mode 控制（fail → null；hold → 手动 resolve；ok → 正常返回）
  function failingPageHandlers(
    total: number,
    pages: ReturnType<typeof holdPage>,
    mode: () => 'fail' | 'hold' | 'ok',
  ): Record<string, BridgeHandler> {
    return {
      ...baseHandlers(() => makeRange(1, 200)),
      count_memes: () => total,
      search_memes: (args) => {
        const offset = args[3] as number
        const limit = args[4] as number
        if (offset === 0) return makeRange(1, 200)
        if (offset === 200 || offset === 400) {
          const now = mode()
          if (now === 'fail') return null
          if (now === 'hold') return pages.handler(args)
          return makeRange(offset + 1, 200)
        }
        return makeRange(offset + 1, Math.max(0, Math.min(limit, total - offset)))
      },
    }
  }

  it('footerRetriesFailedRange', async () => {
    const total = 530
    const pages = holdPage()
    let mode: 'fail' | 'hold' | 'ok' = 'fail'
    const { wrapper, state, model, calls } = await setupMainWindow(failingPageHandlers(total, pages, () => mode), [0, 9])
    wrappers.push(wrapper)
    installGeometry()
    expect(state.hi).toBe(200)
    await expect(model.ensureRange(200, 400)).resolves.toBe(false)
    expect(state.loadError).toBe(true)
    expect(offsetCalls(calls, 200)).toBe(1)
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    scrollState.value = 120
    const queryGen = state.queryGen
    const countCalls = calls.filter(call => call.method === 'count_memes').length
    // 非空选择在重试期间保持（重放不做 search、不漂白选择）
    state.selectedIds = new Set([1, 2])
    // 失败入口可见且带可访问名称与精确文案
    const retry = wrapper.find('.grid-retry')
    expect(retry.exists()).toBe(true)
    expect(retry.text()).toContain('加载失败，点击重试')
    expect(retry.attributes('aria-label')).toBe('重新加载表情包')
    expect(retry.attributes('disabled')).toBeUndefined()
    // 点击：仅重放该 offset；挂起期间单飞并显示加载中
    mode = 'hold'
    await retry.trigger('click')
    await flush()
    expect(offsetCalls(calls, 200)).toBe(2)
    expect(wrapper.find('.grid-foot').text()).toContain('加载中')
    expect(wrapper.find('.grid-retry').exists()).toBe(false)
    expect(state.selectedIds.size).toBe(2)
    // 在途不重复请求；旧退避计时器已被提前清除
    await vi.advanceTimersByTimeAsync(3000)
    await flush()
    expect(offsetCalls(calls, 200)).toBe(2)
    // 成功：恢复总数、不新增 count、不换代、不重排滚动、不动选择
    pages.resolve(200, makeRange(201, 200))
    await flush(8)
    expect(state.hi).toBe(400)
    expect(state.loadError).toBe(false)
    expect(state.queryGen).toBe(queryGen)
    expect(calls.filter(call => call.method === 'count_memes').length).toBe(countCalls)
    expect(wrapper.find('.grid-foot').text()).toContain('共 530 项')
    expect(wrapper.find('.grid-retry').exists()).toBe(false)
    expect(wrap.scrollTop).toBe(120)
    expect(state.selectedIds.size).toBe(2)
    expect(state.selectedIds.has(1)).toBe(true)
    expect(state.selectedIds.has(2)).toBe(true)
  })

  it('footerKeepsFailureAfterRetryFails', async () => {
    const total = 530
    const pages = holdPage()
    let mode: 'fail' | 'hold' | 'ok' = 'fail'
    const { wrapper, state, model, calls } = await setupMainWindow(failingPageHandlers(total, pages, () => mode), [0, 9])
    wrappers.push(wrapper)
    await expect(model.ensureRange(200, 400)).resolves.toBe(false)
    expect(state.loadError).toBe(true)
    expect(offsetCalls(calls, 200)).toBe(1)
    // 提前点击：先清掉 1s 退避计时器，再重放一次
    mode = 'hold'
    await wrapper.find('.grid-retry').trigger('click')
    await flush()
    expect(offsetCalls(calls, 200)).toBe(2)
    await vi.advanceTimersByTimeAsync(999)
    await flush()
    expect(offsetCalls(calls, 200)).toBe(2)
    // 再次失败：错误入口保留、已有缓存保留
    mode = 'fail'
    pages.resolve(200, null)
    await flush(8)
    expect(state.loadError).toBe(true)
    expect(state.hi).toBe(200)
    expect(state.slots[0]?.id).toBe(1)
    expect(wrapper.find('.grid-retry').exists()).toBe(true)
    // 自动退避仍按原预算收敛（1s/2s/3s 各一次后停止，不无限 pump）
    await vi.advanceTimersByTimeAsync(1000)
    await flush()
    expect(offsetCalls(calls, 200)).toBe(3)
    await vi.advanceTimersByTimeAsync(2000)
    await flush()
    expect(offsetCalls(calls, 200)).toBe(4)
    await vi.advanceTimersByTimeAsync(3000)
    await flush()
    expect(offsetCalls(calls, 200)).toBe(5)
    await vi.advanceTimersByTimeAsync(10000)
    await flush()
    expect(offsetCalls(calls, 200)).toBe(5)
    expect(wrapper.find('.grid-retry').exists()).toBe(true)
  })

  it('gridActionsAreBlockedDuringGesturesAndSaving', async () => {
    const total = 530
    const pages = holdPage()
    let mode: 'fail' | 'hold' | 'ok' = 'fail'
    const persist = deferred<boolean>()
    const reorderCalls: number[][] = []
    const handlers: Record<string, BridgeHandler> = {
      ...failingPageHandlers(total, pages, () => mode),
      reorder_memes: (args) => {
        reorderCalls.push((args[0] as number[]).slice())
        return persist.promise
      },
    }
    const { wrapper, state, model, calls } = await setupMainWindow(handlers, [0, 9])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    await expect(model.ensureRange(200, 400)).resolves.toBe(false)
    expect(state.loadError).toBe(true)
    // 滚动超过两屏 → 回顶按钮可见（后续手势阶段不推进计时器，避免触发原退避）
    scrollState.value = 1300
    wrap.dispatchEvent(new Event('scroll'))
    await nextTick()
    expect(wrapper.find('#back-to-top').exists()).toBe(true)
    const pageCalls = () => calls.filter(call => call.method === 'search_memes').length
    // 手势期间：重试/回顶都显示禁用态，且 handler 守卫让点击无任何副作用
    const clickBothBlocked = async (expectedScroll: number) => {
      const pageCallsBefore = pageCalls()
      const retry = wrapper.find('.grid-retry')
      expect(retry.exists()).toBe(true)
      expect((retry.element as HTMLButtonElement).disabled).toBe(true)
      await retry.trigger('click')
      const top = wrapper.find('#back-to-top')
      expect(top.exists()).toBe(true)
      expect((top.element as HTMLButtonElement).disabled).toBe(true)
      await top.trigger('click')
      await nextTick()
      expect(pageCalls()).toBe(pageCallsBefore)
      expect(offsetCalls(calls, 200)).toBe(1)
      expect(wrap.scrollTop).toBe(expectedScroll)
    }
    const slotsAt = (from: number) => state.slots.slice(from, from + 4).map((record: Meme | undefined) => record?.id)
    // A. 框选 armed→selecting：不取消会话、不改选择
    const selectedBefore = sorted(state.selectedIds)
    wrap.dispatchEvent(pointerEvent('pointerdown', { clientX: 360, clientY: 155, buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointermove', { clientX: 430, clientY: 250, buttons: 1 }))
    await nextTick()
    expect(document.querySelector('.marquee-overlay')).not.toBeNull()
    await clickBothBlocked(1300)
    expect(document.querySelector('.marquee-overlay')).not.toBeNull()
    expect(sorted(state.selectedIds)).toEqual(selectedBefore)
    document.dispatchEvent(pointerEvent('pointerup', { clientX: 430, clientY: 250, buttons: 0 }))
    await nextTick()
    expect(document.querySelector('.marquee-overlay')).toBeNull()
    // B. 排序 armed（未过门槛）：不取消会话、不改数组
    cardOf(33).dispatchEvent(pointerEvent('pointerdown', { clientX: 56, clientY: geometry.rowTop(8) + 30, buttons: 1 }))
    await nextTick()
    const armedSlots = slotsAt(32)
    await clickBothBlocked(1300)
    expect(slotsAt(32)).toEqual(armedSlots)
    document.dispatchEvent(pointerEvent('pointercancel', { buttons: 0 }))
    await nextTick()
    // C. 排序 active（已过门槛、预览已生成）：不取消手势、不改预览
    cardOf(33).dispatchEvent(pointerEvent('pointerdown', { clientX: 56, clientY: geometry.rowTop(8) + 30, buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointermove', { clientX: geometry.colLeft(3) + 20, clientY: geometry.rowTop(8) + 30, buttons: 1 }))
    await nextTick()
    expect(document.querySelector('.drag-ghost')).not.toBeNull()
    const previewSlots = slotsAt(32)
    await clickBothBlocked(1300)
    expect(document.querySelector('.drag-ghost')).not.toBeNull()
    expect(slotsAt(32)).toEqual(previewSlots)
    document.dispatchEvent(pointerEvent('pointercancel', { buttons: 0 }))
    await nextTick()
    expect(document.querySelector('.drag-ghost')).toBeNull()
    // D. saving（RPC 挂起）：不取消保存、不重复提交
    cardOf(33).dispatchEvent(pointerEvent('pointerdown', { clientX: 56, clientY: geometry.rowTop(8) + 30, buttons: 1 }))
    document.dispatchEvent(pointerEvent('pointermove', { clientX: geometry.colLeft(3) + 20, clientY: geometry.rowTop(8) + 30, buttons: 1 }))
    await nextTick()
    document.dispatchEvent(pointerEvent('pointerup', { clientX: geometry.colLeft(3) + 20, clientY: geometry.rowTop(8) + 30, buttons: 0 }))
    await nextTick()
    expect(reorderCalls.length).toBe(1)
    expect((reorderCalls[0] ?? [])[35]).toBe(33)
    await clickBothBlocked(1300)
    persist.resolve(true)
    await flush(8)
    expect(reorderCalls.length).toBe(1)
    expect(state.slots[35]?.id).toBe(33)
  })

  it('backToTopUsesTwoViewportThreshold', async () => {
    const items = () => makeRange(1, 200)
    const { wrapper, state } = await setupMainWindow(baseHandlers(items), [0, 9])
    wrappers.push(wrapper)
    installGeometry()
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    const scrollTo = async (value: number) => {
      scrollState.value = value
      wrap.dispatchEvent(new Event('scroll'))
      await nextTick()
    }
    await scrollTo(1199)
    expect(wrapper.find('#back-to-top').exists()).toBe(false)
    await scrollTo(1200)
    expect(wrapper.find('#back-to-top').exists()).toBe(false)
    await scrollTo(1201)
    expect(wrapper.find('#back-to-top').exists()).toBe(true)
    await scrollTo(1200)
    expect(wrapper.find('#back-to-top').exists()).toBe(false)
    // 视口高度变化后按新阈值重算（resize 触发）
    await scrollTo(700)
    expect(wrapper.find('#back-to-top').exists()).toBe(false)
    Object.defineProperty(wrap, 'clientHeight', { configurable: true, get: () => 300 })
    wrapper.findComponent({ name: 'Virtualizer' }).vm.$emit('resize')
    await nextTick()
    expect(wrapper.find('#back-to-top').exists()).toBe(true)
    // 0 视口不显示
    Object.defineProperty(wrap, 'clientHeight', { configurable: true, get: () => 0 })
    wrapper.findComponent({ name: 'Virtualizer' }).vm.$emit('resize')
    await nextTick()
    expect(wrapper.find('#back-to-top').exists()).toBe(false)
    // 空库不显示
    state.total = 0
    await nextTick()
    expect(wrapper.find('#back-to-top').exists()).toBe(false)
    // 虚拟化不可用不显示（ResizeObserver 缺失 → 不挂库）
    vi.stubGlobal('ResizeObserver', undefined)
    const noVirtual = await setupMainWindow(baseHandlers(items), [0, 9])
    wrappers.push(noVirtual.wrapper)
    scrollState.value = 5000
    document.getElementById('grid-wrap')?.dispatchEvent(new Event('scroll'))
    await nextTick()
    expect(noVirtual.wrapper.find('#back-to-top').exists()).toBe(false)
    expect(noVirtual.wrapper.find('.grid-foot').text()).toContain('当前环境不支持虚拟滚动')
  })

  it('backToTopIncludesFolderHeader', async () => {
    const items = () => makeRange(1, 200)
    const { wrapper, state, calls } = await setupMainWindow(baseHandlers(items), [0, 9])
    wrappers.push(wrapper)
    installGeometry()
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    // 当前分组为正 ID：网格顶部渲染 folder 头块，startMargin 含头块
    state.collections = [{ id: 1, name: '大分组', count: 2, children: [{ id: 2, name: '小分组', count: 1 }] }]
    state.activeCollection = 1
    await nextTick()
    await flush()
    expect(document.querySelector('.folder-grid')).not.toBeNull()
    await enableSortMode(wrapper)
    scrollState.value = 1300
    wrap.dispatchEvent(new Event('scroll'))
    await flush()
    const button = wrapper.find('#back-to-top')
    expect(button.exists()).toBe(true)
    expect(button.element.tagName).toBe('BUTTON')
    expect(button.attributes('title')).toBe('回到顶部')
    expect(button.attributes('aria-label')).toBe('回到顶部')
    expect(button.classes()).toContain('with-organize-bar')
    expect((button.element as HTMLButtonElement).disabled).toBe(false)
    state.selectedIds = new Set([1, 2])
    const pageCalls = calls.filter(call => call.method === 'search_memes').length
    await button.trigger('click')
    await flush()
    for (let i = 0; i < 3; i++) await stepAnimationFrame(16)
    // scrollTo(0) 而不是 scrollToIndex(0)：命中容器最顶部（含 folder 头块）
    expect(mockVirtua.scrollToCalls).toEqual([0])
    expect(mockVirtua.scrollToIndexCalls).toEqual([])
    expect(wrap.scrollTop).toBe(0)
    expect(state.selectedIds.size).toBe(2)
    expect(state.hi).toBe(200)
    expect(calls.filter(call => call.method === 'search_memes').length).toBe(pageCalls)
  })

  it('backToTopFallsBackWithoutHandle', async () => {
    const items = () => makeRange(1, 200)
    mockVirtua.hasHandle = false
    const { wrapper, state, calls } = await setupMainWindow(baseHandlers(items), [0, 9])
    wrappers.push(wrapper)
    installGeometry()
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    scrollState.value = 1300
    wrap.dispatchEvent(new Event('scroll'))
    await flush()
    expect(wrapper.find('#back-to-top').exists()).toBe(true)
    const pageCalls = calls.filter(call => call.method === 'search_memes').length
    // 滚动方法缺失/调用异常：只归零仍连接的 wrap，不发 search
    await wrapper.find('#back-to-top').trigger('click')
    await flush()
    expect(mockVirtua.scrollToCalls).toEqual([])
    expect(mockVirtua.scrollToIndexCalls).toEqual([])
    expect(wrap.scrollTop).toBe(0)
    expect(wrapper.find('#back-to-top').exists()).toBe(false)
    expect(calls.filter(call => call.method === 'search_memes').length).toBe(pageCalls)
    // 刷新复位滚动：按钮不残留
    scrollState.value = 1300
    wrap.dispatchEvent(new Event('scroll'))
    await flush()
    expect(wrapper.find('#back-to-top').exists()).toBe(true)
    ;(globalThis as unknown as { refreshMemes: () => void }).refreshMemes()
    await flush(8)
    expect(wrap.scrollTop).toBe(0)
    expect(wrapper.find('#back-to-top').exists()).toBe(false)
    expect(state.loadError).toBe(false)
  })

  it('gridActionsIgnoreLateSettlementAfterUnmountOrQuery', async () => {
    const total = 530
    let mode: 'fail' | 'hold' | 'ok' = 'fail'
    // 逐请求持有的队列：旧请求与新请求各自独立 resolve，模拟迟到结算
    const held: Array<Deferred<Meme[] | null>> = []
    const handlers: Record<string, BridgeHandler> = {
      ...baseHandlers(() => makeRange(1, 200)),
      count_memes: () => total,
      search_memes: (args) => {
        const offset = args[3] as number
        const limit = args[4] as number
        if (offset === 0) return makeRange(1, 200)
        if (offset === 200 || offset === 400) {
          if (mode === 'fail') return null
          if (mode === 'hold') {
            const wait = deferred<Meme[] | null>()
            held.push(wait)
            return wait.promise
          }
          return makeRange(offset + 1, 200)
        }
        return makeRange(offset + 1, Math.max(0, Math.min(limit, total - offset)))
      },
    }
    const { wrapper, state, model, calls } = await setupMainWindow(handlers, [0, 9])
    wrappers.push(wrapper)
    await expect(model.ensureRange(200, 400)).resolves.toBe(false)
    mode = 'hold'
    await wrapper.find('.grid-retry').trigger('click')
    await flush()
    expect(offsetCalls(calls, 200)).toBe(2)
    expect(held.length).toBe(1)
    // 新查询换代：本地 pending 复位，旧重放结算不得复活错误/按钮/需求
    ;(globalThis as unknown as { refreshMemes: () => void }).refreshMemes()
    await flush(8)
    expect(state.loadError).toBe(false)
    expect(wrapper.find('.grid-retry').exists()).toBe(false)
    // 新查询下再次失败并开始新一轮重试（挂起）：旧结算不得改动新重试的 pending/错误态
    mode = 'fail'
    await expect(model.ensureRange(200, 400)).resolves.toBe(false)
    expect(state.loadError).toBe(true)
    expect(offsetCalls(calls, 200)).toBe(3)
    mode = 'hold'
    await wrapper.find('.grid-retry').trigger('click')
    await flush()
    expect(offsetCalls(calls, 200)).toBe(4)
    expect(held.length).toBe(2)
    expect(wrapper.find('.grid-foot').text()).toContain('加载中')
    const settledCalls = calls.length
    held[0]?.resolve(null)
    await flush(8)
    await vi.advanceTimersByTimeAsync(10000)
    await flush()
    expect(calls.length).toBe(settledCalls)
    expect(state.loadError).toBe(true)
    expect(state.hi).toBe(200)
    expect(wrapper.find('.grid-foot').text()).toContain('加载中')
    // 新重试 resolve 后正常提交（旧结算未打断它）
    held[1]?.resolve(makeRange(201, 200))
    await flush(8)
    expect(state.hi).toBe(400)
    expect(state.loadError).toBe(false)
    expect(state.selectedIds.size).toBe(0)
    // 卸载时挂起的重试：结算不得新增请求
    mode = 'fail'
    await expect(model.ensureRange(400, 600)).resolves.toBe(false)
    expect(state.loadError).toBe(true)
    mode = 'hold'
    await wrapper.find('.grid-retry').trigger('click')
    await flush()
    expect(held.length).toBe(3)
    const beforeUnmount = calls.length
    wrapper.unmount()
    held[2]?.resolve(null)
    await flush(8)
    await vi.advanceTimersByTimeAsync(10000)
    await flush()
    expect(calls.length).toBe(beforeUnmount)
  })

  it('backToTopSupportsKeyboardFocus', async () => {
    const items = () => makeRange(1, 200)
    const { wrapper } = await setupMainWindow(baseHandlers(items), [0, 9])
    wrappers.push(wrapper)
    installGeometry()
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    const showButtonAt = async (top: number) => {
      scrollState.value = top
      wrap.dispatchEvent(new Event('scroll'))
      await nextTick()
    }
    await showButtonAt(1300)
    const button = wrapper.find('#back-to-top')
    expect(button.exists()).toBe(true)
    const el = button.element as HTMLButtonElement
    expect(el.tagName).toBe('BUTTON')
    expect(el.getAttribute('aria-label')).toBe('回到顶部')
    expect(el.disabled).toBe(false)
    expect(el.tabIndex).toBeGreaterThanOrEqual(0)
    // 原生 button 不重复绑键：keydown 本身不触发操作（浏览器 Enter 默认行为留人工）
    el.focus()
    expect(document.activeElement).toBe(el)
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await nextTick()
    expect(mockVirtua.scrollToCalls).toEqual([])
    // 点击后按钮消失：焦点从按钮交还网格
    await button.trigger('click')
    await nextTick()
    expect(wrapper.find('#back-to-top').exists()).toBe(false)
    expect((document.activeElement as HTMLElement | null)?.id).toBe('grid-wrap')
    // 其他控件焦点不被抢
    await showButtonAt(1300)
    const input = document.getElementById('search') as HTMLInputElement
    input.focus()
    expect(document.activeElement).toBe(input)
    await wrapper.find('#back-to-top').trigger('click')
    await nextTick()
    expect(wrapper.find('#back-to-top').exists()).toBe(false)
    expect(document.activeElement).toBe(input)
  })

  it('keepsTheMarqueeArmedWithoutBoxOrSelectionUntilThreshold', async () => {
    const items = () => makeRange(1, 40)
    const { wrapper, state } = await setupMainWindow(baseHandlers(items), [0, 9])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    installGeometry()
    const wrap = document.getElementById('grid-wrap') as HTMLElement
    state.selectedIds = new Set([7])
    // 起手仅 armed：不画框、不改选择
    wrap.dispatchEvent(pointerEvent('pointerdown', { clientX: 2, clientY: 96, buttons: 1 }))
    await nextTick()
    expect(document.querySelector('.marquee-overlay')).toBeNull()
    expect(sorted(state.selectedIds)).toEqual([7])
    // 8px 门槛内移动仍为 armed
    document.dispatchEvent(pointerEvent('pointermove', { clientX: 6, clientY: 100, buttons: 1 }))
    await nextTick()
    expect(document.querySelector('.marquee-overlay')).toBeNull()
    expect(sorted(state.selectedIds)).toEqual([7])
    // 抬起：结束会话但未激活，不吞掉随后 click
    document.dispatchEvent(pointerEvent('pointerup', { clientX: 6, clientY: 100, buttons: 0 }))
    await flush()
    expect(document.querySelector('.marquee-overlay')).toBeNull()
    expect(sorted(state.selectedIds)).toEqual([7])
    cardOf(1).dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(sorted(state.selectedIds)).toEqual([1, 7])
  })

  it('footerRetryDoesNotStealFocusMovedDuringRequest', async () => {
    const total = 530
    const pages = holdPage()
    let mode: 'fail' | 'hold' | 'ok' = 'fail'
    const { wrapper, state, model } = await setupMainWindow(failingPageHandlers(total, pages, () => mode), [0, 9])
    wrappers.push(wrapper)
    await expect(model.ensureRange(200, 400)).resolves.toBe(false)
    expect(state.loadError).toBe(true)
    const retry = wrapper.find('.grid-retry')
    const retryEl = retry.element as HTMLButtonElement
    retryEl.focus()
    expect(document.activeElement).toBe(retryEl)
    // 挂起期间用户把焦点移到搜索框：结算不得抢回网格
    mode = 'hold'
    await retry.trigger('click')
    await flush()
    const input = document.getElementById('search') as HTMLInputElement
    input.focus()
    expect(document.activeElement).toBe(input)
    pages.resolve(200, makeRange(201, 200))
    await flush(8)
    expect(state.loadError).toBe(false)
    expect(wrapper.find('.grid-retry').exists()).toBe(false)
    expect(document.activeElement).toBe(input)
    // 焦点未被移走时：成功结算仍把焦点从已消失的按钮交还网格
    mode = 'fail'
    await expect(model.ensureRange(400, 600)).resolves.toBe(false)
    expect(state.loadError).toBe(true)
    const retry2 = wrapper.find('.grid-retry')
    const retry2El = retry2.element as HTMLButtonElement
    retry2El.focus()
    expect(document.activeElement).toBe(retry2El)
    mode = 'hold'
    await retry2.trigger('click')
    await flush()
    pages.resolve(400, makeRange(401, 200))
    await flush(8)
    expect(wrapper.find('.grid-retry').exists()).toBe(false)
    expect((document.activeElement as HTMLElement | null)?.id).toBe('grid-wrap')
  })

  it('initFailureKeepsRetryEntryAndRecoversViaLoadInitData', async () => {
    const gate = deferred<unknown>()
    let mode: 'fail' | 'hold' = 'fail'
    const initPayload = () => ({
      memes: makeRange(1, 200),
      tags: ['标签A'],
      collections: [{ id: 1, name: '分组A', count: 3 }],
      show_startup_animation: false,
      startup_bg_color: '#101010',
    })
    const handlers: Record<string, BridgeHandler> = {
      ...baseHandlers(() => makeRange(1, 200)),
      get_init_data: () => (mode === 'fail' ? null : gate.promise),
    }
    const { wrapper, state, calls } = await setupMainWindow(handlers, [0, 9])
    wrappers.push(wrapper)
    // 三次初始化尝试全部失败
    await flush()
    await vi.advanceTimersByTimeAsync(500)
    await flush()
    await vi.advanceTimersByTimeAsync(1000)
    await flush()
    await vi.advanceTimersByTimeAsync(1500)
    await flush()
    expect(calls.filter(call => call.method === 'get_init_data').length).toBe(3)
    expect(state.loadError).toBe(true)
    // 后台流程完成但跳过 search：保留 init 重试入口（否则描述被清、入口消失）
    await flush(8)
    expect(calls.filter(call => call.method === 'search_memes').length).toBe(0)
    expect(calls.filter(call => call.method === 'count_memes').length).toBe(0)
    const retry = wrapper.find('.grid-retry')
    expect(retry.exists()).toBe(true)
    // 点击重试：走 loadInitData（而不是 seed 重放）；空库挂起期间也显示加载中
    mode = 'hold'
    await retry.trigger('click')
    await nextTick()
    expect(state.loadError).toBe(false)
    expect(wrapper.find('.grid-foot').text()).toContain('加载中')
    gate.resolve(initPayload())
    await flush(8)
    expect(calls.filter(call => call.method === 'get_init_data').length).toBe(4)
    expect(state.allTags).toEqual(['标签A'])
    expect(state.collections.length).toBe(1)
    expect(state.total).toBe(200)
    expect(state.hi).toBe(200)
    expect(state.loadError).toBe(false)
    expect(wrapper.find('.grid-foot').text()).toContain('共 200 项')
    expect(wrapper.find('.grid-retry').exists()).toBe(false)
  })
})
