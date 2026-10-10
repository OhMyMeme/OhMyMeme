<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { useDialog } from 'naive-ui'
import { showToast, markDirty, disabledPlugins } from '../../shared/store'

const dialog = useDialog()

// 插件列表与其声明式 UI 投影
const plugins = ref<any[]>([])
const contributions = ref<any[]>([])
// 版本回退下拉的当前选择（按插件 id）
const rollbackSel = reactive<Record<string, string>>({})
// 启用状态（按插件 id），save() 由此派生 disabled_plugins
const enabledState = reactive<Record<string, boolean>>({})
// 展开中的详情面板（按 provider）
const openDetails = reactive<Record<string, boolean>>({})
// 已加载的详情数据缓存（panel 配置值 + iframe 挂载标记）
const detailData = reactive<Record<string, any>>({})
const fileInput = ref<HTMLInputElement | null>(null)

const KIND_LABELS: Record<string, string> = { source: '导入来源', sync: '同步', transport: '传输' }

// 通用确认框
function confirmDialog(title: string, content: string): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    dialog.warning({
      title, content,
      positiveText: '确定', negativeText: '取消',
      onPositiveClick: () => resolve(true),
      onNegativeClick: () => resolve(false),
      onClose: () => resolve(false),
      onMaskClick: () => resolve(false),
    })
  })
}

// 从 enabledState 派生禁用插件 id 列表并写入共享 ref
function syncDisabled() {
  disabledPlugins.value = Object.keys(enabledState).filter((id) => !enabledState[id])
}

// 该 provider 的声明式注入项（详情面板/iframe）
function detailInjections(provider: string): any[] {
  return contributions.value
    .filter((item) => item.provider === provider)
    .map((item) => item.injection)
    .filter((inj) => inj.point === 'plugin_detail.panel' || inj.point === 'plugin_detail.iframe')
}

// 该 provider 是否有可展开详情
function hasDetail(provider: string): boolean {
  return detailInjections(provider).length > 0
}

// 元信息行文案
function metaText(plugin: any): string {
  const kind = KIND_LABELS[plugin.kind] || plugin.kind
  const origin = plugin.origin === 'bundled' ? '官方' : '第三方'
  return [kind, origin, plugin.version].filter(Boolean).join(' · ')
}

// 是否显示版本回退控件
function canRollback(plugin: any): boolean {
  return plugin.origin !== 'bundled' && (plugin.versions || []).length >= 2
}

// 拉取插件列表与 UI 投影并初始化状态
async function initPanel() {
  try {
    const [pluginsResp, uiResp] = await Promise.all([
      fetch('/api/plugins', { credentials: 'same-origin' }),
      fetch('/api/plugins/ui', { credentials: 'same-origin' }),
    ])
    if (!pluginsResp.ok) throw new Error(String(pluginsResp.status))
    const data: any = await pluginsResp.json()
    contributions.value = uiResp.ok ? ((await uiResp.json()).contributions || []) : []
    plugins.value = data.plugins || []
    Object.keys(enabledState).forEach((k) => delete enabledState[k])
    Object.keys(openDetails).forEach((k) => delete openDetails[k])
    plugins.value.forEach((p) => {
      enabledState[p.id] = p.enabled
      if (canRollback(p)) rollbackSel[p.id] = p.version
    })
    syncDisabled()
  } catch (_) {
    plugins.value = []
    contributions.value = []
  }
}

// 启用开关变更：更新派生禁用列表并标脏
function onToggleEnabled(id: string, value: boolean) {
  enabledState[id] = value
  syncDisabled()
  markDirty()
}

// 安装本地 ZIP 插件
async function installPluginFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input && input.files && input.files[0]
  if (!file) return
  try {
    const buffer = await file.arrayBuffer()
    const resp = await fetch('/api/plugins/install', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/octet-stream' }, body: buffer,
    })
    const data: any = await resp.json()
    if (!resp.ok || !data.ok) throw new Error(data.error || '安装失败')
    showToast('插件已安装：' + data.plugin + ' ' + data.version)
    initPanel()
  } catch (error: any) {
    showToast('安装失败：' + (error.message || error))
  } finally {
    input.value = ''
  }
}

