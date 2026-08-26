import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { motion } from 'motion/react'
import { ArrowLeft, Warning, NotePencil, PencilSimple, Trash, Check, X } from '@phosphor-icons/react'
import { getSelfPracticeSession, selfPracticeVideoUrl, createSelfNote, updateSelfNote, deleteSelfNote } from '../lib/api'
import type { SelfPracticeSession, SelfNote, PoseFeature } from '../types'
import { SELF_PRACTICE_METRIC_LABELS } from '../types'
import VideoTimeline from '../components/VideoTimeline'
import { cn } from '../lib/utils'

type PoseMetricName = Exclude<keyof PoseFeature, 'profile' | 'profile_version' | 'frames_analyzed' | 'pose_detected_ratio' | 'sampling_rate_hz' | 'sampling_warning'>

const METRIC_NAMES = Object.keys(SELF_PRACTICE_METRIC_LABELS) as PoseMetricName[]

export default function SessionReview() {
  const { id } = useParams<{ id: string }>()

  const [session, setSession] = useState<SelfPracticeSession | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [currentSec, setCurrentSec] = useState(0)
  const [durationSec, setDurationSec] = useState(0)
  const [draftText, setDraftText] = useState('')
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null)
  const [editingText, setEditingText] = useState('')
  const [noteError, setNoteError] = useState<string | null>(null)

  const videoRef = useRef<HTMLVideoElement | null>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchSession = useCallback(async () => {
    if (!id) return
    try {
      const data = await getSelfPracticeSession(id)
      setSession(data)
      setFetchError(null)
    } catch (err: any) {
      setFetchError(err?.response?.data?.detail || 'Không thể tải phiên luyện tập')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    fetchSession()
  }, [fetchSession])

  useEffect(() => {
    if (!session || session.state !== 'processing') {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
      return
    }
    pollingRef.current = setInterval(fetchSession, 3000)
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
    }
  }, [session?.state, fetchSession])

  const handleSeek = useCallback((sec: number) => {
    if (videoRef.current) videoRef.current.currentTime = sec
    setCurrentSec(sec)
  }, [])

  const handleAddNote = useCallback(async () => {
    if (!id) return
    setNoteError(null)
    try {
      const note = await createSelfNote(id, currentSec, draftText)
      setSession(prev => (prev ? { ...prev, notes: [...prev.notes, note].sort((a, b) => a.mark_sec - b.mark_sec) } : prev))
      setDraftText('')
    } catch (err: any) {
      setNoteError(err?.response?.data?.detail || 'Không thể thêm ghi chú')
    }
  }, [id, currentSec, draftText])

  const startEditing = useCallback((note: SelfNote) => {
    setEditingNoteId(note.note_id)
    setEditingText(note.text)
  }, [])

  const handleSaveEdit = useCallback(async () => {
    if (!id || !editingNoteId) return
    try {
      const updated = await updateSelfNote(id, editingNoteId, { text: editingText })
      setSession(prev =>
        prev ? { ...prev, notes: prev.notes.map(n => (n.note_id === updated.note_id ? updated : n)) } : prev
      )
      setEditingNoteId(null)
    } catch (err: any) {
      setNoteError(err?.response?.data?.detail || 'Không thể cập nhật ghi chú')
    }
  }, [id, editingNoteId, editingText])

  const handleDeleteNote = useCallback(async (noteId: string) => {
    if (!id) return
    try {
      await deleteSelfNote(id, noteId)
      setSession(prev => (prev ? { ...prev, notes: prev.notes.filter(n => n.note_id !== noteId) } : prev))
    } catch (err: any) {
      setNoteError(err?.response?.data?.detail || 'Không thể xóa ghi chú')
    }
  }, [id])

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-6 py-16 flex items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    )
  }

  if (fetchError || !session) {
    return (
      <div className="max-w-4xl mx-auto px-6 py-16">
        <Link to="/app/luyen-tap" className="inline-flex items-center gap-2 text-sm text-text-secondary hover:text-text-primary mb-8">
          <ArrowLeft className="h-4 w-4" />
          Quay lại
        </Link>
        <div className="rounded-xl border border-error/20 bg-error-light p-8 text-center">
          <Warning className="h-10 w-10 text-error mx-auto mb-3" weight="bold" />
          <p className="text-sm font-medium text-error">{fetchError || 'Không tìm thấy phiên'}</p>
        </div>
      </div>
    )
  }

  const isProcessing = session.state === 'processing'
  const isFailed = session.state === 'failed'
  const isCompleted = session.state === 'completed'

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mb-6">
        <Link to="/app/luyen-tap" className="inline-flex items-center gap-2 text-sm text-text-secondary hover:text-text-primary mb-4">
          <ArrowLeft className="h-4 w-4" />
          Ghi phiên mới
        </Link>
        <h1 className="text-2xl font-semibold text-text-primary">Xem lại phiên luyện tập</h1>
      </motion.div>

      {isProcessing && (
        <div className="rounded-xl border border-border bg-surface p-6 flex items-center gap-4">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          <p className="text-sm text-text-secondary">Đang phân tích bản ghi -- trang sẽ tự cập nhật khi xong.</p>
        </div>
      )}

      {isFailed && (
        <div className="rounded-xl border border-error/20 bg-error-light p-6">
          <div className="flex items-start gap-3">
            <Warning className="h-5 w-5 text-error shrink-0 mt-0.5" weight="bold" />
            <div>
              <p className="text-sm font-semibold text-error">Phân tích thất bại</p>
              {session.error_message && <p className="mt-1 text-xs text-error/80">{session.error_message}</p>}
            </div>
          </div>
        </div>
      )}

      {isCompleted && (
        <>
          <div className="rounded-xl border border-border bg-surface p-5 mb-6">
            <video
              ref={videoRef}
              src={selfPracticeVideoUrl(session.id)}
              controls
              className="w-full rounded-lg bg-black aspect-video mb-4"
              onLoadedMetadata={e => setDurationSec(e.currentTarget.duration)}
              onTimeUpdate={e => setCurrentSec(e.currentTarget.currentTime)}
            />
            <VideoTimeline
              durationSec={durationSec}
              currentSec={currentSec}
              events={session.events}
              notes={session.notes}
              onSeek={handleSeek}
            />
          </div>

          {session.pose_feature?.sampling_warning && (
            <div className="mb-6 rounded-xl border border-warning/20 bg-warning-light p-4 flex items-center gap-3">
              <Warning className="h-5 w-5 text-warning shrink-0" weight="bold" />
              <p className="text-sm text-text-primary">{session.pose_feature.sampling_warning}</p>
            </div>
          )}

          <div className="grid gap-6 sm:grid-cols-2 mb-6">
            <div className="rounded-xl border border-border bg-surface p-5">
              <h3 className="text-sm font-semibold text-text-primary mb-4">Chỉ số đo được</h3>
              <dl className="space-y-3">
                {METRIC_NAMES.map(name => {
                  const metric = session.pose_feature?.[name]
                  return (
                    <div key={name} className="flex items-center justify-between text-xs">
                      <dt className="text-text-secondary">{SELF_PRACTICE_METRIC_LABELS[name]}</dt>
                      <dd className="text-text-primary font-medium">
                        {metric?.measured ? `${metric.value} ${metric.unit}` : 'không đo được'}
                      </dd>
                    </div>
                  )
                })}
              </dl>
            </div>

            <div className="rounded-xl border border-border bg-surface p-5">
              <h3 className="text-sm font-semibold text-text-primary mb-4">Sự kiện phát hiện được</h3>
              {session.events.length === 0 ? (
                <p className="text-xs text-text-muted">Không có sự kiện nào.</p>
              ) : (
                <ul className="space-y-2 max-h-64 overflow-y-auto">
                  {session.events.map(event => (
                    <li key={event.event_id}>
                      <button
                        type="button"
                        onClick={() => handleSeek(event.start_sec)}
                        className="w-full text-left text-xs rounded-lg border border-border p-2 hover:bg-surface-elevated"
                      >
                        <span className="font-mono text-text-muted">{Math.round(event.start_sec)}s</span>{' '}
                        <span className="text-text-primary">{event.label}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className="rounded-xl border border-border bg-surface p-5">
            <h3 className="text-sm font-semibold text-text-primary mb-4 flex items-center gap-2">
              <NotePencil className="h-4 w-4" />
              Ghi chú tự xem lại
            </h3>

            {noteError && <p className="mb-3 text-xs text-error">{noteError}</p>}

            <div className="flex items-center gap-2 mb-4">
              <span className="text-xs font-mono text-text-muted shrink-0">{Math.round(currentSec)}s</span>
              <input
                type="text"
                value={draftText}
                onChange={e => setDraftText(e.target.value)}
                placeholder="Ghi chú tại thời điểm hiện tại của video..."
                className="flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-primary"
              />
              <button
                type="button"
                onClick={handleAddNote}
                className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover"
              >
                Thêm
              </button>
            </div>

            {session.notes.length === 0 ? (
              <p className="text-xs text-text-muted">Chưa có ghi chú nào.</p>
            ) : (
              <ul className="space-y-2">
                {session.notes.map(note => (
                  <li key={note.note_id} className="flex items-center gap-2 rounded-lg border border-border p-2">
                    <button
                      type="button"
                      onClick={() => handleSeek(note.mark_sec)}
                      className="text-xs font-mono text-text-muted shrink-0 hover:text-accent"
                    >
                      {Math.round(note.mark_sec)}s
                    </button>
                    {editingNoteId === note.note_id ? (
                      <>
                        <input
                          type="text"
                          value={editingText}
                          onChange={e => setEditingText(e.target.value)}
                          className="flex-1 rounded border border-border bg-surface px-2 py-1 text-xs text-text-primary"
                        />
                        <button type="button" onClick={handleSaveEdit} className="text-success">
                          <Check className="h-4 w-4" weight="bold" />
                        </button>
                        <button type="button" onClick={() => setEditingNoteId(null)} className="text-text-muted">
                          <X className="h-4 w-4" weight="bold" />
                        </button>
                      </>
                    ) : (
                      <>
                        <span className={cn('flex-1 text-sm text-text-primary', !note.text && 'italic text-text-muted')}>
                          {note.text || '(trống)'}
                        </span>
                        <button type="button" onClick={() => startEditing(note)} className="text-text-muted hover:text-accent">
                          <PencilSimple className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeleteNote(note.note_id)}
                          className="text-text-muted hover:text-error"
                        >
                          <Trash className="h-4 w-4" />
                        </button>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  )
}
