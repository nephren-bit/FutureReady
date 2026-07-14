import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { motion } from 'motion/react'
import { ArrowLeft, CheckCircle, XCircle, Lightbulb, Warning, TrendUp } from '@phosphor-icons/react'
import { getReport } from '../lib/api'
import { cn } from '../lib/utils'
import type { EvaluationReport, ScoreBreakdown, DerivedFeatures } from '../types'
import ScoreRadar from '../components/charts/ScoreRadar'
import ScoreBar from '../components/charts/ScoreBar'

const SCORE_LABELS: Record<string, string> = {
  resume_score: 'CV',
  slide_content_score: 'Nội dung Slide',
  slide_visual_score: 'Hình ảnh Slide',
  speech_delivery_score: 'Giọng nói',
  transcript_quality_score: 'Chất lượng nội dung',
  body_language_score: 'Ngôn ngữ cơ thể',
  emotional_confidence_score: 'Tự tin cảm xúc',
  presentation_readiness: 'Sẵn sàng thuyết trình',
  interview_readiness: 'Sẵn sàng phỏng vấn',
}

const DERIVED_LABELS: Record<keyof DerivedFeatures, string> = {
  professionalism: 'Chuyên nghiệp',
  presentation_density: 'Mật độ thuyết trình',
  communication_confidence: 'Tự tin giao tiếp',
  visual_engagement: 'Sự thu hút trực quan',
  voice_confidence: 'Tự tin giọng nói',
  presentation_readiness: 'Sẵn sàng thuyết trình',
}

function formatLabel(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function scoreColor(score: number): string {
  if (score > 70) return 'text-success'
  if (score > 40) return 'text-warning'
  return 'text-error'
}

function scoreBg(score: number): string {
  if (score > 70) return 'bg-success'
  if (score > 40) return 'bg-warning'
  return 'bg-error'
}

function scoreRing(score: number): string {
  if (score > 70) return 'border-success'
  if (score > 40) return 'border-warning'
  return 'border-error'
}

function nonNullScores(scores: ScoreBreakdown): Record<string, number> {
  const result: Record<string, number> = {}
  for (const [key, val] of Object.entries(scores)) {
    if (key !== 'overall_score' && val !== null && val !== undefined) {
      result[key] = val
    }
  }
  return result
}

const sectionAnim = {
  initial: { opacity: 0, y: 24 },
  whileInView: { opacity: 1, y: 0 },
  viewport: { once: true },
  transition: { duration: 0.5, ease: 'easeOut' },
}

function Skeleton() {
  return (
    <div className="mx-auto max-w-5xl animate-pulse px-4 py-12 sm:px-6">
      <div className="mb-8 flex items-center gap-3">
        <div className="h-5 w-5 rounded bg-surface-elevated" />
        <div className="h-6 w-48 rounded bg-surface-elevated" />
      </div>
      <div className="mb-12 flex flex-col items-center gap-6 md:flex-row md:items-start">
        <div className="h-[300px] w-full rounded-xl bg-surface-elevated md:w-1/2" />
        <div className="flex w-full flex-col gap-3 md:w-1/2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-8 rounded bg-surface-elevated" />
          ))}
        </div>
      </div>
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="mb-6">
          <div className="mb-3 h-6 w-40 rounded bg-surface-elevated" />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="h-20 rounded-xl bg-surface-elevated" />
            <div className="h-20 rounded-xl bg-surface-elevated" />
          </div>
        </div>
      ))}
    </div>
  )
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="mx-auto max-w-5xl px-4 py-24 text-center sm:px-6">
      <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-error-light">
        <Warning className="h-8 w-8 text-error" weight="fill" />
      </div>
      <h2 className="mb-2 text-xl font-semibold text-text-primary">
        Không thể tải báo cáo
      </h2>
      <p className="mb-6 text-sm text-text-secondary">{message}</p>
      <div className="flex items-center justify-center gap-3">
        <button
          onClick={onRetry}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover"
        >
          Thử lại
        </button>
        <Link
          to="/app"
          className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-text-secondary transition-colors hover:bg-surface-elevated"
        >
          Quay lại Bảng điều khiển
        </Link>
      </div>
    </div>
  )
}

