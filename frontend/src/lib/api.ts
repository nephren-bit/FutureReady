import axios from 'axios'
import type {
  Session,
  SessionCreateResponse,
  EvaluationReport,
  PreliminaryEvaluation,
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
