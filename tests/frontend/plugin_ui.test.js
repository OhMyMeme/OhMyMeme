import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

// useDialog 需要 provider；用具名 stub 让网络分组的确认框在测试中直接放行
vi.mock('naive-ui', async importOriginal => {
  const actual = await importOriginal()
  return {
    ...actual,
    useDialog: () => ({ warning: options => options.onPositiveClick?.() }),
  }
})

const root = process.cwd()
const data = JSON.parse(readFileSync(resolve(root, 'src/webui/plugin-ui.json'), 'utf8'))
const observations = []

// 重置模块图，避免 settings-vue/plugin-ui 的整快照缓存跨用例；再加载现用边界与组件
async function loadFresh() {
  vi.resetModules()
  const pluginUI = await import(
    '../../src/ohmymeme/presentation/frontend/settings-vue/shared/plugin-ui'
  )
  const bridge = await import(
    '../../src/ohmymeme/presentation/frontend/settings-vue/shared/bridge'
  )
  const store = await import(
    '../../src/ohmymeme/presentation/frontend/settings-vue/shared/store'
  )
  const ImportGroup = (
    await import(
      '../../src/ohmymeme/presentation/frontend/settings-vue/features/import/ImportGroup.vue'
    )
  ).default
  const wizards = {
    QqWizard: (
      await import(
        '../../src/ohmymeme/presentation/frontend/settings-vue/features/import/QqWizard.vue'
      )
    ).default,
    QqntWizard: (
      await import(
        '../../src/ohmymeme/presentation/frontend/settings-vue/features/import/QqntWizard.vue'
      )
    ).default,
    TelegramWizard: (
      await import(
        '../../src/ohmymeme/presentation/frontend/settings-vue/features/import/TelegramWizard.vue'
      )
    ).default,
    DouyinWizard: (
      await import(
        '../../src/ohmymeme/presentation/frontend/settings-vue/features/import/DouyinWizard.vue'
      )
    ).default,
    WechatWizard: (
      await import(
        '../../src/ohmymeme/presentation/frontend/settings-vue/features/import/WechatWizard.vue'
      )
    ).default,
  }
  const NetworkGroup = (
    await import(
      '../../src/ohmymeme/presentation/frontend/settings-vue/features/network/NetworkGroup.vue'
    )
  ).default
  return { ...pluginUI, ...bridge, store, ImportGroup, wizards, NetworkGroup }
}

// 承接导入/设置组件真实调用的 Bridge 桩：记录方法名与参数
function bridgeStub(results = {}) {
  const calls = []
  globalThis.pywebview = {
    api: new Proxy(
      {},
      {
        get: (_target, method) => (...args) => {
          calls.push({ method, args })
          // 结果可为函数：按调用时的真实状态求值（如 LAN 状态机），否则返回固定值
          if (Object.hasOwn(results, method)) {
            const result = results[method]
            return typeof result === 'function' ? result(...args) : result
          }
          if (String(method).includes('cancel') || method === 'save_settings') return null
          if (method === 'lan_get_ip') return '127.0.0.1'
          // 真实 ABI：sync_test 成功返回字符串 'ok'，不是 {ok} 对象
          if (method === 'sync_test') return 'ok'
          return { ok: true }
        },
      },
    ),
  }
  return calls
}

const ModalStub = {
  name: 'NModal',
  props: { show: { type: Boolean, default: false } },
  template: '<div v-if="show" class="n-modal"><slot /></div>',
}

async function clickButton(wrapper, text) {
  // 只点击当前可见（未被 v-show display:none 隐藏）的按钮，避免命中未显示阶段的按钮
  const button = wrapper
    .findAll('button')
    .find(el => el.text().includes(text) && isVisible(el.element))
  if (!button) throw new Error('button not found (visible): ' + text)
  await button.trigger('click')
  await flushPromises()
}

