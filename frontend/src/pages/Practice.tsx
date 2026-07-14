import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'motion/react'
import {
  Microphone,
  MicrophoneSlash,
  Stop,
  Lightbulb,
  Warning,
  CheckCircle,
  XCircle,
  ArrowClockwise,
  FileText,
  VideoCamera,
  X,
} from '@phosphor-icons/react'
import ScoreBar from '../components/charts/ScoreBar'
import {
  practiceStreamUrl,
  getPracticeEvaluation,
  createPracticeSession,
  uploadPracticeSlide,
  uploadPracticeResume,
} from '../lib/api'
import { cn } from '../lib/utils'
import type { EvaluationMode, PracticeEvaluation } from '../types'

type Phase = 'idle' | 'connecting' | 'recording' | 'finalizing' | 'completed' | 'failed'

// Every supported MediaRecorder MIME type, in preference order, mapped to the
// `audio_format` the backend's `WS /practice/stream` expects (see
// routers/practice.py -- it just appends bytes to a file with this
// extension and lets Whisper/Librosa decode whatever the browser produced).
const MIME_CANDIDATES: { mime: string; format: string }[] = [
  { mime: 'audio/webm;codecs=opus', format: 'webm' },
  { mime: 'audio/webm', format: 'webm' },
  { mime: 'audio/ogg;codecs=opus', format: 'ogg' },
  { mime: 'audio/ogg', format: 'ogg' },
  { mime: 'audio/mp4', format: 'm4a' },
]

