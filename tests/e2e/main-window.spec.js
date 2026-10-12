import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { fileURLToPath } from 'node:url'

const staticAssets = new Map([
  [
    '/vue.html',
    [
      fileURLToPath(new URL('../../src/webui/vue.html', import.meta.url)),
      'text/html; charset=utf-8',
    ],
  ],
  [
    '/dist/ohmymeme.js',
    [
      fileURLToPath(
        new URL('../../src/webui/dist/ohmymeme.js', import.meta.url),
      ),
      'text/javascript; charset=utf-8',
    ],
  ],
])

test('collapses the real Vue main-window sidebar after its toggle is clicked', async ({ page }, testInfo) => {
  const server = createServer((request, response) => {
    const pathname = new URL(
      request.url ?? '/',
      'http://127.0.0.1',
    ).pathname
    const asset = staticAssets.get(pathname)
    if (asset === undefined) {
      response.writeHead(404)
      response.end()
      return
    }
    response.writeHead(200, { 'Content-Type': asset[1] })
    response.end(readFileSync(asset[0]))
  })

  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  const address = server.address()
  if (address === null || typeof address === 'string') {
    throw new Error('The static browser test server has no TCP address')
  }

  try {
    await page.addInitScript(() => {
      window.pywebview = {
        api: {
          get_init_data: async () => ({
            memes: [],
            tags: [],
            collections: [],
            show_startup_animation: false,
            startup_bg_color: '#000000',
          }),
          count_memes: async () => 0,
          search_memes: async () => [],
          get_tags: async () => [],
          get_collections: async () => [],
          rescan_cache: async () => true,
          run_auto_sync: async () => true,
          check_update: async () => ({ pending: false, has_update: false }),
        },
      }
    })

    await page.goto(`http://127.0.0.1:${address.port}/vue.html`)
    const sidebar = page.locator('#sidebar')
    await expect(page.locator('.sidebar-toggle')).toBeVisible()
    await expect(sidebar).not.toHaveClass(/collapsed/)

    await page.locator('.sidebar-toggle').click()

    await expect(sidebar).toHaveClass(/collapsed/)
    await page.screenshot({ path: testInfo.outputPath('main-window.png') })
  } finally {
    await new Promise((resolve, reject) => {
      server.close(error => (error ? reject(error) : resolve()))
    })
  }
})

// 小数据真实渲染：3 条完整 fixture 经虚拟行渲染为真卡（不声称大数据 DOM 上限）
const memeFixtures = [
  {
    id: 1,
    name: 'meme one',
    filename: 'one.png',
    file_hash: 'hash-one',
    width: 16,
    height: 16,
    mime_type: 'image/png',
  },
  {
    id: 2,
    name: 'meme two',
    filename: 'two.png',
    file_hash: 'hash-two',
    width: 16,
    height: 16,
    mime_type: 'image/png',
  },
  {
    id: 3,
    name: 'meme three',
    filename: 'three.png',
    file_hash: 'hash-three',
    width: 16,
    height: 16,
    mime_type: 'image/png',
  },
]

// 1x1 PNG：为缩略图/原图请求提供固定小图，避免无关 404
const tinyPng = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
)

test('renders a small meme result through virtual rows', async ({ page }) => {
  const server = createServer((request, response) => {
    const pathname = new URL(
      request.url ?? '/',
      'http://127.0.0.1',
    ).pathname
    if (pathname.startsWith('/api/thumb/') || pathname.startsWith('/api/original/')) {
      response.writeHead(200, { 'Content-Type': 'image/png' })
      response.end(tinyPng)
      return
    }
    const asset = staticAssets.get(pathname)
    if (asset === undefined) {
      response.writeHead(404)
      response.end()
      return
    }
    response.writeHead(200, { 'Content-Type': asset[1] })
    response.end(readFileSync(asset[0]))
  })

  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  const address = server.address()
  if (address === null || typeof address === 'string') {
    throw new Error('The static browser test server has no TCP address')
  }

  try {
    await page.addInitScript(memes => {
      window.pywebview = {
        api: {
          get_init_data: async () => ({
            memes,
            tags: [],
            collections: [],
            show_startup_animation: false,
            startup_bg_color: '#000000',
          }),
          count_memes: async () => memes.length,
          search_memes: async (_keyword, _tags, _collectionId, offset) =>
            offset === 0 ? memes : [],
          get_tags: async () => [],
          get_collections: async () => [],
          rescan_cache: async () => true,
          run_auto_sync: async () => true,
          check_update: async () => ({ pending: false, has_update: false }),
        },
      }
    }, memeFixtures)

    await page.goto(`http://127.0.0.1:${address.port}/vue.html`)
    // 等 300ms 后台流程（rescan → auto_sync → search）完成后的 footer 文案
    await expect(page.locator('.grid-foot')).toHaveText(/共 3 项/)

    const cards = page.locator('#meme-grid .meme-card[data-meme-id]')
    await expect(cards).toHaveCount(3)
    expect(
      await cards.evaluateAll(elements => elements.map(element => element.dataset.memeId)),
    ).toEqual(['1', '2', '3'])
    expect(await page.locator('#meme-grid .meme-card[data-meme-id] img').count()).toBe(3)
    expect(await page.locator('#meme-grid .virtual-meme-row').count()).toBeGreaterThan(0)
    await expect(page.locator('#meme-grid .meme-card.skeleton')).toHaveCount(0)
    await expect(page.locator('.grid-spacer')).toHaveCount(0)
    await expect(page.locator('#empty')).toBeHidden()

    const gridWrapStyles = await page.locator('#grid-wrap').evaluate(element => {
      const style = getComputedStyle(element)
      return { overflowY: style.overflowY, overflowAnchor: style.overflowAnchor }
    })
    expect(gridWrapStyles.overflowY).toBe('auto')
    expect(gridWrapStyles.overflowAnchor).toBe('none')
  } finally {
    await new Promise((resolve, reject) => {
      server.close(error => (error ? reject(error) : resolve()))
    })
  }
})