// jsdom 无布局：用祖先链上的 hidden / inline display:none 判定可见性，不用 getClientRects
function isVisible(element) {
  let node = element
  while (node && node.nodeType === 1) {
    if (node.hasAttribute('hidden')) return false
    if (node.style && node.style.display === 'none') return false
    node = node.parentElement
  }
  return !!(element && element.isConnected)
}

const mountedWrappers = []
function mountTracked(component, options) {
  const wrapper = mount(component, options)
  mountedWrappers.push(wrapper)
  return wrapper
}

// 读取真实消费的 NProgress percentage（回退到可见的百分比文案）
function progressValue(wrapper) {
  const progress = wrapper.findComponent({ name: 'Progress' })
  if (progress.exists()) return Number(progress.props('percentage'))
  const match = wrapper.text().match(/(\d+)%/)
  return match ? Number(match[1]) : NaN
}

beforeEach(() => {
  document.body.innerHTML = '<div id="toast" role="status" aria-live="polite"></div>'
  vi.useFakeTimers()
})

afterEach(() => {
  mountedWrappers.splice(0).forEach(wrapper => {
    try { wrapper.unmount() } catch (_) { /* ignore */ }
  })
  vi.clearAllTimers()
  vi.useRealTimers()
  delete globalThis.pywebview
  delete globalThis.fetch
  document.body.innerHTML = ''
})

describe('settings Vue plugin UI projection', () => {
  it('accepts the fixed nine-provider snapshot and exposes its labels/screens', async () => {
    const ui = await loadFresh()
    ui.installPluginUI(data)
    const snapshot = ui.getPluginUI()
    expect(snapshot.contributions).toHaveLength(9)
    expect(snapshot.contributions.map(row => row.provider)).toEqual([
      'source.qqnt',
      'source.telegram',
      'source.douyin',
      'source.wechat',
      'sync.ftp',
      'sync.s3',
      'sync.r2',
      'sync.webdav',
      'transport.lan',
    ])
    expect(snapshot.contributions[0].label).toBe('电脑版 QQ（QQNT 本地缓存）')
    expect(snapshot.contributions[8].screen).toBe('lan')
    observations.push({ case: 'nine-providers', providers: snapshot.contributions.map(r => r.provider) })
  })

  it.each([
    ['label', 'Other non-empty label'],
    ['label', true],
    ['label', ''],
    ['icon', '<svg onload=run()>'],
    ['handler', 'eval'],
    ['provider', 'source.unknown'],
    ['provider', 'qq.mobile'],
    ['script', 'run()'],
    ['html', '<img onerror=run()>'],
    ['javascript', 'run()'],
    ['bridge_methods', ['execute']],
    ['extra', {}],
    ['screen', 'body'],
  ])('rejects %s before installing the snapshot', async (field, value) => {
    const ui = await loadFresh()
    const input = structuredClone(data)
    input.contributions[0][field] = value
    expect(() => ui.installPluginUI(input)).toThrow(field)
    expect(ui.getPluginUI()).toBeNull()
  })

  it.each([
    ['action', 'execute'],
    ['label', 'Misleading PASS'],
    ['arguments', []],
    ['progress_fields', ['html']],
    ['script', 'run()'],
    ['args', [true]],
  ])('rejects action %s and preserves an installed snapshot', async (field, value) => {
    const ui = await loadFresh()
    ui.installPluginUI(data)
    const before = ui.getPluginUI()
    const input = structuredClone(data)
    const action = input.contributions[1].actions.find(row => row.action === 'start_tg_import')
    action[field] = value
    expect(() => ui.installPluginUI(input)).toThrow(field)
    expect(ui.getPluginUI()).toEqual(before)
  })

  it('validates actual arguments before invoking the Bridge, without changing defaults', async () => {
    const ui = await loadFresh()
    const calls = bridgeStub()
    ui.installPluginUI(data)
    for (const [method, args] of [
      ['lan_start', [true, '']],
      ['lan_start', [1.5, '']],
      ['start_tg_import', [null, '', 1]],
      ['start_douyin_import', []],
      ['sync_push', ['true']],
      ['qqnt_check_env', ['extra']],
    ]) {
      expect(ui.api(method, ...args)).toBeNull()
    }
    expect(calls).toEqual([])
    ui.api('start_tg_import')
    ui.api('sync_push')
    ui.api('lan_start', 17852, '')
    await flushPromises()
    expect(calls).toEqual([
      { method: 'start_tg_import', args: [] },
      { method: 'sync_push', args: [] },
      { method: 'lan_start', args: [17852, ''] },
    ])
    observations.push({ case: 'args', accepted: calls, rejected_calls: 0 })
  })

  it('reads progress only from projected fields', async () => {
    const ui = await loadFresh()
    ui.installPluginUI(data)
    expect(ui.pluginProgressValue('get_sync_progress', { progress: 41 }, 'progress')).toBe(41)
    expect(ui.pluginUILabel('sync_test')).toBe('测试连接')
    expect(() => ui.pluginProgressValue('get_sync_progress', {}, 'html')).toThrow('progress_fields')
  })
})

