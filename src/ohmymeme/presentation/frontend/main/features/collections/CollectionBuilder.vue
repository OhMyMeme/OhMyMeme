<script setup lang="ts">
import { computed, h, ref } from 'vue'
import { NAutoComplete, NButton, NInput, NModal, NSpin } from 'naive-ui'
import type { AutoCompleteOption, AutoCompleteProps } from 'naive-ui'
import { Check } from '@lucide/vue'
import { useCollectionBuilder } from './useCollectionBuilder'
import type { CollectionOption } from './useCollectionBuilder'

const cb = useCollectionBuilder()

// 创建项值前缀，避免与已有分组同名时选项 key 冲突
const CREATE_VALUE_PREFIX = '\u0000create:'
// 名称输入是否聚焦：聚焦且存在候选时展开候选列表
const nameFocused = ref(false)

interface NameOption extends AutoCompleteOption {
  label: string
  value: string
  create?: boolean
  option?: CollectionOption
}

// 名称候选：已输入名称时首项为创建新分组，随后为已有分组
const nameOptions = computed<NameOption[]>(() => {
  const name = cb.collectionName.value.trim()
  const options: NameOption[] = []
  if (name) options.push({ label: name, value: CREATE_VALUE_PREFIX + name, create: true })
  for (const o of cb.collectionOptions.value) options.push({ label: o.name, value: o.name, option: o })
  return options
})

// 候选列表是否展开：聚焦且存在候选时展开已有分组列表
function showNameOptions() {
  return nameFocused.value && nameOptions.value.length > 0
}

// 候选渲染：创建项加「创建新分组」提示，已有分组仅显示名称
function renderNameLabel(raw: Parameters<NonNullable<AutoCompleteProps['renderLabel']>>[0]) {
  // 本组件的候选均由 nameOptions 生成，按 NameOption 渲染
  const option = raw as unknown as NameOption
  if (!option.create) return option.label
  return h('span', { style: 'display:flex;align-items:center;justify-content:space-between;width:100%' }, [
    h('span', { style: 'color:var(--blue-9)' }, '「' + option.label + '」'),
    h('span', { style: 'font-size:11px;color:var(--gray-11);margin-left:8px' }, '创建新分组'),
  ])
}

// 输入变化：同步到分组名（选中已有分组时 watch 会回退为新建）
function onNameInput(value: string) {
  cb.collectionName.value = value
}

// 选择候选：创建项走新建并保留已输入名称，已有分组走选中并回填名称
function onNameSelect(value: unknown) {
  const opt = nameOptions.value.find(o => o.value === value)
  if (!opt) return
  if (opt.create) {
    cb.createNew()
    cb.collectionName.value = opt.label
  } else if (opt.option) {
    cb.selectCollection(opt.option)
    cb.collectionName.value = opt.option.name
  }
}

// 关闭分组编辑器且不把 Esc 传给窗口快捷键。
function onBoxKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') { e.stopPropagation(); cb.close() }
}

// NModal 遮罩点击等关闭统一按取消处理
function onShowChange(show: boolean) {
  if (!show) cb.close()
}
</script>