// 自研框选：从实测留白起手拖过两张卡，空白点击不清空，Escape 取消手势不退出整理
test('marquee selects rendered memes from blank space', async ({ page }) => {
  const server = createServer((request, response) => {
    const pathname = new URL(
      request.url ?? '/',
      'http://127.0.0.1',
    ).pathname
    if (pathname.startsWith('/api/thumb/') || pathname.startsWith('/api/original/')) {
      response.writeHead(200, { 'Content-Type': 'image/png' })
      response.end(tinyPng)
      return
    }
    const asset = staticAssets.get(pathname)
    if (asset === undefined) {
      response.writeHead(404)
      response.end()
      return
    }
    response.writeHead(200, { 'Content-Type': asset[1] })
    response.end(readFileSync(asset[0]))
  })

  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  const address = server.address()
  if (address === null || typeof address === 'string') {
    throw new Error('The static browser test server has no TCP address')
  }

  try {
    await page.addInitScript(memes => {
      // 可观察的后台完成标记：rescan → auto_sync → search 调用计数（不依赖相同 footer 文案）
      const calls = { rescan: false, autoSync: false, search: 0 }
      window.__ohmymemeCalls = calls
      window.pywebview = {
        api: {
          get_init_data: async () => ({
            memes,
            tags: [],
            collections: [],
            show_startup_animation: false,
            startup_bg_color: '#000000',
          }),
          count_memes: async () => memes.length,
          search_memes: async (_keyword, _tags, _collectionId, offset) => {
            calls.search += 1
            return offset === 0 ? memes : []
          },
          get_tags: async () => [],
          get_collections: async () => [],
          rescan_cache: async () => {
            calls.rescan = true
            return true
          },
          run_auto_sync: async () => {
            calls.autoSync = true
            return true
          },
          check_update: async () => ({ pending: false, has_update: false }),
        },
      }
    }, memeFixtures)

    await page.goto(`http://127.0.0.1:${address.port}/vue.html`)
    // 等后台流程可观察完成（rescan → auto_sync → 至少一次 search）后再开启整理模式
    await page.waitForFunction(() => {
      const calls = window.__ohmymemeCalls
      return !!calls && calls.rescan && calls.autoSync && calls.search >= 1
    })
    await expect(page.locator('.grid-foot')).toHaveText(/共 3 项/)
    await page.locator('button[title="整理模式"]').click()
    const cards = page.locator('#meme-grid .meme-card[data-meme-id]')
    await expect(cards).toHaveCount(3)

    const first = await cards.nth(0).boundingBox()
    const second = await cards.nth(1).boundingBox()
    if (!first || !second) throw new Error('marquee fixture cards must be laid out')
    // 起手点：首行上方留白（网格 padding 内、卡外）；收手点：第二张卡右下角
    const startX = first.x + 2
    const startY = Math.max(2, first.y - 4)
    const endX = second.x + second.width - 4
    const endY = second.y + second.height - 4

    await page.mouse.move(startX, startY)
    await page.mouse.down()
    await page.mouse.move(endX, endY, { steps: 4 })
    await page.mouse.up()
    await expect(page.locator('#organize-bar .count')).toHaveText(/已选 2 项/)

    // 空白点击不清空既有选择（未过 8px 门槛）
    await page.mouse.click(startX, startY)
    await expect(page.locator('#organize-bar .count')).toHaveText(/已选 2 项/)

    // 再次框选后按 Escape：取消手势并回滚起手快照，第一次不退出整理
    await page.mouse.move(startX, startY)
    await page.mouse.down()
    await page.mouse.move(endX, endY, { steps: 3 })
    await page.keyboard.press('Escape')
    await page.mouse.up()
    await expect(page.locator('#organize-bar')).toBeVisible()
    await expect(page.locator('#organize-bar .count')).toHaveText(/已选 2 项/)
  } finally {
    await new Promise((resolve, reject) => {
      server.close(error => (error ? reject(error) : resolve()))
    })
  }
})