describe('settings Vue import group and wizards', () => {
  const pluginRows = [
    { id: 'source.qqnt', available: true, enabled: false },
    { id: 'source.telegram', available: true, enabled: true },
    { id: 'source.douyin', available: true, enabled: true },
    { id: 'source.wechat', available: true, enabled: true },
  ]
  const injected = [
    {
      provider: 'community.demo',
      enabled: true,
      injection: {
        point: 'imports.row',
        label: 'Demo 来源',
        description: '本地目录导入',
        fields: [
          { key: 'source_dir', type: 'string', label: '源目录', required: true },
          { key: 'limit', type: 'int', label: '数量', required: false },
        ],
        actions: [{ name: 'run', label: '运行', kind: 'import' }],
      },
    },
  ]

  function mockFetch(calls = []) {
    globalThis.fetch = vi.fn(async (url, options) => {
      if (url === '/api/plugins') return { ok: true, json: async () => ({ plugins: pluginRows }) }
      if (url === '/api/plugins/ui') return { ok: true, json: async () => ({ contributions: injected }) }
      if (url === '/api/plugins/ui/action') {
        calls.push(JSON.parse(options.body))
        return { ok: true, json: async () => ({ ok: true, result: {} }) }
      }
      throw new Error('unexpected fetch: ' + url)
    })
  }

  it('renders the fixed rows, disabled state and injected rows through the host projection', async () => {
    const ui = await loadFresh()
    const actionCalls = []
    mockFetch(actionCalls)
    const wrapper = mountTracked(ui.ImportGroup)
    await flushPromises()

    const rows = wrapper.findAll('.import-row:not(.import-injected-row)')
    expect(rows.map(row => row.find('.import-name').text())).toEqual([
      '手机版 QQ（ADB 拉取）',
      '电脑版 QQ（QQNT 本地缓存）',
      'Telegram Desktop',
      '抖音',
      '微信',
    ])
    expect(rows[1].classes()).toContain('import-row-disabled')
    expect(rows[1].find('.import-status').text()).toBe('已禁用（重启生效）')

    const injectedRow = wrapper.find('.import-injected-row')
    expect(injectedRow.find('.import-name').text()).toBe('Demo 来源')
    await injectedRow.find('[data-inject-field="source_dir"]').setValue('D:/tmp')
    await injectedRow.find('[data-inject-field="limit"]').setValue('5')
    await injectedRow.find('button').trigger('click')
    await flushPromises()
    expect(actionCalls[0]).toMatchObject({
      provider: 'community.demo',
      name: 'run',
      payload: { source_dir: 'D:/tmp', limit: 5 },
    })
    observations.push({ case: 'import-group', labels: rows.map(r => r.find('.import-name').text()) })
  })

  it('runs the QQNT start/progress/cancel wiring and consumes progress fields', async () => {
    const ui = await loadFresh()
    ui.installPluginUI(data)
    const calls = bridgeStub({
      qqnt_check_env: { ok: true, error: '', message: '', accounts: [{ qq: '10001', nickname: 'n', count: 3 }] },
      qqnt_pick_base: { ok: true, base: 'D:/out' },
      qqnt_default_dir: { ok: true, dir: 'D:/out/10001' },
      qqnt_get_progress: { status: 'running', progress: 40, message: 'qq-progress' },
    })
    const wrapper = mountTracked(ui.wizards.QqntWizard, { global: { stubs: { NModal: ModalStub } } })
    await wrapper.vm.open()
    await flushPromises()
    expect(calls.map(call => call.method)).toContain('qqnt_check_env')

    await clickButton(wrapper, '下一步')
    await clickButton(wrapper, '选择文件夹')
    await clickButton(wrapper, '开始提取')
    expect(calls.find(call => call.method === 'qqnt_start').args).toEqual([
      '10001',
      'D:/out/10001',
      false,
      false,
    ])
    await vi.advanceTimersByTimeAsync(300)
    expect(calls.find(call => call.method === 'qqnt_get_progress')).toBeTruthy()
    // 真实消费投影进度字段：percentage=40 且 message=qq-progress
    const percentage = progressValue(wrapper)
    expect(percentage).toBe(40)
    expect(wrapper.text()).toContain('qq-progress')
    await clickButton(wrapper, '关闭')
    expect(calls.some(call => call.method === 'qqnt_cancel')).toBe(true)
    observations.push({ case: 'qqnt', percentage, methods: calls.map(call => call.method) })
  })

  it('runs Telegram and Douyin controllers, consumes progress fields and cancels on close', async () => {
    const ui = await loadFresh()
    ui.installPluginUI(data)
    const calls = bridgeStub({
      get_tg_import_progress: { status: 'done', progress: 37, message: 'tg-progress' },
      get_douyin_import_progress: { status: 'done', progress: 38, message: 'dy-progress' },
    })

    const tg = mountTracked(ui.wizards.TelegramWizard, { global: { stubs: { NModal: ModalStub } } })
    await tg.vm.open()
    await clickButton(tg, '开始导入')
    expect(calls.find(call => call.method === 'start_tg_import').args).toEqual([
      null,
      '',
      true,
    ])
    await vi.advanceTimersByTimeAsync(300)
    expect(progressValue(tg)).toBe(37)
    expect(tg.text()).toContain('tg-progress')
    // 终态输出（done）：标题切换为导入完成，按原代码仍可关闭并取消
    expect(tg.text()).toContain('导入完成')
    await clickButton(tg, '关闭')
    expect(calls.some(call => call.method === 'cancel_tg_import')).toBe(true)

    const dy = mountTracked(ui.wizards.DouyinWizard, { global: { stubs: { NModal: ModalStub } } })
    await dy.vm.open()
    await dy.find('input[type="password"]').setValue('fixture-cookie')
    await clickButton(dy, '开始下载')
    expect(calls.find(call => call.method === 'start_douyin_import').args).toEqual([
      'fixture-cookie',
    ])
    await vi.advanceTimersByTimeAsync(300)
    expect(progressValue(dy)).toBe(38)
    expect(dy.text()).toContain('dy-progress')
    expect(dy.text()).toContain('导入完成')
    await clickButton(dy, '关闭')
    expect(calls.some(call => call.method === 'cancel_douyin_import')).toBe(true)
    observations.push({ case: 'tg-douyin', methods: calls.map(call => call.method) })
  })

  it('runs the WeChat inspect/start/progress/cancel wiring', async () => {
    const ui = await loadFresh()
    ui.installPluginUI(data)
    const calls = bridgeStub({
      inspect_wechat_environment: { status: 'supported', account_directory_count: 1, accounts: [{ status: 'supported' }] },
      // 运行中：真实消费进度字段；关闭时仍在运行才取消（终态不取消）
      get_wechat_import_progress: { status: 'running', progress: 39, message: 'wx-progress' },
    })
    const wz = mountTracked(ui.wizards.WechatWizard, { global: { stubs: { NModal: ModalStub } } })
    await wz.vm.open()
    await clickButton(wz, '检测环境')
    expect(calls.some(call => call.method === 'inspect_wechat_environment')).toBe(true)
    await clickButton(wz, '开始导入')
    expect(calls.find(call => call.method === 'start_wechat_import').args).toEqual([
      null,
      true,
      null,
    ])
    await vi.advanceTimersByTimeAsync(300)
    expect(progressValue(wz)).toBe(39)
    expect(wz.text()).toContain('wx-progress')
    await clickButton(wz, '取消导入')
    expect(calls.some(call => call.method === 'cancel_wechat_import')).toBe(true)
    observations.push({ case: 'wechat', methods: calls.map(call => call.method) })
  })
})

