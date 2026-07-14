import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { motion } from 'motion/react'
import {
  ArrowLeft,
  FileText,
  VideoCamera,
  UploadSimple,
  CheckCircle,
  XCircle,
  ArrowClockwise,
  Trash,
  Warning,
} from '@phosphor-icons/react'
import {
  getSession,
  uploadSlide,
  uploadResume,
  uploadVideo,
  deleteSession,
  retrySession,
  getPreliminary,
} from '../lib/api'
import type { Session, PreliminaryEvaluation, SessionState } from '../types'
import { STATE_PROGRESS, STATE_LABELS } from '../types'
import { cn } from '../lib/utils'

const STATE_ORDER: SessionState[] = [
  'CREATED', 'PENDING_UPLOAD',
  'SLIDE_EXTRACTING', 'SLIDE_ANALYZING', 'SLIDE_SCORING', 'SLIDE_REASONING', 'SLIDE_EVALUATED',
  'RESUME_EXTRACTING', 'RESUME_ANALYZING', 'RESUME_SCORING', 'RESUME_REASONING', 'RESUME_EVALUATED',
  'VIDEO_EXTRACTING', 'VIDEO_ANALYZING', 'SPEECH_EXTRACTING', 'SPEECH_ANALYZING',
  'EMOTION_ANALYZING', 'FACE_MESH_ANALYZING', 'TRANSCRIPT_ANALYZING',
  'VIDEO_SCORING', 'VIDEO_REASONING', 'VIDEO_EVALUATED',
  'FEATURE_FUSING', 'SCORING', 'PROMPT_BUILDING', 'REASONING',
  'COMPLETED', 'FAILED',
]

function stateIndex(s: SessionState): number {
  const idx = STATE_ORDER.indexOf(s)
  return idx >= 0 ? idx : 0
}

function getProgress(state: SessionState): number {
  return (STATE_PROGRESS as Record<string, number>)[state] ?? 0
}

function getLabel(state: SessionState): string {
  return (STATE_LABELS as Record<string, string>)[state] ?? state
}

function extractFileName(path: string): string {
  const parts = path.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || path
}

interface DropzoneProps {
  accept: string
  icon: React.ReactNode
  label: string
  hint: string
  disabled: boolean
  uploading: boolean
  dragOver: boolean
  fileName?: string
  onDragOver: (e: React.DragEvent) => void
  onDragLeave: (e: React.DragEvent) => void
  onDrop: (e: React.DragEvent) => void
  onClick: () => void
}

function Dropzone({
  accept,
  icon,
  label,
  hint,
  disabled,
  uploading,
  dragOver,
  fileName,
  onDragOver,
  onDragLeave,
  onDrop,
  onClick,
}: DropzoneProps) {
  return (
    <div
      onDragOver={disabled ? undefined : onDragOver}
      onDragLeave={onDragLeave}
      onDrop={disabled ? undefined : onDrop}
      onClick={disabled ? undefined : onClick}
      className={cn(
        'rounded-xl border-2 border-dashed p-8 text-center transition-all duration-200',
        uploading && 'border-accent/40 bg-accent-light/20 pointer-events-none',
        !uploading && disabled && fileName && 'border-success/30 bg-success/5 opacity-70 cursor-default',
        !uploading && !disabled && dragOver && 'border-accent bg-accent-light/50 cursor-pointer scale-[1.01]',
        !uploading && !disabled && !dragOver && 'border-border hover:border-accent/40 hover:bg-surface-elevated/30 cursor-pointer',
      )}
    >
      {uploading ? (
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          <p className="text-sm text-text-secondary">Đang tải lên...</p>
        </div>
      ) : disabled && fileName ? (
        <div className="flex flex-col items-center gap-3">
          <CheckCircle className="h-8 w-8 text-success" weight="bold" />
          <p className="text-sm font-medium text-text-primary">{fileName}</p>
          <p className="text-xs text-text-muted">Đã tải lên</p>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3">
          <div className="rounded-full bg-surface-elevated p-3">{icon}</div>
          <div>
            <p className="text-sm font-medium text-text-primary">{label}</p>
            <p className="mt-1 text-xs text-text-muted">{hint}</p>
          </div>
        </div>
      )}
    </div>
  )
}

