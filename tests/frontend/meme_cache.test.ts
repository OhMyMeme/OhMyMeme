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
})
