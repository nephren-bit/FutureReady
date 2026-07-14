import { useState, useEffect, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'motion/react'
import { Plus, FileText, VideoCamera, Trash, ArrowClockwise } from '@phosphor-icons/react'
import { listSessions, deleteSession, retrySession } from '../lib/api'
import { cn } from '../lib/utils'
import type { Session, SessionState } from '../types'
import { STATE_LABELS } from '../types'

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat('vi-VN', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(iso))
}

function truncatePath(path: string | undefined): string {
  if (!path) return ''
  const parts = path.split('/')
  const name = parts[parts.length - 1]
  if (name.length <= 40) return name
  return name.slice(0, 37) + '...'
}

function stateColor(state: SessionState): string {
  if (state === 'COMPLETED') return 'bg-success-light text-success'
  if (state === 'FAILED') return 'bg-error-light text-error'
  if (state === 'CREATED' || state === 'PENDING_UPLOAD') return 'bg-surface-elevated text-text-secondary'
  return 'bg-accent-light text-accent'
}

function modeBadge(mode: string): string {
  if (mode === 'presentation') return 'bg-accent-light text-accent'
  return 'bg-emerald-50 text-emerald-600'
}

function SkeletonCard() {
  return (
    <div className="rounded-xl border border-border bg-surface p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div className="h-6 w-24 rounded-full bg-surface-elevated animate-pulse" />
        <div className="h-6 w-20 rounded-full bg-surface-elevated animate-pulse" />
      </div>
      <div className="space-y-2">
        <div className="h-4 w-32 rounded bg-surface-elevated animate-pulse" />
        <div className="h-3 w-48 rounded bg-surface-elevated animate-pulse" />
        <div className="h-3 w-40 rounded bg-surface-elevated animate-pulse" />
      </div>
    </div>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [retryingId, setRetryingId] = useState<string | null>(null)

  const fetchSessions = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listSessions()
      setSessions(data)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Không thể tải danh sách phiên'
      setError(message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.preventDefault()
    e.stopPropagation()
    if (deletingId) return
    if (!window.confirm('Bạn có chắc muốn xóa phiên này?')) return
    setDeletingId(id)
    try {
      await deleteSession(id)
      setSessions((prev) => prev.filter((s) => s.id !== id))
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Không thể xóa phiên'
      alert(message)
    } finally {
      setDeletingId(null)
    }
  }

  async function handleRetry(e: React.MouseEvent, id: string) {
    e.preventDefault()
    e.stopPropagation()
    if (retryingId) return
    setRetryingId(id)
    try {
      await retrySession(id)
      await fetchSessions()
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Không thể thử lại phiên'
      alert(message)
    } finally {
      setRetryingId(null)
    }
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
      >
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl sm:text-3xl font-semibold text-text-primary">
            Bảng điều khiển
          </h1>
          <Link
            to="/app/new"
            className={cn(
              'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg',
              'bg-accent text-white font-medium text-sm',
              'hover:bg-accent-hover transition-colors duration-200',
              'focus:outline-none focus:ring-2 focus:ring-accent/40 focus:ring-offset-2'
            )}
          >
            <Plus size={18} weight="bold" />
            Phiên mới
          </Link>
        </div>

        {loading && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        )}

        {!loading && error && (
          <div className="text-center py-16">
            <p className="text-error text-sm mb-4">{error}</p>
            <button
              onClick={fetchSessions}
              className={cn(
                'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium',
                'bg-surface-elevated text-text-secondary hover:text-text-primary transition-colors'
              )}
            >
              <ArrowClockwise size={16} />
              Thử lại
            </button>
          </div>
        )}

        {!loading && !error && sessions.length === 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.15 }}
            className="text-center py-20"
          >
            <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-surface-elevated mb-6">
              <FileText size={36} className="text-text-muted" />
            </div>
            <h2 className="text-lg font-semibold text-text-primary mb-2">
              Chưa có phiên nào
            </h2>
            <p className="text-text-muted text-sm mb-6 max-w-xs mx-auto">
              Tạo phiên đầu tiên để bắt đầu đánh giá bài thuyết trình hoặc hiệu suất phỏng vấn của bạn.
            </p>
            <Link
              to="/app/new"
              className={cn(
                'inline-flex items-center gap-2 px-5 py-2.5 rounded-lg',
                'bg-accent text-white font-medium text-sm',
                'hover:bg-accent-hover transition-colors duration-200'
              )}
            >
              <Plus size={18} weight="bold" />
              Tạo phiên đầu tiên
            </Link>
          </motion.div>
        )}

        {!loading && !error && sessions.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {sessions.map((session, index) => (
              <motion.div
                key={session.id}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: index * 0.05 }}
              >
                <Link
                  to={`/app/sessions/${session.id}`}
                  className={cn(
                    'block rounded-xl border border-border bg-surface p-5',
                    'transition-all duration-200',
                    'hover:scale-[1.01] hover:shadow-md hover:border-border/80',
                    'focus:outline-none focus:ring-2 focus:ring-accent/30 focus:ring-offset-2'
                  )}
                >
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      {session.mode === 'presentation' ? (
                        <FileText size={16} className="text-accent" />
                      ) : (
                        <VideoCamera size={16} className="text-emerald-600" />
                      )}
                      <span
                        className={cn(
                          'inline-block px-2.5 py-0.5 rounded-full text-xs font-medium capitalize',
                          modeBadge(session.mode)
                        )}
                      >
                        {session.mode === 'presentation' ? 'Thuyết trình' : 'Phỏng vấn'}
                      </span>
                    </div>
                    <div className="flex items-center gap-1">
                      {(session.state === 'FAILED' || session.state === 'CREATED') && (
                        <button
                          onClick={(e) => handleRetry(e, session.id)}
                          disabled={retryingId === session.id}
                          className={cn(
                            'p-1.5 rounded-md text-text-muted',
                            'hover:text-warning hover:bg-warning-light transition-colors',
                            'disabled:opacity-40 disabled:cursor-not-allowed'
                          )}
                          title="Thử lại phiên"
                        >
                          <ArrowClockwise
                            size={15}
                            className={retryingId === session.id ? 'animate-spin' : ''}
                          />
                        </button>
                      )}
                      <button
                        onClick={(e) => handleDelete(e, session.id)}
                        disabled={deletingId === session.id}
                        className={cn(
                          'p-1.5 rounded-md text-text-muted',
                          'hover:text-error hover:bg-error-light transition-colors',
                          'disabled:opacity-40 disabled:cursor-not-allowed'
                        )}
                        title="Xóa phiên"
                      >
                        <Trash size={15} />
                      </button>
                    </div>
                  </div>

                  <div className="mb-3">
                    <span
                      className={cn(
                        'inline-block px-2 py-0.5 rounded text-xs font-medium',
                        stateColor(session.state)
                      )}
                    >
                      {STATE_LABELS[session.state]}
                    </span>
                  </div>

                  <div className="space-y-1 text-xs text-text-muted">
                    <p>{formatDate(session.created_at)}</p>
                    {(session.slide_path || session.resume_path) && (
                      <p className="flex items-center gap-1">
                        <FileText size={12} />
                        {truncatePath(session.slide_path || session.resume_path)}
                      </p>
                    )}
                    {session.video_path && (
                      <p className="flex items-center gap-1">
                        <VideoCamera size={12} />
                        {truncatePath(session.video_path)}
                      </p>
                    )}
                  </div>
                </Link>
              </motion.div>
            ))}
          </div>
        )}
      </motion.div>
    </div>
  )
}
