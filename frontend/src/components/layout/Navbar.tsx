import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { House, Plus, List, Microphone, X, UserCircle, ShieldCheck } from '@phosphor-icons/react'
import { cn } from '../../lib/utils'
import { useAuth } from '../../lib/auth-context'
import { roleLabel } from '../../types/auth'

const navLinks = [
  { to: '/app', label: 'Bảng điều khiển', icon: List },
  { to: '/app/new', label: 'Phiên mới', icon: Plus },
  { to: '/app/practice', label: 'Luyện tập', icon: Microphone },
]

export default function Navbar() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const { user, isAdmin } = useAuth()

  // The admin entry is hidden from non-administrators as a courtesy, not as a
  // control: `/admin/*` answers 403 to their token either way (see
  // routers/dependencies.py). Hiding a link never protected anything.
  const links = isAdmin
    ? [...navLinks, { to: '/app/quan-tri', label: 'Quản trị', icon: ShieldCheck }]
    : navLinks

  function isActive(to: string) {
    if (to === '/app') return location.pathname === '/app' || location.pathname === '/app/'
    return location.pathname.startsWith(to)
  }

  return (
    <header className="sticky top-0 z-50 h-16 glass border-b border-border dark:border-border-dark">
      <nav className="mx-auto flex h-full max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link
          to="/app"
          className="flex items-center gap-2 text-lg font-semibold text-text-primary dark:text-text-primary-dark"
        >
          <House className="h-5 w-5 text-text-muted dark:text-text-muted-dark" weight="fill" />
          <span>EmpathAI</span>
          <span className="h-2 w-2 rounded-full bg-accent" />
        </Link>

        <ul className="hidden items-center gap-1 sm:flex">
          {links.map(({ to, label, icon: Icon }) => (
            <li key={to}>
              <Link
                to={to}
                className={cn(
                  'flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                  isActive(to)
                    ? 'bg-accent-light dark:bg-accent-light-dark text-accent dark:text-accent-hover'
                    : 'text-text-secondary dark:text-text-secondary-dark hover:bg-surface-elevated dark:hover:bg-surface-elevated-dark hover:text-text-primary dark:hover:text-text-primary-dark'
                )}
              >
                <Icon className="h-4 w-4" weight={isActive(to) ? 'fill' : 'regular'} />
                {label}
              </Link>
            </li>
          ))}
        </ul>

        <Link
          to="/app/tai-khoan"
          className={cn(
            'hidden items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors sm:flex',
            isActive('/app/tai-khoan')
              ? 'bg-accent-light dark:bg-accent-light-dark text-accent dark:text-accent-hover'
              : 'text-text-secondary dark:text-text-secondary-dark hover:bg-surface-elevated dark:hover:bg-surface-elevated-dark'
          )}
        >
          <UserCircle className="h-4 w-4" weight={isActive('/app/tai-khoan') ? 'fill' : 'regular'} />
          <span className="max-w-[10rem] truncate">
            {user?.full_name || user?.email || 'Tài khoản'}
          </span>
          {user && (
            <span className="rounded bg-surface-elevated dark:bg-surface-elevated-dark px-1.5 py-0.5 text-xs text-text-muted dark:text-text-muted-dark">
              {roleLabel(user)}
            </span>
          )}
        </Link>

        <button
          type="button"
          onClick={() => setMobileOpen(!mobileOpen)}
          className="flex h-10 w-10 items-center justify-center rounded-lg text-text-secondary dark:text-text-secondary-dark hover:bg-surface-elevated dark:hover:bg-surface-elevated-dark sm:hidden"
          aria-label={mobileOpen ? 'Đóng menu' : 'Mở menu'}
        >
          {mobileOpen ? (
            <X className="h-5 w-5" weight="bold" />
          ) : (
            <List className="h-5 w-5" weight="bold" />
          )}
        </button>
      </nav>

      {mobileOpen && (
        <div className="border-t border-border dark:border-border-dark glass sm:hidden">
          <ul className="flex flex-col gap-1 p-3">
            {links.map(({ to, label, icon: Icon }) => (
              <li key={to}>
                <Link
                  to={to}
                  onClick={() => setMobileOpen(false)}
                  className={cn(
                    'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                    isActive(to)
                      ? 'bg-accent-light dark:bg-accent-light-dark text-accent dark:text-accent-hover'
                      : 'text-text-secondary dark:text-text-secondary-dark hover:bg-surface-elevated dark:hover:bg-surface-elevated-dark hover:text-text-primary dark:hover:text-text-primary-dark'
                  )}
                >
                  <Icon className="h-5 w-5" weight={isActive(to) ? 'fill' : 'regular'} />
                  {label}
                </Link>
              </li>
            ))}
            <li>
              <Link
                to="/app/tai-khoan"
                onClick={() => setMobileOpen(false)}
                className={cn(
                  'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                  isActive('/app/tai-khoan')
                    ? 'bg-accent-light dark:bg-accent-light-dark text-accent dark:text-accent-hover'
                    : 'text-text-secondary dark:text-text-secondary-dark hover:bg-surface-elevated dark:hover:bg-surface-elevated-dark hover:text-text-primary dark:hover:text-text-primary-dark'
                )}
              >
                <UserCircle className="h-5 w-5" weight={isActive('/app/tai-khoan') ? 'fill' : 'regular'} />
                {user?.full_name || user?.email || 'Tài khoản'}
              </Link>
            </li>
          </ul>
        </div>
      )}
    </header>
  )
}
