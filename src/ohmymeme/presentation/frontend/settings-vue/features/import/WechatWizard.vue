<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { NModal, NInput, NSelect, NButton, NProgress } from 'naive-ui'
import { api } from '../../shared/bridge'
import { showToast } from '../../shared/store'
import { pluginProgressValue } from '../../shared/plugin-ui'

// 解包桥接返回值（api 可能返回 Promise 或同步值）
async function call(method: string, ...args: unknown[]): Promise<any> {
  return await api(method, ...args)
}

interface WechatAccount {
  id: string
  path: string
  status: string
}

// 覆盖层显隐
const visible = ref(false)
// 阶段：config 配置 / progress 进度
const phase = ref<'config' | 'progress'>('config')
// 微信根目录
const root = ref('')
// 选中账号
const account = ref('')
// 可用账号列表
const accounts = ref<WechatAccount[]>([])
// 账号下拉显隐（仅多账号时）
const accountGroupVisible = ref(false)
// 配置阶段状态文案
const status = ref('')
// 配置阶段状态色
const statusMode = ref<'' | 'ok' | 'error'>('')
// 进度标题
const progressTitle = ref('正在导入...')
// 进度说明
const progressMsg = ref('准备中')
// 进度百分比
const pct = ref(0)
// 错误文案
const error = ref('')
// 进度阶段关闭按钮文案
const closeLabel = ref('取消导入')
// 导入按钮忙碌态
const busy = ref(false)
// 检测按钮忙碌态
const inspecting = ref(false)
// 进度轮询定时器
let pollTimer: ReturnType<typeof setInterval> | null = null

// 账号是否可用
function isUsable(a: WechatAccount): boolean {
  return a.status === 'supported' || a.status === 'encrypted_index'
}

// 账号下拉选项
function accountOptions(): { label: string; value: string }[] {
  return [{ label: '请选择账号', value: '' }, ...accounts.value.map((a) => ({ label: a.id, value: a.path }))]
}

// 停止轮询
function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

// 打开配置阶段
function open() {
  visible.value = true
  phase.value = 'config'
  error.value = ''
  status.value = ''
  statusMode.value = ''
  busy.value = false
  closeLabel.value = '取消导入'
}

// 选择微信目录
async function pickRoot() {
  const r = await call('pick_wechat_root')
  if (!r || r.cancelled) return
  if (r.ok) { root.value = r.path; showToast('微信目录已设置') }
  else showToast((r && r.error) || '选择失败')
}

// 渲染可用账号下拉
function renderAccounts(r: any) {
  const list: WechatAccount[] = ((r && r.accounts) || []).filter(isUsable)
  if (list.length > 1) {
    accountGroupVisible.value = true
    accounts.value = list
  } else {
    accountGroupVisible.value = false
    accounts.value = []
  }
  account.value = ''
}

// 当前选中账号（多账号下拉未显示时返回 null）
function selectedAccount(): string | null {
  if (!accountGroupVisible.value) return null
  return account.value || null
}

// 检测微信环境
async function inspect() {
  inspecting.value = true
  status.value = ''
  statusMode.value = ''
  try {
    const r = await call('inspect_wechat_environment', root.value || null)
    if (!r) { status.value = '检测失败'; statusMode.value = 'error'; return }
    if (r.status === 'supported' || r.status === 'encrypted_index') {
      const list = (r.accounts || []).filter(isUsable)
      status.value = '已检测到 ' + r.account_directory_count + ' 个账号，其中 ' + list.length + ' 个可用'
      statusMode.value = ''
    } else {
      status.value = r.reason || r.status || '未检测到'
      statusMode.value = 'error'
    }
    renderAccounts(r)
  } catch (e: any) {
    status.value = '检测失败: ' + (e.message || e)
    statusMode.value = 'error'
  } finally {
    inspecting.value = false
  }
}

// 切换到进度阶段
function showProgress() {
  phase.value = 'progress'
  error.value = ''
  progressTitle.value = '正在导入...'
  progressMsg.value = '准备中'
  pct.value = 0
  closeLabel.value = '取消导入'
}

