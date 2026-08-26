import axios from 'axios'
import type {
  SelfPracticeSession,
  SelfPracticeSessionSummary,
  SelfPracticeProfile,
  SelfNote,
} from '../types'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

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
// seeks the file itself.
export function selfPracticeVideoUrl(id: string): string {
  return `/api/self-practice/${id}/video`
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