// 卸载第三方插件
async function uninstallPlugin(pluginId: string) {
  if (!(await confirmDialog('卸载插件', '确定卸载 ' + pluginId + '？该插件目录会被删除，配置保留。'))) return
  try {
    const resp = await fetch('/api/plugins/uninstall', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: pluginId }),
    })
    const data: any = await resp.json()
    if (!resp.ok || !data.ok) throw new Error(data.error || '卸载失败')
    showToast('插件已卸载')
    initPanel()
  } catch (error: any) {
    showToast('卸载失败：' + (error.message || error))
  }
}

// 重载插件（下次使用时按磁盘版本启动）
async function reloadPlugin(pluginId: string) {
  try {
    const resp = await fetch('/api/plugins/reload', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: pluginId }),
    })
    if (!resp.ok) throw new Error(String(resp.status))
    showToast('插件已重载，下次使用时按磁盘版本启动')
  } catch (error: any) {
    showToast('重载失败：' + (error.message || error))
  }
}

// 切换到选定历史版本
async function rollbackPlugin(pluginId: string) {
  const version = rollbackSel[pluginId]
  if (!version) return
  try {
    const resp = await fetch('/api/plugins/rollback', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: pluginId, version }),
    })
    const data: any = await resp.json()
    if (!resp.ok || !data.ok) throw new Error(data.error || '切换失败')
    showToast('已切换到 ' + data.version + '，重启后生效')
    initPanel()
  } catch (error: any) {
    showToast('切换失败：' + (error.message || error))
  }
}

// 执行声明式动作（详情面板按钮/iframe 调用共用）
async function callDeclaredAction(provider: string, name: string, payload: any): Promise<any> {
  const resp = await fetch('/api/plugins/ui/action', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, name, payload }),
  })
  const data: any = await resp.json()
  if (!resp.ok || !data.ok) throw new Error(data.error || '动作失败')
  return data.result
}

// 按字段类型收集详情面板载荷
function collectPanelPayload(fields: any[], values: Record<string, any>): Record<string, any> {
  const payload: Record<string, any> = {}
  for (const field of fields || []) {
    if (field.type === 'bool') payload[field.key] = values[field.key] === true
    else if (field.type === 'int') {
      const parsed = Number.parseInt(values[field.key], 10)
      payload[field.key] = Number.isNaN(parsed) ? 0 : parsed
    } else payload[field.key] = values[field.key]
  }
  return payload
}

// 展开/收起某 provider 的详情；展开时拉取 panel 配置
async function toggleDetail(provider: string) {
  if (openDetails[provider]) {
    cleanupIframes(provider)
    openDetails[provider] = false
    return
  }
  const injections = detailInjections(provider)
  const panels: any[] = []
  const frames: any[] = []
  for (const inj of injections) {
    if (inj.point === 'plugin_detail.panel') {
      let values: Record<string, any> = {}
      try {
        const resp = await fetch('/api/plugins/ui/config?provider=' + encodeURIComponent(provider), { credentials: 'same-origin' })
        if (resp.ok) values = (await resp.json()).values || {}
      } catch (_) { values = {} }
      const fieldValues: Record<string, any> = {}
      const placeholders: Record<string, string> = {}
      for (const field of inj.fields || []) {
        const v = values[field.key]
        if (field.type === 'bool') fieldValues[field.key] = v === true
        else if (field.type === 'secret') { fieldValues[field.key] = ''; placeholders[field.key] = (v && v.configured) ? '已配置（留空保持不变）' : (field.placeholder || '') }
        else fieldValues[field.key] = (v !== undefined && v !== null) ? String(v) : ((field.default !== undefined && field.default !== null) ? String(field.default) : '')
      }
      panels.push({ injection: inj, values: fieldValues, placeholders })
    } else if (inj.point === 'plugin_detail.iframe') {
      frames.push({ injection: inj, loaded: false })
    }
  }
  detailData[provider] = { panels, frames }
  openDetails[provider] = true
}

