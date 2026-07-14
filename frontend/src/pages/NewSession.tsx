import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'motion/react'
import { FileText, VideoCamera, ArrowRight } from '@phosphor-icons/react'
import { createSession } from '../lib/api'
import { cn } from '../lib/utils'
import type { EvaluationMode } from '../types'

const modes: {
  id: EvaluationMode
  label: string
  description: string
  icon: typeof FileText
  iconColor: string
  bgColor: string
  borderColor: string
  borderColorSelected: string
}[] = [
  {
    id: 'presentation',
    label: 'Chế độ Thuyết trình',
    description:
      'Đánh giá slide và bài thuyết trình của bạn. Tải lên slide PowerPoint và video bài thuyết trình.',
    icon: FileText,
    iconColor: 'text-accent',
    bgColor: 'bg-accent-light',
    borderColor: 'border-border',
    borderColorSelected: 'border-accent',
  },
  {
    id: 'interview',
    label: 'Chế độ Phỏng vấn',
    description:
      'Đánh giá CV và hiệu suất phỏng vấn của bạn. Tải lên PDF CV và video phỏng vấn.',
    icon: VideoCamera,
    iconColor: 'text-emerald-600',
    bgColor: 'bg-emerald-50',
    borderColor: 'border-border',
    borderColorSelected: 'border-emerald-500',
  },
]

export default function NewSession() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<EvaluationMode | null>(null)
  const [language, setLanguage] = useState('vi')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit() {
    if (!mode || submitting) return
    setSubmitting(true)
    setError(null)
    try {
      const res = await createSession(mode, language)
      navigate(`/app/sessions/${res.id}`)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Không thể tạo phiên'
      setError(message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
      >
        <h1 className="text-2xl sm:text-3xl font-semibold text-text-primary mb-2">
          Phiên mới
        </h1>
        <p className="text-text-muted text-sm mb-8">
          Chọn chế độ đánh giá và cấu hình phiên của bạn.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-8">
          {modes.map((m) => {
            const Icon = m.icon
            const selected = mode === m.id
            return (
              <motion.button
                key={m.id}
                type="button"
                onClick={() => setMode(m.id)}
                whileHover={{ scale: 1.015 }}
                whileTap={{ scale: 0.985 }}
                className={cn(
                  'relative text-left rounded-xl border-2 p-6 transition-colors duration-200',
                  'bg-surface focus:outline-none focus:ring-2 focus:ring-accent/30 focus:ring-offset-2',
                  selected ? m.borderColorSelected : m.borderColor
                )}
              >
                <div
                  className={cn(
                    'inline-flex items-center justify-center w-11 h-11 rounded-xl mb-4',
                    m.bgColor
                  )}
                >
                  <Icon size={22} className={m.iconColor} weight="duotone" />
                </div>
                <h3 className="text-base font-semibold text-text-primary mb-2">
                  {m.label}
                </h3>
                <p className="text-sm text-text-muted leading-relaxed">
                  {m.description}
                </p>
                {selected && (
                  <motion.div
                    layoutId="mode-indicator"
                    className={cn(
                      'absolute top-4 right-4 w-5 h-5 rounded-full flex items-center justify-center',
                      m.id === 'presentation' ? 'bg-accent' : 'bg-emerald-500'
                    )}
                    transition={{ type: 'spring', stiffness: 400, damping: 25 }}
                  >
                    <svg
                      width="12"
                      height="12"
                      viewBox="0 0 12 12"
                      fill="none"
                      xmlns="http://www.w3.org/2000/svg"
                    >
                      <path
                        d="M2.5 6L5 8.5L9.5 3.5"
                        stroke="white"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </motion.div>
                )}
              </motion.button>
            )
          })}
        </div>

        <div className="mb-8">
          <label
            htmlFor="language"
            className="block text-sm font-medium text-text-primary mb-2"
          >
            Ngôn ngữ
          </label>
          <select
            id="language"
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className={cn(
              'w-full sm:w-64 px-3.5 py-2.5 rounded-lg border border-border',
              'bg-surface text-text-primary text-sm',
              'focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent',
              'transition-colors duration-200'
            )}
          >
            <option value="vi">Tiếng Việt</option>
            <option value="en">Tiếng Anh</option>
          </select>
        </div>

        {error && (
          <div className="mb-6 px-4 py-3 rounded-lg bg-error-light text-error text-sm">
            {error}
          </div>
        )}

        <motion.button
          type="button"
          onClick={handleSubmit}
          disabled={!mode || submitting}
          whileHover={mode && !submitting ? { scale: 1.01 } : {}}
          whileTap={mode && !submitting ? { scale: 0.98 } : {}}
          className={cn(
            'inline-flex items-center gap-2 px-6 py-3 rounded-lg font-medium text-sm',
            'transition-colors duration-200',
            'focus:outline-none focus:ring-2 focus:ring-accent/40 focus:ring-offset-2',
            mode && !submitting
              ? 'bg-accent text-white hover:bg-accent-hover cursor-pointer'
              : 'bg-surface-elevated text-text-muted cursor-not-allowed'
          )}
        >
          {submitting ? (
            <>
              <span className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Đang tạo...
            </>
          ) : (
            <>
              Bắt đầu phiên
              <ArrowRight size={16} weight="bold" />
            </>
          )}
        </motion.button>
      </motion.div>
    </div>
  )
}
