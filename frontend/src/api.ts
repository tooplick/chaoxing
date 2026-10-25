const JSON_HEADERS = { 'Content-Type': 'application/json' }

interface ChapterInfo {
  id: string
  title: string
  done: boolean
  jobs?: Array<{ type: string; name: string; done: boolean }>
}

interface CourseTreeInfo {
  courseId: string
  title?: string
  chapters: ChapterInfo[]
}

import type {
  Account,
  AccountParams,
  AccountStatus,
  Course,
  NotificationConfig,
  TikuConfig,
} from './types'

async function request<T = any>(url: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(url, options)
  let data: any = null
  try {
    data = await res.json()
  } catch {
    data = null
  }
  if (!res.ok) {
    if (res.status === 401 && !url.startsWith('/api/auth/')) {
      window.dispatchEvent(new CustomEvent('auth-expired'))
    }
    throw new Error(data?.error || `请求失败 (${res.status})`)
  }
  return data as T
}

function post<T = any>(url: string, body?: unknown): Promise<T> {
  return request<T>(url, { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(body ?? {}) })
}

export const api = {
  // 管理员认证
  authState: () => request('/api/auth/state'),
  authSetup: (password: string) => post('/api/auth/setup', { password }),
  authLogin: (password: string) => post('/api/auth/login', { password }),
  authLogout: () => post('/api/auth/logout'),

  // 账号
  listAccounts: () => request<{ accounts: Account[] }>('/api/accounts'),
  createAccount: (payload: { label: string; username: string; password?: string; email?: string; cookies?: string }) =>
    post('/api/accounts', payload),
  updateAccount: (id: string, payload: Record<string, unknown>) =>
    request(`/api/accounts/${id}`, { method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify(payload) }),
  deleteAccount: (id: string) => request(`/api/accounts/${id}`, { method: 'DELETE' }),
  testAccount: (id: string) => post(`/api/accounts/${id}/test`),
  accountCourses: (id: string, refresh = false) =>
    request<{ ok: boolean; courses?: Course[]; msg?: string; fetched_at?: number }>(
      `/api/accounts/${id}/courses${refresh ? '?refresh=1' : ''}`,
    ),

  // 任务
  startTask: (id: string, payload: {
    course_ids: string[]
    chapters_courses?: string[]
    params?: Partial<AccountParams>
    force?: boolean
    save_default?: boolean
  }) => post(`/api/accounts/${id}/start`, payload),
  stopTask: (id: string) => post(`/api/accounts/${id}/stop`),
  restartTask: (id: string) => post(`/api/accounts/${id}/restart`),
  faceQr: (id: string, courseId?: string) =>
    post<{ ok: boolean; qr_base64?: string; chapter?: string; msg?: string }>(
      `/api/accounts/${id}/face-qr`, courseId ? { course_id: courseId } : {},
    ),
  faceConfig: (id: string, courseIds: string[]) =>
    post<{ ok: boolean; results?: Array<{ courseId: string; face_capture: boolean | null }>; msg?: string; error?: string }>(
      `/api/accounts/${id}/face-config`, { course_ids: courseIds },
    ),
  faceStatus: (id: string) => request<{ ok: boolean; done?: boolean; status?: number; code?: number | null; error?: string }>(`/api/accounts/${id}/face-status`),
  stopAll: () => post('/api/stop-all'),
  status: () => request<{ accounts: AccountStatus[] }>('/api/status'),
  logTail: (id: string, limit = 50) =>
    request<{ lines: Array<{ seq: number; text: string }> }>(`/api/accounts/${id}/logs/tail?limit=${limit}`),
  chapterTree: (id: string, refresh = false, withJobs = false) =>
    request<{ ok: boolean; courses?: CourseTreeInfo[]; msg?: string; error?: string }>(
      `/api/accounts/${id}/chapter-tree${refresh ? '?refresh=1' : ''}${withJobs ? '?jobs=1' : ''}`,
    ),
  chapterJobs: (id: string, courseId: string, chapterId: string) =>
    request<{ ok: boolean; jobs?: Array<{ type: string; name: string; done: boolean }>; msg?: string; error?: string }>(
      `/api/accounts/${id}/chapter-jobs?courseId=${courseId}&chapterId=${chapterId}`,
    ),

  // 设置
  getTiku: () => request<{ tiku: TikuConfig }>('/api/settings/tiku'),
  putTiku: (tiku: TikuConfig) =>
    request('/api/settings/tiku', { method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify({ tiku }) }),
  testTiku: () => post('/api/settings/tiku/test'),
  fetchModels: (tiku: TikuConfig) => post<{ ok: boolean; models?: string[]; msg?: string }>('/api/settings/tiku/models', { tiku }),
  getNotification: () => request<{ notification: NotificationConfig }>('/api/settings/notification'),
  putNotification: (notification: NotificationConfig) =>
    request('/api/settings/notification', { method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify({ notification }) }),
  getEmail: () => request<{ email: Record<string, string | number | boolean> }>('/api/settings/email'),
  testEmail: (to: string) => post<{ ok: boolean; msg?: string }>('/api/settings/email/test', { to }),
}
