<script setup lang="ts">
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import { NModal, NCheckbox, NRadio, NInput, NButton, NProgress } from 'naive-ui'
import { api } from '../../shared/bridge'
import { showToast } from '../../shared/store'
import { pluginUILabel, pluginProgressValue } from '../../shared/plugin-ui'

// 解包桥接返回值（api 可能返回 Promise 或同步值）
async function call(method: string, ...args: unknown[]): Promise<any> {
  return await api(method, ...args)
}

interface QqntAccount {
  qq: string
  nickname?: string
  count: number
}

// 覆盖层显隐
const visible = ref(false)
// 当前向导步骤
const step = ref(1)
// 错误文案
const error = ref('')
// 环境检测提示
const envMsg = ref('正在检查环境...')
// 手动选择操作区显隐
const showActions = ref(false)
// 手动选择提示
const actionsMsg = ref('')
// 账号列表
const accounts = ref<QqntAccount[]>([])
// 未找到已加载账号提示显隐
const showEmptyHint = ref(false)
// 选中账号
const selectedQQ = ref('')
// 下一步按钮禁用态
const nextDisabled = ref(false)
// 选择的保存根目录
const base = ref('')
// 计算的输出目录
const outputDir = ref('')
// 仅提取图片
const imageOnly = ref(false)
// 输出目录覆盖清空
const overwrite = ref(false)
// 进度标题
const progressTitle = ref('正在提取...')
// 进度说明
const progressMsg = ref('准备中')
// 进度百分比
const progressBar = ref(0)
// 进度百分比文案
const progressPct = ref('0%')
// 进度日志
const progressLog = ref('')
// 完成标题
const doneTitle = ref('提取完成')
// 完成详情
const doneDetail = ref('')
// 完成输出目录
const doneDir = ref('')
// 日志区元素
const logEl = ref<HTMLElement | null>(null)
// 进度轮询定时器
let pollTimer: ReturnType<typeof setInterval> | null = null

// 步骤 2 的下一步按钮文案取自宿主投影；投影缺失时回退
const nextText = computed(() => {
  if (step.value === 1) return '下一步'
  if (step.value === 2) {
    try { return pluginUILabel('qqnt_start') } catch { return '开始提取' }
  }
  return ''
})

// 停止轮询
function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

// 滚动日志到底部
watch(progressLog, async () => {
  await nextTick()
  if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
})

// 打开向导并检测环境
async function open() {
  visible.value = true
  error.value = ''
  step.value = 1
  showActions.value = false
  actionsMsg.value = ''
  showEmptyHint.value = false
  envMsg.value = '正在检查环境...'
  accounts.value = []
  selectedQQ.value = ''
  nextDisabled.value = false
  const st = await call('qqnt_check_env')
  renderEnv(st)
}

// 渲染环境检测结果
function renderEnv(st: any) {
  accounts.value = (st && st.accounts) ? st.accounts : []
  selectedQQ.value = ''
  showActions.value = true
  showEmptyHint.value = false
  nextDisabled.value = true

  if (!st || !st.ok) {
    envMsg.value = '未能定位 QQ 用户数据'
    const err = st && st.error
    if (err === 'config') actionsMsg.value = '未找到配置文件或无法读取，请手动选择：'
    else if (err === 'path_missing') actionsMsg.value = '用户数据目录不存在（可能已迁移或更换路径），请手动选择：'
    else actionsMsg.value = '无法检测 QQ 环境，请手动选择：'
    return
  }
  if (accounts.value.length === 0) {
    envMsg.value = '未找到已加载表情的账号'
    actionsMsg.value = '若你知道用户数据目录（含 QQ 号子目录的 UserDataSavePath 根目录），可手动选择：'
    showEmptyHint.value = true
    return
  }
  envMsg.value = '请选择要提取的账号：'
  actionsMsg.value = '若当前 Windows 用户不在列表中，请手动选择其用户数据目录（含 QQ 号子目录的根目录）：'
  nextDisabled.value = false
  selectedQQ.value = accounts.value[0]?.qq ?? ''
}

// 选择账号
function selectAccount(qq: string, checked: boolean) {
  if (checked) selectedQQ.value = qq
}

