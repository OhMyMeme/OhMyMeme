import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import type { Meme } from '../../src/ohmymeme/presentation/frontend/main/shared/types'

// MainWindow 虚拟网格接线桩：mock virtua 的行渲染窗口与 drag-select 组件，
// jsdom 无布局故手写元素矩形/尺寸；只驱动公开 DOM 事件验证：
// 非 0 可见起点坐标归一化、可见段置换仅写原绝对槽位、live-card 重挂访问当前节点、
// 越界松手不持久化、旧代次回滚不覆盖新数据。

const mockVirtua = vi.hoisted(() => ({ range: [0, 0] as [number, number] }))

vi.mock('virtua/vue', async () => {
  const { defineComponent, h } = await import('vue')
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
      setup(props: any, { slots, expose }: any) {
        expose({
          cache: null,
          scrollOffset: 0,
          scrollSize: 0,
          viewportSize: 0,
          findItemIndex(offset: number) {
            const size = Number(props.itemSize) || 1
            const total = (props.data as unknown[]).length
            if (!total) return 0
            return Math.max(0, Math.min(total - 1, Math.floor(offset / size)))
          },
          getItemOffset(index: number) {
            return index * (Number(props.itemSize) || 0)
          },
          getItemSize() {
            return Number(props.itemSize) || 0
          },
          scrollToIndex() {},
          scrollTo() {},
          scrollBy() {},
        })
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

const DragSelectStub = defineComponent({
  name: 'DragSelect',
  props: {
    modelValue: { default: undefined },
    disabled: Boolean,
    multiple: Boolean,
    clickOptionToSelect: Boolean,
    draggableOnOption: Boolean,
    clickBlankToClear: Boolean,
  },
  emits: ['update:modelValue'],
  setup(_props, { slots }) {
    return () => h('div', { class: 'drag-select' }, slots.default?.())
  },
})

const DragSelectOptionStub = defineComponent({
  name: 'DragSelectOption',
  props: { value: { default: undefined }, disabled: Boolean },
  setup(_props, { slots }) {
    return () => h('div', { class: 'drag-select-option' }, slots.default?.())
  },
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
    // 32ms 足以结算 Vue 过渡/RAF 链（leave 副本清理）；远小于 120ms registry 检查与 1s 重试
    await vi.advanceTimersByTimeAsync(32)
    await nextTick()
  }
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
  cardHeight: number
  rowPitch: number
  colPitch: number
  top: number
  rowTop: (index: number) => number
}

// jsdom 无布局：为 #grid-wrap / #meme-grid / 已挂载行与真卡写入可用矩形与尺寸
function installGeometry(): Geometry {
  const wrap = document.getElementById('grid-wrap') as HTMLElement
  const grid = document.getElementById('meme-grid') as HTMLElement
  const cols = Math.max(1, Number(grid.style.getPropertyValue('--meme-cols')) || 1)
  const cardHeight = Math.max(1, Math.round(parseFloat(grid.style.getPropertyValue('--meme-card-height')) || 140))
  const rowPitch = cardHeight + 10
  const colPitch = 112
  const top = 100
  Object.defineProperty(wrap, 'clientWidth', { configurable: true, get: () => 480 })
  Object.defineProperty(wrap, 'clientHeight', { configurable: true, get: () => 600 })
  wrap.getBoundingClientRect = () => fakeRect(0, 0, 480, 600)
  Object.defineProperty(grid, 'clientWidth', { configurable: true, get: () => 480 })
  grid.getBoundingClientRect = () => fakeRect(0, top, 480, 4000)
  for (const row of Array.from(grid.querySelectorAll<HTMLElement>('.virtual-meme-row'))) {
    const index = Math.max(0, Math.floor(Number(row.dataset.rowStart) / cols))
    row.getBoundingClientRect = () => fakeRect(0, top + index * rowPitch, 480, rowPitch)
    const cards = Array.from(row.querySelectorAll<HTMLElement>('.meme-card[data-meme-id]'))
    cards.forEach((card, col) => {
      card.getBoundingClientRect = () => fakeRect(col * colPitch, top + index * rowPitch, colPitch, cardHeight)
      Object.defineProperty(card, 'offsetWidth', { configurable: true, get: () => colPitch })
      Object.defineProperty(card, 'offsetHeight', { configurable: true, get: () => cardHeight })
    })
  }
  return { cardHeight, rowPitch, colPitch, top, rowTop: (index: number) => top + index * rowPitch }
}

function cardOf(id: number): HTMLElement {
  return document.querySelector<HTMLElement>(`#meme-grid .meme-card[data-meme-id="${id}"]`) as HTMLElement
}

function pointerEvent(type: string, init: Partial<MouseEventInit>): MouseEvent {
  return new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, ...init })
}

async function setupMainWindow(
  handlers: Record<string, BridgeHandler>,
  range: [number, number],
): Promise<{ wrapper: VueWrapper; state: any; calls: Call[] }> {
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
        components: {
          'drag-select': DragSelectStub,
          'drag-select-option': DragSelectOptionStub,
        },
        stubs: CHILD_STUBS,
      },
    },
  )
  // 启动流程：init 数据 → 300ms 降级后台（rescan → auto_sync → search）
  await vi.advanceTimersByTimeAsync(300)
  await flush()
  return { wrapper, state: model.state, calls }
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

