import axios from 'axios'
import type {
  AdminStats,
  AdminUserFilters,
  RegisterPayload,
  TokenResponse,
  User,
  UserListResponse,
  UserRole,
} from '../types/auth'
import type {
  Session,
  SessionCreateResponse,
  EvaluationReport,
  PreliminaryEvaluation,
  RecommendationList,
  PracticeSession,
  PracticeEvaluation,
  EvaluationMode,
} from '../types'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

export async function createSession(
  mode: 'presentation' | 'interview',
  language = 'vi'
): Promise<SessionCreateResponse> {
  const { data } = await api.post('/sessions', { mode, language })
  return data
}

export async function getSession(id: string): Promise<Session> {
  const { data } = await api.get(`/sessions/${id}`)
  return data
}

export async function uploadSlide(id: string, file: File): Promise<{ message: string }> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post(`/sessions/${id}/slide`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function uploadResume(id: string, file: File): Promise<{ message: string }> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post(`/sessions/${id}/resume`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function uploadVideo(id: string, file: File): Promise<{ message: string }> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post(`/sessions/${id}/video`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function getReport(id: string): Promise<EvaluationReport> {
  const { data } = await api.get(`/sessions/${id}/report`)
  return data
}

export async function getPreliminary(
  id: string,
  stage: string
): Promise<PreliminaryEvaluation> {
  const { data } = await api.get(`/sessions/${id}/preliminary/${stage}`)
  return data
}

export async function getRecommendations(id: string): Promise<RecommendationList> {
  const { data } = await api.get(`/sessions/${id}/recommendations`)
  return data
}

export async function retrySession(id: string): Promise<{ message: string }> {
  const { data } = await api.post(`/sessions/${id}/retry`)
  return data
}

export async function deleteSession(id: string): Promise<void> {
  await api.delete(`/sessions/${id}`)
}

export async function listSessions(): Promise<Session[]> {
  const { data } = await api.get('/sessions')
  return data
}

export async function getPracticeSession(id: string): Promise<PracticeSession> {
  const { data } = await api.get(`/practice/${id}`)
  return data
}

export async function getPracticeEvaluation(id: string): Promise<PracticeEvaluation> {
  const { data } = await api.get(`/practice/${id}/evaluation`)
  return data
}

// Creates a practice session ahead of streaming, so a slide deck/resume can
// be attached (via uploadPracticeSlide/uploadPracticeResume below) before the
// WebSocket ever opens. Optional -- a plain audio-only practice can skip
// this and let `WS /practice/stream` create its own session, as before.
export async function createPracticeSession(
  mode: EvaluationMode | null,
  language = 'vi'
): Promise<PracticeSession> {
  const { data } = await api.post('/practice', { mode, language })
  return data
}

export async function uploadPracticeSlide(id: string, file: File): Promise<PracticeSession> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post(`/practice/${id}/slide`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

// Points an <iframe>/<a> straight at the backend (proxied via /api, see
// vite.config.ts) rather than going through axios, since this is rendered
// directly by the browser, not consumed as JSON. The backend converts the
// attached .pptx to PDF on demand via LibreOffice (see routers/practice.py).
export function practiceSlidePreviewUrl(practiceSessionId: string): string {
  return `/api/practice/${practiceSessionId}/slide/preview`
}

export async function uploadPracticeResume(id: string, file: File): Promise<PracticeSession> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post(`/practice/${id}/resume`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

// `/api` is proxied to the backend for plain HTTP (see vite.config.ts), but a
// WebSocket needs its own absolute ws(s):// URL -- axios/fetch don't apply here.
// `practiceSessionId`, if given, reuses a session already created via
// `createPracticeSession` (with its slide/resume already attached) instead of
// having the backend create a fresh one.
export function practiceStreamUrl(
  language: string,
  audioFormat: string,
  practiceSessionId?: string
): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const base = `${protocol}//${window.location.host}/api/practice/stream?language=${encodeURIComponent(language)}&audio_format=${audioFormat}`
  return practiceSessionId ? `${base}&practice_session_id=${practiceSessionId}` : base
}

// ---------------------------------------------------------------------------
// Authentication and account administration
// ---------------------------------------------------------------------------

const TOKEN_STORAGE_KEY = 'futureready.token'

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY)
}

export function storeToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token)
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY)
}

// Attach the token to every request from one place. Doing it per call site
// guarantees that whichever call someone adds next is the one that forgets.
api.interceptors.request.use((config) => {
  const token = getStoredToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// A 401 means the token is gone, expired, or was signed with another key --
// none of which the user can fix by retrying. Drop it so the app falls back to
// the signed-out state instead of looping on requests that cannot succeed.
//
// 403 is deliberately NOT handled here: it means the token is perfectly valid
// and this account simply may not do that. Clearing it would sign the user out
// for clicking something they lack the role for, which is not the same thing.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) clearStoredToken()
    return Promise.reject(error)
  }
)

/** The server's message for a failed request, falling back to something readable. */
export function apiErrorMessage(error: unknown, fallback = 'Đã xảy ra lỗi, vui lòng thử lại.'): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  // FastAPI validation errors arrive as a list of {loc, msg, type}.
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string }
    if (typeof first?.msg === 'string') return first.msg.replace(/^Value error,\s*/, '')
  }
  return fallback
}

export async function register(payload: RegisterPayload): Promise<TokenResponse> {
  const { data } = await api.post('/auth/register', payload)
  return data
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const { data } = await api.post('/auth/login', { email, password })
  return data
}

export async function getCurrentUser(): Promise<User> {
  const { data } = await api.get('/auth/me')
  return data
}

export async function updateProfile(payload: {
  full_name?: string
  preferred_language?: string
}): Promise<User> {
  const { data } = await api.patch('/auth/me', payload)
  return data
}

export async function changePassword(
  currentPassword: string,
  newPassword: string
): Promise<void> {
  await api.patch('/auth/me/password', {
    current_password: currentPassword,
    new_password: newPassword,
  })
}

export async function changeOwnRole(role: UserRole): Promise<User> {
  const { data } = await api.patch('/auth/me/role', { role })
  return data
}

export async function acknowledgeRecordingConsent(): Promise<User> {
  const { data } = await api.post('/auth/me/recording-consent')
  return data
}

export async function adminListUsers(filters: AdminUserFilters = {}): Promise<UserListResponse> {
  const { data } = await api.get('/admin/users', { params: filters })
  return data
}

export async function adminUpdateUser(
  userId: string,
  payload: { role?: UserRole; is_verified?: boolean; is_active?: boolean }
): Promise<User> {
  const { data } = await api.patch(`/admin/users/${userId}`, payload)
  return data
}

export async function adminGetStats(): Promise<AdminStats> {
  const { data } = await api.get('/admin/stats')
  return data
}
