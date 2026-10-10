import { ref } from 'vue'
import { api } from '../../shared/bridge'

export interface LanConfirmDevice {
  name?: string
  model?: string
  os?: string
  ver?: string
  _confirm_id?: string
}

// 待确认的 LAN 设备（由后端 evaluate_js 传入，MainWindow 挂 NModal 消费）
export const lanConfirmVisible = ref(false)
export const lanConfirmDevice = ref<LanConfirmDevice>({})

// 后端 window.showLanDeviceConfirm(device) 入口：标记待确认设备并显示弹窗
export function showLanDeviceConfirm(device: LanConfirmDevice) {
  if (lanConfirmVisible.value) return
  lanConfirmDevice.value = device || {}
  lanConfirmVisible.value = true
}

// 回传用户选择并关闭弹窗（保留确认 id 与取消路径）
export function confirmLanDevice(approved: boolean) {
  if (!lanConfirmVisible.value) return
  const confirmId = lanConfirmDevice.value._confirm_id || ''
  lanConfirmVisible.value = false
  lanConfirmDevice.value = {}
  api('lan_confirm_device', approved, confirmId)
}

// NModal 遮罩点击/键盘关闭统一按拒绝处理
export function onLanConfirmShowChange(show: boolean) {
  if (!show) confirmLanDevice(false)
}
