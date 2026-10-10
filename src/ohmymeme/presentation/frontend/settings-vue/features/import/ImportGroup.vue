<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NButton, NCheckbox, NInput, NInputNumber, NSelect } from 'naive-ui'
import { showToast } from '../../shared/store'
import { getPluginUI } from '../../shared/plugin-ui'
import type { PluginInjectionField, PluginPanelInjection, PluginUIContribution } from '../../shared/plugin-ui'
import QqWizard from './QqWizard.vue'
import QqntWizard from './QqntWizard.vue'
import TelegramWizard from './TelegramWizard.vue'
import DouyinWizard from './DouyinWizard.vue'
import WechatWizard from './WechatWizard.vue'

// 五个固定导入行的向导引用
const qqRef = ref<InstanceType<typeof QqWizard> | null>(null)
const qqntRef = ref<InstanceType<typeof QqntWizard> | null>(null)
const tgRef = ref<InstanceType<typeof TelegramWizard> | null>(null)
const dyRef = ref<InstanceType<typeof DouyinWizard> | null>(null)
const wechatRef = ref<InstanceType<typeof WechatWizard> | null>(null)

interface SourcePlugin {
  id: string
  available?: boolean
  enabled?: boolean
}

interface InjectedRow {
  provider: string
  enabled: boolean
  injection: PluginPanelInjection
  values: Record<string, string | number | boolean>
}

// 插件来源可用/启用状态（按固定行插件 id 索引）
const sourceState = ref<Record<string, { available: boolean; enabled: boolean }>>({})
// 声明式注入导入行
const injectedRows = ref<InjectedRow[]>([])

// 无对应插件包时隐藏固定行
function rowHidden(pluginId: string): boolean {
  const s = sourceState.value[pluginId]
  return !!(s && !s.available)
}

// 插件被禁用时禁用固定行
function rowDisabled(pluginId: string): boolean {
  const s = sourceState.value[pluginId]
  return !!(s && s.available && !s.enabled)
}

// 固定行展示标签取自宿主投影（按 screen 匹配），投影缺失时回退到内置文案
function rowLabel(screen: string, fallback: string): string {
  const ui = getPluginUI()
  const row = ui?.contributions.find((item) => item.screen === screen)
  return row ? row.label : fallback
}

// 初始化注入行的初始值（enum 取首项，bool 取默认，数值转 number，其余取默认字符串）
function initValues(fields: PluginInjectionField[]): Record<string, string | number | boolean> {
  const values: Record<string, string | number | boolean> = {}
  for (const field of fields || []) {
    if (field.type === 'enum') values[field.key] = (field.options && field.options[0]) || ''
    else if (field.type === 'bool') values[field.key] = field.default === true
    else if (field.type === 'int') values[field.key] = typeof field.default === 'number' ? field.default : 0
    else values[field.key] = (field.default !== undefined && field.default !== null) ? String(field.default) : ''
  }
  return values
}

// 按字段类型收集动作载荷
function collectPayload(
  fields: PluginInjectionField[],
  values: Record<string, string | number | boolean>,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {}
  for (const field of fields || []) {
    const value = values[field.key]
    if (field.type === 'bool') payload[field.key] = value === true
    else if (field.type === 'int') {
      const parsed = Number.parseInt(String(value ?? 0), 10)
      payload[field.key] = Number.isNaN(parsed) ? 0 : parsed
    } else payload[field.key] = value
  }
  return payload
}

// 枚举字段下拉选项
function enumOptions(field: PluginInjectionField): { label: string; value: string }[] {
  return (field.options || []).map((option) => ({ label: option, value: option }))
}

// imports.row 注入判别（收窄到面板注入形状）
function isImportsRow(item: PluginUIContribution): item is Omit<PluginUIContribution, 'injection'> & { injection: PluginPanelInjection } {
  return item.injection.point === 'imports.row'
}

// 写入注入行字段值（保持 [] 动态键）
function setFieldValue(row: InjectedRow, key: string, value: string | number | boolean) {
  row.values[key] = value
}

// 执行插件声明式动作
async function callInjectedAction(provider: string, action: { name: string; label: string; kind: string }, fields: PluginInjectionField[], values: Record<string, string | number | boolean>) {
  try {
    const resp = await fetch('/api/plugins/ui/action', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, name: action.name, payload: collectPayload(fields, values) }),
    })
    const data: { ok?: boolean; error?: string } = await resp.json()
    if (!resp.ok || !data.ok) throw new Error(data.error || '动作失败')
    showToast(action.kind === 'query' ? '查询完成' : '已执行：' + action.label)
  } catch (error) {
    showToast('执行失败：' + (error instanceof Error ? error.message : String(error)))
  }
}

