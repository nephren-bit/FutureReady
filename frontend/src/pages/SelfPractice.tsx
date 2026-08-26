import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'motion/react'
import { Microphone, Record, Stop, Warning, UploadSimple, FileVideo, VideoCamera } from '@phosphor-icons/react'
import { createSelfPracticeSession } from '../lib/api'
import type { SelfPracticeProfile } from '../types'
import { cn } from '../lib/utils'

// Matches routers/self_practice.py's _ALLOWED_EXTENSIONS.
const ALLOWED_UPLOAD_EXTENSIONS = ['.mp4', '.mov', '.m4v', '.webm']

// Same MIME-detection approach as Practice.tsx, but video+audio together --
// this flow uploads the whole recording once, it does not stream chunks.
const MIME_CANDIDATES = [
  'video/webm;codecs=vp9,opus',
  'video/webm;codecs=vp8,opus',
  'video/webm',
  'video/mp4',
]

function pickMimeType(): string | null {
  if (typeof MediaRecorder === 'undefined') return null
  return MIME_CANDIDATES.find(m => MediaRecorder.isTypeSupported(m)) ?? null
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

const PROFILES: { value: SelfPracticeProfile; label: string; hint: string }[] = [
  { value: 'presentation_solo', label: 'Thuyết trình', hint: 'Đứng hoặc ngồi, ghi hình gần webcam' },
  { value: 'interview_solo', label: 'Phỏng vấn', hint: 'Ngồi trả lời câu hỏi trước webcam' },
]

type Phase = 'setup' | 'recording' | 'preview' | 'uploading' | 'failed'
type SourceMode = 'record' | 'upload'

function hasAllowedExtension(filename: string): boolean {
  const lower = filename.toLowerCase()
  return ALLOWED_UPLOAD_EXTENSIONS.some(ext => lower.endsWith(ext))
}

export default function SelfPractice() {
  const navigate = useNavigate()

  const [profile, setProfile] = useState<SelfPracticeProfile>('presentation_solo')
  const [sourceMode, setSourceMode] = useState<SourceMode>('record')
  const [phase, setPhase] = useState<Phase>('setup')
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)

  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const recordedBlobRef = useRef<Blob | null>(null)
  const uploadFilenameRef = useRef<string>('luyen-tap.webm')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const supported = typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia

  const cleanupMedia = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    streamRef.current?.getTracks().forEach(track => track.stop())
    streamRef.current = null
    recorderRef.current = null
  }, [])

  useEffect(() => () => cleanupMedia(), [cleanupMedia])

  useEffect(() => {
    if (phase === 'recording' && videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current
    }
  }, [phase])

  const handleStart = useCallback(async () => {
    setError(null)
    const mime = pickMimeType()
    if (!supported || !mime) {
      setError('Trình duyệt này không hỗ trợ ghi hình (MediaRecorder).')
      return
    }

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: { facingMode: 'user', width: 1280, height: 720 },
      })
    } catch {
      setError('Không thể truy cập camera/microphone. Vui lòng cấp quyền và thử lại.')
      return
    }

    streamRef.current = stream
    chunksRef.current = []
    const recorder = new MediaRecorder(stream, { mimeType: mime })
    recorderRef.current = recorder
    recorder.ondataavailable = e => {
      if (e.data.size > 0) chunksRef.current.push(e.data)
    }
    recorder.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: mime })
      recordedBlobRef.current = blob
      uploadFilenameRef.current = `luyen-tap.${mime.includes('mp4') ? 'mp4' : 'webm'}`
      setPreviewUrl(URL.createObjectURL(blob))
      setPhase('preview')
    }

    recorder.start(1000)
    setPhase('recording')
    setElapsed(0)
    timerRef.current = setInterval(() => setElapsed(prev => prev + 1), 1000)
  }, [supported])

  const handleStop = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    recorderRef.current?.stop()
    streamRef.current?.getTracks().forEach(track => track.stop())
  }, [])

  const handleDiscard = useCallback(() => {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    recordedBlobRef.current = null
    setPreviewUrl(null)
    setPhase('setup')
  }, [previewUrl])

  const handleFileSelected = useCallback((file: File) => {
    setError(null)
    if (!hasAllowedExtension(file.name)) {
      setError(`Định dạng không được hỗ trợ. Chỉ nhận: ${ALLOWED_UPLOAD_EXTENSIONS.join(', ')}`)
      return
    }
    recordedBlobRef.current = file
    uploadFilenameRef.current = file.name
    setPreviewUrl(URL.createObjectURL(file))
    setPhase('preview')
  }, [])

  const handleUpload = useCallback(async () => {
    const blob = recordedBlobRef.current
    if (!blob) return
    setPhase('uploading')
    setError(null)
    try {
      const session = await createSelfPracticeSession(profile, blob, uploadFilenameRef.current)
      navigate(`/app/phien/${session.id}`)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Không thể tải lên bản ghi.')
      setPhase('preview')
    }
  }, [profile, navigate])

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mb-8">
        <h1 className="text-2xl font-semibold text-text-primary">Tự luyện tập</h1>
        <p className="mt-2 text-sm text-text-secondary">
          Ghi hình trực tiếp trước webcam hoặc tải lên một video đã quay sẵn -- hệ thống sẽ chỉ ra những
          điểm đo được trên video, không chấm điểm tổng.
        </p>
      </motion.div>

      {!supported && (
        <div className="mb-6 rounded-xl border border-error/20 bg-error-light p-4 flex items-center gap-3">
          <Warning className="h-5 w-5 text-error shrink-0" weight="bold" />
          <p className="text-sm text-text-primary">Trình duyệt này không hỗ trợ ghi hình trực tiếp.</p>
        </div>
      )}

      {error && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-6 rounded-xl border border-error/20 bg-error-light p-4 flex items-center gap-3"
        >
          <Warning className="h-5 w-5 text-error shrink-0" weight="bold" />
          <p className="text-sm text-text-primary">{error}</p>
        </motion.div>
      )}

      {phase === 'setup' && (
        <div className="rounded-xl border border-border bg-surface p-6">
          <h3 className="text-sm font-semibold text-text-primary mb-4">Chọn hồ sơ luyện tập</h3>
          <div className="grid gap-3 sm:grid-cols-2 mb-6">
            {PROFILES.map(p => (
              <button
                key={p.value}
                type="button"
                onClick={() => setProfile(p.value)}
                className={cn(
                  'rounded-lg border p-4 text-left transition-colors',
                  profile === p.value
                    ? 'border-accent bg-accent-light/40'
                    : 'border-border hover:border-accent/40'
                )}
              >
                <p className="text-sm font-medium text-text-primary">{p.label}</p>
                <p className="mt-1 text-xs text-text-muted">{p.hint}</p>
              </button>
            ))}
          </div>

          <div className="mb-4 inline-flex rounded-lg border border-border p-1">
            <button
              type="button"
              onClick={() => setSourceMode('record')}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                sourceMode === 'record' ? 'bg-accent text-white' : 'text-text-secondary hover:text-text-primary'
              )}
            >
              <VideoCamera className="h-3.5 w-3.5" />
              Ghi trực tiếp
            </button>
            <button
              type="button"
              onClick={() => setSourceMode('upload')}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                sourceMode === 'upload' ? 'bg-accent text-white' : 'text-text-secondary hover:text-text-primary'
              )}
            >
              <FileVideo className="h-3.5 w-3.5" />
              Tải video có sẵn
            </button>
          </div>

          {sourceMode === 'record' ? (
            <div>
              <button
                type="button"
                onClick={handleStart}
                disabled={!supported}
                className="inline-flex items-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
              >
                <Record className="h-4 w-4" weight="fill" />
                Bắt đầu ghi hình
              </button>
            </div>
          ) : (
            <div>
              <div
                onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={e => {
                  e.preventDefault()
                  setDragOver(false)
                  const file = e.dataTransfer.files[0]
                  if (file) handleFileSelected(file)
                }}
                onClick={() => fileInputRef.current?.click()}
                className={cn(
                  'flex cursor-pointer flex-col items-center gap-2 rounded-lg border-2 border-dashed p-8 text-center transition-colors',
                  dragOver ? 'border-accent bg-accent-light/30' : 'border-border hover:border-accent/40'
                )}
              >
                <FileVideo className="h-8 w-8 text-text-muted" />
                <p className="text-sm font-medium text-text-primary">Kéo thả video vào đây, hoặc bấm để chọn</p>
                <p className="text-xs text-text-muted">Định dạng: {ALLOWED_UPLOAD_EXTENSIONS.join(', ')}</p>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept={ALLOWED_UPLOAD_EXTENSIONS.join(',')}
                className="hidden"
                onChange={e => {
                  const file = e.target.files?.[0]
                  if (file) handleFileSelected(file)
                  e.target.value = ''
                }}
              />
            </div>
          )}
        </div>
      )}

      {phase === 'recording' && (
        <div className="rounded-xl border border-border bg-surface p-6">
          <div className="overflow-hidden rounded-lg border border-border bg-black aspect-video mb-4">
            <video ref={videoRef} autoPlay muted playsInline className="h-full w-full -scale-x-100 object-cover" />
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-text-secondary">
              <span className="h-2 w-2 animate-pulse rounded-full bg-error" />
              Đang ghi -- {formatElapsed(elapsed)}
            </div>
            <button
              type="button"
              onClick={handleStop}
              className="inline-flex items-center gap-2 rounded-lg bg-error px-5 py-2.5 text-sm font-medium text-white hover:opacity-90"
            >
              <Stop className="h-4 w-4" weight="fill" />
              Dừng
            </button>
          </div>
        </div>
      )}

      {(phase === 'preview' || phase === 'uploading') && previewUrl && (
        <div className="rounded-xl border border-border bg-surface p-6">
          <div className="overflow-hidden rounded-lg border border-border bg-black aspect-video mb-4">
            <video src={previewUrl} controls className="h-full w-full object-cover" />
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleUpload}
              disabled={phase === 'uploading'}
              className="inline-flex items-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
            >
              <UploadSimple className={cn('h-4 w-4', phase === 'uploading' && 'animate-pulse')} weight="bold" />
              {phase === 'uploading' ? 'Đang tải lên...' : 'Tải lên và phân tích'}
            </button>
            <button
              type="button"
              onClick={handleDiscard}
              disabled={phase === 'uploading'}
              className="rounded-lg border border-border px-5 py-2.5 text-sm font-medium text-text-secondary hover:bg-surface-elevated disabled:opacity-50"
            >
              {sourceMode === 'upload' ? 'Chọn video khác' : 'Ghi lại'}
            </button>
          </div>
        </div>
      )}

      <div className="mt-6 flex items-start gap-2 text-xs text-text-muted">
        <Microphone className="h-4 w-4 shrink-0 mt-0.5" />
        Bản ghi chỉ được dùng để phân tích chỉ số chuyển động -- không được chấm điểm hay so sánh với người khác.
      </div>
    </div>
  )
}
