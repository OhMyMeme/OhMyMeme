<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import type { MenuItem, MenuTrigger } from '../composables/useContextMenu'

const props = defineProps<{
  visible: boolean
  x: number
  y: number
  items: MenuItem[]
  trigger: MenuTrigger
  submenuVisible: boolean
  submenuItems: MenuItem[]
  submenuX: number
  submenuY: number
}>()

const emit = defineEmits<{
  action: [action: string, trigger: MenuTrigger]
  'show-submenu': [items: MenuItem[], x: number, y: number]
  close: []
}>()

const menuEl = ref<HTMLElement>()
const submenuEl = ref<HTMLElement>()
const pos = ref({ x: props.x, y: props.y })
const subPos = ref({ x: props.submenuX, y: props.submenuY })

// 把菜单位置钳制在窗口可见范围内（越界时翻转/内移）
function clamp(el: HTMLElement | undefined, x: number, y: number) {
  if (!el) return { x, y }
  const w = el.offsetWidth
  const h = el.offsetHeight
  const vw = window.innerWidth
  const vh = window.innerHeight
  let left = x
  let top = y
  if (left + w > vw) left = Math.max(4, vw - w - 4)
  if (top + h > vh) top = Math.max(4, vh - h - 4)
  if (left < 4) left = 4
  if (top < 4) top = 4
  return { x: left, y: top }
}

watch(() => [props.visible, props.items, props.x, props.y], async () => {
  if (props.visible) {
    await nextTick()
    pos.value = clamp(menuEl.value, props.x, props.y)
  }
})

watch(() => [props.submenuVisible, props.submenuItems, props.submenuX, props.submenuY], async () => {
  if (props.submenuVisible) {
    await nextTick()
    subPos.value = clamp(submenuEl.value, props.submenuX, props.submenuY)
  }
})

function onClick(action: string) {
  emit('action', action, {} as MenuTrigger)
}

function onSubmenuEnter(e: MouseEvent, action: string) {
  if (action === 'add-to-subgroup') {
    emit('show-submenu', [], e.clientX, e.clientY)
  }
}
</script>

<template>
  <div v-if="visible" class="ctx-overlay" @click="emit('close')" @contextmenu.prevent="emit('close')">
    <div ref="menuEl" class="ctx-menu" :style="{ left: pos.x + 'px', top: pos.y + 'px' }">
      <button
        v-for="item in items"
        :key="item.action"
        class="ctx-item"
        :class="{ danger: item.danger, disabled: item.disabled }"
        :disabled="item.disabled"
        @click.stop="onClick(item.action)"
        @mouseenter="onSubmenuEnter($event, item.action)"
      >
        {{ item.label }}
      </button>
    </div>
    <div v-if="submenuVisible" ref="submenuEl" class="ctx-submenu" :style="{ left: subPos.x + 'px', top: subPos.y + 'px' }">
      <button
        v-for="item in submenuItems"
        :key="item.action"
        class="ctx-item"
        @click.stop="onClick(item.action)"
      >
        {{ item.label }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.ctx-overlay {
  position: fixed;
  inset: 0;
  z-index: 700;
}

.ctx-menu, .ctx-submenu {
  position: fixed;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 4px;
  min-width: 160px;
  box-shadow: var(--shadow-lg);
  z-index: 701;
  animation: ctxFadeIn 0.1s ease;
}

@keyframes ctxFadeIn {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}

.ctx-item {
  display: block;
  width: 100%;
  padding: 7px 12px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--fg);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
  transition: background 0.1s;
}

.ctx-item:hover {
  background: var(--surface-2);
}

.ctx-item.danger {
  color: var(--danger);
}

.ctx-item.danger:hover {
  background: rgba(239, 68, 68, 0.1);
}

.ctx-item.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.ctx-item.disabled:hover {
  background: transparent;
}
</style>
