import { expect, test } from '@playwright/test'
import { createServer } from 'node:http'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../../src/webui/', import.meta.url))
const files = new Map([
  ['/settings/', ['settings.html', 'text/html; charset=utf-8']],
  ['/settings.css', ['settings.css', 'text/css; charset=utf-8']],
  ['/settings.js', ['settings.js', 'text/javascript; charset=utf-8']],
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

const PLUGINS = [
  { id: 'source.qqnt', label: '电脑版 QQ（QQNT 本地缓存）', kind: 'source', origin: 'bundled', version: '1', enabled: false, available: true, versions: [] },
  { id: 'source.telegram', label: 'Telegram Desktop', kind: 'source', origin: 'bundled', version: '1', enabled: true, available: false, versions: [] },
  { id: 'source.douyin', label: '抖音', kind: 'source', origin: 'bundled', version: '1', enabled: true, available: true, versions: [] },
  { id: 'source.wechat', label: '微信', kind: 'source', origin: 'bundled', version: '1', enabled: true, available: true, versions: [] },
  { id: 'community.demo', label: 'Demo', kind: 'source', origin: 'installed', version: '1.0.0', enabled: true, available: true, versions: ['1.0.0'] },
]

const CONTRIBUTIONS = [
  {
    provider: 'community.demo',
    available: true,
    enabled: true,
    injection: {
      point: 'imports.row',
      label: 'Demo 来源',
      description: '本地目录导入',
      icon: 'generic',
      fields: [
        { key: 'source_dir', type: 'string', label: '源目录', required: true },
        { key: 'limit', type: 'int', label: '数量', required: false },
      ],
      actions: [{ name: 'run', label: '运行', kind: 'import' }],
    },
  },
]

test('settings import area reflects source status and injected rows', async ({ page }) => {
  const server = await startServer()
  const address = server.address()
  if (address === null || typeof address === 'string') throw new Error('server address unavailable')
  const actions = []
  try {
    await page.addInitScript(() => {
      window.pywebview = {
        api: {
          check_connectivity: async () => 'ok',
          get_settings: async () => ({ hotkey: 'Ctrl+Alt+N' }),
          get_current_version: async () => '0.0.0',
        },
      }
    })
    await page.route('**/api/plugins', route => route.fulfill({ json: { plugins: PLUGINS } }))
    await page.route('**/api/plugins/ui', route => route.fulfill({ json: { contributions: CONTRIBUTIONS } }))
    await page.route('**/api/plugins/ui/action', route => {
      actions.push(route.request().postDataJSON())
      return route.fulfill({ json: { ok: true, result: {} } })
    })
    await page.goto(`http://127.0.0.1:${address.port}/settings/`)
    await page.evaluate(() => switchSettingsGroup('import'))

    const qqnt = page.locator('[onclick="startQQNTWizard()"]')
    await expect(qqnt).toHaveClass(/import-row-disabled/)
    await expect(qqnt.locator('.import-status')).toHaveText('已禁用（重启生效）')
    await expect(qqnt).toBeDisabled()

    const telegram = page.locator('[onclick="openTGImportDialog()"]')
    await expect(telegram).toHaveClass(/import-row-missing/)
    await expect(telegram.locator('.import-status')).toHaveText('不可用：缺少插件包')
    await expect(telegram).toBeDisabled()

    const douyin = page.locator('[onclick="openDYImportDialog()"]')
    await expect(douyin).not.toHaveClass(/import-row-disabled|import-row-missing/)
    await expect(douyin).toBeEnabled()

    const injected = page.locator('#import-injected .import-injected-row')
    await expect(injected).toHaveCount(1)
    await expect(injected.locator('.import-name')).toHaveText('Demo 来源')
    await injected.locator('input[data-inject-field="source_dir"]').fill('D:/tmp')
    await injected.locator('input[data-inject-field="limit"]').fill('5')
    await injected.getByRole('button', { name: '运行' }).click()
    await expect.poll(() => actions.length).toBe(1)
    expect(actions[0]).toMatchObject({
      provider: 'community.demo',
      name: 'run',
      payload: { source_dir: 'D:/tmp', limit: 5 },
    })
    await expect(page.locator('#toast')).toContainText('已执行')
  } finally {
    await page.close()
    server.closeAllConnections()
    await new Promise((resolve, reject) => server.close(error => (error ? reject(error) : resolve())))
  }
})