// 上一步
function prev() {
  if (step.value === 2) step.value = 1
}

// 下一步
function next() {
  if (step.value === 1) {
    if (!selectedQQ.value) { showToast('请先选择一个账号'); return }
    base.value = ''
    outputDir.value = ''
    step.value = 2
  } else if (step.value === 2) {
    if (!outputDir.value) { showToast('请先选择保存文件夹'); return }
    startExtract()
  }
}

// 选择配置文件
async function pickIni() {
  const r = await call('qqnt_pick_ini')
  if (r && !r.cancelled) renderEnv(r)
}

// 选择用户数据目录
async function pickUserdata() {
  const r = await call('qqnt_pick_userdata')
  if (r && !r.cancelled) renderEnv(r)
}

// 选择保存文件夹
async function pickBase() {
  const r = await call('qqnt_pick_base')
  if (!r || !r.ok) { showToast('选择失败'); return }
  base.value = r.base
  await recomputeDir()
}

// 重新计算输出目录
async function recomputeDir() {
  if (!base.value || !selectedQQ.value) return
  const r = await call('qqnt_default_dir', base.value, selectedQQ.value)
  if (r && r.ok) outputDir.value = r.dir
}

// 开始提取并轮询进度
async function startExtract() {
  progressTitle.value = '正在提取...'
  progressMsg.value = '准备中'
  progressBar.value = 0
  progressPct.value = '0%'
  progressLog.value = ''
  error.value = ''
  step.value = 3
  const r = await call('qqnt_start', selectedQQ.value, outputDir.value, imageOnly.value, overwrite.value)
  if (!r || !r.ok) { error.value = '启动失败'; return }
  pollTimer = setInterval(async () => {
    const s = await call('qqnt_get_progress')
    if (!s) return
    const progress = Number(pluginProgressValue('qqnt_get_progress', s, 'progress') ?? 0)
    progressBar.value = progress
    progressPct.value = progress + '%'
    progressMsg.value = String(pluginProgressValue('qqnt_get_progress', s, 'message') ?? '')
    if (s.log) progressLog.value = s.log.join('\n')
    if (s.status === 'done') {
      stopPoll()
      renderDone(s.result)
    } else if (s.status === 'cancelled') {
      stopPoll()
      renderDone(s.result, true)
    } else if (s.status === 'error') {
      stopPoll()
      progressTitle.value = '提取失败'
      error.value = s.error || '未知错误'
    }
  }, 300)
}

// 渲染提取结果
function renderDone(res: any, cancelled?: boolean) {
  step.value = 4
  doneTitle.value = cancelled ? '已取消' : '提取完成'
  if (!res) { doneDetail.value = '已取消或无结果'; doneDir.value = ''; return }
  let txt = '成功复制 ' + res.copied + ' / ' + res.total + ' 个'
  if (res.failed > 0) txt += '，失败 ' + res.failed + ' 个'
  if (res.skipped > 0) txt += '，跳过 ' + res.skipped + ' 个'
  if (res.renamed > 0) txt += '，修正扩展名 ' + res.renamed + ' 个'
  if (res.unrecognized > 0) txt += '，未识别 ' + res.unrecognized + ' 个'
  doneDetail.value = txt
  doneDir.value = res.output_dir || ''
}

// 打开输出目录
function openDir() {
  call('qqnt_open_dir', outputDir.value)
}

// 关闭向导并取消提取
function close() {
  visible.value = false
  stopPoll()
  call('qqnt_cancel')
}

// 模态层被 Esc 关闭时同步取消
function onUpdateShow(v: boolean) {
  if (!v) close()
}

onUnmounted(stopPoll)

defineExpose({ open })
</script>

