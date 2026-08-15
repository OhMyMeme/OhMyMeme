<script setup lang="ts">
import { ref } from 'vue'
import type { Collection } from '../types'

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
const hasChildren = !!(props.node.children && props.node.children.length > 0)

function toggleExpand(e: MouseEvent) {
  e.stopPropagation()
  expanded.value = !expanded.value
}

function onChildContext(e: MouseEvent, id: number, name: string) {
  emit('folder-context', e, id, name)
}
</script>

<template>
  <div class="tree-node">
    <div
      class="tree-row"
      :class="{ active: activeId === node.id }"
      :style="{ paddingLeft: (8 + depth * 14) + 'px' }"
      @click="emit('select', node.id)"
      @contextmenu="emit('folder-context', $event, node.id, node.name)"
    >
      <span
        v-if="hasChildren && !collapsed"
        class="tree-toggle"
        :class="{ expanded }"
        @click="toggleExpand"
      >▶</span>
      <span v-else-if="!collapsed" class="tree-toggle leaf"></span>
      <span v-if="!collapsed" class="tree-icon">{{ node.id === -4 ? '🗂️' : '📁' }}</span>
      <span v-if="!collapsed" class="tree-label">{{ node.name }}</span>
      <span v-if="!collapsed" class="tree-count">{{ node.count || 0 }}</span>
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
