export interface Meme {
  id: number
  filename: string
  file_hash: string
  width: number
  height: number
  file_size: number
  mime_type: string
  original_name: string | null
  collection_sort_order?: number
  tags?: string[]
  is_animated?: boolean
  auto_play_gif?: boolean
  hover_to_play?: boolean
}

export interface Collection {
  id: number
  name: string
  count: number
  parent_id: number | null
  children?: Collection[]
}

export interface Tag {
  name: string
  count: number
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}
