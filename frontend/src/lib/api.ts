import axios from 'axios'
import type {
  Session,
  SessionCreateResponse,
  EvaluationReport,
  PreliminaryEvaluation,
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
