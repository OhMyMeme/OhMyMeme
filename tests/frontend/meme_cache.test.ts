import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Meme } from '../../src/ohmymeme/presentation/frontend/main/shared/types'
import type { useMemes as UseMemesFactory } from '../../src/ohmymeme/presentation/frontend/main/features/memes/useMemes'

// 纯缓存逻辑测试：mock 桥接 api/bridgeReady，模块级 state 经 vi.resetModules 隔离
vi.mock('../../src/ohmymeme/presentation/frontend/main/shared/bridge', () => ({
  api: vi.fn(async () => null),
  bridgeReady: vi.fn(() => true),
}))

type Model = ReturnType<typeof UseMemesFactory>
type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void }
type Handler = (args: unknown[]) => unknown
type Call = { name: string; args: unknown[] }
type BridgeStub = {
  api: { mockImplementation: (impl: (method: string, ...args: unknown[]) => unknown) => void }
}

function deferred<T>(): Deferred<T> {
  let resolve: (value: T) => void = () => {}
  const promise = new Promise<T>(r => { resolve = r })
  return { promise, resolve }
}

function makeMeme(id: number): Meme {
  return {
    id,
    filename: `meme-${id}.png`,
    name: `meme ${id}`,
    file_hash: `hash-${id}`,
    width: 16,
    height: 16,
    mime_type: 'image/png',
  }
}

function makeRange(startId: number, count: number): Meme[] {
  return Array.from({ length: count }, (_, index) => makeMeme(startId + index))
}

// 自动分页响应：按 offset/limit 从总数切片（id = 槽位序号 + 1）
function autoPage(total: () => number) {
  return (args: unknown[]): Meme[] => {
    const offset = args[3] as number
    const limit = args[4] as number
    const count = Math.max(0, Math.min(limit, total() - offset))
    return makeRange(offset + 1, count)
  }
}

// 手动分页响应：按 offset 挂起；resolve 后条目删除，下次请求重新武装
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

// 每个用例重新载入模块：mock 与 useMemes 均取自同一模块图
async function loadModel(handlers: Record<string, Handler>): Promise<{ model: Model; calls: Call[] }> {
  vi.resetModules()
  const bridge = (await import('../../src/ohmymeme/presentation/frontend/main/shared/bridge')) as unknown as BridgeStub
  const mod = await import('../../src/ohmymeme/presentation/frontend/main/features/memes/useMemes')
  const calls: Call[] = []
  bridge.api.mockImplementation(async (name: string, ...args: unknown[]) => {
    calls.push({ name, args })
    const handler = handlers[name]
    if (!handler) throw new Error(`unexpected bridge call: ${name}`)
    return await handler(args)
  })
  return { model: mod.useMemes(), calls }
}

// 分页请求的 offset 调用计数
function offsetCalls(calls: Call[], offset: number): number {
  return calls.filter(call => call.name === 'search_memes' && call.args[3] === offset).length
}

// 刷新已排队的微任务与 0ms 计时器
async function flush(rounds = 3): Promise<void> {
  for (let i = 0; i < rounds; i++) {
    await vi.advanceTimersByTimeAsync(0)
    await Promise.resolve()
  }
}

