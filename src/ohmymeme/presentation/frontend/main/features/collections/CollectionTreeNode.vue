<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Collection } from '../../shared/types'

const props = defineProps<{
  node: Collection
  activeId: number | null
  depth: number
  collapsed: boolean
}>()

const emit = defineEmits<{
  select: [id: number]
  'folder-context': [e: MouseEvent, id: number, name: string]
}>()

const expanded = ref(props.depth < 2)
const hasChildren = computed(() => !!(props.node.children && props.node.children.length > 0))
// 折叠态头像：取分组名首 1-2 字符
const avatarText = computed(() => {
  const name = (props.node.name || '').trim()
  return name ? Array.from(name).slice(0, 2).join('') : '?'
})

function toggleExpand(e: MouseEvent) {
  e.stopPropagation()
  expanded.value = !expanded.value
}

function onChildContext(e: MouseEvent, id: number, name: string) {
  emit('folder-context', e, id, name)
}

function onMoreClick(e: MouseEvent) {
  emit('folder-context', e, props.node.id, props.node.name)
}
</script>

<template>
  <div class="tree-node">
    <div
      class="tree-row"
      :class="{ active: activeId === node.id }"
      :style="{ paddingLeft: (8 + depth * 14) + 'px' }"
      role="treeitem"
      tabindex="0"
      :aria-selected="activeId === node.id"
      @click="emit('select', node.id)"
      @contextmenu="emit('folder-context', $event, node.id, node.name)"
      @keydown.enter.prevent="emit('select', node.id)"
      @keydown.space.prevent="emit('select', node.id)"
    >
      <span
        v-if="hasChildren && !collapsed"
        class="tree-toggle"
        :class="{ expanded }"
        role="button"
        tabindex="0"
        :aria-expanded="expanded"
        @click="toggleExpand"
        @keydown.enter.prevent="toggleExpand"
        @keydown.space.prevent="toggleExpand"
      >▶</span>
      <span v-else-if="!collapsed" class="tree-toggle leaf"></span>
      <span class="tree-icon" :title="collapsed ? node.name : ''">
        <template v-if="collapsed">
          <span class="tree-avatar" :title="node.name">{{ avatarText }}</span>
        </template>
        <svg v-else-if="node.id === -4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>
        <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>
      </span>
      <span v-if="!collapsed" class="tree-label">{{ node.name }}</span>
      <span v-if="!collapsed" class="tree-count">{{ node.count || 0 }}</span>
      <button
        v-if="!collapsed"
        class="tree-more"
        aria-label="分组操作"
        @click.stop="onMoreClick"
      >⋯</button>
    </div>

    <div v-if="hasChildren && expanded && !collapsed" class="tree-children">
      <CollectionTreeNode
        v-for="child in node.children"
        :key="child.id"
        :node="child"
        :active-id="activeId"
        :depth="depth + 1"
        :collapsed="collapsed"
        @select="emit('select', $event)"
        @folder-context="onChildContext"
      />
    </div>
  </div>
</template>

<style scoped>
.tree-node {
  margin-bottom: 1px;
}

.tree-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background 0.1s;
  min-width: 0;
}

.tree-row:hover {
  background: var(--surface-2);
}

.tree-row.active {
  background: var(--primary-light);
  color: var(--primary);
}

.tree-toggle {
  width: 14px;
  height: 14px;
  font-size: 9px;
  color: var(--muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: transform 0.15s ease;
  user-select: none;
}

.tree-toggle.expanded {
  transform: rotate(90deg);
}

.tree-toggle.leaf {
  cursor: default;
}

.tree-icon {
  font-size: 13px;
  flex-shrink: 0;
}

.tree-avatar {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: var(--surface-2);
  color: var(--fg-secondary);
  font-size: 11px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  user-select: none;
}

.tree-row.active .tree-avatar {
  background: var(--primary-light);
  color: var(--primary-strong);
}

.tree-more {
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--muted);
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.1s;
}

.tree-row:hover .tree-more,
.tree-more:focus-visible {
  opacity: 1;
}

.tree-more:hover {
  background: var(--surface-2);
  color: var(--fg);
}

.tree-label {
  flex: 1;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.tree-count {
  font-size: 11px;
  color: var(--muted);
  flex-shrink: 0;
}

.tree-row.active .tree-count {
  color: var(--primary);
}
</style>
