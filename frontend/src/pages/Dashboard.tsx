import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'motion/react'
import { Plus, VideoCamera, Trash, ArrowClockwise, Warning } from '@phosphor-icons/react'
import { listSelfPracticeSessions, deleteSelfPracticeSession } from '../lib/api'
import { cn } from '../lib/utils'
import type { SelfPracticeSessionSummary, SelfPracticeState } from '../types'

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat('vi-VN', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(iso))
}

const STATE_LABELS: Record<SelfPracticeState, string> = {
  processing: 'Đang xử lý',
  completed: 'Hoàn tất',
  failed: 'Thất bại',
}

function stateColor(state: SelfPracticeState): string {
  if (state === 'completed') return 'bg-success-light text-success'
  if (state === 'failed') return 'bg-error-light text-error'
  return 'bg-accent-light text-accent'
}

const PROFILE_LABELS: Record<string, string> = {
  presentation_solo: 'Thuyết trình',
  interview_solo: 'Phỏng vấn',
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
        <div className="h-3 w-40 rounded bg-surface-elevated animate-pulse" />
      </div>
    </div>
  )
}

export default function Dashboard() {
  const [sessions, setSessions] = useState<SelfPracticeSessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const fetchSessions = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listSelfPracticeSessions()
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
      await deleteSelfPracticeSession(id)
      setSessions((prev) => prev.filter((s) => s.id !== id))
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Không thể xóa phiên'
      alert(message)
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
      >
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-8">
          <h1 className="text-2xl sm:text-3xl font-semibold text-text-primary">
            Bảng điều khiển
          </h1>
          {sessions.length > 0 && (
            <Link
              to="/app/luyen-tap"
              className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover transition-colors"
            >
              <Plus size={16} weight="bold" />
              Ghi phiên mới
            </Link>
          )}
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
            <Warning className="h-8 w-8 text-error mx-auto mb-3" weight="bold" />
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
              <VideoCamera size={36} className="text-text-muted" />
            </div>
            <h2 className="text-lg font-semibold text-text-primary mb-2">
              Chưa có phiên tự luyện nào
            </h2>
            <p className="text-text-muted text-sm mb-6 max-w-xs mx-auto">
              Ghi lại buổi thuyết trình hoặc phỏng vấn tự luyện đầu tiên của bạn trước webcam.
            </p>
            <Link
              to="/app/luyen-tap"
              className={cn(
                'inline-flex items-center gap-2 px-5 py-2.5 rounded-lg',
                'bg-accent text-white font-medium text-sm',
                'hover:bg-accent-hover transition-colors duration-200'
              )}
            >
              <Plus size={18} weight="bold" />
              Ghi phiên đầu tiên
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
                  to={`/app/phien/${session.id}`}
                  className={cn(
                    'block rounded-xl border border-border bg-surface p-5',
                    'transition-all duration-200',
                    'hover:scale-[1.01] hover:shadow-md hover:border-border/80',
                    'focus:outline-none focus:ring-2 focus:ring-accent/30 focus:ring-offset-2'
                  )}
                >
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <VideoCamera size={16} className="text-accent" />
                      <span className="inline-block px-2.5 py-0.5 rounded-full text-xs font-medium bg-accent-light text-accent">
                        {PROFILE_LABELS[session.profile] ?? session.profile}
                      </span>
                    </div>
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

                  <div className="mb-3">
                    <span className={cn('inline-block px-2 py-0.5 rounded text-xs font-medium', stateColor(session.state))}>
                      {STATE_LABELS[session.state]}
                    </span>
                  </div>

                  <p className="text-xs text-text-muted">{formatDate(session.created_at)}</p>
                </Link>
              </motion.div>
            ))}
          </div>
        )}
      </motion.div>
    </div>
  )
}
