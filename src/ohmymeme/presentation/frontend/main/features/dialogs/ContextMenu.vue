<script setup lang="ts">
import { computed, h, onUnmounted, watch } from 'vue'
import type { VNodeChild } from 'vue'
import { NDropdown } from 'naive-ui'
import type { MenuItem, MenuTrigger } from './useContextMenu'

const props = defineProps<{
  visible: boolean
  x: number
  y: number
  items: MenuItem[]
  trigger: MenuTrigger
}>()

const emit = defineEmits<{
  action: [action: string, trigger: MenuTrigger]
  close: []
}>()

// MenuItem 转 NDropdown 选项（保留子菜单、危险色与禁用态）
function toOption(item: MenuItem): Record<string, unknown> {
  const option: Record<string, unknown> = {
    key: item.action,
    label: item.label,
    disabled: item.disabled === true,
    danger: item.danger === true,
  }
  if (item.children && item.children.length) option['children'] = item.children.map(toOption)
  return option
}

const options = computed(() => props.items.map(toOption))

// 危险项用主题 danger 色渲染（Naive 菜单无内建 danger 色）
function renderLabel(option: Record<string, unknown>): VNodeChild {
  const label = String(option['label'] ?? '')
  if (option['danger'] === true) return h('span', { style: 'color: var(--red-11)' }, label)
  return label
}

// 选中菜单项：动作交回父组件分发
function onSelect(key: string | number) {
  emit('action', String(key), props.trigger)
}

// 菜单关闭（选择/点外/键盘）统一通知父组件
function onShowChange(show: boolean) {
  if (!show) emit('close')
}

// 菜单打开期间屏蔽系统右键菜单并按旧行为关闭
function onDocContextMenu(e: MouseEvent) {
  e.preventDefault()
  emit('close')
}
watch(() => props.visible, (visible) => {
  if (visible) document.addEventListener('contextmenu', onDocContextMenu, true)
  else document.removeEventListener('contextmenu', onDocContextMenu, true)
})
onUnmounted(() => document.removeEventListener('contextmenu', onDocContextMenu, true))
</script>

<template>
  <NDropdown
    trigger="manual"
    placement="bottom-start"
    :show="visible"
    :x="x"
    :y="y"
    :options="options"
    :render-label="renderLabel"
    @select="onSelect"
    @update:show="onShowChange"
    @clickoutside="onShowChange(false)"
  />
</template>
