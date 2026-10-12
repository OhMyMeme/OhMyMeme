import { ref } from 'vue'

export interface MenuItem {
  action: string
  label: string
  danger?: boolean
  disabled?: boolean
  divider?: boolean
  children?: MenuItem[]
}

export interface MenuTrigger {
  memeId?: number
  filename?: string
  memeName?: string
  favorited?: boolean | undefined
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

export function useContextMenu() {
  // 打开菜单：记录条目、上下文与坐标（子菜单由条目 children 携带）
  function show(newItems: MenuItem[], newTrigger: MenuTrigger, posX: number, posY: number) {
    items.value = newItems
    trigger.value = newTrigger
    x.value = posX
    y.value = posY
    visible.value = true
  }

  // 关闭菜单
  function hide() {
    visible.value = false
  }

  return {
    visible,
    x,
    y,
    items,
    trigger,
    show,
    hide,
  }
}