export default function SessionDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [uploading, setUploading] = useState<'slide' | 'resume' | 'video' | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [dragOverType, setDragOverType] = useState<string | null>(null)
  const [preliminary, setPreliminary] = useState<Record<string, PreliminaryEvaluation>>({})
  const [deleting, setDeleting] = useState(false)
  const [retrying, setRetrying] = useState(false)

  const slideInputRef = useRef<HTMLInputElement>(null)
  const resumeInputRef = useRef<HTMLInputElement>(null)
  const videoInputRef = useRef<HTMLInputElement>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const fetchedStagesRef = useRef<Set<string>>(new Set())

  const fetchSession = useCallback(async () => {
    if (!id) return
    try {
      const data = await getSession(id)
      setSession(data)
      setFetchError(null)
    } catch (err: any) {
      setFetchError(err?.response?.data?.detail || 'Không thể tải phiên')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    fetchSession()
  }, [fetchSession])

  useEffect(() => {
    if (!session || session.state === 'COMPLETED' || session.state === 'FAILED') {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
      return
    }
    pollingRef.current = setInterval(() => {
      fetchSession()
    }, 3000)
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
    }
  }, [session?.state, fetchSession])

  const fetchPreliminary = useCallback(async (stage: string) => {
    if (!id) return
    try {
      const data = await getPreliminary(id, stage)
      setPreliminary(prev => ({ ...prev, [stage]: data }))
    } catch {
      fetchedStagesRef.current.delete(stage)
    }
  }, [id])

  useEffect(() => {
    if (!session) return
    const stages: string[] = []
    if (session.slide_path && !fetchedStagesRef.current.has('slide')) {
      fetchedStagesRef.current.add('slide')
      stages.push('slide')
    }
    if (session.resume_path && !fetchedStagesRef.current.has('resume')) {
      fetchedStagesRef.current.add('resume')
      stages.push('resume')
    }
    if (session.video_path && !fetchedStagesRef.current.has('video')) {
      fetchedStagesRef.current.add('video')
      stages.push('video')
    }
    if (session.state === 'COMPLETED' && !fetchedStagesRef.current.has('final')) {
      fetchedStagesRef.current.add('final')
      stages.push('final')
    }
    stages.forEach(fetchPreliminary)
  }, [session, fetchPreliminary])

  const handleUpload = useCallback(async (type: 'slide' | 'resume' | 'video', file: File) => {
    if (!id) return
    setUploading(type)
    setUploadError(null)
    try {
      if (type === 'slide') await uploadSlide(id, file)
      else if (type === 'resume') await uploadResume(id, file)
      else await uploadVideo(id, file)
      await fetchSession()
    } catch (err: any) {
      setUploadError(err?.response?.data?.detail || `Không thể tải lên ${type}`)
    } finally {
      setUploading(null)
    }
  }, [id, fetchSession])

  const handleDelete = useCallback(async () => {
    if (!id) return
    setDeleting(true)
    try {
      await deleteSession(id)
      navigate('/app')
    } catch (err: any) {
      setUploadError(err?.response?.data?.detail || 'Không thể xóa phiên')
      setDeleting(false)
    }
  }, [id, navigate])

  const handleRetry = useCallback(async () => {
    if (!id) return
    setRetrying(true)
    setUploadError(null)
    try {
      await retrySession(id)
      fetchedStagesRef.current.clear()
      setPreliminary({})
      await fetchSession()
    } catch (err: any) {
      setUploadError(err?.response?.data?.detail || 'Không thể thử lại phiên')
    } finally {
      setRetrying(false)
    }
  }, [id, fetchSession])

  const makeDragHandlers = useCallback((type: 'slide' | 'resume' | 'video') => ({
    onDragOver: (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setDragOverType(type)
    },
    onDragLeave: (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setDragOverType(null)
    },
    onDrop: (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setDragOverType(null)
      const file = e.dataTransfer.files[0]
      if (file) handleUpload(type, file)
    },
  }), [handleUpload])

  const slideHandlers = makeDragHandlers('slide')
  const resumeHandlers = makeDragHandlers('resume')
  const videoHandlers = makeDragHandlers('video')

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-6 py-16">
        <div className="flex items-center justify-center py-24">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        </div>
      </div>
    )
  }

  if (fetchError || !session) {
    return (
      <div className="max-w-4xl mx-auto px-6 py-16">
        <Link
          to="/app"
          className="inline-flex items-center gap-2 text-sm text-text-secondary hover:text-text-primary transition-colors mb-8"
        >
          <ArrowLeft className="h-4 w-4" />
          Quay lại Bảng điều khiển
        </Link>
        <div className="rounded-xl border border-error/20 bg-error-light p-8 text-center">
          <Warning className="h-10 w-10 text-error mx-auto mb-3" weight="bold" />
          <p className="text-sm font-medium text-error">{fetchError || 'Không tìm thấy phiên'}</p>
        </div>
      </div>
    )
  }

  const isPresentation = session.mode === 'presentation'
  const isCompleted = session.state === 'COMPLETED'
  const isFailed = session.state === 'FAILED'
  const isTerminal = isCompleted || isFailed
  const isProcessingState = !isTerminal && session.state !== 'CREATED' && session.state !== 'PENDING_UPLOAD'
  const progress = getProgress(session.state)

  const slideUploaded = !!session.slide_path
  const resumeUploaded = !!session.resume_path
  const videoUploaded = !!session.video_path
  const firstUploaded = isPresentation ? slideUploaded : resumeUploaded
  const firstUploading = uploading === (isPresentation ? 'slide' : 'resume')
  const videoUploading = uploading === 'video'

  const pastFirstStage = isPresentation
    ? stateIndex(session.state) >= stateIndex('SLIDE_EVALUATED')
    : stateIndex(session.state) >= stateIndex('RESUME_EVALUATED')

  const showFirstUpload = !isTerminal
  const showVideoUpload = (pastFirstStage || videoUploaded) && !isTerminal

  const firstFileName = isPresentation
    ? (slideUploaded ? extractFileName(session.slide_path!) : undefined)
    : (resumeUploaded ? extractFileName(session.resume_path!) : undefined)
  const videoFileName = videoUploaded ? extractFileName(session.video_path!) : undefined

  const firstAreaDisabled = firstUploaded || isProcessingState || uploading !== null
  const videoAreaDisabled = !firstUploaded || videoUploaded || isProcessingState || uploading !== null

  const showProcessing = isProcessingState && !showVideoUpload

  const prelimStages = Object.keys(preliminary)

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="mb-8"
      >
        <Link
          to="/app"
          className="inline-flex items-center gap-2 text-sm text-text-secondary hover:text-text-primary transition-colors mb-6"
        >
          <ArrowLeft className="h-4 w-4" />
          Quay lại Bảng điều khiển
        </Link>

        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div className="flex items-center gap-3 flex-wrap">
            <span
              className={cn(
                'inline-flex items-center rounded-full px-3 py-1 text-xs font-medium',
                isPresentation ? 'bg-accent-light text-accent' : 'bg-success-light text-success',
              )}
            >
              {isPresentation ? 'Thuyết trình' : 'Phỏng vấn'}
            </span>
            <span
              className={cn(
                'inline-flex items-center rounded-full px-3 py-1 text-xs font-medium',
                isCompleted
                  ? 'bg-success-light text-success'
                  : isFailed
                    ? 'bg-error-light text-error'
                    : 'bg-surface-elevated text-text-secondary',
              )}
            >
              {getLabel(session.state)}
            </span>
          </div>
          <p className="text-xs text-text-muted shrink-0">
            {new Date(session.created_at).toLocaleDateString('vi-VN', {
              year: 'numeric',
              month: 'short',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
            })}
          </p>
        </div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.05 }}
        className="mb-8"
      >
        <div className="rounded-xl border border-border bg-surface p-5">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-medium text-text-secondary">Tiến trình</p>
            <p className="text-xs text-text-muted">{Math.max(0, progress)}%</p>
          </div>
          <div className="h-2 w-full rounded-full bg-surface-elevated overflow-hidden">
            <motion.div
              className={cn(
                'h-full rounded-full',
                isCompleted ? 'bg-success' : isFailed ? 'bg-error' : 'bg-accent',
              )}
              initial={{ width: 0 }}
              animate={{ width: `${Math.max(0, progress)}%` }}
              transition={{ duration: 0.5, ease: 'easeOut' }}
            />
          </div>
          <p className="mt-2 text-xs text-text-muted">{getLabel(session.state)}</p>
        </div>
      </motion.div>

      {uploadError && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-6 rounded-xl border border-error/20 bg-error-light p-4 flex items-center gap-3"
        >
          <Warning className="h-5 w-5 text-error shrink-0" weight="bold" />
          <p className="text-sm text-text-primary">{uploadError}</p>
        </motion.div>
      )}

      {showFirstUpload && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.1 }}
          className="mb-6"
        >
          <div className="rounded-xl border border-border bg-surface p-5">
            <h3 className="text-sm font-semibold text-text-primary mb-4">
              {isPresentation ? 'Tải lên Slide Thuyết trình' : 'Tải lên CV'}
            </h3>
            <Dropzone
              accept={isPresentation ? '.pptx' : '.pdf'}
              icon={<FileText className="h-6 w-6 text-accent" />}
              label={isPresentation ? 'Kéo thả slide vào đây (.pptx)' : 'Kéo thả CV vào đây (.pdf)'}
              hint="Kéo thả hoặc nhấn để chọn"
              disabled={firstAreaDisabled}
              uploading={firstUploading}
              dragOver={dragOverType === (isPresentation ? 'slide' : 'resume')}
              fileName={firstFileName}
              {...(isPresentation ? slideHandlers : resumeHandlers)}
              onClick={() =>
                (isPresentation ? slideInputRef : resumeInputRef).current?.click()
              }
            />
            <input
              ref={isPresentation ? slideInputRef : resumeInputRef}
              type="file"
              accept={isPresentation ? '.pptx' : '.pdf'}
              className="hidden"
              onChange={e => {
                const file = e.target.files?.[0]
                if (file) {
                  handleUpload(isPresentation ? 'slide' : 'resume', file)
                  e.target.value = ''
                }
              }}
            />
          </div>
        </motion.div>
      )}

      {showVideoUpload && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.15 }}
          className="mb-6"
        >
          <div className="rounded-xl border border-border bg-surface p-5">
            <h3 className="text-sm font-semibold text-text-primary mb-4">Tải lên Video Ghi hình</h3>
            <Dropzone
              accept=".mp4,.mov"
              icon={<VideoCamera className="h-6 w-6 text-accent" />}
              label="Kéo thả video vào đây (.mp4, .mov)"
              hint="Kéo thả hoặc nhấn để chọn"
              disabled={videoAreaDisabled}
              uploading={videoUploading}
              dragOver={dragOverType === 'video'}
              fileName={videoFileName}
              {...videoHandlers}
              onClick={() => videoInputRef.current?.click()}
            />
            <input
              ref={videoInputRef}
              type="file"
              accept=".mp4,.mov"
              className="hidden"
              onChange={e => {
                const file = e.target.files?.[0]
                if (file) {
                  handleUpload('video', file)
                  e.target.value = ''
                }
              }}
            />
          </div>
        </motion.div>
      )}

      {showProcessing && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.2 }}
          className="mb-6"
        >
          <div className="rounded-xl border border-border bg-surface p-5">
            <div className="flex items-center gap-4">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
              <div>
                <p className="text-sm font-medium text-text-primary">Đang xử lý</p>
                <p className="text-xs text-text-muted">{getLabel(session.state)}</p>
              </div>
            </div>
          </div>
        </motion.div>
      )}

      {prelimStages.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.25 }}
          className="mb-6"
        >
          <h3 className="text-sm font-semibold text-text-primary mb-4">Kết quả sơ bộ</h3>
          <div className="grid gap-4 sm:grid-cols-2">
            {prelimStages.map(stage => {
              const ev = preliminary[stage]
              const scoreColor =
                ev.score >= 70 ? 'text-success' : ev.score >= 40 ? 'text-warning' : 'text-error'
              const barColor =
                ev.score >= 70 ? 'bg-success' : ev.score >= 40 ? 'bg-warning' : 'bg-error'
              return (
                <div key={stage} className="rounded-xl border border-border bg-surface p-5">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-medium text-text-secondary capitalize">{stage}</span>
                    <span className={cn('text-lg font-bold', scoreColor)}>{ev.score}</span>
                  </div>
                  <div className="h-1.5 w-full rounded-full bg-surface-elevated mb-3 overflow-hidden">
                    <div
                      className={cn('h-full rounded-full transition-all duration-500', barColor)}
                      style={{ width: `${Math.min(100, Math.max(0, ev.score))}%` }}
                    />
                  </div>
                  <p className="text-xs text-text-muted leading-relaxed">{ev.reasoning}</p>
                </div>
              )
            })}
          </div>
        </motion.div>
      )}

      {isFailed && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.2 }}
          className="mb-6"
        >
          <div className="rounded-xl border border-error/20 bg-error-light p-6">
            <div className="flex items-start gap-3 mb-4">
              <XCircle className="h-5 w-5 text-error shrink-0 mt-0.5" weight="bold" />
              <div>
                <p className="text-sm font-semibold text-error">Phiên thất bại</p>
                {session.error_message && (
                  <p className="mt-1 text-xs text-error/80">{session.error_message}</p>
                )}
                {session.failed_state && (
                  <p className="mt-1 text-xs text-error/80">
                    Thất bại tại: {getLabel(session.failed_state as SessionState)}
                  </p>
                )}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={handleRetry}
                disabled={retrying}
                className={cn(
                  'inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors',
                  'bg-accent text-white hover:bg-accent-hover',
                  retrying && 'opacity-50 cursor-not-allowed',
                )}
              >
                <ArrowClockwise className={cn('h-4 w-4', retrying && 'animate-spin')} />
                {retrying ? 'Đang thử lại...' : 'Thử lại'}
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                className={cn(
                  'inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors',
                  'border border-error/30 text-error hover:bg-error-light',
                  deleting && 'opacity-50 cursor-not-allowed',
                )}
              >
                <Trash className="h-4 w-4" />
                {deleting ? 'Đang xóa...' : 'Xóa'}
              </button>
            </div>
          </div>
        </motion.div>
      )}

      {isCompleted && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.2 }}
          className="mb-6"
        >
          <div className="rounded-xl border border-success/20 bg-success-light p-6 text-center">
            <CheckCircle className="h-10 w-10 text-success mx-auto mb-3" weight="bold" />
            <p className="text-sm font-semibold text-success mb-1">Đánh giá hoàn tất</p>
            <p className="text-xs text-success/80 mb-4">
              Phiên của bạn đã được đánh giá hoàn tất.
            </p>
            <Link
              to={`/app/sessions/${session.id}/report`}
              className="inline-flex items-center gap-2 rounded-lg bg-success px-5 py-2.5 text-sm font-medium text-white hover:opacity-90 transition-opacity"
            >
              Xem Báo cáo Chi tiết
            </Link>
          </div>
        </motion.div>
      )}

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.3 }}
      >
        <div className="rounded-xl border border-border bg-surface p-5">
          <h3 className="text-sm font-semibold text-text-primary mb-4">Thông tin Phiên</h3>
          <dl className="grid grid-cols-2 gap-4 text-xs">
            <div>
              <dt className="text-text-muted mb-1">Mã phiên</dt>
              <dd className="font-mono text-text-primary break-all">{session.id}</dd>
            </div>
            <div>
              <dt className="text-text-muted mb-1">Chế độ</dt>
              <dd className="text-text-primary capitalize">{session.mode}</dd>
            </div>
            <div>
              <dt className="text-text-muted mb-1">Ngôn ngữ</dt>
              <dd className="text-text-primary uppercase">{session.language}</dd>
            </div>
            <div>
              <dt className="text-text-muted mb-1">Trạng thái</dt>
              <dd className="text-text-primary">{getLabel(session.state)}</dd>
            </div>
            <div>
              <dt className="text-text-muted mb-1">Tạo lúc</dt>
              <dd className="text-text-primary">
                {new Date(session.created_at).toLocaleDateString('vi-VN', {
                  year: 'numeric',
                  month: 'short',
                  day: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </dd>
            </div>
            <div>
              <dt className="text-text-muted mb-1">Cập nhật lúc</dt>
              <dd className="text-text-primary">
                {new Date(session.updated_at).toLocaleDateString('vi-VN', {
                  year: 'numeric',
                  month: 'short',
                  day: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </dd>
            </div>
          </dl>
        </div>
      </motion.div>
    </div>
  )
}