describe('settings Vue network group', () => {
  it('starts LAN only when stopped, reflects running state, then stops', async () => {
    const ui = await loadFresh()
    ui.installPluginUI(data)
    let lanStatus = { status: 'stopped', port: 17852, clients: [], allow_secret_config: false }
    let lanStartArgs = null
    const calls = bridgeStub({
      lan_get_status: () => lanStatus,
      lan_start: (port, secret) => {
        lanStartArgs = [port, secret]
        lanStatus = { status: 'running', port, clients: [], allow_secret_config: false }
        return { ok: true, status: lanStatus }
      },
      lan_stop: () => {
        lanStatus = { ...lanStatus, status: 'stopped' }
        return { ok: true }
      },
    })
    const wrapper = mountTracked(ui.NetworkGroup, { global: { stubs: { NModal: ModalStub } } })
    await flushPromises()

    const lanToggle = () => wrapper.findAll('.n-checkbox').find(el => el.text().includes('开启互联访问'))
    const lanBox = lanToggle()
    expect(lanBox).toBeTruthy()
    // 停止态：初始未勾选，界面显示已停止
    expect(lanBox.classes()).not.toContain('n-checkbox--checked')
    expect(wrapper.text()).toContain('已停止')

    await lanToggle().trigger('click')
    await flushPromises()
    expect(lanStartArgs).toEqual([17852, ''])
    expect(wrapper.text()).toContain('运行中')
    expect(lanToggle().classes()).toContain('n-checkbox--checked')

    // 运行中再次点击应停止服务，而不是再次启动
    await lanToggle().trigger('click')
    await flushPromises()
    expect(calls.some(call => call.method === 'lan_stop')).toBe(true)
    expect(wrapper.text()).toContain('已停止')
    expect(lanToggle().classes()).not.toContain('n-checkbox--checked')
    observations.push({ case: 'lan', lanStartArgs, methods: calls.map(call => call.method) })
  })

  it('renders sync_test string result and check_sync_status diffs without calling get_sync_status', async () => {
    const ui = await loadFresh()
    ui.installPluginUI(data)
    const calls = bridgeStub({
      lan_get_status: { status: 'stopped', port: 17852, clients: [], allow_secret_config: false },
      check_sync_status: { ok: true, synced: false, local_count: 5, remote_count: 3, local_extra: 2, local_missing: 0 },
    })
    const wrapper = mountTracked(ui.NetworkGroup, { global: { stubs: { NModal: ModalStub } } })
    await flushPromises()
    ui.store.settings.sync_type = 'ftp'
    ui.store.settings.ftp_host = 'fixture.invalid'
    await wrapper.vm.$nextTick()

    await clickButton(wrapper, '测试连接')
    expect(wrapper.find('#s-sync-status').text()).toBe('连接成功')

    await clickButton(wrapper, '检查同步状态')
    expect(wrapper.find('#s-sync-status').text()).toContain('本地共 5 个，云端共 3 个，本地多余 2 个')
    // 现用方法为 check_sync_status，绝不回退到 get_sync_status
    expect(calls.some(call => call.method === 'get_sync_status')).toBe(false)
    observations.push({ case: 'sync-status', methods: calls.map(call => call.method) })
  })

  it('streams sync progress from projected fields and uploads through the fixed API', async () => {
    const ui = await loadFresh()
    ui.installPluginUI(data)
    let finish
    const calls = bridgeStub({
      lan_get_status: { status: 'stopped', port: 17852, clients: [], allow_secret_config: false },
      get_sync_progress: { status: 'uploading', current_file: 'one.webp', progress: 41, speed: 123 },
      sync_push: new Promise(resolve => { finish = resolve }),
    })
    const wrapper = mountTracked(ui.NetworkGroup, { global: { stubs: { NModal: ModalStub } } })
    await flushPromises()
    ui.store.settings.sync_type = 'ftp'
    ui.store.settings.ftp_host = 'fixture.invalid'
    await wrapper.vm.$nextTick()

    await clickButton(wrapper, '上传到远端')
    await flushPromises()
    expect(calls.some(call => call.method === 'sync_push')).toBe(true)
    await vi.advanceTimersByTimeAsync(300)
    expect(calls.some(call => call.method === 'get_sync_progress')).toBe(true)
    expect(progressValue(wrapper)).toBe(41)
    expect(wrapper.text()).toContain('one.webp')
    finish({ ok: true, uploaded: 1 })
    await flushPromises()
    observations.push({ case: 'sync-progress', methods: calls.map(call => call.method) })
  })
})

