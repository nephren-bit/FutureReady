import axios from 'axios'
import type {
  AdminUser,
  AuthResponse,
  PeerNote,
  PeerReviewInvite,
  PeerReviewState,
  QualityReport,
  RubricScores,
  SelfPracticeSession,
  SelfPracticeSessionSummary,
  SelfPracticeProfile,
  SelfNote,
} from '../types'
import { AUTH_LOGOUT_EVENT, clearAuth, getStoredToken } from './auth'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

// Every route past /auth/register and /auth/login requires a token
// (Nhóm B, Task 13) -- attach it here once instead of at every call site.
api.interceptors.request.use(config => {
  const token = getStoredToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// A 401 means the token is missing, expired, or was revoked by a password
// change (routers/deps.py) -- drop the stale session everywhere at once
// instead of leaving the UI showing a logged-in state that the backend no
// longer honors. AuthContext listens for this to update React state; a
// plain localStorage write wouldn't trigger a re-render on its own.
api.interceptors.response.use(
  response => response,
  error => {
    if (error?.response?.status === 401) {
      clearAuth()
      window.dispatchEvent(new Event(AUTH_LOGOUT_EVENT))
    }
    return Promise.reject(error)
  }
)

// ---------------------------------------------------------------------------
// Accounts (Nhóm B) -- register, login, change password.
// ---------------------------------------------------------------------------

export async function registerAccount(email: string, password: string, fullName: string): Promise<AuthResponse> {
  const { data } = await api.post('/auth/register', { email, password, full_name: fullName })
  return data
}

export async function loginAccount(email: string, password: string): Promise<AuthResponse> {
  const { data } = await api.post('/auth/login', { email, password })
  return data
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<AuthResponse> {
  const { data } = await api.post('/auth/change-password', {
    old_password: oldPassword,
    new_password: newPassword,
  })
  return data
}

// ---------------------------------------------------------------------------
// Admin (Nhóm B, Task 13) -- list accounts, lock/unlock. No delete: locking
// via is_active is the removal mechanism.
// ---------------------------------------------------------------------------

export async function listAdminUsers(): Promise<AdminUser[]> {
  const { data } = await api.get('/admin/users')
  return data
}

export async function setUserActive(userId: string, isActive: boolean): Promise<AdminUser> {
  const { data } = await api.patch(`/admin/users/${userId}`, { is_active: isActive })
  return data
}

// Detection-quality dashboard (Nhom B Task 14 / Nhom C Task 18).
export async function getQualityReport(): Promise<QualityReport> {
  const { data } = await api.get('/admin/quality-report')
  return data
}

// ---------------------------------------------------------------------------
// Self Practice (specs/in-class-analysis) -- the product's sole API.
//
// (This file used to also call a Session API and a Live Practice API for a
// larger upload-and-score evaluation pipeline -- removed along with that
// pipeline.)
// ---------------------------------------------------------------------------

export async function listSelfPracticeSessions(): Promise<SelfPracticeSessionSummary[]> {
  const { data } = await api.get('/self-practice')
  return data
}

export async function createSelfPracticeSession(
  profile: SelfPracticeProfile,
  video: Blob,
  filename: string
): Promise<SelfPracticeSession> {
  const form = new FormData()
  form.append('profile', profile)
  form.append('video', video, filename)
  const { data } = await api.post('/self-practice', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function getSelfPracticeSession(id: string): Promise<SelfPracticeSession> {
  const { data } = await api.get(`/self-practice/${id}`)
  return data
}

export async function deleteSelfPracticeSession(id: string): Promise<void> {
  await api.delete(`/self-practice/${id}`)
}

// Points a plain <video src> straight at the backend (proxied via /api, see
// vite.config.ts) rather than going through axios -- the browser streams and
// seeks the file itself, which is why the token has to ride along as a
// query param instead of the usual Authorization header: a <video> element
// issues a plain browser GET and can't attach custom headers to it.
// routers/deps.py's get_current_user_from_header_or_query is the one
// dependency that accepts it this way; every other endpoint stays
// header-only.
export function selfPracticeVideoUrl(id: string): string {
  const token = getStoredToken()
  const query = token ? `?access_token=${encodeURIComponent(token)}` : ''
  return `/api/self-practice/${id}/video${query}`
}

export async function createSelfNote(sessionId: string, markSec: number, text = ''): Promise<SelfNote> {
  const { data } = await api.post(`/self-practice/${sessionId}/notes`, { mark_sec: markSec, text })
  return data
}

export async function updateSelfNote(
  sessionId: string,
  noteId: string,
  patch: { mark_sec?: number; text?: string }
): Promise<SelfNote> {
  const { data } = await api.patch(`/self-practice/${sessionId}/notes/${noteId}`, patch)
  return data
}

export async function deleteSelfNote(sessionId: string, noteId: string): Promise<void> {
  await api.delete(`/self-practice/${sessionId}/notes/${noteId}`)
}

// ---------------------------------------------------------------------------
// Peer review ("nhờ bạn chấm hộ", Nhom C) -- owner-facing invite management,
// then the rater-facing blind-review flow by token.
// ---------------------------------------------------------------------------

export async function createPeerInvite(sessionId: string): Promise<PeerReviewInvite> {
  const { data } = await api.post(`/self-practice/${sessionId}/peer-invites`)
  return data
}

export async function listPeerInvites(sessionId: string): Promise<PeerReviewInvite[]> {
  const { data } = await api.get(`/self-practice/${sessionId}/peer-invites`)
  return data
}

export async function revokePeerInvite(sessionId: string, inviteId: string): Promise<PeerReviewInvite> {
  const { data } = await api.delete(`/self-practice/${sessionId}/peer-invites/${inviteId}`)
  return data
}

export async function getPeerReviewInvite(token: string): Promise<PeerReviewState> {
  const { data } = await api.get(`/peer-review/invites/${token}`)
  return data
}

// Same query-param pattern as selfPracticeVideoUrl -- a plain <video src>
// can't carry the Authorization header. Named access_token, not token, so
// it never collides with this route's own {token} path parameter (the
// invite token) -- see routers/deps.py's get_current_user_from_header_or_query.
export function peerReviewVideoUrl(token: string): string {
  const authToken = getStoredToken()
  const query = authToken ? `?access_token=${encodeURIComponent(authToken)}` : ''
  return `/api/peer-review/invites/${token}/video${query}`
}

export async function addPeerMark(token: string, markSec: number, text?: string): Promise<PeerNote> {
  const { data } = await api.post(`/peer-review/invites/${token}/marks`, { mark_sec: markSec, text })
  return data
}

export async function submitPeerRubric(
  token: string,
  rubricScores: RubricScores,
  text?: string
): Promise<PeerReviewState> {
  const { data } = await api.post(`/peer-review/invites/${token}/submit`, {
    rubric_scores: rubricScores,
    text,
  })
  return data
}
