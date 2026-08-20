import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Eye, EyeSlash, SignIn, SpinnerGap, Warning } from '@phosphor-icons/react'
import { apiErrorMessage } from '../lib/api'
import { useAuth } from '../lib/auth-context'

export default function Login() {
  const { user, signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Where the guard bounced them from, so they land back there rather than on
  // the dashboard.
  const from = (location.state as { from?: string } | null)?.from ?? '/app'

  if (user) return <Navigate to={from} replace />

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await signIn(email.trim(), password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(apiErrorMessage(err, 'Đăng nhập không thành công.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-12">
      <div className="mb-8">
        <Link to="/" className="text-sm text-text-muted dark:text-text-muted-dark hover:underline">
          ← Về trang chủ
        </Link>
        <h1 className="mt-4 text-2xl font-semibold text-text-primary dark:text-text-primary-dark">
          Đăng nhập
        </h1>
        <p className="mt-1 text-sm text-text-secondary dark:text-text-secondary-dark">
          Chưa có tài khoản?{' '}
          <Link to="/dang-ky" className="font-medium text-accent hover:underline">
            Đăng ký ngay
          </Link>
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-text-primary dark:text-text-primary-dark">Email</span>
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="ban@truong.edu.vn"
            className="rounded-lg border border-border dark:border-border-dark bg-surface dark:bg-surface-dark px-3 py-2.5 text-sm text-text-primary dark:text-text-primary-dark outline-none focus:border-accent"
          />
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-text-primary dark:text-text-primary-dark">Mật khẩu</span>
          <div className="relative">
            <input
              type={showPassword ? 'text' : 'password'}
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-border dark:border-border-dark bg-surface dark:bg-surface-dark px-3 py-2.5 pr-11 text-sm text-text-primary dark:text-text-primary-dark outline-none focus:border-accent"
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              aria-label={showPassword ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1.5 text-text-muted dark:text-text-muted-dark hover:text-text-primary dark:hover:text-text-primary-dark"
            >
              {showPassword ? <EyeSlash className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </label>

        {error && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-lg bg-error-light px-3 py-2.5 text-sm text-error"
          >
            <Warning className="mt-0.5 h-4 w-4 shrink-0" weight="fill" />
            <span>{error}</span>
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="mt-2 flex items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-60"
        >
          {submitting ? (
            <SpinnerGap className="h-4 w-4 animate-spin" weight="bold" />
          ) : (
            <SignIn className="h-4 w-4" weight="bold" />
          )}
          {submitting ? 'Đang đăng nhập…' : 'Đăng nhập'}
        </button>
      </form>
    </div>
  )
}
