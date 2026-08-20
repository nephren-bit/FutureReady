import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import {
  Eye,
  EyeSlash,
  GraduationCap,
  SpinnerGap,
  Student,
  UserPlus,
  Warning,
} from '@phosphor-icons/react'
import { apiErrorMessage } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import type { UserRole } from '../types/auth'
import { cn } from '../lib/utils'

// Mirrors MIN_PASSWORD_LENGTH in models/auth_models.py. Checked here as well
// as on the server — the report requires both — but the browser check exists
// to save a round trip, not to enforce anything. The server rejects a short
// password regardless of what this form allows.
const MIN_PASSWORD_LENGTH = 8

const ROLE_CHOICES: { value: UserRole; label: string; description: string; icon: typeof Student }[] = [
  {
    value: 'learner',
    label: 'Người học',
    description: 'Tạo phiên đánh giá, xem báo cáo của mình, luyện tập và theo dõi tiến bộ.',
    icon: Student,
  },
  {
    value: 'lecturer',
    label: 'Giảng viên',
    description: 'Có đủ quyền của người học, kèm quyền xem báo cáo học viên và chỉnh trọng số chấm điểm.',
    icon: GraduationCap,
  },
]

export default function Register() {
  const { user, signUp } = useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [role, setRole] = useState<UserRole>('learner')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (user) return <Navigate to="/app" replace />

  // Byte length, not character count: bcrypt caps at 72 *bytes*, and
  // Vietnamese characters take up to three bytes each in UTF-8. A 40-character
  // Vietnamese passphrase can exceed the limit while a 40-character ASCII one
  // never will, so counting characters here would let through a password the
  // server then rejects.
  const passwordBytes = new TextEncoder().encode(password).length
  const tooLong = passwordBytes > 72
  const tooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH
  const mismatch = confirmPassword.length > 0 && password !== confirmPassword

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)

    if (password !== confirmPassword) {
      setError('Hai lần nhập mật khẩu không khớp.')
      return
    }

    setSubmitting(true)
    try {
      await signUp({
        email: email.trim(),
        password,
        full_name: fullName.trim(),
        role,
      })
      // Registration signs the user straight in — there is no approval queue.
      navigate('/app', { replace: true })
    } catch (err) {
      setError(apiErrorMessage(err, 'Đăng ký không thành công.'))
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
          Tạo tài khoản
        </h1>
        <p className="mt-1 text-sm text-text-secondary dark:text-text-secondary-dark">
          Đã có tài khoản?{' '}
          <Link to="/dang-nhap" className="font-medium text-accent hover:underline">
            Đăng nhập
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
          <span className="text-sm font-medium text-text-primary dark:text-text-primary-dark">
            Họ và tên
          </span>
          <input
            type="text"
            autoComplete="name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="Nguyễn Văn An"
            className="rounded-lg border border-border dark:border-border-dark bg-surface dark:bg-surface-dark px-3 py-2.5 text-sm text-text-primary dark:text-text-primary-dark outline-none focus:border-accent"
          />
        </label>

        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-sm font-medium text-text-primary dark:text-text-primary-dark">
            Bạn dùng hệ thống với vai trò nào?
          </legend>
          {ROLE_CHOICES.map(({ value, label, description, icon: Icon }) => (
            <button
              key={value}
              type="button"
              onClick={() => setRole(value)}
              aria-pressed={role === value}
              className={cn(
                'flex items-start gap-3 rounded-lg border px-3 py-3 text-left transition-colors',
                role === value
                  ? 'border-accent bg-accent-light dark:bg-accent-light-dark'
                  : 'border-border dark:border-border-dark hover:bg-surface-elevated dark:hover:bg-surface-elevated-dark'
              )}
            >
              <Icon
                className={cn('mt-0.5 h-5 w-5 shrink-0', role === value ? 'text-accent' : 'text-text-muted dark:text-text-muted-dark')}
                weight={role === value ? 'fill' : 'regular'}
              />
              <span className="flex flex-col gap-0.5">
                <span className="text-sm font-medium text-text-primary dark:text-text-primary-dark">
                  {label}
                </span>
                <span className="text-xs text-text-secondary dark:text-text-secondary-dark">
                  {description}
                </span>
              </span>
            </button>
          ))}
          <p className="text-xs text-text-muted dark:text-text-muted-dark">
            Đổi được bất cứ lúc nào trong cài đặt, không mất dữ liệu.
          </p>
        </fieldset>

        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-text-primary dark:text-text-primary-dark">
            Mật khẩu
          </span>
          <div className="relative">
            <input
              type={showPassword ? 'text' : 'password'}
              required
              minLength={MIN_PASSWORD_LENGTH}
              autoComplete="new-password"
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
          {tooShort && (
            <span className="text-xs text-warning">
              Mật khẩu cần ít nhất {MIN_PASSWORD_LENGTH} ký tự.
            </span>
          )}
          {tooLong && (
            <span className="text-xs text-warning">
              Mật khẩu dài {passwordBytes} byte, vượt giới hạn 72 byte. Ký tự tiếng Việt chiếm nhiều
              byte hơn, hãy rút ngắn lại.
            </span>
          )}
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-text-primary dark:text-text-primary-dark">
            Nhập lại mật khẩu
          </span>
          <input
            type={showPassword ? 'text' : 'password'}
            required
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className="rounded-lg border border-border dark:border-border-dark bg-surface dark:bg-surface-dark px-3 py-2.5 text-sm text-text-primary dark:text-text-primary-dark outline-none focus:border-accent"
          />
          {mismatch && <span className="text-xs text-warning">Hai lần nhập chưa khớp.</span>}
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
          disabled={submitting || tooShort || tooLong || mismatch}
          className="mt-2 flex items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-60"
        >
          {submitting ? (
            <SpinnerGap className="h-4 w-4 animate-spin" weight="bold" />
          ) : (
            <UserPlus className="h-4 w-4" weight="bold" />
          )}
          {submitting ? 'Đang tạo tài khoản…' : 'Tạo tài khoản'}
        </button>
      </form>
    </div>
  )
}