// 保存详情面板配置
async function savePanel(provider: string, panel: any) {
  try {
    const resp = await fetch('/api/plugins/ui/config', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, values: collectPanelPayload(panel.injection.fields, panel.values) }),
    })
    const data: any = await resp.json()
    if (!resp.ok || !data.ok) throw new Error(data.error || '保存失败')
    showToast('配置已保存')
  } catch (error: any) {
    showToast('保存失败：' + (error.message || error))
  }
}

// 详情面板声明式动作
function runPanelAction(provider: string, panel: any, action: any) {
  callDeclaredAction(provider, action.name, collectPanelPayload(panel.injection.fields, panel.values)).then(
    () => showToast('已执行：' + action.label),
    (error: any) => showToast('执行失败：' + ((error && error.message) || error)),
  )
}

// iframe 的 postMessage 监听器集合（用于清理）
const iframeListeners: Record<string, Array<(e: MessageEvent) => void>> = {}

// 挂载沙箱 iframe：固定 postMessage 协议 + 速率/体积限制 + 动作 allowlist
function mountIframe(provider: string, frame: any, holder: HTMLElement) {
  if (frame.loaded) return
  frame.loaded = true
  const injection = frame.injection
  const el = document.createElement('iframe')
  el.className = 'plugin-ui-frame'
  el.setAttribute('sandbox', 'allow-scripts')
  el.style.height = (injection.height || 360) + 'px'
  const rate = { start: Date.now(), count: 0 }
  const entry = injection.entry.split('/').map((part: string) => encodeURIComponent(part)).join('/')
  const onMessage = (event: MessageEvent) => {
    if (event.source !== el.contentWindow) return
    const data: any = event.data
    if (!data || typeof data !== 'object') return
    if (data.type === 'ready') {
      el.contentWindow!.postMessage({ type: 'init', provider }, '*')
      return
    }
    if (data.type !== 'call' || typeof data.name !== 'string') return
    const now = Date.now()
    if (now - rate.start > 1000) { rate.start = now; rate.count = 0 }
    rate.count += 1
    if (rate.count > 20) return
    let size = 0
    try { size = JSON.stringify(data).length } catch (_) { return }
    if (size > 65536) return
    callDeclaredAction(provider, data.name, data.payload || {}).then(
      (result) => el.contentWindow!.postMessage({ type: 'result', id: data.id, result }, '*'),
      (error) => el.contentWindow!.postMessage({ type: 'error', id: data.id, error: String((error && error.message) || error) }, '*'),
    )
  }
  window.addEventListener('message', onMessage)
  ;(iframeListeners[provider] = iframeListeners[provider] || []).push(onMessage)
  el.src = '/api/plugins/' + encodeURIComponent(provider) + '/ui/' + entry
  holder.appendChild(el)
}

// 收起详情时移除该 provider 的所有 iframe 监听
function cleanupIframes(provider: string) {
  const listeners = iframeListeners[provider] || []
  listeners.forEach((fn) => window.removeEventListener('message', fn))
  iframeListeners[provider] = []
}

onMounted(initPanel)
onUnmounted(() => {
  Object.keys(iframeListeners).forEach(cleanupIframes)
})
defineExpose({ initPanel })

// 用户点击「加载自定义界面」后挂载 iframe（需显式触发）
function loadIframe(provider: string, frame: any, ev: Event) {
  const btn = ev.target as HTMLElement
  const holder = btn.parentElement?.querySelector('.plugin-ui-holder') as HTMLElement | null
  if (!holder || frame.loaded) return
  mountIframe(provider, frame, holder)
  ;(btn as HTMLButtonElement).disabled = true
  btn.textContent = '已加载'
}
</script>