describe('useMemes 连续缓存模型', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('searchSeedsFirstChunk', async () => {
    const total = () => 530
    const { model, calls } = await loadModel({ count_memes: total, search_memes: autoPage(total) })
    model.state.selectedIds = new Set([5])
    await expect(model.search()).resolves.toBe(true)
    expect(model.state.total).toBe(530)
    expect(model.state.slots.length).toBe(530)
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(200)
    expect(model.state.slots[0]?.id).toBe(1)
    expect(model.state.slots[199]?.id).toBe(200)
    expect(model.state.slots[200]).toBeUndefined()
    expect(model.state.slots[529]).toBeUndefined()
    expect(model.state.selectedIds.size).toBe(0)
    expect(model.state.loading).toBe(false)
    expect(calls.filter(call => call.name === 'search_memes').length).toBe(1)
  })

  it('ensureRangeReusesCachedChunk', async () => {
    const total = () => 530
    const { model, calls } = await loadModel({ count_memes: total, search_memes: autoPage(total) })
    await model.search()
    const before = model.state.slots[100]
    const callsBefore = calls.length
    await expect(model.ensureRange(30, 70)).resolves.toBe(true)
    expect(calls.length).toBe(callsBefore)
    expect(model.state.slots[100]).toBe(before)
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(200)
  })

  it('ensureRangeAlignsChunks', async () => {
    const total = () => 530
    const { model, calls } = await loadModel({ count_memes: total, search_memes: autoPage(total) })
    await model.search()
    const before = calls.length
    await model.ensureRange(199, 401)
    expect(calls.slice(before).map(call => [call.args[3], call.args[4]])).toEqual([
      [200, 200],
      [400, 200],
    ])
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(530)
    expect(model.state.slots[199]?.id).toBe(200)
    expect(model.state.slots[200]?.id).toBe(201)
    expect(model.state.slots[400]?.id).toBe(401)
    expect(model.state.slots[529]?.id).toBe(530)
  })

  it('ensureRangeExtendsBothEdges', async () => {
    const total = () => 3000
    const { model } = await loadModel({ count_memes: total, search_memes: autoPage(total) })
    await model.search()
    await model.ensureRange(400, 800, 'jump')
    expect(model.state.lo).toBe(400)
    expect(model.state.hi).toBe(800)
    const kept = model.state.slots[500]
    await model.ensureRange(200, 1000)
    expect(model.state.lo).toBe(200)
    expect(model.state.hi).toBe(1000)
    expect(model.state.slots[500]).toBe(kept)
    expect(model.state.slots.slice(200, 1000).every(record => record !== undefined)).toBe(true)
    expect(model.state.slots[199]).toBeUndefined()
    expect(model.state.slots[1000]).toBeUndefined()
  })

  it('ensureRangeDeduplicatesInflight', async () => {
    const total = () => 5000
    const pages = holdPage()
    const { model, calls } = await loadModel({
      count_memes: total,
      search_memes: args => (args[3] === 0 ? autoPage(total)(args) : pages.handler(args)),
    })
    await model.search()
    const first = model.ensureRange(0, 1000)
    const second = model.ensureRange(0, 600)
    expect(offsetCalls(calls, 200)).toBe(1)
    expect(offsetCalls(calls, 400)).toBe(1)
    expect(offsetCalls(calls, 600)).toBe(1)
    expect(offsetCalls(calls, 800)).toBe(1)
    pages.resolve(200, makeRange(201, 200))
    pages.resolve(400, makeRange(401, 200))
    await flush()
    expect(model.state.slots[200]).toBeUndefined()
    pages.resolve(600, makeRange(601, 200))
    pages.resolve(800, makeRange(801, 200))
    await expect(first).resolves.toBe(true)
    await expect(second).resolves.toBe(true)
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(1000)
  })

  it('trimForwardDropsHeadChunks', async () => {
    const total = () => 5000
    const { model } = await loadModel({ count_memes: total, search_memes: autoPage(total) })
    await model.search()
    await model.ensureRange(0, 2000)
    expect(model.state.hi).toBe(2000)
    model.state.selectedIds = new Set([1, 1999])
    const kept = model.state.slots[500]
    await model.ensureRange(2000, 2200, 'forward')
    expect(model.state.lo).toBe(200)
    expect(model.state.hi).toBe(2200)
    expect(model.state.hi - model.state.lo).toBe(2000)
    expect(model.state.slots.length).toBe(5000)
    expect(model.state.slots[0]).toBeUndefined()
    expect(model.state.slots[199]).toBeUndefined()
    expect(model.state.slots[200]).toBeDefined()
    expect(model.state.slots[2199]).toBeDefined()
    expect(model.state.slots[2200]).toBeUndefined()
    expect(model.state.slots[500]).toBe(kept)
    expect(model.state.selectedIds.size).toBe(2)
    expect(model.state.selectedIds.has(1)).toBe(true)
  })

  it('trimBackwardDropsTailChunks', async () => {
    const total = () => 5000
    const { model } = await loadModel({ count_memes: total, search_memes: autoPage(total) })
    await model.search()
    await model.ensureRange(2000, 4000, 'jump')
    expect(model.state.lo).toBe(2000)
    expect(model.state.hi).toBe(4000)
    const kept = model.state.slots[3000]
    await model.ensureRange(1800, 2000, 'backward')
    expect(model.state.lo).toBe(1800)
    expect(model.state.hi).toBe(3800)
    expect(model.state.hi - model.state.lo).toBe(2000)
    expect(model.state.slots[3799]).toBeDefined()
    expect(model.state.slots[3800]).toBeUndefined()
    expect(model.state.slots[1800]).toBeDefined()
    expect(model.state.slots[1799]).toBeUndefined()
    expect(model.state.slots[3000]).toBe(kept)
  })

  it('ensureRangeJumpsWithoutWalkingIntermediatePages', async () => {
    const total = () => 9000
    const { model, calls } = await loadModel({ count_memes: total, search_memes: autoPage(total) })
    await model.search()
    const before = calls.length
    await model.ensureRange(8000, 8400, 'jump')
    expect(calls.slice(before).map(call => call.args[3])).toEqual([8000, 8200])
    expect(model.state.lo).toBe(8000)
    expect(model.state.hi).toBe(8400)
    expect(model.state.rangeGen).toBeGreaterThan(1)
    expect(model.state.slots[0]).toBeUndefined()
    expect(model.state.slots[7999]).toBeUndefined()
    expect(model.state.slots[8000]?.id).toBe(8001)
    expect(model.state.slots[8399]?.id).toBe(8400)
    expect(model.state.slots[8400]).toBeUndefined()
  })

  it('failedJumpRetainsCommittedWindow', async () => {
    const total = () => 9000
    const pages = holdPage()
    let mode: 'fail' | 'ok' = 'fail'
    const { model, calls } = await loadModel({
      count_memes: total,
      search_memes: args => {
        const offset = args[3] as number
        if (offset === 0) return autoPage(total)(args)
        return mode === 'fail' ? null : pages.handler(args)
      },
    })
    await model.search()
    const kept = model.state.slots[0]
    await expect(model.ensureRange(8000, 8400, 'jump')).resolves.toBe(false)
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(200)
    expect(model.state.slots[0]).toBe(kept)
    expect(model.state.slots[8000]).toBeUndefined()
    expect(model.state.loadError).toBe(true)
    expect(offsetCalls(calls, 8000)).toBe(1)
    mode = 'ok'
    await vi.advanceTimersByTimeAsync(1000)
    await flush()
    expect(offsetCalls(calls, 8000)).toBe(2)
    pages.resolve(8000, makeRange(8001, 200))
    pages.resolve(8200, makeRange(8201, 200))
    await flush()
    expect(model.state.lo).toBe(8000)
    expect(model.state.hi).toBe(8400)
    expect(model.state.loadError).toBe(false)
  })

  it('outOfOrderPagesNeverCommitHoles', async () => {
    const total = () => 9000
    const pages = holdPage()
    const { model } = await loadModel({
      count_memes: total,
      search_memes: args => (args[3] === 0 ? autoPage(total)(args) : pages.handler(args)),
    })
    await model.search()
    const pending = model.ensureRange(0, 1000)
    pages.resolve(400, makeRange(401, 200))
    await flush()
    expect(model.state.slots[400]).toBeUndefined()
    expect(model.state.slots[200]).toBeUndefined()
    pages.resolve(200, null)
    pages.resolve(600, makeRange(601, 200))
    pages.resolve(800, makeRange(801, 200))
    await expect(pending).resolves.toBe(false)
    expect(model.state.hi).toBe(200)
    expect(model.state.slots.slice(200, 1000).every(record => record === undefined)).toBe(true)
    await vi.advanceTimersByTimeAsync(1000)
    await flush()
    pages.resolve(200, makeRange(201, 200))
    pages.resolve(400, makeRange(401, 200))
    pages.resolve(600, makeRange(601, 200))
    pages.resolve(800, makeRange(801, 200))
    await flush()
    expect(model.state.hi).toBe(1000)
    expect(model.state.slots.slice(0, 1000).every(record => record !== undefined)).toBe(true)
  })

  it('loadedSlicePreservesAbsoluteStart', async () => {
    const total = () => 3000
    const { model } = await loadModel({ count_memes: total, search_memes: autoPage(total) })
    await model.search()
    await model.ensureRange(400, 800, 'jump')
    const slice = model.loadedSlice()
    expect(slice.start).toBe(400)
    expect(slice.items.length).toBe(400)
    expect(slice.items[0]?.id).toBe(401)
    expect(slice.items[399]?.id).toBe(800)
  })

  it('setLoadedSliceOnlyPermutesCurrentIds', async () => {
    const total = () => 3000
    const { model } = await loadModel({ count_memes: total, search_memes: autoPage(total) })
    await model.search()
    await model.ensureRange(400, 800, 'jump')
    const original = model.loadedSlice().items
    expect(model.setLoadedSlice(400, [...original].reverse())).toBe(true)
    expect(model.state.slots[400]?.id).toBe(800)
    expect(model.state.slots[799]?.id).toBe(401)
    expect(model.state.lo).toBe(400)
    expect(model.state.hi).toBe(800)
    expect(model.state.total).toBe(3000)
    expect(model.setLoadedSlice(399, original)).toBe(false)
    const foreign = [...original]
    foreign[0] = makeMeme(999999)
    expect(model.setLoadedSlice(400, foreign)).toBe(false)
    const duplicated = [...original]
    duplicated[1] = duplicated[0] as Meme
    expect(model.setLoadedSlice(400, duplicated)).toBe(false)
    expect(model.setLoadedSlice(400, original.slice(0, 399))).toBe(false)
    expect(model.state.slots[400]?.id).toBe(800)
    expect(model.state.slots[799]?.id).toBe(401)
  })

  it('queryChangeDiscardsStaleResults', async () => {
    const countA = deferred<number | null>()
    const pageA = deferred<Meme[] | null>()
    const countB = deferred<number | null>()
    const pageB = deferred<Meme[] | null>()
    const { model } = await loadModel({
      count_memes: args => (args[0] === '' ? countA.promise : countB.promise),
      search_memes: args => (args[0] === '' ? pageA.promise : pageB.promise),
    })
    const searchA = model.search()
    model.setSearch('b')
    const searchB = model.search()
    expect(model.state.loading).toBe(true)
    countA.resolve(530)
    pageA.resolve(makeRange(1, 200))
    await flush()
    expect(model.state.total).toBe(0)
    expect(model.state.slots.length).toBe(0)
    expect(model.state.loading).toBe(true)
    countB.resolve(3)
    pageB.resolve(makeRange(1, 3))
    await expect(searchB).resolves.toBe(true)
    await expect(searchA).resolves.toBe(true)
    expect(model.state.total).toBe(3)
    expect(model.state.slots.length).toBe(3)
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(3)
    expect(model.state.loading).toBe(false)
  })

  it('latestJumpWins', async () => {
    const total = () => 9000
    const pages = holdPage()
    const { model } = await loadModel({
      count_memes: total,
      search_memes: args => (args[3] === 0 ? autoPage(total)(args) : pages.handler(args)),
    })
    await model.search()
    const first = model.ensureRange(400, 800)
    const second = model.ensureRange(8000, 8400)
    pages.resolve(400, makeRange(401, 200))
    pages.resolve(600, makeRange(601, 200))
    await flush()
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(200)
    expect(model.state.rangeLoading).toBe(true)
    await expect(first).resolves.toBe(false)
    pages.resolve(8000, makeRange(8001, 200))
    pages.resolve(8200, makeRange(8201, 200))
    await expect(second).resolves.toBe(true)
    expect(model.state.lo).toBe(8000)
    expect(model.state.hi).toBe(8400)
    expect(model.state.rangeLoading).toBe(false)
  })

  it('mergedJumpKeepsCommittedPagesDense', async () => {
    const total = () => 3000
    const pages = holdPage()
    let hold = false
    const { model } = await loadModel({
      count_memes: total,
      search_memes: args => {
        const offset = args[3] as number
        if (offset === 0) return autoPage(total)(args)
        return hold ? pages.handler(args) : autoPage(total)(args)
      },
    })
    await model.search()
    await model.ensureRange(400, 800, 'jump')
    expect(model.state.lo).toBe(400)
    expect(model.state.hi).toBe(800)
    // 挂起远跳 [1000,1200) 后再请求 [200,1000)：合并后必须按扩展提交，旧页 2/3 保留
    hold = true
    const jump = model.ensureRange(1000, 1200, 'jump')
    const merged = model.ensureRange(200, 1000)
    pages.resolve(200, makeRange(201, 200))
    pages.resolve(800, makeRange(801, 200))
    pages.resolve(1000, makeRange(1001, 200))
    await expect(merged).resolves.toBe(true)
    await expect(jump).resolves.toBe(true)
    expect(model.state.lo).toBe(200)
    expect(model.state.hi).toBe(1200)
    expect(model.state.hi - model.state.lo).toBe(1000)
    // 密集连续：不得在旧页 2/3 处出现孔洞
    expect(model.state.slots.slice(200, 1200).every(record => record !== undefined)).toBe(true)
    expect(model.state.slots[600]?.id).toBe(601)
    expect(model.state.slots[1000]?.id).toBe(1001)
  })

  it('cachedRangeSupersedesStaleJump', async () => {
    const total = () => 9000
    const pages = holdPage()
    const { model } = await loadModel({
      count_memes: total,
      search_memes: args => (args[3] === 0 ? autoPage(total)(args) : pages.handler(args)),
    })
    await model.search()
    const jump = model.ensureRange(8000, 8400, 'jump')
    // 已缓存范围命中也属于最新需求：不得让旧远跳随后接管窗口
    await expect(model.ensureRange(0, 200)).resolves.toBe(true)
    pages.resolve(8000, makeRange(8001, 200))
    pages.resolve(8200, makeRange(8201, 200))
    await flush()
    await expect(jump).resolves.toBe(false)
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(200)
    expect(model.state.slots[8000]).toBeUndefined()
  })

  it('cachedRangeCancelsPendingJumpRetry', async () => {
    const total = () => 9000
    const pages = holdPage()
    let mode: 'fail' | 'ok' = 'fail'
    const { model, calls } = await loadModel({
      count_memes: total,
      search_memes: args => {
        const offset = args[3] as number
        if (offset === 0) return autoPage(total)(args)
        return mode === 'fail' ? null : pages.handler(args)
      },
    })
    await model.search()
    // 远跳整批失败：需求结算进入 1s 退避重试（旧窗口保留）
    await expect(model.ensureRange(8000, 8400, 'jump')).resolves.toBe(false)
    expect(model.state.loadError).toBe(true)
    expect(offsetCalls(calls, 8000)).toBe(1)
    expect(offsetCalls(calls, 8200)).toBe(1)
    // 退避未到期前回到已缓存区：命中即最新权威，必须撤销旧远跳与重试计时
    await expect(model.ensureRange(0, 200)).resolves.toBe(true)
    expect(model.state.loadError).toBe(false)
    mode = 'ok'
    await vi.advanceTimersByTimeAsync(5000)
    await flush()
    // 旧远跳的退避重放不得再发请求，也不得延迟接管窗口
    expect(offsetCalls(calls, 8000)).toBe(1)
    expect(offsetCalls(calls, 8200)).toBe(1)
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(200)
    expect(model.state.slots[8000]).toBeUndefined()
    expect(model.state.rangeLoading).toBe(false)
  })

  it('retriesAreBoundedAndGenerationScoped', async () => {
    const total = () => 530
    let mode: 'fail' | 'ok' = 'fail'
    const { model, calls } = await loadModel({
      count_memes: args => (args[0] === 'q' ? 300 : total()),
      search_memes: args => {
        const offset = args[3] as number
        if (args[0] === 'q') return offset === 0 ? makeRange(1, 200) : makeRange(offset + 1, 0)
        if (offset === 0) return autoPage(total)(args)
        if (offset === 200) return mode === 'fail' ? null : makeRange(201, 200)
        return autoPage(total)(args)
      },
    })
    await model.search()
    const genBefore = model.state.queryGen
    await expect(model.ensureRange(200, 400)).resolves.toBe(false)
    expect(model.state.loadError).toBe(true)
    expect(offsetCalls(calls, 200)).toBe(1)
    await vi.advanceTimersByTimeAsync(999)
    await flush()
    expect(offsetCalls(calls, 200)).toBe(1)
    await vi.advanceTimersByTimeAsync(1)
    await flush()
    expect(offsetCalls(calls, 200)).toBe(2)
    await vi.advanceTimersByTimeAsync(1999)
    await flush()
    expect(offsetCalls(calls, 200)).toBe(2)
    await vi.advanceTimersByTimeAsync(1)
    await flush()
    expect(offsetCalls(calls, 200)).toBe(3)
    await vi.advanceTimersByTimeAsync(2999)
    await flush()
    expect(offsetCalls(calls, 200)).toBe(3)
    await vi.advanceTimersByTimeAsync(1)
    await flush()
    expect(offsetCalls(calls, 200)).toBe(4)
    await vi.advanceTimersByTimeAsync(10000)
    await flush()
    expect(offsetCalls(calls, 200)).toBe(4)
    expect(model.state.loadError).toBe(true)
    expect(model.state.queryGen).toBe(genBefore)
    expect(calls.filter(call => call.name === 'count_memes').length).toBe(1)
    await expect(model.ensureRange(200, 400)).resolves.toBe(false)
    expect(offsetCalls(calls, 200)).toBe(5)
    model.setSearch('q')
    await model.search()
    const afterSearch = offsetCalls(calls, 200)
    await vi.advanceTimersByTimeAsync(10000)
    await flush()
    expect(offsetCalls(calls, 200)).toBe(afterSearch)
    expect(model.state.total).toBe(300)
  })

  it('retryRangeReplaysLastFailure', async () => {
    const total = () => 530
    let mode: 'fail' | 'ok' = 'fail'
    const { model, calls } = await loadModel({
      count_memes: total,
      search_memes: args => {
        const offset = args[3] as number
        if (offset === 0) return autoPage(total)(args)
        if (offset === 200) return mode === 'fail' ? null : makeRange(201, 200)
        return autoPage(total)(args)
      },
    })
    await model.search()
    await expect(model.ensureRange(200, 400)).resolves.toBe(false)
    expect(offsetCalls(calls, 200)).toBe(1)
    mode = 'ok'
    await expect(model.retryRange()).resolves.toBe(true)
    expect(offsetCalls(calls, 200)).toBe(2)
    expect(model.state.hi).toBe(400)
    expect(model.state.loadError).toBe(false)
  })

  it('totalChangeResetsOffsetGeneration', async () => {
    let backendTotal = 530
    const pages = holdPage()
    const { model, calls } = await loadModel({
      count_memes: () => backendTotal,
      search_memes: args => {
        const offset = args[3] as number
        return offset === 0 ? autoPage(() => backendTotal)(args) : pages.handler(args)
      },
    })
    await model.search()
    const pending = model.ensureRange(0, 600)
    pages.resolve(200, makeRange(201, 200))
    pages.resolve(400, makeRange(401, 30))
    await expect(pending).resolves.toBe(false)
    expect(model.state.hi).toBe(200)
    expect(model.state.slots[200]).toBeUndefined()
    expect(model.state.slots[400]).toBeUndefined()
    expect(model.state.loadError).toBe(true)
    expect(calls.filter(call => call.name === 'count_memes').length).toBe(1)
    backendTotal = 430
    await vi.advanceTimersByTimeAsync(1000)
    await flush()
    expect(calls.filter(call => call.name === 'count_memes').length).toBe(2)
    pages.resolve(200, makeRange(201, 200))
    pages.resolve(400, makeRange(401, 30))
    await flush()
    expect(model.state.total).toBe(430)
    expect(model.state.slots.length).toBe(430)
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(430)
    expect(model.state.slots[200]?.id).toBe(201)
    expect(model.state.slots[429]?.id).toBe(430)
    expect(model.state.slots.slice(0, 430).every(record => record !== undefined)).toBe(true)
    expect(offsetCalls(calls, 400)).toBe(2)
    // total 变化后旧窗口全部作废：第 0 页也按新偏移代次重取（不再复用旧前缀）
    expect(offsetCalls(calls, 0)).toBe(2)
    backendTotal = 1000
    await model.search()
    expect(model.state.total).toBe(1000)
    expect(model.state.slots.length).toBe(1000)
    expect(model.state.slots[200]).toBeUndefined()
    backendTotal = 450
    await model.search()
    expect(model.state.slots.length).toBe(450)
    // 该段分页按 offset 挂起：先保存 Promise，手动释放两页后再等待（避免未 resolve 的 await 挂起）
    const tail = model.ensureRange(200, 450)
    pages.resolve(200, makeRange(201, 200))
    pages.resolve(400, makeRange(401, 50))
    await expect(tail).resolves.toBe(true)
    expect(model.state.hi).toBe(450)
    expect(model.state.hi).toBe(model.state.total)
    expect(model.state.slots[449]?.id).toBe(450)
    backendTotal = 0
    await model.search()
    expect(model.state.total).toBe(0)
    expect(model.state.slots.length).toBe(0)
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(0)
    const callsBefore = calls.length
    await expect(model.ensureRange(0, 200)).resolves.toBe(true)
    expect(calls.length).toBe(callsBefore)
  })

  it('invalidRangesAreNoop', async () => {
    let backendTotal = 530
    const { model, calls } = await loadModel({
      count_memes: () => backendTotal,
      search_memes: args => autoPage(() => backendTotal)(args),
    })
    await model.search()
    const kept = model.state.slots[100]
    const pageCalls = calls.filter(call => call.name === 'search_memes').length
    await expect(model.ensureRange(Number.NaN, 100)).resolves.toBe(true)
    await expect(model.ensureRange(400, 200)).resolves.toBe(true)
    await expect(model.ensureRange(200, 200)).resolves.toBe(true)
    await expect(model.ensureRange(Number.POSITIVE_INFINITY, 300)).resolves.toBe(true)
    await expect(model.ensureRange(600, 800)).resolves.toBe(true)
    await expect(model.ensureRange(-50, 50)).resolves.toBe(true)
    expect(calls.filter(call => call.name === 'search_memes').length).toBe(pageCalls)
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(200)
    expect(model.state.slots[100]).toBe(kept)
    backendTotal = 0
    await model.search()
    const emptyCalls = calls.length
    await expect(model.ensureRange(0, 200)).resolves.toBe(true)
    expect(calls.length).toBe(emptyCalls)
  })

  it('selectAllSurvivesEvictionButNotQueryChange', async () => {
    const total = () => 5000
    const late = deferred<Meme[] | null>()
    const { model } = await loadModel({
      count_memes: args => (args[0] === 'y' ? 10 : total()),
      search_memes: args => {
        const offset = args[3] as number
        if (args[4] === 999999) return args[0] === 'x' ? late.promise : makeRange(1, 5000)
        if (args[0] === 'y') return offset === 0 ? makeRange(1, 10) : makeRange(offset + 1, 0)
        return autoPage(total)(args)
      },
    })
    await model.search()
    await model.ensureRange(0, 2000)
    await expect(model.selectAll()).resolves.toBe(true)
    expect(model.state.selectedIds.size).toBe(5000)
    expect(model.state.slots[2000]).toBeUndefined()
    await model.ensureRange(2000, 2200, 'forward')
    expect(model.state.lo).toBe(200)
    expect(model.state.selectedIds.size).toBe(5000)
    expect(model.state.selectedIds.has(1)).toBe(true)
    model.setSearch('x')
    const stale = model.selectAll()
    model.setSearch('y')
    await model.search()
    expect(model.state.selectedIds.size).toBe(0)
    late.resolve(makeRange(1, 10))
    await expect(stale).resolves.toBe(false)
    expect(model.state.selectedIds.size).toBe(0)
  })

  it('disposeInvalidatesRequestsAndTimers', async () => {
    const total = () => 530
    let mode: 'fail' | 'hold' = 'fail'
    const pages = holdPage()
    const { model, calls } = await loadModel({
      count_memes: total,
      search_memes: args => {
        const offset = args[3] as number
        if (offset === 0) return autoPage(total)(args)
        return mode === 'fail' ? null : pages.handler(args)
      },
    })
    await model.search()
    await expect(model.ensureRange(200, 400)).resolves.toBe(false)
    expect(offsetCalls(calls, 200)).toBe(1)
    model.dispose()
    await vi.advanceTimersByTimeAsync(5000)
    await flush()
    expect(offsetCalls(calls, 200)).toBe(1)
    expect(model.state.hi).toBe(200)
    mode = 'hold'
    await model.search()
    expect(model.state.hi).toBe(200)
    const pending = model.ensureRange(0, 600)
    expect(offsetCalls(calls, 200)).toBe(2)
    model.dispose()
    pages.resolve(200, makeRange(201, 200))
    pages.resolve(400, makeRange(401, 200))
    await flush()
    await vi.advanceTimersByTimeAsync(5000)
    await flush()
    expect(model.state.hi).toBe(200)
    expect(model.state.slots[200]).toBeUndefined()
    expect(offsetCalls(calls, 200)).toBe(2)
    expect(model.state.rangeLoading).toBe(false)
    await expect(pending).resolves.toBe(false)
  })

  it('pinDefersWindowCommitUntilRelease', async () => {
    const total = () => 9000
    const pages = holdPage()
    const { model } = await loadModel({
      count_memes: args => (args[0] === 'x' ? 300 : total()),
      search_memes: args => {
        if (args[0] === 'x') return args[3] === 0 ? makeRange(1, 200) : makeRange((args[3] as number) + 1, 0)
        const offset = args[3] as number
        if (offset === 2000 || offset === 8000 || offset === 8200) return pages.handler(args)
        return autoPage(total)(args)
      },
    })
    await model.search()
    await model.ensureRange(0, 2000)
    expect(model.state.hi).toBe(2000)
    const release = model.pinLoadedRange()
    const pinned = model.ensureRange(2000, 2200, 'forward')
    pages.resolve(2000, makeRange(2001, 200))
    await expect(pinned).resolves.toBe(true)
    await flush()
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(2000)
    expect(model.state.slots[2000]).toBeUndefined()
    release()
    expect(model.state.lo).toBe(200)
    expect(model.state.hi).toBe(2200)
    expect(model.state.slots[2000]?.id).toBe(2001)
    release()
    expect(model.state.lo).toBe(200)
    expect(model.state.hi).toBe(2200)
    const release2 = model.pinLoadedRange()
    const pinnedJump = model.ensureRange(8000, 8400)
    pages.resolve(8000, makeRange(8001, 200))
    pages.resolve(8200, makeRange(8201, 200))
    await expect(pinnedJump).resolves.toBe(true)
    model.setSearch('x')
    await model.search()
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(200)
    release2()
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(200)
    expect(model.state.slots[8000]).toBeUndefined()
  })

  it('extensionPinCommitsAdjacentPagesWithoutTrim', async () => {
    const total = () => 9000
    const { model } = await loadModel({ count_memes: total, search_memes: autoPage(total) })
    await model.search()
    await model.ensureRange(400, 2400, 'jump')
    expect(model.state.lo).toBe(400)
    expect(model.state.hi).toBe(2400)
    const release = model.pinLoadedRange({ allowExtension: true })
    const slice = model.loadedSlice()
    expect(slice.start).toBe(400)
    expect(slice.items.length).toBe(2000)
    // 模拟拖拽预览：窗口首项移到末尾，扩展提交必须保留预览后的旧记录
    const preview = [...slice.items.slice(1), slice.items[0] as Meme]
    expect(model.setLoadedSlice(400, preview)).toBe(true)
    expect(model.state.slots[400]?.id).toBe(402)
    expect(model.state.slots[2399]?.id).toBe(401)
    // 向后补一页：扩展 pin 下立即提交且不裁剪
    await expect(model.ensureRange(2400, 2600, 'forward')).resolves.toBe(true)
    expect(model.state.lo).toBe(400)
    expect(model.state.hi).toBe(2600)
    expect(model.state.slots[2400]?.id).toBe(2401)
    expect(model.state.slots[2599]?.id).toBe(2600)
    // 向前补一页：保留拖过路径与预览置换，窗口密集增长到 2400
    await expect(model.ensureRange(200, 400, 'backward')).resolves.toBe(true)
    expect(model.state.lo).toBe(200)
    expect(model.state.hi).toBe(2600)
    expect(model.state.hi - model.state.lo).toBe(2400)
    expect(model.state.slots[200]?.id).toBe(201)
    expect(model.state.slots[399]?.id).toBe(400)
    expect(model.state.slots[400]?.id).toBe(402)
    expect(model.state.slots[2398]?.id).toBe(2400)
    expect(model.state.slots[2399]?.id).toBe(401)
    expect(model.state.slots[2400]?.id).toBe(2401)
    expect(model.state.slots[2599]?.id).toBe(2600)
    expect(model.state.slots[2600]).toBeUndefined()
    expect(model.state.slots.slice(200, 2600).every(record => record !== undefined)).toBe(true)
    release()
    expect(model.state.lo).toBe(200)
    expect(model.state.hi).toBe(2600)
  })

  it('extensionPinRejectsRemoteTakeover', async () => {
    const total = () => 9000
    const { model, calls } = await loadModel({ count_memes: total, search_memes: autoPage(total) })
    await model.search()
    await model.ensureRange(0, 2000)
    expect(model.state.hi).toBe(2000)
    const release = model.pinLoadedRange({ allowExtension: true })
    const source = model.state.slots[100]
    // 远跳响应不得清原窗口或改源记录
    await expect(model.ensureRange(8000, 8400, 'jump')).resolves.toBe(false)
    await flush()
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(2000)
    expect(model.state.slots[100]).toBe(source)
    expect(model.state.slots[8000]).toBeUndefined()
    expect(model.state.loadError).toBe(false)
    // 被拒的远跳不得进入退避重放
    await vi.advanceTimersByTimeAsync(5000)
    await flush()
    expect(offsetCalls(calls, 8000)).toBe(1)
    expect(model.state.lo).toBe(0)
    release()
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(2000)
    // 释放后普通远跳恢复接管
    await expect(model.ensureRange(8000, 8400, 'jump')).resolves.toBe(true)
    expect(model.state.lo).toBe(8000)
    expect(model.state.hi).toBe(8400)
    expect(offsetCalls(calls, 8000)).toBe(2)
  })

  it('freezePinWinsOverExtensionPin', async () => {
    const total = () => 9000
    const pages = holdPage()
    const { model, calls } = await loadModel({
      count_memes: total,
      search_memes: args => (args[3] === 2000 ? pages.handler(args) : autoPage(total)(args)),
    })
    await model.search()
    await model.ensureRange(0, 2000)
    expect(model.state.hi).toBe(2000)
    const releaseExt = model.pinLoadedRange({ allowExtension: true })
    const releaseFreeze = model.pinLoadedRange()
    // 冻结优先：扩展 pin 存在也不提交在途页
    const pinned = model.ensureRange(2000, 2200, 'forward')
    pages.resolve(2000, makeRange(2001, 200))
    await expect(pinned).resolves.toBe(true)
    await flush()
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(2000)
    expect(model.state.slots[2000]).toBeUndefined()
    // 释放扩展 pin 不改变冻结暂缓
    releaseExt()
    expect(model.state.hi).toBe(2000)
    expect(model.state.slots[2000]).toBeUndefined()
    // 失效在途需求后再释放冻结：暂缓需求已清，不混入旧页
    model.invalidateRangeRequests()
    releaseFreeze()
    await flush()
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(2000)
    expect(model.state.slots[2000]).toBeUndefined()
    expect(offsetCalls(calls, 2000)).toBe(1)
    // 完全释放后普通补页恢复
    const redo = model.ensureRange(2000, 2200, 'forward')
    pages.resolve(2000, makeRange(2001, 200))
    await expect(redo).resolves.toBe(true)
    expect(model.state.lo).toBe(200)
    expect(model.state.hi).toBe(2200)
    expect(model.state.slots[2000]?.id).toBe(2001)
    expect(offsetCalls(calls, 2000)).toBe(2)
  })

  it('releasedExtensionTrimsCachedViewport', async () => {
    const total = () => 9000
    const { model, calls } = await loadModel({ count_memes: total, search_memes: autoPage(total) })
    await model.search()
    const release = model.pinLoadedRange({ allowExtension: true })
    // 扩展 pin 内补到 2400 项：不裁剪
    await model.ensureRange(0, 2400)
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(2400)
    expect(model.state.hi - model.state.lo).toBe(2400)
    model.state.selectedIds = new Set([1, 2399])
    // pin 期间缓存命中也不裁剪
    await expect(model.ensureRange(0, 200)).resolves.toBe(true)
    expect(model.state.hi - model.state.lo).toBe(2400)
    const callsBefore = calls.length
    release()
    // 释放后缓存命中同样恢复 2000 预算：无网络请求且受保护视口完整
    await expect(model.ensureRange(1000, 1200)).resolves.toBe(true)
    expect(calls.length).toBe(callsBefore)
    expect(model.state.lo).toBe(400)
    expect(model.state.hi).toBe(2400)
    expect(model.state.hi - model.state.lo).toBe(2000)
    expect(model.state.slots[399]).toBeUndefined()
    expect(model.state.slots[400]?.id).toBe(401)
    expect(model.state.slots[1000]?.id).toBe(1001)
    expect(model.state.slots[1199]?.id).toBe(1200)
    expect(model.state.slots[2399]?.id).toBe(2400)
    expect(model.state.total).toBe(9000)
    expect(model.state.slots.length).toBe(9000)
    expect(model.state.selectedIds.size).toBe(2)
    expect(model.state.selectedIds.has(1)).toBe(true)
    expect(model.state.selectedIds.has(2399)).toBe(true)
  })

  it('stalePinReleaseDoesNotTouchNewPins', async () => {
    let backendTotal = 9000
    let shortMode = true
    const pages = holdPage()
    const { model, calls } = await loadModel({
      count_memes: () => backendTotal,
      search_memes: args => {
        const offset = args[3] as number
        const limit = args[4] as number
        if (offset === 0) return autoPage(() => backendTotal)(args)
        if (offset === 2000 && shortMode) return makeRange(offset + 1, 10)
        if (offset === 2200) return pages.handler(args)
        return makeRange(offset + 1, Math.max(0, Math.min(limit, backendTotal - offset)))
      },
    })
    await model.search()
    expect(model.state.hi).toBe(200)
    // 总数漂移换代：漂移失败进入退避重放，重读 count 后旧 pin 失效
    await expect(model.ensureRange(2000, 2200, 'forward')).resolves.toBe(false)
    expect(model.state.loadError).toBe(true)
    expect(offsetCalls(calls, 2000)).toBe(1)
    const oldPin = model.pinLoadedRange()
    shortMode = false
    backendTotal = 5000
    await vi.advanceTimersByTimeAsync(1000)
    await flush(6)
    expect(model.state.total).toBe(5000)
    expect(model.state.slots.length).toBe(5000)
    expect(model.state.lo).toBe(2000)
    expect(model.state.hi).toBe(2200)
    expect(model.state.slots[2000]?.id).toBe(2001)
    // 新 pin 的暂缓提交不受旧 release 影响
    const newPin = model.pinLoadedRange()
    const held = model.ensureRange(2200, 2400, 'forward')
    pages.resolve(2200, makeRange(2201, 200))
    await expect(held).resolves.toBe(true)
    await flush()
    expect(model.state.lo).toBe(2000)
    expect(model.state.hi).toBe(2200)
    expect(model.state.slots[2200]).toBeUndefined()
    oldPin()
    await flush()
    expect(model.state.hi).toBe(2200)
    expect(model.state.slots[2200]).toBeUndefined()
    newPin()
    expect(model.state.hi).toBe(2400)
    expect(model.state.slots[2200]?.id).toBe(2201)
    // 重复释放幂等
    oldPin()
    newPin()
    expect(model.state.hi).toBe(2400)
    // 查询换代：旧 token 不得触碰新查询下的 pin 与暂缓提交
    const stalePin = model.pinLoadedRange()
    model.setSearch('x')
    await model.search()
    expect(model.state.total).toBe(5000)
    expect(model.state.hi).toBe(200)
    const queryPin = model.pinLoadedRange()
    await expect(model.ensureRange(200, 400, 'forward')).resolves.toBe(true)
    await flush()
    expect(model.state.hi).toBe(200)
    expect(model.state.slots[200]).toBeUndefined()
    stalePin()
    await flush()
    expect(model.state.hi).toBe(200)
    expect(model.state.slots[200]).toBeUndefined()
    queryPin()
    expect(model.state.hi).toBe(400)
    expect(model.state.slots[200]?.id).toBe(201)
    // dispose 换代：旧生命周期 token 释放不影响复活后的新 pin
    const dyingPin = model.pinLoadedRange()
    model.dispose()
    await model.search()
    expect(model.state.hi).toBe(200)
    const revivedPin = model.pinLoadedRange()
    await expect(model.ensureRange(200, 400, 'forward')).resolves.toBe(true)
    await flush()
    expect(model.state.hi).toBe(200)
    expect(model.state.slots[200]).toBeUndefined()
    dyingPin()
    await flush()
    expect(model.state.hi).toBe(200)
    expect(model.state.slots[200]).toBeUndefined()
    revivedPin()
    expect(model.state.hi).toBe(400)
    dyingPin()
    revivedPin()
    expect(model.state.hi).toBe(400)
    expect(model.state.slots[200]?.id).toBe(201)
  })

  it('invalidateRangeRequestsRetainsOrderAndSelection', async () => {
    const total = () => 9000
    const pages = holdPage()
    let mode: 'hold' | 'fail' | 'ok' = 'hold'
    const { model, calls } = await loadModel({
      count_memes: total,
      search_memes: args => {
        const offset = args[3] as number
        if (offset === 0) return autoPage(total)(args)
        if (offset === 2000) return mode === 'fail' ? null : pages.handler(args)
        return autoPage(total)(args)
      },
    })
    await model.search()
    await model.ensureRange(0, 2000)
    model.state.selectedIds = new Set([1, 1999])
    const kept = model.state.slots[500]
    const genBefore = model.state.rangeGen
    // A. 活动需求被 supersede：旧响应不得提交
    const pending = model.ensureRange(2000, 2200, 'forward')
    model.invalidateRangeRequests()
    await expect(pending).resolves.toBe(false)
    pages.resolve(2000, makeRange(2001, 200))
    await flush()
    expect(model.state.total).toBe(9000)
    expect(model.state.slots.length).toBe(9000)
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(2000)
    expect(model.state.slots[500]).toBe(kept)
    expect(model.state.slots[2000]).toBeUndefined()
    expect(model.state.rangeGen).toBeGreaterThan(genBefore)
    expect(model.state.rangeLoading).toBe(false)
    expect(model.state.selectedIds.size).toBe(2)
    expect(model.state.selectedIds.has(1)).toBe(true)
    expect(model.state.selectedIds.has(1999)).toBe(true)
    // B. 退避重试与 lastSpec：失效后不得重放，也不能再被 retryRange 复活
    mode = 'fail'
    const failedCalls = offsetCalls(calls, 2000)
    await expect(model.ensureRange(2000, 2200, 'forward')).resolves.toBe(false)
    expect(model.state.loadError).toBe(true)
    expect(offsetCalls(calls, 2000)).toBe(failedCalls + 1)
    model.invalidateRangeRequests()
    await vi.advanceTimersByTimeAsync(5000)
    await flush()
    expect(offsetCalls(calls, 2000)).toBe(failedCalls + 1)
    await expect(model.retryRange()).resolves.toBe(true)
    expect(offsetCalls(calls, 2000)).toBe(failedCalls + 1)
    // C. 正常新需求仍可加载
    mode = 'ok'
    const okCalls = offsetCalls(calls, 2000)
    const redo = model.ensureRange(2000, 2200, 'forward')
    pages.resolve(2000, makeRange(2001, 200))
    await expect(redo).resolves.toBe(true)
    expect(offsetCalls(calls, 2000)).toBe(okCalls + 1)
    expect(model.state.lo).toBe(200)
    expect(model.state.hi).toBe(2200)
    expect(model.state.slots[2000]?.id).toBe(2001)
    expect(model.state.loadError).toBe(false)
    expect(model.state.selectedIds.size).toBe(2)
  })

  it('trimsTailWhenProtectedViewportPinsTheHead', async () => {
    const total = () => 9000
    const { model } = await loadModel({ count_memes: total, search_memes: autoPage(total) })
    await model.search()
    const release = model.pinLoadedRange({ allowExtension: true })
    await model.ensureRange(0, 2400)
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(2400)
    release()
    // 视口回到窗口头部：头部被保护范围钉住时，必须从另一端（尾部）释放到预算
    await expect(model.ensureRange(0, 200)).resolves.toBe(true)
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(2000)
    expect(model.state.hi - model.state.lo).toBe(2000)
    expect(model.state.slots[199]).toBeDefined()
    expect(model.state.slots[2000]).toBeUndefined()
    expect(model.state.slots[2399]).toBeUndefined()
    expect(model.state.total).toBe(9000)
    expect(model.state.slots.length).toBe(9000)
  })

  it('trimsBothEdgesWhenOneSideIsPinnedByProtection', async () => {
    const total = () => 9000
    const { model } = await loadModel({ count_memes: total, search_memes: autoPage(total) })
    await model.search()
    const release = model.pinLoadedRange({ allowExtension: true })
    await model.ensureRange(0, 2400)
    release()
    // 中间视口：近侧（头部）先按页释放，仍超预算时远侧（尾部）继续释放到预算
    model.state.selectedIds = new Set([1, 2399])
    await expect(model.ensureRange(200, 600)).resolves.toBe(true)
    expect(model.state.lo).toBe(200)
    expect(model.state.hi).toBe(2200)
    expect(model.state.hi - model.state.lo).toBe(2000)
    expect(model.state.slots[199]).toBeUndefined()
    expect(model.state.slots[200]).toBeDefined()
    expect(model.state.slots[599]).toBeDefined()
    expect(model.state.slots[2200]).toBeUndefined()
    expect(model.state.selectedIds.size).toBe(2)
    expect(model.state.total).toBe(9000)
  })

  it('retryRangeReplaysFailedSeedWithoutQueryChange', async () => {
    const total = () => 530
    let mode: 'fail' | 'ok' = 'fail'
    const { model, calls } = await loadModel({
      count_memes: total,
      search_memes: args => {
        const offset = args[3] as number
        if (offset === 0) return mode === 'fail' ? null : autoPage(total)(args)
        return autoPage(total)(args)
      },
    })
    await expect(model.search()).resolves.toBe(false)
    expect(model.state.loadError).toBe(true)
    expect(offsetCalls(calls, 0)).toBe(1)
    const gen = model.state.queryGen
    model.state.selectedIds = new Set([7])
    mode = 'ok'
    await expect(model.retryRange()).resolves.toBe(true)
    expect(offsetCalls(calls, 0)).toBe(2)
    expect(calls.filter(call => call.name === 'count_memes').length).toBe(2)
    expect(model.state.queryGen).toBe(gen)
    expect(model.state.total).toBe(530)
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(200)
    expect(model.state.slots[0]?.id).toBe(1)
    expect(model.state.slots[199]?.id).toBe(200)
    expect(model.state.loadError).toBe(false)
    expect(model.state.selectedIds.size).toBe(1)
    expect(model.state.selectedIds.has(7)).toBe(true)
    // 手动重试已清退避计时器：不会再有自动重放
    await vi.advanceTimersByTimeAsync(10000)
    await flush()
    expect(offsetCalls(calls, 0)).toBe(2)
  })

  it('retryRangeReplaysFailedInitAndRestoresInitData', async () => {
    let mode: 'fail' | 'ok' = 'fail'
    const { model, calls } = await loadModel({
      get_init_data: () => (mode === 'fail'
        ? null
        : {
            memes: makeRange(1, 200),
            collections: [{ id: 3, name: '分组', count: 2 }],
            tags: ['已有标签'],
            show_startup_animation: false,
            startup_bg_color: '#101010',
          }),
      count_memes: () => 200,
    })
    const init = model.loadInitData()
    await flush()
    await vi.advanceTimersByTimeAsync(500)
    await flush()
    await vi.advanceTimersByTimeAsync(1000)
    await flush()
    await vi.advanceTimersByTimeAsync(1500)
    await flush()
    await expect(init).resolves.toBe(false)
    expect(model.state.loadError).toBe(true)
    expect(model.state.ready).toBe(false)
    expect(calls.filter(call => call.name === 'get_init_data').length).toBe(3)
    mode = 'ok'
    await expect(model.retryRange()).resolves.toBe(true)
    expect(calls.filter(call => call.name === 'get_init_data').length).toBe(4)
    expect(model.state.allTags).toEqual(['已有标签'])
    expect(model.state.collections.length).toBe(1)
    expect(model.state.showStartupAnimation).toBe(false)
    expect(model.state.total).toBe(200)
    expect(model.state.lo).toBe(0)
    expect(model.state.hi).toBe(200)
    expect(model.state.slots[0]?.id).toBe(1)
    expect(model.state.loadError).toBe(false)
    expect(model.state.ready).toBe(true)
  })

  it('retryRangeClearsExhaustedInitCountError', async () => {
    let mode: 'fail' | 'ok' = 'fail'
    const { model, calls } = await loadModel({
      get_init_data: () => ({
        memes: makeRange(1, 200),
        collections: [],
        tags: [],
        show_startup_animation: true,
        startup_bg_color: '#000000',
      }),
      count_memes: () => (mode === 'fail' ? null : 200),
    })
    await expect(model.loadInitData()).resolves.toBe(true)
    expect(model.state.total).toBe(200)
    expect(model.state.loadError).toBe(false)
    // 静默退避读 count 耗尽：loadError 置位，但 count 失败描述仍保留
    await vi.advanceTimersByTimeAsync(1000)
    await flush()
    await vi.advanceTimersByTimeAsync(2000)
    await flush()
    await vi.advanceTimersByTimeAsync(3000)
    await flush()
    expect(calls.filter(call => call.name === 'count_memes').length).toBe(4)
    expect(model.state.loadError).toBe(true)
    // 手动重试读到相同 count：总数不变也必须清错误并消费描述
    mode = 'ok'
    await expect(model.retryRange()).resolves.toBe(true)
    expect(calls.filter(call => call.name === 'count_memes').length).toBe(5)
    expect(model.state.total).toBe(200)
    expect(model.state.loadError).toBe(false)
    await expect(model.retryRange()).resolves.toBe(true)
    expect(calls.filter(call => call.name === 'count_memes').length).toBe(5)
  })

  it('staleCountRefreshStopsWithoutRaisingLoadErrorAfterQueryChange', async () => {
    let countCalls = 0
    const held = deferred<number | null>()
    const { model, calls } = await loadModel({
      get_init_data: () => ({
        memes: makeRange(1, 200),
        collections: [],
        tags: [],
        show_startup_animation: true,
        startup_bg_color: '#000000',
      }),
      count_memes: () => {
        countCalls += 1
        if (countCalls === 1) return null
        if (countCalls === 2) return held.promise
        return 200
      },
      search_memes: args => autoPage(() => 200)(args),
    })
    await expect(model.loadInitData()).resolves.toBe(true)
    expect(model.state.loadError).toBe(false)
    // 首个退避刷新在途时发起新查询：旧 count 链不得续排、不得置位 loadError
    await vi.advanceTimersByTimeAsync(1000)
    await flush()
    await expect(model.search()).resolves.toBe(true)
    expect(model.state.total).toBe(200)
    held.resolve(null)
    await flush()
    await vi.advanceTimersByTimeAsync(10000)
    await flush()
    expect(calls.filter(call => call.name === 'count_memes').length).toBe(3)
    expect(model.state.loadError).toBe(false)
  })

  it('staleSeedFailureNeverRevivesAfterInvalidateSearchOrDispose', async () => {
    const total = () => 530
    let mode: 'fail' | 'ok' = 'fail'
    const { model, calls } = await loadModel({
      count_memes: total,
      search_memes: args => {
        const offset = args[3] as number
        if (offset === 0) return mode === 'fail' ? null : autoPage(total)(args)
        return autoPage(total)(args)
      },
    })
    // A. 失效清描述：retryRange 为既有 no-op，不重放旧 seed、不新 search
    await expect(model.search()).resolves.toBe(false)
    expect(model.state.loadError).toBe(true)
    const failedPageCalls = offsetCalls(calls, 0)
    const failedCountCalls = calls.filter(call => call.name === 'count_memes').length
    model.invalidateRangeRequests()
    await expect(model.retryRange()).resolves.toBe(true)
    expect(offsetCalls(calls, 0)).toBe(failedPageCalls)
    expect(calls.filter(call => call.name === 'count_memes').length).toBe(failedCountCalls)
    expect(model.state.loadError).toBe(true)
    // B. 新一代查询成功后：旧 seed 描述不得复活
    mode = 'fail'
    await expect(model.search()).resolves.toBe(false)
    mode = 'ok'
    await expect(model.search()).resolves.toBe(true)
    const okPageCalls = offsetCalls(calls, 0)
    const okCountCalls = calls.filter(call => call.name === 'count_memes').length
    await expect(model.retryRange()).resolves.toBe(true)
    expect(offsetCalls(calls, 0)).toBe(okPageCalls)
    expect(calls.filter(call => call.name === 'count_memes').length).toBe(okCountCalls)
    expect(model.state.loadError).toBe(false)
    // C. dispose 清描述：卸载时与复活前都不得重放旧 seed
    mode = 'fail'
    await expect(model.search()).resolves.toBe(false)
    model.dispose()
    const disposedPageCalls = offsetCalls(calls, 0)
    await expect(model.retryRange()).resolves.toBe(false)
    expect(offsetCalls(calls, 0)).toBe(disposedPageCalls)
    mode = 'ok'
    await expect(model.search()).resolves.toBe(true)
    const revivedPageCalls = offsetCalls(calls, 0)
    expect(revivedPageCalls).toBe(disposedPageCalls + 1)
    await expect(model.retryRange()).resolves.toBe(true)
    expect(offsetCalls(calls, 0)).toBe(revivedPageCalls)
    expect(model.state.loadError).toBe(false)
  })

  it('cacheHitKeepsPendingNonRangeFailureError', async () => {
    // 同查询刷新种子失败（旧窗口保留）后，缓存命中与分页提交都不得清掉错误入口
    const total = () => 530
    let seedMode: 'ok' | 'fail' = 'ok'
    const { model, calls } = await loadModel({
      count_memes: total,
      search_memes: args => {
        const offset = args[3] as number
        if (offset === 0) return seedMode === 'fail' ? null : makeRange(1, 200)
        return makeRange(offset + 1, 200)
      },
    })
    await expect(model.search()).resolves.toBe(true)
    expect(model.state.hi).toBe(200)
    expect(model.state.loadError).toBe(false)
    // 同查询再刷新：种子失败但旧窗口保留 → 错误入口 + seed 描述
    seedMode = 'fail'
    await expect(model.search()).resolves.toBe(false)
    expect(model.state.loadError).toBe(true)
    expect(model.state.hi).toBe(200)
    expect(model.state.total).toBe(530)
    expect(offsetCalls(calls, 0)).toBe(2)
    // 缓存命中的分页请求只清分页类状态（lastFailed/退避），不清未解决的 seed 失败
    await expect(model.ensureRange(0, 200)).resolves.toBe(true)
    expect(model.state.loadError).toBe(true)
    expect(offsetCalls(calls, 0)).toBe(2)
    // 分页提交成功同样只清分页类失败
    await expect(model.ensureRange(200, 400)).resolves.toBe(true)
    expect(model.state.hi).toBe(400)
    expect(model.state.loadError).toBe(true)
    // 描述仍可重放：修复种子后手动重试成功并清错误
    seedMode = 'ok'
    await expect(model.retryRange()).resolves.toBe(true)
    expect(offsetCalls(calls, 0)).toBe(3)
    expect(model.state.loadError).toBe(false)
    expect(model.state.total).toBe(530)
    expect(model.state.hi).toBe(200)
  })

  it('invalidationDiscardsInFlightSeedAndCountFailures', async () => {
    // A. 种子在途时失效（拖拽保存前）：失败结果不登记、不续排
    const seedHold = deferred<Meme[] | null>()
    const seedRun = await loadModel({
      count_memes: () => 530,
      search_memes: args => ((args[3] as number) === 0 ? seedHold.promise : makeRange(201, 200)),
    })
    const searchPromise = seedRun.model.search()
    await flush()
    expect(offsetCalls(seedRun.calls, 0)).toBe(1)
    seedRun.model.invalidateRangeRequests()
    seedHold.resolve(null)
    await flush()
    await expect(searchPromise).resolves.toBe(true)
    expect(seedRun.model.state.loadError).toBe(false)
    expect(seedRun.model.state.loading).toBe(false)
    expect(seedRun.model.state.total).toBe(0)
    await vi.advanceTimersByTimeAsync(10000)
    await flush()
    expect(offsetCalls(seedRun.calls, 0)).toBe(1)
    expect(seedRun.model.state.loadError).toBe(false)
    await expect(seedRun.model.retryRange()).resolves.toBe(true)
    expect(offsetCalls(seedRun.calls, 0)).toBe(1)
    // B. count 退避刷新在途时失效：失败不重新登记、链不续排、错误态不复活
    let countMode: 'fail' | 'hold' = 'fail'
    const countHold = deferred<number | null>()
    const countRun = await loadModel({
      get_init_data: () => ({
        memes: makeRange(1, 200),
        collections: [],
        tags: [],
        show_startup_animation: true,
        startup_bg_color: '#000000',
      }),
      count_memes: () => (countMode === 'fail' ? null : countMode === 'hold' ? countHold.promise : 200),
    })
    await expect(countRun.model.loadInitData()).resolves.toBe(true)
    expect(countRun.model.state.loadError).toBe(false)
    countMode = 'hold'
    await vi.advanceTimersByTimeAsync(1000)
    await flush()
    expect(countRun.calls.filter(call => call.name === 'count_memes').length).toBe(2)
    countRun.model.invalidateRangeRequests()
    countHold.resolve(null)
    await flush(8)
    await vi.advanceTimersByTimeAsync(10000)
    await flush()
    expect(countRun.calls.filter(call => call.name === 'count_memes').length).toBe(2)
    expect(countRun.model.state.loadError).toBe(false)
    expect(countRun.model.state.total).toBe(200)
    await expect(countRun.model.retryRange()).resolves.toBe(true)
    expect(countRun.calls.filter(call => call.name === 'count_memes').length).toBe(2)
  })
})
