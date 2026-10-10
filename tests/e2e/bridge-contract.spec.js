import { expect, test } from '@playwright/test'
import { createServer } from 'node:http'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../../src/webui/', import.meta.url))
// 现用两窗口入口：主窗口 vue.html/dist/ohmymeme.js，设置窗口 vue-settings.html/dist/settings-vue.js
const files = new Map([
  ['/vue.html', ['vue.html', 'text/html; charset=utf-8']],
  ['/dist/ohmymeme.js', ['dist/ohmymeme.js', 'text/javascript; charset=utf-8']],
  ['/settings/', ['vue-settings.html', 'text/html; charset=utf-8']],
  ['/dist/settings-vue.js', ['dist/settings-vue.js', 'text/javascript; charset=utf-8']],
  ['/api/plugin-ui', ['plugin-ui.json', 'application/json; charset=utf-8']],
])

function startServer() {
  const server = createServer((request, response) => {
    const asset = files.get(new URL(request.url ?? '/', 'http://127.0.0.1').pathname)
    if (!asset) {
      response.writeHead(404)
      response.end()
      return
    }
    response.writeHead(200, { 'Content-Type': asset[1] })
    response.end(readFileSync(`${root}${asset[0]}`))
  })
  return new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => resolve(server))
  })
}

test('main bridge rejects malformed init payload without breaking the shell', async ({ page }) => {
  const server = await startServer()
  const address = server.address()
  if (address === null || typeof address === 'string') throw new Error('server address unavailable')
  try {
    await page.addInitScript(() => {
      window.pywebview = { api: {
        get_init_data: async () => [],
        count_memes: async () => 0,
        search_memes: async () => [],
        get_tags: async () => [],
        get_collections: async () => [],
        rescan_cache: async () => true,
        run_auto_sync: async () => ({ fetched: false, synced: false, error: '' }),
        check_update: async () => ({ pending: false, has_update: false }),
      } }
    })
    await page.goto(`http://127.0.0.1:${address.port}/vue.html`)
    await expect(page.locator('#app-mount')).toBeVisible()
    await expect(page.locator('.sidebar-toggle')).toBeVisible()
  } finally {
    await page.close()
    server.closeAllConnections()
    await new Promise((resolve, reject) => server.close(error => (error ? reject(error) : resolve())))
  }
})

test('settings decoder turns a malformed bridge result into a fail-closed UI state', async ({ page }) => {
  const server = await startServer()
  const address = server.address()
  if (address === null || typeof address === 'string') throw new Error('server address unavailable')
  try {
    await page.addInitScript(() => {
      window.pywebview = { api: {
        get_settings: async () => ({ hotkey: 'Ctrl+Alt+N' }),
        check_connectivity: async () => 'malformed',
      } }
    })
    await page.goto(`http://127.0.0.1:${address.port}/settings/`)

    // 外壳挂载后，BaseGroup 挂载即探测；坏 bridge 结果只呈现可读 fail-closed 文案
    await expect(page.locator('#settings-nav [data-group="base"]')).toBeVisible()
    await expect(page.getByText('● 无网络连接')).toBeVisible()
    // 用户再次触发同一探测，仍返回同一 fail-closed 结果（不暴露全局 api）
    await page.getByText('浏览器来源尝试获取原图').click()
    await expect(page.getByText('● 无网络连接')).toBeVisible()
    await expect(page.locator('#settings-nav [data-group="base"]')).toBeVisible()
  } finally {
    await page.close()
    server.closeAllConnections()
    await new Promise((resolve, reject) => server.close(error => (error ? reject(error) : resolve())))
  }
})
