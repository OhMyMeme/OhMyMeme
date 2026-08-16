import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { api } from '../utils/api'

export interface CollectionBuilderMeme {
  id: number
  filename: string
  name?: string
  original_name?: string | null
}

export interface CollectionOption {
  id: number
  name: string
  depth?: string
}

export interface CollectionConfirm {
  name: string
  memeIds: number[]
  existingId: number | null
}

const visible = ref(false)
const loading = ref(false)
const searchQuery = ref('')
const allMemes = ref<CollectionBuilderMeme[]>([])
const selectedIds = ref(new Set<number>())
const collectionName = ref('')
const collectionOptions = ref<CollectionOption[]>([])
const showDropdown = ref(false)
// 已选中的已有分组 id（null = 新建分组）
const selectedId = ref<number | null>(null)
const selectedName = ref('')
// 打开时预选的表情（右键「添加分组」带入），切换新建/已有分组时保留
const preselectIds = ref<number[]>([])

let onConfirmCallback: ((result: CollectionConfirm) => void) | null = null

export function useCollectionBuilder() {
  async function open(onConfirm: (result: CollectionConfirm) => void, preselect: number[] = []) {
    onConfirmCallback = onConfirm
    preselectIds.value = preselect
    visible.value = true
    loading.value = true
    searchQuery.value = ''
    selectedIds.value = new Set(preselect)
    collectionName.value = ''
    selectedId.value = null
    selectedName.value = ''
    showDropdown.value = false

    const [memes, collections] = await Promise.all([
      api('search_memes', '', [], null, 0, 999999),
      api('get_collections'),
    ])

    allMemes.value = memes || []
    collectionOptions.value = (collections || [])
      .filter((c: any) => c.id > 0)
      .map((c: any) => ({ id: c.id, name: c.name }))

    loading.value = false
  }

  function close() {
    visible.value = false
    showDropdown.value = false
  }

  function toggleMeme(memeId: number) {
    const newSet = new Set(selectedIds.value)
    if (newSet.has(memeId)) newSet.delete(memeId)
    else newSet.add(memeId)
    selectedIds.value = newSet
  }

  function selectCollection(opt: CollectionOption) {
    selectedId.value = opt.id
    selectedName.value = opt.name
    collectionName.value = opt.name
    showDropdown.value = false
    // 已有分组：加载其现有成员，并保留预选的表情（右键带入的新增项）
    api('get_collection_members', opt.id).then((members: any) => {
      const ids = new Set((members || []).map((m: any) => m.id))
      preselectIds.value.forEach(id => ids.add(id))
      selectedIds.value = ids
    })
  }
  function createNew() {
    selectedId.value = null
    selectedName.value = ''
    collectionName.value = ''
    selectedIds.value = new Set(preselectIds.value)
    showDropdown.value = false
  }

  // 用户手动改输入框文字 → 视为新建分组，取消已选分组
  watch(collectionName, (val) => {
    if (selectedId.value != null && val !== selectedName.value) {
      selectedId.value = null
    }
  })

  function confirm() {
    const name = collectionName.value.trim()
    if (!name) return
    const memeIds = Array.from(selectedIds.value)
    if (onConfirmCallback) {
      onConfirmCallback({ name, memeIds, existingId: selectedId.value })
    }
    close()
  }

  const filteredMemes = computed(() => {
    if (!searchQuery.value) return allMemes.value
    const q = searchQuery.value.toLowerCase()
    return allMemes.value.filter(m =>
      (m.name || m.original_name || m.filename).toLowerCase().includes(q)
    )
  })

  function onClickOutside(e: MouseEvent) {
    const dropdown = document.getElementById('cb-dropdown')
    const input = document.getElementById('cb-name')
    if (dropdown && !dropdown.contains(e.target as Node) &&
        input && !input.contains(e.target as Node)) {
      showDropdown.value = false
    }
  }

  onMounted(() => {
    document.addEventListener('click', onClickOutside)
  })

  onUnmounted(() => {
    document.removeEventListener('click', onClickOutside)
  })

  return {
    visible,
    loading,
    searchQuery,
    selectedIds,
    selectedId,
    collectionName,
    collectionOptions,
    showDropdown,
    allMemes,
    filteredMemes,
    open,
    close,
    toggleMeme,
    selectCollection,
    createNew,
    confirm,
  }
}
