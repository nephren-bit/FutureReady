import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'motion/react'
import { UserPlus, Warning } from '@phosphor-icons/react'
import { useAuth } from '../contexts/AuthContext'

// Mirrors models.auth_models.MIN_PASSWORD_LENGTH -- the server is the real
// gate, this is only so the person doesn't wait for a round-trip to find out.
const MIN_PASSWORD_LENGTH = 8

export default function Register() {
  const { register } = useAuth()
  const navigate = useNavigate()

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)

    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Mật khẩu phải có ít nhất ${MIN_PASSWORD_LENGTH} ký tự.`)
      return
    }

    setSubmitting(true)
    try {
      // No approval queue, no role selection -- registering logs the
      // account in immediately (specs/in-class-analysis/plan.md).
      await register(email, password, fullName)
      navigate('/app', { replace: true })
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Không thể đăng ký. Vui lòng thử lại.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-6 py-12">
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-sm rounded-xl border border-border bg-surface p-6"
      >
        <h1 className="text-xl font-semibold text-text-primary">Đăng ký</h1>
        <p className="mt-1 text-sm text-text-secondary">Tạo tài khoản và vào luyện tập ngay.</p>

        {error && (
          <div role="alert" className="mt-4 rounded-lg border border-error/20 bg-error-light p-3 flex items-center gap-2">
            <Warning className="h-4 w-4 text-error shrink-0" weight="bold" />
            <p className="text-xs text-text-primary">{error}</p>
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-5 space-y-4">
          <div>
            <label htmlFor="full_name" className="mb-1.5 block text-xs font-medium text-text-secondary">
              Họ tên
            </label>
            <input
              id="full_name"
              type="text"
              required
              autoComplete="name"
              value={fullName}
              onChange={e => setFullName(e.target.value)}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-primary"
            />
          </div>
          <div>
            <label htmlFor="email" className="mb-1.5 block text-xs font-medium text-text-secondary">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-primary"
            />
          </div>
          <div>
            <label htmlFor="password" className="mb-1.5 block text-xs font-medium text-text-secondary">
              Mật khẩu
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={MIN_PASSWORD_LENGTH}
              autoComplete="new-password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-primary"
            />
            <p className="mt-1 text-xs text-text-muted">Ít nhất {MIN_PASSWORD_LENGTH} ký tự.</p>
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
          >
            <UserPlus className="h-4 w-4" weight="bold" />
            {submitting ? 'Đang đăng ký...' : 'Đăng ký'}
          </button>
        </form>

        <p className="mt-5 text-center text-sm text-text-secondary">
          Đã có tài khoản?{' '}
          <Link to="/login" className="font-medium text-accent hover:text-accent-hover">
            Đăng nhập
          </Link>
        </p>
      </motion.div>
    </div>
  )
}