// 拉取插件来源与声明式注入并渲染
async function initImportSources() {
  let sources: SourcePlugin[] = []
  let contributions: PluginUIContribution[] = []
  try {
    const [sourceResp, uiResp] = await Promise.all([
      fetch('/api/plugins', { credentials: 'same-origin' }),
      fetch('/api/plugins/ui', { credentials: 'same-origin' }),
    ])
    if (sourceResp.ok) {
      const data: { plugins?: SourcePlugin[] } = await sourceResp.json()
      sources = data.plugins || []
    }
    if (uiResp.ok) {
      const data: { contributions?: PluginUIContribution[] } = await uiResp.json()
      contributions = data.contributions || []
    }
  } catch (error) {
    return
  }

  const map: Record<string, { available: boolean; enabled: boolean }> = {}
  sources.forEach((plugin) => { map[plugin.id] = { available: !!plugin.available, enabled: !!plugin.enabled } })
  sourceState.value = map

  injectedRows.value = contributions
    .filter(isImportsRow)
    .map((item) => ({
      provider: item.provider,
      enabled: item.enabled,
      injection: item.injection,
      values: initValues(item.injection.fields),
    }))
}

onMounted(initImportSources)
</script>

<template>
  <div class="section">
    <div class="section-title">导入表情包</div>
    <p style="font-size:11.5px;color:var(--muted);margin-bottom:10px;line-height:1.6">从其他软件导入表情包，点击对应来源开始</p>

    <NButton class="import-row" @click="qqRef?.open()">
      <span class="import-ico">
        <svg viewBox="0 0 1024 1024" fill="currentColor"><path d="M824.8 613.2c-16-51.4-34.4-94.6-62.7-165.3C766.5 262.2 689.3 112 511.5 112 331.7 112 256.2 265.2 261 447.9c-28.4 70.8-46.7 113.7-62.7 165.3-34 109.5-23 154.8-14.6 155.8 18 2.2 70.1-82.4 70.1-82.4 0 49 25.2 112.9 79.8 159-26.4 8.1-85.7 29.9-71.6 53.8 11.4 19.3 196.2 12.3 249.5 6.3 53.3 6 238.1 13 249.5-6.3 14.1-23.8-45.3-45.7-71.6-53.8 54.6-46.2 79.8-110.1 79.8-159 0 0 52.1 84.6 70.1 82.4 8.5-1.1 19.5-46.4-14.5-155.8z"/></svg>
      </span>
      <span class="import-name">手机版 QQ（ADB 拉取）</span>
    </NButton>

    <NButton v-if="!rowHidden('source.qqnt')" class="import-row" :class="{ 'import-row-disabled': rowDisabled('source.qqnt') }" :disabled="rowDisabled('source.qqnt')" @click="qqntRef?.open()">
      <span class="import-ico">
        <svg viewBox="0 0 1024 1024" fill="currentColor"><path d="M824.8 613.2c-16-51.4-34.4-94.6-62.7-165.3C766.5 262.2 689.3 112 511.5 112 331.7 112 256.2 265.2 261 447.9c-28.4 70.8-46.7 113.7-62.7 165.3-34 109.5-23 154.8-14.6 155.8 18 2.2 70.1-82.4 70.1-82.4 0 49 25.2 112.9 79.8 159-26.4 8.1-85.7 29.9-71.6 53.8 11.4 19.3 196.2 12.3 249.5 6.3 53.3 6 238.1 13 249.5-6.3 14.1-23.8-45.3-45.7-71.6-53.8 54.6-46.2 79.8-110.1 79.8-159 0 0 52.1 84.6 70.1 82.4 8.5-1.1 19.5-46.4-14.5-155.8z"/></svg>
      </span>
      <span class="import-name">{{ rowLabel('qqnt', '电脑版 QQ（QQNT 本地缓存）') }}</span>
      <span v-if="rowDisabled('source.qqnt')" class="import-status">已禁用（重启生效）</span>
    </NButton>

    <NButton v-if="!rowHidden('source.telegram')" class="import-row" :class="{ 'import-row-disabled': rowDisabled('source.telegram') }" :disabled="rowDisabled('source.telegram')" @click="tgRef?.open()">
      <span class="import-ico">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M21.7 3.3L2.9 10.6c-.8.3-.7 1.5.1 1.7l4.6 1.5 1.7 5.1c.2.7 1.1.9 1.6.4l2.4-2.4 4.4 3.2c.6.4 1.4.1 1.6-.6l3.5-15.1c.2-.9-.7-1.6-1.5-1.3zm-12.2 9.3l7.7-5.8c.3-.2.6.2.3.5l-6.2 6.3-.3 3.2-1.5-4.2z"/></svg>
      </span>
      <span class="import-name">{{ rowLabel('telegram', 'Telegram Desktop') }}</span>
      <span v-if="rowDisabled('source.telegram')" class="import-status">已禁用（重启生效）</span>
    </NButton>

    <NButton v-if="!rowHidden('source.douyin')" class="import-row" :class="{ 'import-row-disabled': rowDisabled('source.douyin') }" :disabled="rowDisabled('source.douyin')" @click="dyRef?.open()">
      <span class="import-ico">
        <svg viewBox="0 0 1024 1024" fill="currentColor"><path d="M937.4 423.9c-84 0-165.7-27.3-232.9-77.8v352.3c0 179.9-138.6 325.6-309.6 325.6S85.3 878.3 85.3 698.4c0-179.9 138.6-325.6 309.6-325.6 17.1 0 33.7 1.5 49.9 4.3v186.6c-15.5-6.1-32-9.2-48.6-9.2-76.3 0-138.2 65-138.2 145.3 0 80.2 61.9 145.3 138.2 145.3 76.2 0 138.1-65.1 138.1-145.3V0H707c0 134.5 103.7 243.5 231.6 243.5v180.3l-1.2 0.1"/></svg>
      </span>
      <span class="import-name">{{ rowLabel('douyin', '抖音') }}</span>
      <span v-if="rowDisabled('source.douyin')" class="import-status">已禁用（重启生效）</span>
    </NButton>

    <NButton v-if="!rowHidden('source.wechat')" class="import-row" :class="{ 'import-row-disabled': rowDisabled('source.wechat') }" :disabled="rowDisabled('source.wechat')" @click="wechatRef?.open()">
      <span class="import-ico">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M15.5 9.2c0-3-2.9-5.2-6.5-5.2S2.5 6.2 2.5 9.2c0 1.6.9 3 2.4 4l-.8 2.8 3.2-1.8c.8.2 1.6.4 2.5.4"/><path d="M21.5 14.6c0-2.5-2.4-4.4-5.4-4.4s-5.4 1.9-5.4 4.4 2.4 4.4 5.4 4.4c.7 0 1.4-.1 2-.3l2.8 1.6-.7-2.5c1.4-1 1.3-1.9 1.3-3.2z"/></svg>
      </span>
      <span class="import-name">{{ rowLabel('wechat', '微信') }}</span>
      <span v-if="rowDisabled('source.wechat')" class="import-status">已禁用（重启生效）</span>
    </NButton>

    <div id="import-injected" class="import-injected">
      <div v-for="(row, idx) in injectedRows" :key="idx" class="import-row import-injected-row" :class="{ 'import-row-disabled': !row.enabled }">
        <span class="plugin-info">
          <span class="import-name">{{ row.injection.label }}</span>
          <span v-if="row.injection.description" class="plugin-meta">{{ row.injection.description }}</span>
          <span v-if="!row.enabled" class="import-status">已禁用（重启生效）</span>
        </span>
        <div class="import-injected-fields">
          <div v-for="field in row.injection.fields" :key="field.key" class="injected-field">
            <label v-if="field.type !== 'bool'" :for="'import-field-' + row.provider + '-' + field.key">{{ field.label }}{{ field.required ? ' *' : '' }}</label>
            <NSelect
              v-if="field.type === 'enum'"
              size="small"
              :aria-label="field.label"
              :value="String(row.values[field.key] ?? '')"
              :options="enumOptions(field)"
              @update:value="(v) => setFieldValue(row, field.key, String(v ?? ''))"
            />
            <NCheckbox
              v-else-if="field.type === 'bool'"
              :checked="row.values[field.key] === true"
              @update:checked="(v) => setFieldValue(row, field.key, v)"
            >{{ field.label }}</NCheckbox>
            <NInputNumber
              v-else-if="field.type === 'int'"
              size="small"
              :show-button="false"
              :input-props="{ id: 'import-field-' + row.provider + '-' + field.key, 'aria-label': field.label, 'data-inject-field': field.key }"
              :value="Number(row.values[field.key] ?? 0)"
              @update:value="(v) => setFieldValue(row, field.key, v ?? 0)"
            />
            <NInput
              v-else
              size="small"
              :type="field.type === 'secret' ? 'password' : 'text'"
              :input-props="{ id: 'import-field-' + row.provider + '-' + field.key, 'aria-label': field.label, 'data-inject-field': field.key }"
              :placeholder="field.placeholder || ''"
              :value="String(row.values[field.key] ?? '')"
              @update:value="(v) => setFieldValue(row, field.key, v)"
            />
          </div>
        </div>
        <div class="plugin-actions">
          <NButton v-for="action in row.injection.actions" :key="action.name" size="small" type="primary" @click="callInjectedAction(row.provider, action, row.injection.fields, row.values)">{{ action.label }}</NButton>
        </div>
      </div>
    </div>
  </div>

  <QqWizard ref="qqRef" />
  <QqntWizard ref="qqntRef" />
  <TelegramWizard ref="tgRef" />
  <DouyinWizard ref="dyRef" />
  <WechatWizard ref="wechatRef" />
</template>