export default function Report() {
  const { id } = useParams<{ id: string }>()
  const [report, setReport] = useState<EvaluationReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function fetchReport() {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      const data = await getReport(id)
      setReport(data)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'An unexpected error occurred'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchReport()
  }, [id])

  if (loading) return <Skeleton />
  if (error) return <ErrorState message={error} onRetry={fetchReport} />
  if (!report) return null

  const overall = report.scores.overall_score
  const filteredScores = nonNullScores(report.scores)
  const derived = report.derived_features
  const reasoning = report.reasoning

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
      <motion.header {...sectionAnim} className="mb-12">
        <Link
          to={`/app/sessions/${id}`}
          className="mb-6 inline-flex items-center gap-2 text-sm font-medium text-text-secondary transition-colors hover:text-accent"
        >
          <ArrowLeft className="h-4 w-4" />
          Quay lại Phiên
        </Link>

        <div className="flex flex-col items-center gap-8 md:flex-row md:items-start">
          <div className="flex flex-col items-center">
            <h1 className="mb-6 text-2xl font-bold text-text-primary">
              Báo cáo Đánh giá
            </h1>
            <div
              className={cn(
                'relative flex h-36 w-36 items-center justify-center rounded-full border-4 bg-surface',
                scoreRing(overall)
              )}
            >
              <div className="text-center">
                <span className={cn('text-4xl font-bold tabular-nums', scoreColor(overall))}>
                  {Math.round(overall)}
                </span>
                <span className="block text-xs font-medium text-text-muted">trên 100</span>
              </div>
            </div>
          </div>

          {Object.keys(filteredScores).length > 0 && (
            <div className="w-full md:w-auto md:flex-1">
              <ScoreRadar scores={report.scores} />
            </div>
          )}
        </div>
      </motion.header>

      {Object.keys(filteredScores).length > 0 && (
        <motion.section {...sectionAnim} className="mb-12">
          <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold text-text-primary">
            <TrendUp className="h-5 w-5 text-accent" weight="fill" />
            Phân tích Điểm số
          </h2>
          <div className="grid gap-4 rounded-xl border border-border bg-surface p-6 sm:grid-cols-2">
            {Object.entries(filteredScores).map(([key, val]) => (
              <ScoreBar key={key} label={SCORE_LABELS[key] ?? formatLabel(key)} score={val} />
            ))}
          </div>
        </motion.section>
      )}

      {derived && (
        <motion.section {...sectionAnim} className="mb-12">
          <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold text-text-primary">
            <TrendUp className="h-5 w-5 text-accent" weight="fill" />
            Đặc trưng Thuộc tính
          </h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {(Object.entries(DERIVED_LABELS) as [keyof DerivedFeatures, string][]).map(
              ([key, label]) => {
                const val = derived[key]
                return (
                  <div
                    key={key}
                    className="rounded-xl border border-border bg-surface p-4"
                  >
                    <p className="mb-1 text-xs font-medium text-text-muted">{label}</p>
                    <p className={cn('text-2xl font-bold tabular-nums', scoreColor(val))}>
                      {Math.round(val)}
                    </p>
                    <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-neutral-100">
                      <div
                        className={cn('h-full rounded-full transition-all duration-500', scoreBg(val))}
                        style={{ width: `${Math.max(0, Math.min(100, val))}%` }}
                      />
                    </div>
                  </div>
                )
              }
            )}
          </div>
        </motion.section>
      )}

      {reasoning && (reasoning.strengths.length > 0 || reasoning.weaknesses.length > 0) && (
        <motion.section {...sectionAnim} className="mb-12">
          <h2 className="mb-4 text-lg font-semibold text-text-primary">
            Điểm mạnh &amp; Điểm yếu
          </h2>
          <div className="grid gap-4 md:grid-cols-2">
            {reasoning.strengths.length > 0 && (
              <div className="rounded-xl border border-border bg-surface p-5">
                <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-success">
                  <CheckCircle className="h-4 w-4" weight="fill" />
                  Điểm mạnh
                </h3>
                <ul className="space-y-2">
                  {reasoning.strengths.map((item, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-2 rounded-lg bg-success-light px-3 py-2 text-sm text-text-secondary"
                    >
                      <CheckCircle className="mt-0.5 h-4 w-4 shrink-0 text-success" weight="fill" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {reasoning.weaknesses.length > 0 && (
              <div className="rounded-xl border border-border bg-surface p-5">
                <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-error">
                  <XCircle className="h-4 w-4" weight="fill" />
                  Điểm yếu
                </h3>
                <ul className="space-y-2">
                  {reasoning.weaknesses.map((item, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-2 rounded-lg bg-error-light px-3 py-2 text-sm text-text-secondary"
                    >
                      <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-error" weight="fill" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </motion.section>
      )}

      {reasoning && reasoning.improvement_plan.length > 0 && (
        <motion.section {...sectionAnim} className="mb-12">
          <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold text-text-primary">
            <Lightbulb className="h-5 w-5 text-warning" weight="fill" />
            Kế hoạch Cải thiện
          </h2>
          <div className="rounded-xl border border-border bg-surface p-5">
            <ol className="space-y-3">
              {reasoning.improvement_plan.map((item, i) => (
                <li key={i} className="flex items-start gap-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-warning-light text-xs font-bold text-warning">
                    {i + 1}
                  </span>
                  <span className="pt-0.5 text-sm text-text-secondary">{item}</span>
                </li>
              ))}
            </ol>
          </div>
        </motion.section>
      )}

      {reasoning &&
        (reasoning.presentation_feedback || reasoning.interview_feedback || reasoning.suggestions.length > 0) && (
          <motion.section {...sectionAnim} className="mb-12">
            <h2 className="mb-4 text-lg font-semibold text-text-primary">
              Phản hồi AI
            </h2>

            {reasoning.presentation_feedback && (
              <div className="mb-4 rounded-xl border border-border bg-surface p-5">
                <h3 className="mb-2 text-sm font-semibold text-text-primary">
                  Phản hồi Thuyết trình
                </h3>
                <p className="text-sm leading-relaxed text-text-secondary">
                  {reasoning.presentation_feedback}
                </p>
              </div>
            )}

            {reasoning.interview_feedback && (
              <div className="mb-4 rounded-xl border border-border bg-surface p-5">
                <h3 className="mb-2 text-sm font-semibold text-text-primary">
                  Phản hồi Phỏng vấn
                </h3>
                <p className="text-sm leading-relaxed text-text-secondary">
                  {reasoning.interview_feedback}
                </p>
              </div>
            )}

            {reasoning.suggestions.length > 0 && (
              <div className="rounded-xl border border-border bg-surface p-5">
                <h3 className="mb-3 text-sm font-semibold text-text-primary">Đề xuất</h3>
                <ul className="space-y-2">
                  {reasoning.suggestions.map((item, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-text-secondary">
                      <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-accent" weight="fill" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </motion.section>
        )}

      {reasoning && reasoning.interview_questions && reasoning.interview_questions.length > 0 && (
        <motion.section {...sectionAnim} className="mb-12">
          <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold text-text-primary">
            <Question className="h-5 w-5 text-accent" weight="fill" />
            Câu hỏi Phỏng vấn
          </h2>
          <div className="rounded-xl border border-border bg-surface p-5">
            <ol className="space-y-3">
              {reasoning.interview_questions.map((q, i) => (
                <li key={i} className="flex items-start gap-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-light text-xs font-bold text-accent">
                    {i + 1}
                  </span>
                  <span className="pt-0.5 text-sm text-text-secondary">{q}</span>
                </li>
              ))}
            </ol>
          </div>
        </motion.section>
      )}

      <motion.footer {...sectionAnim} className="border-t border-border pt-8">
        <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-center sm:gap-4">
          <Link
            to="/app"
            className="rounded-lg border border-border px-5 py-2.5 text-sm font-medium text-text-secondary transition-colors hover:bg-surface-elevated"
          >
            Quay lại Bảng điều khiển
          </Link>
          <Link
            to="/app/new"
            className="rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-hover"
          >
            Phiên mới
          </Link>
        </div>
      </motion.footer>
    </div>
  )
}
