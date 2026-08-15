import { ref, reactive } from 'vue'

export interface MenuItem {
  action: string
  label: string
  danger?: boolean
  disabled?: boolean
  divider?: boolean
}

export interface MenuTrigger {
  memeId?: number
  filename?: string
  memeName?: string
  favorited?: boolean
  isFolder?: boolean
  folderId?: number
  folderName?: string
  isRecent?: boolean
  isFavorite?: boolean
  isUncategorized?: boolean
}

const visible = ref(false)
const x = ref(0)
const y = ref(0)
const items = ref<MenuItem[]>([])
const trigger = ref<MenuTrigger>({})
const submenuVisible = ref(false)
const submenuItems = ref<MenuItem[]>([])
const submenuX = ref(0)
const submenuY = ref(0)

export function useContextMenu() {
  function show(newItems: MenuItem[], newTrigger: MenuTrigger, posX: number, posY: number) {
    items.value = newItems
    trigger.value = newTrigger
    x.value = posX
    y.value = posY
    visible.value = true
    submenuVisible.value = false
  }

  function hide() {
    visible.value = false
    submenuVisible.value = false
  }

  function showSubmenu(subItems: MenuItem[], sx: number, sy: number) {
    submenuItems.value = subItems
    submenuX.value = sx
    submenuY.value = sy
    submenuVisible.value = true
  }

  return {
    visible,
    x,
    y,
    items,
    trigger,
    submenuVisible,
    submenuItems,
    submenuX,
    submenuY,
    show,
    hide,
    showSubmenu,
  }
}
