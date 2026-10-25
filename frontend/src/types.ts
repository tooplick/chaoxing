export interface AccountParams {
  speed: number
  jobs: number
  notopen_action: 'retry' | 'continue'
  retry_interval: number
  work_redo_enabled: boolean
  work_max_retries: number
  add_learning_count: boolean
  target_count: number
}

export interface Account {
  id: string
  label: string
  username: string
  password: string
  email?: string
  owner: string | null
  params: AccountParams
  course_ids: string[]
  created_at: string
}

export type RunState = 'idle' | 'starting' | 'running' | 'finished' | 'stopped' | 'error'

export type BlockedReason = 'face' | 'cooldown' | null | undefined

export interface VideoProgress {
  name: string
  percent: number
  pos: string
  total: string
}

export interface AccountStatus {
  id: string
  label: string
  username: string
  state: RunState
  needs_attention?: boolean
  blocked_reason?: BlockedReason
  videos?: VideoProgress[]
  started_at?: string
  finished_at?: string | null
  exit_code?: number | null
  error?: string | null
  current_course?: string
  current_chapter?: string
  completed?: number
  failed?: number
  total?: number | null
}

export interface Course {
  courseId: string
  clazzId: string
  cpi: string
  title: string
  teacher: string
}

/** tiku.json 的值类型: 字符串/数字/布尔 */
export type TikuConfig = Record<string, string | number | boolean>

export interface NotificationConfig {
  provider?: string
  url?: string
  tg_chat_id?: string
}
