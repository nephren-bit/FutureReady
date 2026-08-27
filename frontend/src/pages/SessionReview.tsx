import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { motion } from 'motion/react'
import {
  ArrowLeft,
  Warning,
  NotePencil,
  PencilSimple,
  Trash,
  Check,
  X,
  UserPlus,
  Copy,
  Star,
} from '@phosphor-icons/react'
import {
  getSelfPracticeSession,
  selfPracticeVideoUrl,
  createSelfNote,
  updateSelfNote,
  deleteSelfNote,
  createPeerInvite,
  listPeerInvites,
  revokePeerInvite,
} from '../lib/api'
import type { SelfPracticeSession, SelfNote, PeerReviewInvite } from '../types'
import { RUBRIC_LABELS } from '../types'
import VideoTimeline, { EVENT_COLORS } from '../components/VideoTimeline'
import { cn } from '../lib/utils'

const INVITE_STATUS_LABELS: Record<PeerReviewInvite['status'], string> = {
  pending: 'Đang chờ',
  completed: 'Đã chấm xong',
  expired: 'Hết hạn',
  revoked: 'Đã thu hồi',
}

function inviteStatusColor(status: PeerReviewInvite['status']): string {
  if (status === 'completed') return 'bg-success-light text-success'
  if (status === 'pending') return 'bg-accent-light text-accent'
  return 'bg-surface-elevated text-text-muted'
}

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

  const [invites, setInvites] = useState<PeerReviewInvite[]>([])
  const [inviteError, setInviteError] = useState<string | null>(null)
  const [creatingInvite, setCreatingInvite] = useState(false)
  const [copiedInviteId, setCopiedInviteId] = useState<string | null>(null)

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

  const fetchInvites = useCallback(async () => {
    if (!id) return
    try {
      setInvites(await listPeerInvites(id))
    } catch {
      // Not fatal to the page -- the review itself already loaded fine.
    }
  }, [id])

  useEffect(() => {
    if (session?.state === 'completed') fetchInvites()
  }, [session?.state, fetchInvites])

  const handleCreateInvite = useCallback(async () => {
    if (!id) return
    setInviteError(null)
    setCreatingInvite(true)
    try {
      const invite = await createPeerInvite(id)
      setInvites(prev => [invite, ...prev])
    } catch (err: any) {
      setInviteError(err?.response?.data?.detail || 'Không thể tạo lời mời.')
    } finally {
      setCreatingInvite(false)
    }
  }, [id])

  const handleRevokeInvite = useCallback(async (inviteId: string) => {
    if (!id) return
    try {
      const updated = await revokePeerInvite(id, inviteId)
      setInvites(prev => prev.map(inv => (inv.invite_id === updated.invite_id ? updated : inv)))
    } catch (err: any) {
      setInviteError(err?.response?.data?.detail || 'Không thể thu hồi lời mời.')
    }
  }, [id])

  const handleCopyLink = useCallback(async (invite: PeerReviewInvite) => {
    const url = `${window.location.origin}/cham-ho/${invite.token}`
    try {
      await navigator.clipboard.writeText(url)
      setCopiedInviteId(invite.invite_id)
      setTimeout(() => setCopiedInviteId(prev => (prev === invite.invite_id ? null : prev)), 2000)
    } catch {
      setInviteError('Không thể sao chép liên kết -- hãy tự chọn và sao chép.')
    }
  }, [])

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
        <div role="alert" className="rounded-xl border border-error/20 bg-error-light p-8 text-center">
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
              peerNotes={session.peer_notes}
              onSeek={handleSeek}
            />
          </div>

          {session.pose_feature?.sampling_warning && (
            <div className="mb-6 rounded-xl border border-warning/20 bg-warning-light p-4 flex items-center gap-3">
              <Warning className="h-5 w-5 text-warning shrink-0" weight="bold" />
              <p className="text-sm text-text-primary">{session.pose_feature.sampling_warning}</p>
            </div>
          )}

          <div className="rounded-xl border border-border bg-surface p-5 mb-6">
            <h3 className="text-sm font-semibold text-text-primary mb-4">Sự kiện phát hiện được</h3>
            {session.events.length === 0 ? (
              <p className="text-xs text-text-muted">Chưa phát hiện sự kiện nào trong lần ghi này.</p>
            ) : (
              <ul className="space-y-2">
                {session.events.map(event => (
                  <li key={event.event_id}>
                    <button
                      type="button"
                      onClick={() => handleSeek(event.start_sec)}
                      className="flex w-full items-center gap-2 rounded-lg border border-border p-2 text-left text-xs hover:bg-surface-elevated"
                    >
                      <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', EVENT_COLORS[event.type] ?? 'bg-text-muted')} />
                      <span className="text-text-primary">
                        Điểm đánh dấu lúc <span className="font-mono">{Math.round(event.start_sec)}s</span>: {event.label}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-xl border border-border bg-surface p-5">
            <h3 className="text-sm font-semibold text-text-primary mb-4 flex items-center gap-2">
              <NotePencil className="h-4 w-4" />
              Ghi chú tự xem lại
            </h3>

            {noteError && <p role="alert" className="mb-3 text-xs text-error">{noteError}</p>}

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
                        <button
                          type="button"
                          onClick={handleSaveEdit}
                          aria-label="Lưu ghi chú"
                          title="Lưu"
                          className="rounded-md p-1.5 text-success hover:bg-success-light"
                        >
                          <Check className="h-4 w-4" weight="bold" />
                        </button>
                        <button
                          type="button"
                          onClick={() => setEditingNoteId(null)}
                          aria-label="Huỷ chỉnh sửa"
                          title="Huỷ"
                          className="rounded-md p-1.5 text-text-muted hover:bg-surface-elevated"
                        >
                          <X className="h-4 w-4" weight="bold" />
                        </button>
                      </>
                    ) : (
                      <>
                        <span className={cn('flex-1 text-sm text-text-primary', !note.text && 'italic text-text-muted')}>
                          {note.text || '(trống)'}
                        </span>
                        <button
                          type="button"
                          onClick={() => startEditing(note)}
                          aria-label="Sửa ghi chú"
                          title="Sửa"
                          className="rounded-md p-1.5 text-text-muted hover:bg-surface-elevated hover:text-accent"
                        >
                          <PencilSimple className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeleteNote(note.note_id)}
                          aria-label="Xoá ghi chú"
                          title="Xoá"
                          className="rounded-md p-1.5 text-text-muted hover:bg-error-light hover:text-error"
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

          <div className="mt-6 rounded-xl border border-border bg-surface p-5">
            <h3 className="text-sm font-semibold text-text-primary mb-1 flex items-center gap-2">
              <UserPlus className="h-4 w-4" />
              Nhờ bạn chấm hộ
            </h3>
            <p className="mb-4 text-xs text-text-muted">
              Bạn được mời sẽ xem video và chấm mù -- không thấy dải mốc máy hay bảng chỉ số cho tới khi
              nộp xong đánh giá.
            </p>

            {inviteError && <p role="alert" className="mb-3 text-xs text-error">{inviteError}</p>}

            <button
              type="button"
              onClick={handleCreateInvite}
              disabled={creatingInvite}
              className="mb-4 inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
            >
              <UserPlus className="h-4 w-4" />
              {creatingInvite ? 'Đang tạo...' : 'Tạo lời mời mới'}
            </button>

            {invites.length === 0 ? (
              <p className="text-xs text-text-muted">Chưa gửi lời mời nào.</p>
            ) : (
              <ul className="space-y-2">
                {invites.map(invite => (
                  <li
                    key={invite.invite_id}
                    className="flex items-center gap-2 rounded-lg border border-border p-2 text-xs"
                  >
                    <span className={cn('rounded-full px-2 py-1 font-medium shrink-0', inviteStatusColor(invite.status))}>
                      {INVITE_STATUS_LABELS[invite.status]}
                    </span>
                    <span className="flex-1 truncate font-mono text-text-muted">{invite.token}</span>
                    {invite.status === 'pending' && (
                      <>
                        <button
                          type="button"
                          onClick={() => handleCopyLink(invite)}
                          className="inline-flex items-center gap-1 text-text-muted hover:text-accent"
                        >
                          <Copy className="h-3.5 w-3.5" />
                          {copiedInviteId === invite.invite_id ? 'Đã chép' : 'Chép liên kết'}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleRevokeInvite(invite.invite_id)}
                          className="text-text-muted hover:text-error"
                        >
                          Thu hồi
                        </button>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {session.peer_notes.length > 0 && (
            <div className="mt-6 rounded-xl border border-border bg-surface p-5">
              <h3 className="text-sm font-semibold text-text-primary mb-4 flex items-center gap-2">
                <Star className="h-4 w-4" />
                Đánh giá từ bạn bè
              </h3>
              <ul className="space-y-2">
                {session.peer_notes.map(note =>
                  note.mark_sec !== null ? (
                    <li key={note.note_id} className="flex items-center gap-2 rounded-lg border border-border p-2">
                      <button
                        type="button"
                        onClick={() => handleSeek(note.mark_sec as number)}
                        className="text-xs font-mono text-text-muted shrink-0 hover:text-accent"
                      >
                        {Math.round(note.mark_sec)}s
                      </button>
                      <span className="flex-1 text-sm text-text-primary">{note.text || '(đánh dấu, không có ghi chú)'}</span>
                    </li>
                  ) : (
                    <li key={note.note_id} className="rounded-lg border border-border p-3">
                      <div className="flex flex-wrap gap-4">
                        {Object.entries(note.rubric_scores).map(([criterion, score]) => (
                          <span key={criterion} className="text-xs text-text-secondary">
                            {RUBRIC_LABELS[criterion as keyof typeof RUBRIC_LABELS] ?? criterion}:{' '}
                            <span className="font-semibold text-text-primary">{score}/5</span>
                          </span>
                        ))}
                      </div>
                      {note.text && <p className="mt-2 text-sm text-text-primary">{note.text}</p>}
                    </li>
                  )
                )}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  )
}
