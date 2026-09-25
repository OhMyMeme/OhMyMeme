export interface Meme {
  id: number
  filename: string
  name: string
  file_hash: string
  from_stego?: number
  width: number
  height: number
  mime_type: string
  is_gif?: boolean
  is_animated?: boolean
  favorited?: boolean
  auto_play_gif?: boolean
  hover_to_play?: boolean
  ai_status?: string | null
}

export interface AiSuggestion {
  meme_id: number
  filename: string
  tags: string[]
  name: string
  description: string
  visible_text: string
  emotions: string[]
  intents: string[]
  provider: string
  created_at: string
  existing_tags: string[]
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
