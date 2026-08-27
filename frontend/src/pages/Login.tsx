import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { motion } from 'motion/react'
import { SignIn, Warning } from '@phosphor-icons/react'
import { useAuth } from '../contexts/AuthContext'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // ProtectedApp redirects here with `from` set to wherever the person was
  // trying to go -- send them back there instead of always landing on the
  // dashboard.
  const from = (location.state as { from?: string } | null)?.from ?? '/app'

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(email, password)
      navigate(from, { replace: true })
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Không thể đăng nhập. Vui lòng thử lại.')
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
        <h1 className="text-xl font-semibold text-text-primary">Đăng nhập</h1>
        <p className="mt-1 text-sm text-text-secondary">Vào lại phiên tự luyện của bạn.</p>

        {error && (
          <div className="mt-4 rounded-lg border border-error/20 bg-error-light p-3 flex items-center gap-2">
            <Warning className="h-4 w-4 text-error shrink-0" weight="bold" />
            <p className="text-xs text-text-primary">{error}</p>
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-5 space-y-4">
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
              autoComplete="current-password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-primary"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
          >
            <SignIn className="h-4 w-4" weight="bold" />
            {submitting ? 'Đang đăng nhập...' : 'Đăng nhập'}
          </button>
        </form>

        <p className="mt-5 text-center text-sm text-text-secondary">
          Chưa có tài khoản?{' '}
          <Link to="/register" className="font-medium text-accent hover:text-accent-hover">
            Đăng ký
          </Link>
        </p>
      </motion.div>
    </div>
  )
}