<template>
  <NModal :show="visible" :mask-closable="false" :closable="false" @update:show="onUpdateShow">
    <div style="background:var(--surface);border-radius:var(--radius-lg);padding:24px 28px;width:460px;border:1px solid var(--border);box-shadow:var(--shadow-lg)">
      <div style="font-size:14px;font-weight:600;color:var(--fg);margin-bottom:14px">从电脑版 QQ 提取</div>

      <div v-show="step === 1">
        <div style="font-size:12px;color:var(--muted);margin-bottom:10px;line-height:1.6">{{ envMsg }}</div>
        <div style="max-height:220px;overflow-y:auto;margin-bottom:12px">
          <div v-for="a in accounts" :key="a.qq" class="check-row" style="padding:8px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);margin-bottom:6px;background:var(--card)">
            <NRadio :checked="selectedQQ === a.qq" :value="a.qq" @update:checked="(v) => selectAccount(a.qq, v)" />
            <span style="font-size:13px;color:var(--fg)">{{ a.nickname ? a.nickname + '（' + a.qq + '）' : a.qq }}</span>
            <span style="margin-left:auto;font-size:11px;color:var(--muted)">{{ a.count }} 个</span>
          </div>
          <div v-if="showEmptyHint" style="font-size:12px;color:var(--muted);line-height:1.6">请先在电脑版 QQ 中打开「收藏表情」，将表情全部加载（滑到底），再返回此处重试。</div>
        </div>
        <div v-show="showActions" style="margin-bottom:12px">
          <div style="font-size:12px;color:var(--muted);margin-bottom:8px">{{ actionsMsg }}</div>
          <div style="display:flex;gap:8px">
            <NButton size="small" @click="pickIni">选择配置文件</NButton>
            <NButton size="small" @click="pickUserdata">选择用户数据目录</NButton>
          </div>
        </div>
      </div>

      <div v-show="step === 2">
        <div style="font-size:12px;color:var(--muted);margin-bottom:10px;line-height:1.6">选择保存文件夹，将导出到其下「昵称（QQ号）_提取的表情」目录</div>
        <div style="display:flex;gap:8px;margin-bottom:10px">
          <NInput readonly :value="base" placeholder="选择保存文件夹" style="flex:1" :input-props="{ id: 'qqnt-out-base' }" />
          <NButton size="small" @click="pickBase">选择文件夹</NButton>
        </div>
        <label style="font-size:11.5px;color:var(--muted);margin-bottom:4px;display:block">输出目录</label>
        <NInput readonly :value="outputDir" style="margin-bottom:10px" :input-props="{ id: 'qqnt-out-dir' }" />
        <div class="check-row" style="margin-bottom:8px">
          <NCheckbox :checked="imageOnly" @update:checked="(v) => imageOnly = v">仅提取图片（跳过非图片文件）</NCheckbox>
        </div>
        <div class="check-row" style="margin-bottom:8px">
          <NCheckbox :checked="overwrite" @update:checked="(v) => overwrite = v">输出目录已存在时覆盖清空</NCheckbox>
        </div>
      </div>

      <div v-show="step === 3">
        <div style="font-size:13px;font-weight:500;color:var(--fg);margin-bottom:4px">{{ progressTitle }}</div>
        <div style="font-size:12px;color:var(--fg-secondary);margin-bottom:12px;word-break:break-all">{{ progressMsg }}</div>
        <NProgress type="line" :percentage="progressBar" :show-indicator="false" :height="8" />
        <div style="font-size:11.5px;color:var(--muted);margin-top:6px;margin-bottom:12px"><span>{{ progressPct }}</span></div>
        <div ref="logEl" style="max-height:160px;overflow-y:auto;font-size:11px;color:var(--muted);text-align:left;line-height:1.6;background:var(--bg);border-radius:var(--radius-sm);padding:8px 10px">{{ progressLog }}</div>
      </div>

      <div v-show="step === 4">
        <div style="font-size:13px;font-weight:500;color:var(--fg);margin-bottom:10px">{{ doneTitle }}</div>
        <div style="font-size:12.5px;color:var(--fg-secondary);line-height:1.8;margin-bottom:14px">{{ doneDetail }}<br>{{ doneDir }}</div>
        <NButton size="small" style="width:100%" @click="openDir">打开输出目录</NButton>
      </div>

      <div v-if="error" style="font-size:12px;color:var(--danger);margin-top:8px">{{ error }}</div>

      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
        <NButton v-if="step === 2" size="small" @click="prev">上一步</NButton>
        <NButton v-if="step <= 2" size="small" type="primary" :disabled="nextDisabled" @click="next">{{ nextText }}</NButton>
        <NButton size="small" quaternary @click="close">关闭</NButton>
      </div>
    </div>
  </NModal>
</template>
