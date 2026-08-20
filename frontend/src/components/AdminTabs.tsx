import { Link, useLocation } from 'react-router-dom'
import { BookOpen, Users } from '@phosphor-icons/react'
import { cn } from '../lib/utils'

const TABS = [
  { to: '/app/quan-tri', label: 'Tài khoản', icon: Users, exact: true },
  { to: '/app/quan-tri/tai-nguyen', label: 'Tài nguyên học tập', icon: BookOpen, exact: false },
]

/**
 * Navigation between the administration screens.
 *
 * Rendered inside pages that are already behind `RequireAdmin`, so it never
 * needs a role check of its own -- a non-administrator cannot reach a page
 * that renders it.
 */
export default function AdminTabs() {
  const location = useLocation()

  return (
    <nav className="mb-6 flex gap-1 border-b border-border dark:border-border-dark">
      {TABS.map(({ to, label, icon: Icon, exact }) => {
        const active = exact ? location.pathname === to : location.pathname.startsWith(to)
        return (
          <Link
            key={to}
            to={to}
            className={cn(
              '-mb-px flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors',
              active
                ? 'border-accent text-accent'
                : 'border-transparent text-text-secondary dark:text-text-secondary-dark hover:text-text-primary dark:hover:text-text-primary-dark'
            )}
          >
            <Icon className="h-4 w-4" weight={active ? 'fill' : 'regular'} />
            {label}
          </Link>
        )
      })}
    </nav>
  )
}
