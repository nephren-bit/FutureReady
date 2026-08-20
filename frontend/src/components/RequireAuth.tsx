import { Navigate, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { SpinnerGap } from '@phosphor-icons/react'
import { useAuth } from '../lib/auth-context'

/**
 * Route guards.
 *
 * These decide what is *shown*, never what is *allowed*. Every protected
 * route is enforced again on the server by `require_user` / `require_lecturer`
 * / `require_admin`, because anything the browser decides can be bypassed by
 * not using the browser. Hiding the admin link is a courtesy to the user, not
 * a security control — `GET /admin/users` answers 403 to a learner's token
 * whether or not the link was ever rendered.
 */

function Loading() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <SpinnerGap
        className="h-8 w-8 animate-spin text-text-muted dark:text-text-muted-dark"
        weight="bold"
      />
    </div>
  )
}

function NoAccess({ message }: { message: string }) {
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-md flex-col items-center justify-center gap-3 px-6 text-center">
      <h1 className="text-xl font-semibold text-text-primary dark:text-text-primary-dark">
        Không có quyền truy cập
      </h1>
      <p className="text-sm text-text-secondary dark:text-text-secondary-dark">{message}</p>
    </div>
  )
}

/** Any signed-in account. Sends guests to sign-in, remembering where they were headed. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return <Loading />
  if (!user) {
    // `state.from` lets the sign-in page return the user to the page they
    // actually wanted instead of dumping everyone on the dashboard.
    return <Navigate to="/dang-nhap" state={{ from: location.pathname }} replace />
  }
  return <>{children}</>
}

/** Lecturer or administrator (permission matrix rows 9 and 10). */
export function RequireLecturer({ children }: { children: ReactNode }) {
  const { user, loading, isLecturer } = useAuth()
  const location = useLocation()

  if (loading) return <Loading />
  if (!user) return <Navigate to="/dang-nhap" state={{ from: location.pathname }} replace />
  if (!isLecturer) {
    return <NoAccess message="Mục này dành cho giảng viên. Bạn có thể đổi vai trò trong phần cài đặt tài khoản." />
  }
  return <>{children}</>
}

/** Administrator only (permission matrix rows 11 to 15). */
export function RequireAdmin({ children }: { children: ReactNode }) {
  const { user, loading, isAdmin } = useAuth()
  const location = useLocation()

  if (loading) return <Loading />
  if (!user) return <Navigate to="/dang-nhap" state={{ from: location.pathname }} replace />
  if (!isAdmin) {
    return (
      <NoAccess message="Mục này dành cho quản trị viên. Quyền quản trị chỉ được cấp bằng lệnh tại máy chủ, không đăng ký được từ giao diện." />
    )
  }
  return <>{children}</>
}
