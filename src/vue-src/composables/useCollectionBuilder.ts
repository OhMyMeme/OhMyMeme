import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { api, rememberFocus, restoreFocus } from '../utils/api'

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
// 已有分组成员加载中：期间禁用确认，避免以不完整的成员集提交
const memberLoading = ref(false)
// 分组成员加载失败：保留现有选择、禁用确认，提供重试
const memberLoadError = ref(false)
// 选择模式：'' = 构建模式（双栏），'add'/'move' = 批量加入/移动（仅选分组）
const pickMode = ref<'' | 'add' | 'move'>('')
const pickFromId = ref(0)

let onConfirmCallback: ((result: CollectionConfirm) => void) | null = null
let memberReqGen = 0

// 展平分组树（含子分组），子分组 label 带「父/子」路径；供 CollectionBuilder 下拉与右键子菜单共用
export function flattenCollections(items: any[], prefix: string, out: CollectionOption[]) {
  for (const c of items) {
    if (!c || c.id <= 0) continue
    const label = prefix ? prefix + '/' + c.name : c.name
    out.push({ id: c.id, name: c.name, depth: label })
    if (c.children && c.children.length) flattenCollections(c.children, label, out)
  }
}

// 收集 rootId 及其所有后代分组 id
function collectSubtreeIds(items: any[], rootId: number): number[] {
  for (const c of items) {
    if (!c || c.id <= 0) continue
    if (c.id === rootId) {
      const out: number[] = []
      const walk = (n: any) => {
        out.push(n.id)
        for (const ch of n.children || []) walk(ch)
      }
      walk(c)
      return out
    }
    const r = collectSubtreeIds(c.children || [], rootId)
    if (r.length) return r
  }
  return []
}

export function useCollectionBuilder() {
  async function open(onConfirm: (result: CollectionConfirm) => void, preselect: number[] = []) {
    onConfirmCallback = onConfirm
    preselectIds.value = preselect
    pickMode.value = ''
    pickFromId.value = 0
    memberReqGen++
    memberLoading.value = false
    memberLoadError.value = false
    rememberFocus()
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
    const opts: CollectionOption[] = []
    flattenCollections(collections || [], '', opts)
    collectionOptions.value = opts

    loading.value = false
    await nextTick()
    const nameInput = document.getElementById('cb-name') as HTMLInputElement | null
    nameInput?.focus()
    nameInput?.select()
  }

  // 选择模式打开：不加载表情库，仅选分组后确认（批量加入/移动）
  async function openPick(onConfirm: (result: CollectionConfirm) => void, mode: 'add' | 'move', preselect: number[] = [], fromId = 0) {
    onConfirmCallback = onConfirm
    preselectIds.value = preselect
    pickMode.value = mode
    pickFromId.value = fromId
    memberReqGen++
    memberLoading.value = false
    memberLoadError.value = false
    rememberFocus()
    visible.value = true
    loading.value = true
    searchQuery.value = ''
    selectedIds.value = new Set(preselect)
    collectionName.value = ''
    selectedId.value = null
    selectedName.value = ''
    showDropdown.value = false

    const collections = await api('get_collections')
    const opts: CollectionOption[] = []
    flattenCollections(collections || [], '', opts)
    // move 模式排除源分组及其整棵子树（移入后代等于移出后又加回递归视图，后端同样拒绝）
    const excluded =
      mode === 'move' && fromId > 0 ? collectSubtreeIds(collections || [], fromId) : []
    collectionOptions.value = excluded.length
      ? opts.filter(o => !excluded.includes(o.id))
      : opts

    loading.value = false
    await nextTick()
    const nameInput = document.getElementById('cb-name') as HTMLInputElement | null
    nameInput?.focus()
    nameInput?.select()
  }

  function close() {
    memberReqGen++
    memberLoading.value = false
    memberLoadError.value = false
    visible.value = false
    showDropdown.value = false
    pickMode.value = ''
    pickFromId.value = 0
    restoreFocus()
  }

  function toggleMeme(memeId: number) {
    const newSet = new Set(selectedIds.value)
    if (newSet.has(memeId)) newSet.delete(memeId)
    else newSet.add(memeId)
    selectedIds.value = newSet
  }

  function loadMembers(cid: number) {
    const gen = ++memberReqGen
    memberLoading.value = true
    memberLoadError.value = false
    api('get_collection_members', cid).then((members: any) => {
      if (gen !== memberReqGen || cid !== selectedId.value) return
      memberLoading.value = false
      if (members == null) {
        // 加载失败：保留现有选择，标记错误并阻止提交不完整的成员集
        memberLoadError.value = true
        return
      }
      const ids = new Set((members || []).map((m: any) => m.id))
      preselectIds.value.forEach(id => ids.add(id))
      selectedIds.value = ids
    })
  }

  function selectCollection(opt: CollectionOption) {
    selectedId.value = opt.id
    // selectedName 与输入框显示值保持一致（含父路径），避免 watch 误判为手动改名
    selectedName.value = opt.depth || opt.name
    collectionName.value = opt.depth || opt.name
    showDropdown.value = false
    // 选择模式不加载成员（批量操作为追加/移动语义，非覆盖）
    if (pickMode.value) return
    // 已有分组：加载其现有成员，并保留预选的表情（右键带入的新增项）
    loadMembers(opt.id)
  }
  function createNew() {
    memberReqGen++
    memberLoading.value = false
    memberLoadError.value = false
    selectedId.value = null
    selectedName.value = ''
    // 保留输入框中的名称，直接确认即创建该分组
    selectedIds.value = new Set(pickMode.value ? selectedIds.value : preselectIds.value)
    showDropdown.value = false
  }
  function retryLoadMembers() {
    if (selectedId.value != null) loadMembers(selectedId.value)
  }

  // 用户手动改输入框文字 → 视为新建分组，取消已选分组并恢复预选
  watch(collectionName, (val) => {
    if (selectedId.value != null && val !== selectedName.value) {
      memberReqGen++
      memberLoading.value = false
      memberLoadError.value = false
      selectedId.value = null
      selectedIds.value = new Set(preselectIds.value)
    }
  })

  function confirm() {
    const name = collectionName.value.trim()
    if (!name || memberLoading.value || memberLoadError.value) return
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

  // 分组下拉按输入词过滤（匹配组名或父路径）
  const filteredCollectionOptions = computed(() => {
    const q = collectionName.value.trim().toLowerCase()
    if (!q) return collectionOptions.value
    return collectionOptions.value.filter(o =>
      o.name.toLowerCase().includes(q) || (o.depth || '').toLowerCase().includes(q)
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
    memberLoading,
    memberLoadError,
    searchQuery,
    selectedIds,
    selectedId,
    collectionName,
    collectionOptions,
    filteredCollectionOptions,
    showDropdown,
    allMemes,
    filteredMemes,
    pickMode,
    pickFromId,
    open,
    openPick,
    close,
    toggleMeme,
    selectCollection,
    createNew,
    retryLoadMembers,
    confirm,
  }
}
