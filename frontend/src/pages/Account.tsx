import { useState } from 'react'
import type { FormEvent } from 'react'
import { CheckCircle, SpinnerGap, Warning } from '@phosphor-icons/react'
import { apiErrorMessage, changeOwnRole, changePassword, updateProfile } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import { cn } from '../lib/utils'
import type { UserRole } from '../types/auth'
import { roleLabel } from '../types/auth'

/**
 * The signed-in user's own settings — permission matrix row 3.
 *
 * Role switching lives here because the report requires it to be changeable
 * "in settings, without losing data". Only `role` is written; sessions,
 * reports, and practice history all survive the switch untouched.
 */
export default function Account() {
  const { user, setUser, signOut } = useAuth()

  const [fullName, setFullName] = useState(user?.full_name ?? '')
  const [profileState, setProfileState] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [profileError, setProfileError] = useState<string | null>(null)

  const [roleState, setRoleState] = useState<'idle' | 'saving'>('idle')
  const [roleError, setRoleError] = useState<string | null>(null)

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [passwordState, setPasswordState] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [passwordError, setPasswordError] = useState<string | null>(null)

  if (!user) return null

  async function saveProfile(event: FormEvent) {
    event.preventDefault()
    setProfileError(null)
    setProfileState('saving')
    try {
      setUser(await updateProfile({ full_name: fullName.trim() }))
      setProfileState('saved')
    } catch (err) {
      setProfileError(apiErrorMessage(err, 'Không lưu được hồ sơ.'))
      setProfileState('idle')
    }
  }

  async function switchRole(role: UserRole) {
    if (role === user?.role) return
    setRoleError(null)
    setRoleState('saving')
    try {
      setUser(await changeOwnRole(role))
    } catch (err) {
      setRoleError(apiErrorMessage(err, 'Không đổi được vai trò.'))
    } finally {
      setRoleState('idle')
    }
  }

  async function savePassword(event: FormEvent) {
    event.preventDefault()
    setPasswordError(null)
    setPasswordState('saving')
    try {
      await changePassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setPasswordState('saved')
    } catch (err) {
      setPasswordError(apiErrorMessage(err, 'Không đổi được mật khẩu.'))
      setPasswordState('idle')
    }
  }

  const inputClass =
    'rounded-lg border border-border dark:border-border-dark bg-surface dark:bg-surface-dark px-3 py-2.5 text-sm text-text-primary dark:text-text-primary-dark outline-none focus:border-accent'
  const cardClass =
    'rounded-xl border border-border dark:border-border-dark bg-surface dark:bg-surface-dark p-5'

  return (
    <div className="mx-auto max-w-2xl px-4 py-8 sm:px-6">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-text-primary dark:text-text-primary-dark">
          Tài khoản
        </h1>
        <p className="mt-1 text-sm text-text-secondary dark:text-text-secondary-dark">
          {user.email} · {roleLabel(user)}
          {user.is_verified && ' · đã xác minh'}
        </p>
      </header>

      <div className="flex flex-col gap-4">
        <form onSubmit={saveProfile} className={cardClass}>
          <h2 className="mb-3 text-sm font-semibold text-text-primary dark:text-text-primary-dark">
            Hồ sơ cá nhân
          </h2>
          <label className="flex flex-col gap-1.5">
            <span className="text-sm text-text-secondary dark:text-text-secondary-dark">Họ và tên</span>
            <input
              type="text"
              value={fullName}
              onChange={(e) => {
                setFullName(e.target.value)
                setProfileState('idle')
              }}
              className={inputClass}
            />
          </label>
          <p className="mt-2 text-xs text-text-muted dark:text-text-muted-dark">
            Email là danh tính đăng nhập nên không sửa được ở đây.
          </p>
          {profileError && <p className="mt-2 text-xs text-error">{profileError}</p>}
          <button
            type="submit"
            disabled={profileState === 'saving'}
            className="mt-3 flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-60"
          >
            {profileState === 'saving' && <SpinnerGap className="h-4 w-4 animate-spin" weight="bold" />}
            {profileState === 'saved' && <CheckCircle className="h-4 w-4" weight="fill" />}
            {profileState === 'saved' ? 'Đã lưu' : 'Lưu'}
          </button>
        </form>

        <section className={cardClass}>
          <h2 className="mb-1 text-sm font-semibold text-text-primary dark:text-text-primary-dark">
            Vai trò
          </h2>
          <p className="mb-3 text-xs text-text-muted dark:text-text-muted-dark">
            Đổi vai trò không làm mất dữ liệu — lịch sử phiên và báo cáo vẫn giữ nguyên, đổi ngược lại
            là thấy lại đầy đủ.
          </p>

          {user.is_admin ? (
            <p className="rounded-lg bg-surface-elevated dark:bg-surface-elevated-dark px-3 py-2.5 text-xs text-text-secondary dark:text-text-secondary-dark">
              Tài khoản này có quyền quản trị viên. Quyền đó chỉ cấp và thu hồi bằng lệnh tại máy chủ,
              không đổi được từ giao diện.
            </p>
          ) : (
            <div className="flex gap-2">
              {(['learner', 'lecturer'] as UserRole[]).map((role) => (
                <button
                  key={role}
                  type="button"
                  disabled={roleState === 'saving'}
                  onClick={() => switchRole(role)}
                  aria-pressed={user.role === role}
                  className={cn(
                    'flex-1 rounded-lg border px-3 py-2.5 text-sm font-medium transition-colors disabled:opacity-60',
                    user.role === role
                      ? 'border-accent bg-accent-light dark:bg-accent-light-dark text-accent'
                      : 'border-border dark:border-border-dark text-text-secondary dark:text-text-secondary-dark hover:bg-surface-elevated dark:hover:bg-surface-elevated-dark'
                  )}
                >
                  {role === 'learner' ? 'Người học' : 'Giảng viên'}
                </button>
              ))}
            </div>
          )}
          {roleError && <p className="mt-2 text-xs text-error">{roleError}</p>}
        </section>

        <form onSubmit={savePassword} className={cardClass}>
          <h2 className="mb-3 text-sm font-semibold text-text-primary dark:text-text-primary-dark">
            Đổi mật khẩu
          </h2>
          <div className="flex flex-col gap-3">
            <label className="flex flex-col gap-1.5">
              <span className="text-sm text-text-secondary dark:text-text-secondary-dark">
                Mật khẩu hiện tại
              </span>
              <input
                type="password"
                required
                autoComplete="current-password"
                value={currentPassword}
                onChange={(e) => {
                  setCurrentPassword(e.target.value)
                  setPasswordState('idle')
                }}
                className={inputClass}
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-sm text-text-secondary dark:text-text-secondary-dark">
                Mật khẩu mới
              </span>
              <input
                type="password"
                required
                minLength={8}
                autoComplete="new-password"
                value={newPassword}
                onChange={(e) => {
                  setNewPassword(e.target.value)
                  setPasswordState('idle')
                }}
                className={inputClass}
              />
            </label>
          </div>
          {passwordError && (
            <div role="alert" className="mt-2 flex items-start gap-2 text-xs text-error">
              <Warning className="mt-0.5 h-3.5 w-3.5 shrink-0" weight="fill" />
              <span>{passwordError}</span>
            </div>
          )}
          <button
            type="submit"
            disabled={passwordState === 'saving'}
            className="mt-3 flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-60"
          >
            {passwordState === 'saving' && <SpinnerGap className="h-4 w-4 animate-spin" weight="bold" />}
            {passwordState === 'saved' && <CheckCircle className="h-4 w-4" weight="fill" />}
            {passwordState === 'saved' ? 'Đã đổi' : 'Đổi mật khẩu'}
          </button>
        </form>

        <button
          type="button"
          onClick={signOut}
          className="self-start rounded-lg border border-border dark:border-border-dark px-4 py-2 text-sm font-medium text-text-secondary dark:text-text-secondary-dark hover:bg-surface-elevated dark:hover:bg-surface-elevated-dark"
        >
          Đăng xuất
        </button>
      </div>
    </div>
  )
}