function pickRecorderFormat(): { mime: string; format: string } | null {
  if (typeof MediaRecorder === 'undefined') return null
  return MIME_CANDIDATES.find((c) => MediaRecorder.isTypeSupported(c.mime)) ?? null
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

const MODES: {
  id: EvaluationMode
  label: string
  prompt: string
  icon: typeof FileText
  iconColor: string
  bgColor: string
  borderColorSelected: string
  fileAccept: string
  fileLabel: string
}[] = [
  {
    id: 'presentation',
    label: 'Thuyết trình',
    prompt: 'Hãy trình bày một chủ đề bạn quen thuộc trong khoảng 1-2 phút, như đang nói trước khán giả.',
    icon: FileText,
    iconColor: 'text-accent',
    bgColor: 'bg-accent-light',
    borderColorSelected: 'border-accent',
    fileAccept: '.pptx',
    fileLabel: 'slide (.pptx)',
  },
  {
    id: 'interview',
    label: 'Phỏng vấn',
    prompt: 'Hãy trả lời một câu hỏi phỏng vấn phổ biến, ví dụ: "Hãy giới thiệu về bản thân bạn."',
    icon: VideoCamera,
    iconColor: 'text-emerald-600',
    bgColor: 'bg-emerald-50',
    borderColorSelected: 'border-emerald-500',
    fileAccept: '.pdf',
    fileLabel: 'CV (.pdf)',
  },
]

// The backend runs this analysis (Layer 1/2 -> Fusion -> Scoring -> Prompt ->
// Reasoning, see `PracticeSessionManager.finalize`) as a single pass rather
// than exposing intermediate checkpoints over the wire the way a session's
// state machine does, so there is no real per-stage signal to poll here.
// This is a simulated, time-based progression through the same named stages
// a session goes through, purely so "finalizing" doesn't read as a single
// opaque spinner -- it always completes for real once `final_evaluation` /
// `final_evaluation_failed` actually arrives, regardless of where the bar is.
function pipelineStages(mode: EvaluationMode | null): string[] {
  const last =
    mode === 'interview' ? 'AI đang tổng hợp nhận xét phỏng vấn' : 'AI đang tổng hợp nhận xét thuyết trình'
  return [
    'Đang trích xuất đặc trưng âm thanh',
    'Đang phân tích giọng nói (Whisper)',
    'Đang tổng hợp đặc trưng',
    'Đang chấm điểm',
    last,
  ]
}

const SCORE_LABELS: Record<string, string> = {
  resume_score: 'CV',
  slide_score: 'Slide',
  speech_score: 'Giọng nói',
  transcript_score: 'Chất lượng nội dung',
  emotion_score: 'Cảm xúc',
  eye_contact_score: 'Giao tiếp bằng mắt',
  voice_confidence_score: 'Tự tin giọng nói',
  presentation_score: 'Thuyết trình',
  communication_score: 'Giao tiếp',
}

function nonNullScores(scores: PracticeEvaluation['scores']): [string, number][] {
  return Object.entries(scores).filter(
    ([key, val]) => key !== 'overall_score' && val !== null && val !== undefined
  ) as [string, number][]
}

export default function Practice() {
  const [mode, setMode] = useState<EvaluationMode | null>(null)
  const [language, setLanguage] = useState('vi')
  const [phase, setPhase] = useState<Phase>('idle')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [transcript, setTranscript] = useState('')
  const [tips, setTips] = useState<string[]>([])
  const [evaluation, setEvaluation] = useState<PracticeEvaluation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [stageIndex, setStageIndex] = useState(0)
  const [file, setFile] = useState<File | null>(null)
  const [connectingLabel, setConnectingLabel] = useState('Đang kết nối và yêu cầu quyền microphone...')

  const wsRef = useRef<WebSocket | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const stageTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const sessionIdRef = useRef<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const supported = typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia
  const stages = pipelineStages(mode)

  const cleanupMedia = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    if (recorderRef.current && recorderRef.current.state !== 'inactive') {
      try {
        recorderRef.current.stop()
      } catch {
        // already stopped
      }
    }
    recorderRef.current = null
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
  }, [])

  useEffect(() => cleanupMedia, [cleanupMedia])

  // Drives the simulated pipeline progress bar while finalizing (see
  // `pipelineStages` above) -- stops as soon as the phase moves on, whether
  // that's because the real result arrived or the flow was reset/failed.
  useEffect(() => {
    if (phase !== 'finalizing') {
      if (stageTimerRef.current) {
        clearInterval(stageTimerRef.current)
        stageTimerRef.current = null
      }
      return
    }
    setStageIndex(0)
    stageTimerRef.current = setInterval(() => {
      setStageIndex((i) => Math.min(i + 1, stages.length - 1))
    }, 1200)
    return () => {
      if (stageTimerRef.current) {
        clearInterval(stageTimerRef.current)
        stageTimerRef.current = null
      }
    }
  }, [phase, stages.length])

  const handleStart = useCallback(async () => {
    if (!mode) return
    setError(null)
    setTranscript('')
    setTips([])
    setEvaluation(null)
    setSessionId(null)
    sessionIdRef.current = null
    setElapsed(0)

    const picked = pickRecorderFormat()
    if (!picked) {
      setError('Trình duyệt này không hỗ trợ ghi âm trực tiếp (MediaRecorder).')
      setPhase('failed')
      return
    }

    setPhase('connecting')
    setConnectingLabel('Đang kết nối và yêu cầu quyền microphone...')

    // If a slide/CV was attached, it has to reach the server before the mic
    // opens: create the practice session up front via REST and upload it
    // there, then hand that session id to the WebSocket below so it streams
    // into the same session instead of creating a fresh, material-less one.
    let practiceSessionId: string | undefined
    if (file) {
      setConnectingLabel(mode === 'presentation' ? 'Đang tải slide lên...' : 'Đang tải CV lên...')
      try {
        const created = await createPracticeSession(mode, language)
        practiceSessionId = created.id
        if (mode === 'presentation') {
          await uploadPracticeSlide(created.id, file)
        } else {
          await uploadPracticeResume(created.id, file)
        }
      } catch (err: any) {
        setError(err?.response?.data?.detail || 'Không thể tải lên tệp đính kèm.')
        setPhase('failed')
        return
      }
      setConnectingLabel('Đang kết nối và yêu cầu quyền microphone...')
    }

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      setError('Không thể truy cập microphone. Vui lòng cấp quyền và thử lại.')
      setPhase('failed')
      return
    }
    streamRef.current = stream

    const ws = new WebSocket(practiceStreamUrl(language, picked.format, practiceSessionId))
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      const recorder = new MediaRecorder(stream, { mimeType: picked.mime })
      recorderRef.current = recorder
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
          e.data.arrayBuffer().then((buf) => ws.send(buf))
        }
      }
      recorder.start(1000)
      setPhase('recording')
      timerRef.current = setInterval(() => setElapsed((prev) => prev + 1), 1000)
    }

    ws.onmessage = (event) => {
      let msg: Record<string, unknown>
      try {
        msg = JSON.parse(event.data)
      } catch {
        return
      }
      switch (msg.type) {
        case 'session_started':
          sessionIdRef.current = msg.session_id as string
          setSessionId(msg.session_id as string)
          break
        case 'partial_transcript':
          setTranscript(msg.transcript as string)
          break
        case 'live_tip':
          setTips((prev) => [msg.message as string, ...prev].slice(0, 4))
          break
        case 'final_evaluation':
          setEvaluation(msg as unknown as PracticeEvaluation)
          setPhase('completed')
          cleanupMedia()
          break
        case 'final_evaluation_failed':
          setError((msg.error_message as string) || 'Không thể tạo đánh giá cuối cùng.')
          setPhase('failed')
          cleanupMedia()
          break
      }
    }

    ws.onerror = () => {
      // onclose fires right after with the real diagnosis; nothing to do here.
    }

    ws.onclose = () => {
      setPhase((current) => {
        if (current === 'completed' || current === 'failed') return current
        cleanupMedia()
        // The server finalizes best-effort even on an unexpected disconnect,
        // so the result may still show up shortly under the session id.
        if (sessionIdRef.current) {
          void recoverEvaluation(sessionIdRef.current)
          return 'finalizing'
        }
        setError('Mất kết nối tới máy chủ trước khi bắt đầu ghi âm.')
        return 'failed'
      })
    }
  }, [mode, language, file, cleanupMedia])

  const recoverEvaluation = useCallback(async (id: string) => {
    for (let attempt = 0; attempt < 8; attempt++) {
      await new Promise((r) => setTimeout(r, 1500))
      try {
        const data = await getPracticeEvaluation(id)
        setEvaluation(data)
        setPhase('completed')
        return
      } catch {
        // 409 (not ready yet) or 404 -- keep polling for a bit.
      }
    }
    setError('Kết nối bị gián đoạn và không thể lấy kết quả đánh giá.')
    setPhase('failed')
  }, [])

  const handleStop = useCallback(() => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'end_session' }))
    }
    if (recorderRef.current && recorderRef.current.state !== 'inactive') {
      recorderRef.current.stop()
    }
    streamRef.current?.getTracks().forEach((t) => t.stop())
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    setPhase('finalizing')
  }, [])

  const handleReset = useCallback(() => {
    cleanupMedia()
    wsRef.current = null
    setPhase('idle')
    setError(null)
    setTranscript('')
    setTips([])
    setEvaluation(null)
    setSessionId(null)
  }, [cleanupMedia])

  const overall = evaluation?.scores.overall_score ?? 0
  const scoreColor = overall >= 70 ? 'text-success' : overall >= 40 ? 'text-warning' : 'text-error'
  const scoreRing = overall >= 70 ? 'border-success' : overall >= 40 ? 'border-warning' : 'border-error'
  const activeModeInfo = MODES.find((m) => m.id === mode) ?? null
  const finalizingProgress =
    phase === 'completed' ? 100 : Math.round(((stageIndex + 1) / stages.length) * 90)

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
      >
        <h1 className="text-2xl sm:text-3xl font-semibold text-text-primary mb-2">
          Luyện tập trực tiếp
        </h1>
        <p className="text-text-muted text-sm mb-8">
          Nói trực tiếp qua microphone và nhận nhận xét tức thì -- không cần tải lên video hay slide.
        </p>

        {!supported && (
          <div className="mb-6 flex items-center gap-3 rounded-xl border border-error/20 bg-error-light p-4">
            <Warning className="h-5 w-5 text-error shrink-0" weight="bold" />
            <p className="text-sm text-text-primary">
              Trình duyệt này không hỗ trợ ghi âm trực tiếp. Hãy thử Chrome, Edge, hoặc Firefox bản mới.
            </p>
          </div>
        )}

        {phase === 'idle' && supported && (
          <div className="rounded-xl border border-border bg-surface p-6 sm:p-8">
            <h2 className="mb-4 text-sm font-medium text-text-primary">Chọn chế độ luyện tập</h2>
            <div className="mb-6 grid grid-cols-1 sm:grid-cols-2 gap-4">
              {MODES.map((m) => {
                const Icon = m.icon
                const selected = mode === m.id
                return (
                  <motion.button
                    key={m.id}
                    type="button"
                    onClick={() => {
                      if (mode !== m.id) setFile(null)
                      setMode(m.id)
                    }}
                    whileHover={{ scale: 1.015 }}
                    whileTap={{ scale: 0.985 }}
                    className={cn(
                      'relative text-left rounded-xl border-2 p-5 transition-colors duration-200',
                      'bg-surface focus:outline-none focus:ring-2 focus:ring-accent/30 focus:ring-offset-2',
                      selected ? m.borderColorSelected : 'border-border'
                    )}
                  >
                    <div
                      className={cn(
                        'inline-flex items-center justify-center w-10 h-10 rounded-lg mb-3',
                        m.bgColor
                      )}
                    >
                      <Icon size={20} className={m.iconColor} weight="duotone" />
                    </div>
                    <h3 className="text-sm font-semibold text-text-primary mb-1">{m.label}</h3>
                    <p className="text-xs text-text-muted leading-relaxed">{m.prompt}</p>
                    {selected && (
                      <motion.div
                        layoutId="practice-mode-indicator"
                        className={cn(
                          'absolute top-3 right-3 w-5 h-5 rounded-full flex items-center justify-center',
                          m.id === 'presentation' ? 'bg-accent' : 'bg-emerald-500'
                        )}
                        transition={{ type: 'spring', stiffness: 400, damping: 25 }}
                      >
                        <CheckCircle size={14} weight="fill" className="text-white" />
                      </motion.div>
                    )}
                  </motion.button>
                )
              })}
            </div>

            {activeModeInfo && (
              <div className="mb-6">
                <label className="block text-sm font-medium text-text-primary mb-2">
                  Tải lên {activeModeInfo.fileLabel} (không bắt buộc)
                </label>
                <p className="mb-2 text-xs text-text-muted">
                  Đính kèm để AI đánh giá cả nội dung {activeModeInfo.id === 'presentation' ? 'slide' : 'CV'}, không chỉ giọng nói.
                </p>
                {file ? (
                  <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surface-elevated px-4 py-2.5">
                    <span className="flex min-w-0 items-center gap-2 text-sm text-text-primary">
                      <FileText size={16} className="text-accent shrink-0" />
                      <span className="truncate">{file.name}</span>
                    </span>
                    <button
                      type="button"
                      onClick={() => setFile(null)}
                      className="shrink-0 text-text-muted hover:text-error transition-colors"
                      aria-label="Bỏ chọn tệp"
                    >
                      <X size={16} />
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="w-full rounded-lg border-2 border-dashed border-border px-4 py-3 text-sm text-text-muted hover:border-accent/40 hover:text-text-primary transition-colors"
                  >
                    Chọn tệp {activeModeInfo.fileAccept}
                  </button>
                )}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept={activeModeInfo.fileAccept}
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) setFile(f)
                    e.target.value = ''
                  }}
                />
              </div>
            )}

            <div className="mb-6">
              <label htmlFor="practice-language" className="block text-sm font-medium text-text-primary mb-2">
                Ngôn ngữ
              </label>
              <select
                id="practice-language"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className={cn(
                  'w-full sm:w-64 px-3.5 py-2.5 rounded-lg border border-border',
                  'bg-surface text-text-primary text-sm',
                  'focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent'
                )}
              >
                <option value="vi">Tiếng Việt</option>
                <option value="en">Tiếng Anh</option>
              </select>
            </div>

            <motion.button
              type="button"
              onClick={handleStart}
              disabled={!mode}
              whileHover={mode ? { scale: 1.02 } : {}}
              whileTap={mode ? { scale: 0.98 } : {}}
              className={cn(
                'inline-flex items-center gap-2 rounded-lg px-6 py-3 text-sm font-medium transition-colors duration-200',
                mode
                  ? 'bg-accent text-white hover:bg-accent-hover cursor-pointer'
                  : 'bg-surface-elevated text-text-muted cursor-not-allowed'
              )}
            >
              <Microphone size={18} weight="bold" />
              Bắt đầu luyện tập
            </motion.button>
          </div>
        )}

        {phase === 'connecting' && (
          <div className="rounded-xl border border-border bg-surface p-8 text-center">
            <div className="mx-auto mb-4 h-8 w-8 animate-spin rounded-full border-2 border-accent border-t-transparent" />
            <p className="text-sm text-text-secondary">{connectingLabel}</p>
          </div>
        )}

        {phase === 'recording' && (
          <div className="rounded-xl border border-border bg-surface p-6">
            <div className="mb-6 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="relative flex h-3 w-3">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-error opacity-75" />
                  <span className="relative inline-flex h-3 w-3 rounded-full bg-error" />
                </span>
                <span className="text-sm font-medium text-text-primary">
                  Đang ghi âm{activeModeInfo ? ` -- ${activeModeInfo.label}` : ''}
                </span>
              </div>
              <span className="font-mono text-sm text-text-muted">{formatElapsed(elapsed)}</span>
            </div>

            <div className="mb-6 min-h-[4.5rem] rounded-lg bg-surface-elevated p-4">
              <p className="text-sm text-text-secondary leading-relaxed">
                {transcript || 'Bắt đầu nói -- văn bản sẽ xuất hiện ở đây...'}
              </p>
            </div>

            {tips.length > 0 && (
              <div className="mb-6 space-y-2">
                {tips.map((tip, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-2 rounded-lg bg-warning-light px-3 py-2 text-xs text-text-secondary"
                  >
                    <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" weight="fill" />
                    {tip}
                  </div>
                ))}
              </div>
            )}

            <motion.button
              type="button"
              onClick={handleStop}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-error px-6 py-3 text-sm font-medium text-white hover:opacity-90 transition-opacity duration-200"
            >
              <Stop size={18} weight="fill" />
              Kết thúc &amp; Phân tích
            </motion.button>
          </div>
        )}

        {phase === 'finalizing' && (
          <div className="rounded-xl border border-border bg-surface p-6">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs font-medium text-text-secondary">Tiến trình phân tích</p>
              <p className="text-xs text-text-muted">{finalizingProgress}%</p>
            </div>
            <div className="h-2 w-full rounded-full bg-surface-elevated overflow-hidden mb-4">
              <motion.div
                className="h-full rounded-full bg-accent"
                initial={{ width: 0 }}
                animate={{ width: `${finalizingProgress}%` }}
                transition={{ duration: 0.4, ease: 'easeOut' }}
              />
            </div>
            <div className="flex items-center gap-3">
              <div className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-accent border-t-transparent" />
              <p className="text-sm text-text-secondary">{stages[stageIndex]}</p>
            </div>
          </div>
        )}

        {phase === 'failed' && (
          <div className="rounded-xl border border-error/20 bg-error-light p-6 text-center">
            <MicrophoneSlash className="mx-auto mb-3 h-8 w-8 text-error" weight="bold" />
            <p className="mb-4 text-sm font-medium text-error">{error || 'Đã xảy ra lỗi.'}</p>
            <button
              onClick={handleReset}
              className="inline-flex items-center gap-2 rounded-lg bg-surface px-4 py-2 text-sm font-medium text-text-secondary border border-border hover:text-text-primary transition-colors"
            >
              <ArrowClockwise size={16} />
              Thử lại
            </button>
          </div>
        )}

        {phase === 'completed' && evaluation && (
          <div>
            <div className="mb-6 flex flex-col items-center gap-4 rounded-xl border border-border bg-surface p-6">
              <div
                className={cn(
                  'flex h-24 w-24 items-center justify-center rounded-full border-4 bg-surface',
                  scoreRing
                )}
              >
                <div className="text-center">
                  <span className={cn('text-2xl font-bold tabular-nums', scoreColor)}>
                    {Math.round(overall)}
                  </span>
                  <span className="block text-[10px] font-medium text-text-muted">trên 100</span>
                </div>
              </div>
              {sessionId && (
                <p className="text-xs text-text-muted font-mono">Phiên: {sessionId}</p>
              )}
            </div>

            {nonNullScores(evaluation.scores).length > 0 && (
              <div className="mb-6 rounded-xl border border-border bg-surface p-5 space-y-3">
                <h3 className="text-sm font-semibold text-text-primary mb-1">Chi tiết điểm số</h3>
                {nonNullScores(evaluation.scores).map(([key, val]) => (
                  <ScoreBar key={key} label={SCORE_LABELS[key] ?? key} score={val} />
                ))}
              </div>
            )}

            {(evaluation.reasoning.strengths.length > 0 || evaluation.reasoning.weaknesses.length > 0) && (
              <div className="mb-6 grid gap-4 sm:grid-cols-2">
                {evaluation.reasoning.strengths.length > 0 && (
                  <div className="rounded-xl border border-border bg-surface p-5">
                    <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-success">
                      <CheckCircle className="h-4 w-4" weight="fill" />
                      Điểm mạnh
                    </h3>
                    <ul className="space-y-2">
                      {evaluation.reasoning.strengths.map((item, i) => (
                        <li
                          key={i}
                          className="rounded-lg bg-success-light px-3 py-2 text-xs text-text-secondary"
                        >
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {evaluation.reasoning.weaknesses.length > 0 && (
                  <div className="rounded-xl border border-border bg-surface p-5">
                    <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-error">
                      <XCircle className="h-4 w-4" weight="fill" />
                      Điểm cần cải thiện
                    </h3>
                    <ul className="space-y-2">
                      {evaluation.reasoning.weaknesses.map((item, i) => (
                        <li
                          key={i}
                          className="rounded-lg bg-error-light px-3 py-2 text-xs text-text-secondary"
                        >
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {evaluation.reasoning.suggestions.length > 0 && (
              <div className="mb-6 rounded-xl border border-border bg-surface p-5">
                <h3 className="mb-3 text-sm font-semibold text-text-primary">Đề xuất</h3>
                <ul className="space-y-2">
                  {evaluation.reasoning.suggestions.map((item, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-text-secondary">
                      <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-accent" weight="fill" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <button
              onClick={handleReset}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-6 py-3 text-sm font-medium text-white hover:bg-accent-hover transition-colors duration-200"
            >
              <Microphone size={18} weight="bold" />
              Luyện tập lại
            </button>
          </div>
        )}
      </motion.div>
    </div>
  )
}
