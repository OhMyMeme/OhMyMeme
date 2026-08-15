import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '../utils/api'

export interface CollectionBuilderMeme {
  id: number
  filename: string
  original_name: string | null
}

export interface CollectionOption {
  id: number
  name: string
  depth?: string
}

const visible = ref(false)
const loading = ref(false)
const searchQuery = ref('')
const allMemes = ref<CollectionBuilderMeme[]>([])
const selectedIds = ref(new Set<number>())
const collectionName = ref('')
const collectionOptions = ref<CollectionOption[]>([])
const showDropdown = ref(false)

let onConfirmCallback: ((name: string, memeIds: number[]) => void) | null = null

export function useCollectionBuilder() {
  async function open(onConfirm: (name: string, memeIds: number[]) => void) {
    onConfirmCallback = onConfirm
    visible.value = true
    loading.value = true
    searchQuery.value = ''
    selectedIds.value = new Set()
    collectionName.value = ''
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
    collectionName.value = opt.name
    showDropdown.value = false
    api('get_collection_members', opt.id).then((members: any) => {
      selectedIds.value = new Set((members || []).map((m: any) => m.id))
    })
  }

  function createNew() {
    collectionName.value = ''
    selectedIds.value = new Set()
    showDropdown.value = false
  }

  function confirm() {
    const name = collectionName.value.trim()
    if (!name) return
    const ids = Array.from(selectedIds.value)
    if (onConfirmCallback) onConfirmCallback(name, ids)
    close()
  }

  const filteredMemes = computed(() => {
    if (!searchQuery.value) return allMemes.value
    const q = searchQuery.value.toLowerCase()
    return allMemes.value.filter(m =>
      (m.original_name || m.filename).toLowerCase().includes(q)
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
    collectionName,
    collectionOptions,
    showDropdown,
    filteredMemes,
    open,
    close,
    toggleMeme,
    selectCollection,
    createNew,
    confirm,
  }
}
