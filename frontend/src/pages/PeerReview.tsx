import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { motion } from 'motion/react'
import { Warning, Star, CheckCircle } from '@phosphor-icons/react'
import { getPeerReviewInvite, peerReviewVideoUrl, addPeerMark, submitPeerRubric } from '../lib/api'
import type { PeerReviewState, RubricCriterion, RubricScores } from '../types'
import { RUBRIC_CRITERIA, RUBRIC_LABELS } from '../types'
import VideoTimeline from '../components/VideoTimeline'

const EMPTY_RUBRIC: RubricScores = { clarity: 3, confidence: 3, engagement: 3 }

/**
 * "/cham-ho/:token" -- blind review while `status === 'pending'` (video +
 * mark button + one required rubric at the end), then the same page shows
 * the revealed machine timeline the instant the rubric is submitted. No
 * navigation between the two phases: the reveal is this page updating its
 * own state, not a redirect to the owner's `/phien/:id` screen.
 */
export default function PeerReview() {
  const { token } = useParams<{ token: string }>()

  const [state, setState] = useState<PeerReviewState | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchErrorStatus, setFetchErrorStatus] = useState<number | null>(null)
  const [fetchErrorDetail, setFetchErrorDetail] = useState<string | null>(null)

  const [currentSec, setCurrentSec] = useState(0)
  const [durationSec, setDurationSec] = useState(0)
  const [markText, setMarkText] = useState('')
  const [markError, setMarkError] = useState<string | null>(null)
  const [rubric, setRubric] = useState<RubricScores>(EMPTY_RUBRIC)
  const [rubricText, setRubricText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const videoRef = useRef<HTMLVideoElement | null>(null)

  const fetchState = useCallback(async () => {
    if (!token) return
    try {
      setState(await getPeerReviewInvite(token))
      setFetchErrorStatus(null)
      setFetchErrorDetail(null)
    } catch (err: any) {
      setFetchErrorStatus(err?.response?.status ?? 0)
      setFetchErrorDetail(err?.response?.data?.detail || 'Không thể mở lời mời này.')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    fetchState()
  }, [fetchState])

  const handleAddMark = useCallback(async () => {
    if (!token) return
    setMarkError(null)
    try {
      const note = await addPeerMark(token, currentSec, markText || undefined)
      setState(prev => (prev ? { ...prev, own_marks: [...prev.own_marks, note] } : prev))
      setMarkText('')
    } catch (err: any) {
      setMarkError(err?.response?.data?.detail || 'Không thể thêm mốc đánh dấu.')
    }
  }, [token, currentSec, markText])

  const handleSubmit = useCallback(async () => {
    if (!token) return
    setSubmitError(null)
    setSubmitting(true)
    try {
      setState(await submitPeerRubric(token, rubric, rubricText || undefined))
    } catch (err: any) {
      setSubmitError(err?.response?.data?.detail || 'Không thể nộp đánh giá.')
    } finally {
      setSubmitting(false)
    }
  }, [token, rubric, rubricText])

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-16 flex items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    )
  }

  if (fetchErrorStatus || !state) {
    const message =
      fetchErrorStatus === 410
        ? fetchErrorDetail || 'Lời mời này không còn dùng được.'
        : fetchErrorStatus === 404
          ? 'Không tìm thấy lời mời này.'
          : fetchErrorDetail || 'Có lỗi xảy ra.'
    return (
      <div className="max-w-3xl mx-auto px-6 py-16">
        <div role="alert" className="rounded-xl border border-error/20 bg-error-light p-8 text-center">
          <Warning className="h-10 w-10 text-error mx-auto mb-3" weight="bold" />
          <p className="text-sm font-medium text-error">{message}</p>
        </div>
      </div>
    )
  }

  const isPending = state.status === 'pending'
  const moments = state.own_marks.filter(note => note.mark_sec !== null)

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mb-6">
        <h1 className="text-2xl font-semibold text-text-primary">Chấm hộ bạn</h1>
        <p className="mt-2 text-sm text-text-secondary">
          {isPending
            ? 'Xem video và đánh dấu những điểm bạn thấy đáng chú ý. Bạn sẽ không thấy kết quả máy đo được cho tới khi nộp đánh giá.'
            : 'Cảm ơn bạn đã chấm! Dưới đây là kết quả máy đo được, cùng những mốc bạn đã đánh dấu.'}
        </p>
      </motion.div>

      <div className="rounded-xl border border-border bg-surface p-5 mb-6">
        <video
          ref={videoRef}
          src={peerReviewVideoUrl(token ?? '')}
          controls
          className="w-full rounded-lg bg-black aspect-video mb-4"
          onLoadedMetadata={e => setDurationSec(e.currentTarget.duration)}
          onTimeUpdate={e => setCurrentSec(e.currentTarget.currentTime)}
        />
        {!isPending && (
          <VideoTimeline
            durationSec={durationSec}
            currentSec={currentSec}
            events={state.events}
            notes={[]}
            peerNotes={state.own_marks}
            onSeek={sec => {
              if (videoRef.current) videoRef.current.currentTime = sec
              setCurrentSec(sec)
            }}
          />
        )}
      </div>

      {isPending && (
        <div className="rounded-xl border border-border bg-surface p-5 mb-6">
          <h3 className="text-sm font-semibold text-text-primary mb-4">Đánh dấu một điểm đáng chú ý</h3>
          {markError && <p role="alert" className="mb-3 text-xs text-error">{markError}</p>}
          <div className="flex items-center gap-2 mb-4">
            <span className="text-xs font-mono text-text-muted shrink-0">{Math.round(currentSec)}s</span>
            <input
              type="text"
              value={markText}
              onChange={e => setMarkText(e.target.value)}
              placeholder="Điều bạn thấy đáng chú ý tại thời điểm này (không bắt buộc)..."
              className="flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-primary"
            />
            <button
              type="button"
              onClick={handleAddMark}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover"
            >
              Đánh dấu
            </button>
          </div>
          {moments.length > 0 && (
            <ul className="space-y-2">
              {moments.map(note => (
                <li key={note.note_id} className="flex items-center gap-2 rounded-lg border border-border p-2 text-sm">
                  <span className="font-mono text-xs text-text-muted shrink-0">{Math.round(note.mark_sec ?? 0)}s</span>
                  <span className="flex-1 text-text-primary">{note.text || '(đánh dấu, không có ghi chú)'}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {isPending && (
        <div className="rounded-xl border border-border bg-surface p-5">
          <h3 className="text-sm font-semibold text-text-primary mb-1 flex items-center gap-2">
            <Star className="h-4 w-4" />
            Đánh giá cuối (bắt buộc để nộp)
          </h3>
          <p className="mb-4 text-xs text-text-muted">Nộp xong sẽ hiện ngay kết quả máy đo được -- không sửa lại được sau đó.</p>

          {submitError && <p role="alert" className="mb-3 text-xs text-error">{submitError}</p>}

          <div className="space-y-4 mb-4">
            {RUBRIC_CRITERIA.map(criterion => (
              <RubricSlider
                key={criterion}
                criterion={criterion}
                value={rubric[criterion]}
                onChange={value => setRubric(prev => ({ ...prev, [criterion]: value }))}
              />
            ))}
          </div>

          <textarea
            value={rubricText}
            onChange={e => setRubricText(e.target.value)}
            placeholder="Nhận xét chung (không bắt buộc)..."
            rows={3}
            className="mb-4 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-primary"
          />

          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="inline-flex items-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
          >
            <CheckCircle className="h-4 w-4" weight="bold" />
            {submitting ? 'Đang nộp...' : 'Nộp đánh giá'}
          </button>
        </div>
      )}
    </div>
  )
}

function RubricSlider({
  criterion,
  value,
  onChange,
}: {
  criterion: RubricCriterion
  value: number
  onChange: (value: number) => void
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-text-secondary">{RUBRIC_LABELS[criterion]}</span>
        <span className="font-semibold text-text-primary">{value}/5</span>
      </div>
      <input
        type="range"
        min={1}
        max={5}
        step={1}
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="w-full accent-[var(--color-accent)]"
      />
    </div>
  )
}