const wrappers: VueWrapper[] = []

describe('MainWindow 虚拟网格接线', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    document.body.innerHTML = ''
    mockVirtua.range = [0, 0]
    ;(globalThis as any).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    // jsdom 无布局：挂载前就给出滚动容器/网格的可用尺寸（refreshLayout 首测即得 4 列）
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
      configurable: true,
      get(this: HTMLElement) {
        return this.id === 'grid-wrap' || this.id === 'meme-grid' ? 480 : 0
      },
    })
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get(this: HTMLElement) {
        return this.id === 'grid-wrap' ? 600 : 0
      },
    })
    if (typeof Element.prototype.scrollTo !== 'function') (Element.prototype as any).scrollTo = () => {}
    if (typeof Element.prototype.scrollBy !== 'function') (Element.prototype as any).scrollBy = () => {}
    if (typeof Element.prototype.setPointerCapture !== 'function') (Element.prototype as any).setPointerCapture = () => {}
    if (typeof Element.prototype.releasePointerCapture !== 'function') (Element.prototype as any).releasePointerCapture = () => {}
  })

  afterEach(() => {
    for (const wrapper of wrappers.splice(0)) wrapper.unmount()
    delete (globalThis as any).pywebview
    vi.useRealTimers()
  })

  // 切到整理模式（可排视图）后才能发起可见段拖拽
  async function enableSortMode(wrapper: VueWrapper) {
    const button = wrapper.find('button[title="整理模式"]')
    expect(button.exists()).toBe(true)
    await button.trigger('click')
    await nextTick()
  }

  it('normalizes pointers for a non-zero visible start and permutes only the mounted segment', async () => {
    const items = () => makeRange(1, 40)
    const { wrapper, state } = await setupMainWindow(baseHandlers(items), [1, 2])
    wrappers.push(wrapper)
    // 已加载窗口为整库，但只有行 1/2（槽位 4..11）被挂载
    expect(state.total).toBe(40)
    expect(state.lo).toBe(0)
    expect(state.hi).toBe(40)
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    const dragged = cardOf(5)
    expect(dragged).toBeTruthy()

    // pointerdown：段首行（行 1）第一张卡
    dragged.dispatchEvent(pointerEvent('pointerdown', {
      clientX: 56,
      clientY: geometry.rowTop(1) + 30,
      buttons: 1,
    }))
    // pointermove：段内第二行（行 2）第四列 → 挂载段局部索引 7
    document.dispatchEvent(pointerEvent('pointermove', {
      clientX: 392,
      clientY: geometry.rowTop(2) + geometry.rowPitch / 2,
      buttons: 1,
    }))
    await flush()

    // 可见段置换：仅 [4,12) 变化，且未越界（坐标已按 deltaY 归一化）
    expect(state.slots[3]?.id).toBe(4)
    expect(state.slots[4]?.id).toBe(6)
    expect(state.slots[10]?.id).toBe(12)
    expect(state.slots[11]?.id).toBe(5)
    expect(state.slots[12]?.id).toBe(13)
    expect(state.slots[39]?.id).toBe(40)
    expect(state.lo).toBe(0)
    expect(state.hi).toBe(40)

    // live-card：跨行重挂后写入当前节点，旧节点不再残留 dragging
    const draggingNodes = Array.from(document.querySelectorAll<HTMLElement>('#meme-grid .meme-card.dragging'))
    expect(draggingNodes.length).toBe(1)
    expect(draggingNodes[0]?.dataset.memeId).toBe('5')
    expect(draggingNodes[0]?.closest('.virtual-meme-row')?.dataset.rowStart).toBe('8')
    expect(draggingNodes[0]?.style.transform).not.toBe('')
  })

  it('rolls back without persisting when the pointer up lands outside the mounted segment', async () => {
    const items = () => makeRange(1, 40)
    const { wrapper, state, calls } = await setupMainWindow(baseHandlers(items), [0, 9])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    const dragged = cardOf(1)
    dragged.dispatchEvent(pointerEvent('pointerdown', {
      clientX: 56,
      clientY: geometry.rowTop(0) + 30,
      buttons: 1,
    }))
    // 段内换位生效：1 ↔ 2
    document.dispatchEvent(pointerEvent('pointermove', {
      clientX: 150,
      clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
      buttons: 1,
    }))
    await flush()
    expect(state.slots[0]?.id).toBe(2)
    expect(state.slots[1]?.id).toBe(1)
    // 越界松手：取消并回滚，禁止提交
    document.dispatchEvent(pointerEvent('pointerup', { clientX: 56, clientY: 0, buttons: 0 }))
    await flush()
    expect(calls.some(call => call.method === 'reorder_memes')).toBe(false)
    expect(state.slots[0]?.id).toBe(1)
    expect(state.slots[1]?.id).toBe(2)
    expect(document.querySelectorAll('#meme-grid .meme-card.dragging').length).toBe(0)
  })

  it('rejects a pointer up whose x leaves the grid columns', async () => {
    const items = () => makeRange(1, 40)
    const { wrapper, state, calls } = await setupMainWindow(baseHandlers(items), [0, 9])
    wrappers.push(wrapper)
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    const dragged = cardOf(1)
    dragged.dispatchEvent(pointerEvent('pointerdown', {
      clientX: 56,
      clientY: geometry.rowTop(0) + 30,
      buttons: 1,
    }))
    document.dispatchEvent(pointerEvent('pointermove', {
      clientX: 150,
      clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
      buttons: 1,
    }))
    await flush()
    expect(state.slots[0]?.id).toBe(2)
    expect(state.slots[1]?.id).toBe(1)
    // x 越出网格内容范围（480px）：y 合法也不提交，取消并回滚
    document.dispatchEvent(pointerEvent('pointerup', {
      clientX: 900,
      clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
      buttons: 0,
    }))
    await flush()
    expect(calls.some(call => call.method === 'reorder_memes')).toBe(false)
    expect(state.slots[0]?.id).toBe(1)
    expect(state.slots[1]?.id).toBe(2)
    expect(document.querySelectorAll('#meme-grid .meme-card.dragging').length).toBe(0)
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
    const dragged = cardOf(1)
    dragged.dispatchEvent(pointerEvent('pointerdown', {
      clientX: 56,
      clientY: geometry.rowTop(0) + 30,
      buttons: 1,
    }))
    document.dispatchEvent(pointerEvent('pointermove', {
      clientX: 150,
      clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
      buttons: 1,
    }))
    await flush()
    expect(state.slots[0]?.id).toBe(2)
    document.dispatchEvent(pointerEvent('pointerup', {
      clientX: 150,
      clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
      buttons: 0,
    }))
    await flush()
    expect(reorderCalls.length).toBe(1)
    const submitted = state.slots.slice(0, 4).map(record => record?.id)
    expect(submitted[0]).toBe(2)
    // 保存挂起期间再次按住移动：不得改动旧会话（显示顺序必须与已提交 ids 一致）
    document.dispatchEvent(pointerEvent('pointermove', {
      clientX: 380,
      clientY: geometry.rowTop(2) + geometry.rowPitch / 2,
      buttons: 1,
    }))
    await flush()
    expect(state.slots.slice(0, 4).map(record => record?.id)).toEqual(submitted)
    persist.resolve(true)
    await flush(8)
    expect(state.slots.slice(0, 4).map(record => record?.id)).toEqual(submitted)
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
    const { wrapper, state } = await setupMainWindow(handlers, [0, 9])
    wrappers.push(wrapper)
    expect(state.slots[0]?.id).toBe(1)
    await enableSortMode(wrapper)
    const geometry = installGeometry()
    const dragged = cardOf(1)
    dragged.dispatchEvent(pointerEvent('pointerdown', {
      clientX: 56,
      clientY: geometry.rowTop(0) + 30,
      buttons: 1,
    }))
    document.dispatchEvent(pointerEvent('pointermove', {
      clientX: 150,
      clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
      buttons: 1,
    }))
    await flush()
    expect(state.slots[0]?.id).toBe(2)
    // 松手触发表格保存（挂起）：提交的是整个连续缓存窗口顺序
    document.dispatchEvent(pointerEvent('pointerup', {
      clientX: 150,
      clientY: geometry.rowTop(0) + geometry.rowPitch / 2,
      buttons: 0,
    }))
    await flush()
    expect(reorderCalls.length).toBe(1)
    const firstReorder = reorderCalls[0] ?? []
    expect(firstReorder.length).toBe(40)
    expect(firstReorder[0]).toBe(2)
    // 保存期间发生新查询：新代次数据落地
    current = orderB
    ;(globalThis as unknown as { refreshMemes: () => void }).refreshMemes()
    await flush(8)
    expect(state.slots[0]?.id).toBe(101)
    // 保存结算：不得用旧快照覆盖新代次
    persist.resolve(true)
    await flush(8)
    expect(state.slots[0]?.id).toBe(101)
    expect(state.slots[4]?.id).toBe(105)
  })
})