<template>
  <div class="section">
    <div class="section-title">插件</div>
    <p style="font-size:11.5px;color:var(--muted);margin-bottom:10px;line-height:1.6">官方插件随应用分发并在后台独立进程运行。禁用或启用后<b>重启应用</b>生效；禁用的插件不会加载，也不会出现在对应导入/同步入口。第三方插件可通过本地 ZIP 包安装（安装前会再次确认），重载后按磁盘版本启动。</p>
    <div style="display:flex;gap:8px;margin-bottom:8px;align-items:center">
      <input ref="fileInput" type="file" accept=".zip,.omplugin" aria-label="选择插件安装包" style="font-size:12px" @change="installPluginFile">
    </div>

    <div v-if="!plugins.length" style="font-size:12px;color:var(--muted)">暂无插件</div>
    <div v-else style="display:flex;flex-direction:column;gap:6px">
      <template v-for="plugin in plugins" :key="plugin.id">
        <div class="plugin-row">
          <span class="plugin-info">
            <span class="plugin-name">{{ plugin.label }}</span>
            <span class="plugin-meta">{{ plugin.id }} · {{ metaText(plugin) }}</span>
          </span>
          <span class="plugin-actions">
            <button v-if="hasDetail(plugin.id)" class="btn btn-secondary btn-sm" @click="toggleDetail(plugin.id)">{{ openDetails[plugin.id] ? '收起' : '详情' }}</button>
            <template v-if="canRollback(plugin)">
              <select class="plugin-version" :value="rollbackSel[plugin.id]" @change="rollbackSel[plugin.id] = ($event.target as HTMLSelectElement).value">
                <option v-for="v in plugin.versions" :key="v" :value="v">{{ v }}</option>
              </select>
              <button class="btn btn-secondary btn-sm" @click="rollbackPlugin(plugin.id)">切换</button>
            </template>
            <button v-if="plugin.origin !== 'bundled'" class="btn btn-danger-outline btn-sm" @click="uninstallPlugin(plugin.id)">卸载</button>
            <button class="btn btn-secondary btn-sm" @click="reloadPlugin(plugin.id)">重载</button>
            <input type="checkbox" :checked="enabledState[plugin.id]" aria-label="启用插件" @change="onToggleEnabled(plugin.id, ($event.target as HTMLInputElement).checked)">
          </span>
        </div>

        <div v-if="openDetails[plugin.id]" class="plugin-detail" style="display:flex">
          <div v-for="(panel, pi) in (detailData[plugin.id]?.panels || [])" :key="'p' + pi" class="plugin-config">
            <div class="section-title">{{ panel.injection.label }}</div>
            <div class="import-injected-fields">
              <label v-for="field in panel.injection.fields" :key="field.key" class="injected-field">
                <span>{{ field.label }}{{ field.required ? ' *' : '' }}</span>
                <select v-if="field.type === 'enum'" :value="panel.values[field.key]" @change="panel.values[field.key] = ($event.target as HTMLSelectElement).value">
                  <option v-for="option in field.options" :key="option" :value="option">{{ option }}</option>
                </select>
                <input v-else-if="field.type === 'bool'" type="checkbox" :checked="panel.values[field.key] === true" @change="panel.values[field.key] = ($event.target as HTMLInputElement).checked">
                <input v-else :type="field.type === 'secret' ? 'password' : field.type === 'int' ? 'number' : 'text'" :placeholder="panel.placeholders[field.key] || field.placeholder || ''" :value="panel.values[field.key]" @input="panel.values[field.key] = ($event.target as HTMLInputElement).value">
              </label>
            </div>
            <div class="plugin-actions">
              <button class="btn btn-primary btn-sm" @click="savePanel(plugin.id, panel)">保存配置</button>
              <button v-for="action in (panel.injection.actions || [])" :key="action.name" class="btn btn-secondary btn-sm" @click="runPanelAction(plugin.id, panel, action)">{{ action.label }}</button>
            </div>
          </div>
          <div v-for="(frame, fi) in (detailData[plugin.id]?.frames || [])" :key="'f' + fi" class="plugin-config">
            <div class="section-title">{{ frame.injection.label || '自定义界面' }}</div>
            <button class="btn btn-secondary btn-sm" @click="loadIframe(plugin.id, frame, $event)">加载自定义界面</button>
            <div class="plugin-ui-holder"></div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