<template>
  <NModal
    :show="cb.visible.value"
    :close-on-esc="false"
    :theme-overrides="{ boxShadow: 'none' }"
    transform-origin="center"
    @update:show="onShowChange"
  >
    <div id="cb-box" role="dialog" aria-modal="true" aria-labelledby="cb-title" @keydown="onBoxKeydown">
      <div class="cb-header">
        <h2 id="cb-title">添加分组</h2>
        <NAutoComplete
          :value="cb.collectionName.value"
          :options="nameOptions"
          :render-label="renderNameLabel"
          :input-props="{ id: 'cb-name', autocomplete: 'off', spellcheck: 'false' }"
          :get-show="showNameOptions"
          placeholder="输入分组名或选择已有分组..."
          style="width: 100%"
          blur-after-select
          @update:value="onNameInput"
          @select="onNameSelect"
          @focus="nameFocused = true"
          @blur="nameFocused = false"
        />
      </div>

      <div class="cb-search">
        <NInput
          v-model:value="cb.searchQuery.value"
          :input-props="{ autocomplete: 'off', spellcheck: 'false' }"
          placeholder="搜索表情包添加到分组..."
          style="width: 100%"
        />
      </div>

      <div v-if="cb.loading.value" class="cb-loading"><NSpin size="small" /></div>

      <div v-else id="cb-cols">
        <div class="cb-col">
          <div class="cb-col-title">表情库 ({{ cb.filteredMemes.value.length }})</div>
          <div class="cb-col-list">
            <div
              v-for="meme in cb.filteredMemes.value"
              :key="meme.id"
              class="cb-meme"
              :class="{ selected: cb.selectedIds.value.has(meme.id) }"
              role="button"
              tabindex="0"
              :aria-pressed="cb.selectedIds.value.has(meme.id)"
              :aria-label="meme.name || meme.original_name || meme.filename"
              @click="cb.toggleMeme(meme.id)"
              @keydown.enter.prevent="cb.toggleMeme(meme.id)"
              @keydown.space.prevent="cb.toggleMeme(meme.id)"
            >
              <img :src="`/api/thumb/${meme.id}/${encodeURIComponent(meme.filename)}`" :alt="meme.name || meme.original_name || meme.filename" loading="lazy">
              <div v-if="cb.selectedIds.value.has(meme.id)" class="cb-check"><Check :size="10" /></div>
            </div>
            <div v-if="cb.filteredMemes.value.length === 0" class="cb-empty">没有表情包</div>
          </div>
        </div>

        <div class="cb-col">
          <div class="cb-col-title">已添加 ({{ cb.selectedIds.value.size }})</div>
          <div class="cb-col-list">
            <div
              v-for="meme in cb.allMemes.value.filter(m => cb.selectedIds.value.has(m.id))"
              :key="meme.id"
              class="cb-meme selected"
              role="button"
              tabindex="0"
              :aria-label="meme.name || meme.original_name || meme.filename"
              @click="cb.toggleMeme(meme.id)"
              @keydown.enter.prevent="cb.toggleMeme(meme.id)"
              @keydown.space.prevent="cb.toggleMeme(meme.id)"
            >
              <img :src="`/api/thumb/${meme.id}/${encodeURIComponent(meme.filename)}`" :alt="meme.name || meme.original_name || meme.filename" loading="lazy">
              <div class="cb-check"><Check :size="10" /></div>
            </div>
            <div v-if="cb.selectedIds.value.size === 0" class="cb-empty">点击左侧表情添加到分组</div>
          </div>
        </div>
      </div>

      <div v-if="cb.memberLoadError.value" class="cb-error">
        <span>分组信息加载失败，请重试</span>
        <NButton class="btn btn-sm btn-secondary" size="small" @click="cb.retryLoadMembers()">重试</NButton>
      </div>

      <div class="cb-footer">
        <NButton class="btn btn-secondary" @click="cb.close()">取消</NButton>
        <NButton class="btn btn-primary" type="primary" :disabled="cb.memberLoading.value || cb.memberLoadError.value || !cb.collectionName.value.trim()" @click="cb.confirm()">{{ cb.selectedId.value != null ? '保存到该分组' : '创建分组' }}</NButton>
      </div>
    </div>
  </NModal>
</template>

<style scoped>
#cb-box {
  background: var(--gray-2);
  border: 1px solid var(--gray-6);
  border-radius: var(--radius-lg);
  width: 640px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: var(--shadow-lg);
}

.cb-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--gray-6);
}

.cb-header h2 {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 10px;
}

.cb-search {
  padding: 12px 20px;
  border-bottom: 1px solid var(--gray-6);
}

.cb-loading {
  padding: 40px;
  text-align: center;
  color: var(--gray-11);
}

#cb-cols {
  flex: 1;
  display: flex;
  overflow: hidden;
  min-height: 0;
}

.cb-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid var(--gray-6);
}

.cb-col:last-child {
  border-right: none;
}

.cb-col-title {
  padding: 8px 14px;
  font-size: 11px;
  font-weight: 600;
  color: var(--gray-11);
  text-transform: uppercase;
  letter-spacing: 0.3px;
  border-bottom: 1px solid var(--gray-6);
  flex-shrink: 0;
}

.cb-col-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(70px, 1fr));
  grid-auto-rows: 70px;
  gap: 6px;
  align-content: start;
}

.cb-meme {
  position: relative;
  border-radius: var(--radius-sm);
  overflow: hidden;
  border: 2px solid var(--gray-6);
  cursor: pointer;
  transition: border-color 0.15s;
}

.cb-meme:hover {
  border-color: var(--blue-9);
}

.cb-meme.selected {
  border-color: var(--blue-9);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.3);
}

.cb-meme img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cb-check {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--blue-9);
  color: white;
  font-size: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.cb-empty {
  grid-column: 1 / -1;
  padding: 20px;
  text-align: center;
  font-size: 12px;
  color: var(--gray-11);
}

.cb-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 20px;
  font-size: 12px;
  color: var(--red-11);
  background: rgba(220, 38, 38, 0.08);
  border-top: 1px solid var(--gray-6);
}

.cb-footer {
  padding: 12px 20px;
  border-top: 1px solid var(--gray-6);
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