describe('settings Vue App shell gating', () => {
  it('does not mount the settings shell until the fixed snapshot validates', async () => {
    vi.resetModules()
    const App = (
      await import('../../src/ohmymeme/presentation/frontend/settings-vue/app/App.vue')
    ).default
    const invalidCalls = bridgeStub()
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({ contributions: [{ provider: 'unexpected' }] }),
    }))
    const wrapper = mountTracked(App)
    await flushPromises()
    expect(wrapper.find('#settings-nav').exists()).toBe(false)
    // 投影校验失败即中止，未挂壳也不会发起任何 Bridge 调用
    expect(invalidCalls).toEqual([])

    vi.resetModules()
    const EmptyApp = (
      await import('../../src/ohmymeme/presentation/frontend/settings-vue/app/App.vue')
    ).default
    const emptyCalls = bridgeStub({ get_settings: {} })
    globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => structuredClone(data) }))
    const empty = mountTracked(EmptyApp)
    await flushPromises()
    // 快照合法但 get_settings 缺 hotkey:string：fallback guard 仍不挂壳
    expect(empty.find('#settings-nav').exists()).toBe(false)
    expect(emptyCalls.some(call => call.method === 'get_settings')).toBe(true)

    vi.resetModules()
    const ValidApp = (
      await import('../../src/ohmymeme/presentation/frontend/settings-vue/app/App.vue')
    ).default
    bridgeStub({ get_settings: { hotkey: 'Ctrl+Alt+N' } })
    globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => structuredClone(data) }))
    const ok = mountTracked(ValidApp)
    await flushPromises()
    expect(ok.find('#settings-nav').exists()).toBe(true)
  })
})

afterAll(() => {
  if (process.env.OHMM_UI_REPORT) {
    writeFileSync(
      resolve(root, process.env.OHMM_UI_REPORT),
      JSON.stringify(
        {
          observations,
          scope:
            'vitest unit tests of the production settings-vue plugin-ui/bridge boundary and components; no browser or network',
        },
        null,
        2,
      ),
    )
  }
})