// 开始导入并轮询进度
async function startImport() {
  busy.value = true
  status.value = ''
  statusMode.value = ''

  const accountSel = selectedAccount()
  if (accountGroupVisible.value && !accountSel) {
    busy.value = false
    status.value = '检测到多个账号，请选择账号'
    statusMode.value = 'error'
    return
  }

  let r: any
  try {
    r = await call('start_wechat_import', root.value || null, true, accountSel)
  } catch (e: any) {
    busy.value = false
    status.value = '启动失败: ' + (e.message || e)
    statusMode.value = 'error'
    return
  }
  if (!r || !r.ok) {
    busy.value = false
    status.value = '启动失败: ' + ((r && r.error) ? r.error : '未知错误')
    statusMode.value = 'error'
    return
  }

  showProgress()

  let nullCount = 0
  let pollInFlight = false
  pollTimer = setInterval(async () => {
    if (pollInFlight) return
    pollInFlight = true
    try {
      const s = await call('get_wechat_import_progress')
      if (!s) {
        nullCount++
        if (nullCount > 20) {
          stopPoll()
          progressTitle.value = '导入失败'
          error.value = '连接中断'
          status.value = '导入失败: 连接中断'
          statusMode.value = 'error'
          closeLabel.value = '关闭'
          busy.value = false
        }
        return
      }
      nullCount = 0

      pct.value = Number(pluginProgressValue('get_wechat_import_progress', s, 'progress') ?? 0)
      progressMsg.value = String(pluginProgressValue('get_wechat_import_progress', s, 'message') ?? '')

      if (s.status === 'done') {
        progressTitle.value = '导入完成'
        stopPoll()
        status.value = s.message || '导入完成'
        statusMode.value = ''
        closeLabel.value = '关闭'
        busy.value = false
      } else if (s.status === 'error') {
        progressTitle.value = '导入失败'
        stopPoll()
        const errCode = s.error_code ? ' [' + s.error_code + ']' : ''
        let errMsg = s.error || '未知错误'
        if (s.error_code === 'no_binary') {
          errMsg += '；请检查网络后重试（需从 GitHub 下载辅助工具）'
        } else if (s.error_code === 'no_key') {
          errMsg += '；请确认微信已登录且为支持的版本'
        }
        status.value = '导入失败: ' + errMsg + errCode
        statusMode.value = 'error'
        error.value = errMsg + errCode
        closeLabel.value = '关闭'
        busy.value = false
      } else if (s.status === 'cancelled') {
        progressTitle.value = '已取消'
        stopPoll()
        closeLabel.value = '关闭'
        busy.value = false
      }
    } catch (e: any) {
      stopPoll()
      progressTitle.value = '导入失败'
      error.value = e.message || '连接异常'
      closeLabel.value = '关闭'
      busy.value = false
    } finally {
      pollInFlight = false
    }
  }, 300)
}

// 关闭覆盖层，运行中则取消导入
function close() {
  visible.value = false
  busy.value = false
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
    call('cancel_wechat_import')
  }
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
    <div style="background:var(--gray-2);border-radius:var(--radius-lg);padding:24px 28px;width:440px;border:1px solid var(--gray-6);box-shadow:var(--shadow-lg)">
      <div v-show="phase === 'config'">
        <div style="font-size:14px;font-weight:600;color:var(--gray-12);margin-bottom:4px">从微信导入</div>
        <div style="font-size:12px;color:var(--gray-11);margin-bottom:12px;line-height:1.6">从微信电脑版本地缓存提取收藏表情（需微信正在运行，仅 Windows 支持）。微信文件目录是存放所有账号数据的根目录（xwechat_files），其下以 wxid_ 开头或含表情库（emoticon.db）的文件夹为各账号目录</div>
        <div class="form-group">
          <label>微信文件目录（根目录）</label>
          <NInput readonly placeholder="未设置，将自动检测" :value="root" :input-props="{ id: 's-wechat-root' }" />
        </div>
        <div style="display:flex;gap:8px;margin-bottom:10px">
          <NButton size="small" style="flex:1" @click="pickRoot">手动指定微信目录</NButton>
        </div>
        <div v-show="accountGroupVisible" class="form-group" style="margin-bottom:10px">
          <label>账号</label>
          <div id="s-wechat-account">
            <NSelect :value="account" :options="accountOptions()" @update:value="(v) => account = String(v ?? '')" />
          </div>
        </div>
        <div class="s-net-status" :class="{ 'status-ok': statusMode === 'ok', 'status-error': statusMode === 'error' }" style="font-size:11.5px;color:var(--gray-11);margin-bottom:10px;word-break:break-all;line-height:1.6">{{ status }}</div>
        <div style="display:flex;gap:8px">
          <NButton size="small" style="flex:1" :loading="inspecting" @click="inspect">检测环境</NButton>
          <NButton size="small" type="primary" style="flex:1" :loading="busy" @click="startImport">开始导入</NButton>
        </div>
      </div>
      <div v-show="phase === 'progress'" style="text-align:center">
        <div style="font-size:14px;font-weight:600;color:var(--gray-12);margin-bottom:4px">{{ progressTitle }}</div>
        <div style="font-size:12px;color:var(--gray-11);margin-bottom:12px;word-break:break-all">{{ progressMsg }}</div>
        <NProgress type="line" :percentage="pct" :show-indicator="false" :height="8" />
        <div style="font-size:11.5px;color:var(--gray-11);margin-top:6px;margin-bottom:16px">
          <span>{{ pct }}%</span>
        </div>
        <NButton size="small" @click="close">{{ closeLabel }}</NButton>
        <div v-if="error" style="font-size:12px;color:var(--red-11);margin-top:8px;word-break:break-all">{{ error }}</div>
      </div>
    </div>
  </NModal>
</template>
