import { useCallback, useEffect, useState } from 'react'
import {
  CheckCircle,
  Lock,
  LockOpen,
  MagnifyingGlass,
  SealCheck,
  SpinnerGap,
  Warning,
} from '@phosphor-icons/react'
import { adminGetStats, adminListUsers, adminUpdateUser, apiErrorMessage } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import AdminTabs from '../components/AdminTabs'
import { cn } from '../lib/utils'
import type { AdminStats, User, UserRole } from '../types/auth'

const PAGE_SIZE = 25

/**
 * Account administration — row 11 of the report's permission matrix.
 *
 * Locking uses `is_active`; nothing here deletes a row. An account's session
 * history is the reason the account existed, and a delete would take it along.
 */
export default function Admin() {
  const { user: currentUser } = useAuth()

  const [users, setUsers] = useState<User[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState<UserRole | ''>('')
  const [activeFilter, setActiveFilter] = useState<'' | 'true' | 'false'>('')
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [savingId, setSavingId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [list, freshStats] = await Promise.all([
        adminListUsers({
          search: search.trim() || undefined,
          role: roleFilter || undefined,
          is_active: activeFilter === '' ? undefined : activeFilter === 'true',
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        }),
        adminGetStats(),
      ])
      setUsers(list.items)
      setTotal(list.total)
      setStats(freshStats)
    } catch (err) {
      setError(apiErrorMessage(err, 'Không tải được danh sách tài khoản.'))
    } finally {
      setLoading(false)
    }
  }, [search, roleFilter, activeFilter, page])

  // Debounced so typing in the search box does not fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(load, 250)
    return () => clearTimeout(timer)
  }, [load])

  async function applyChange(target: User, payload: Partial<Pick<User, 'role' | 'is_verified' | 'is_active'>>) {
    setSavingId(target.id)
    setError(null)
    try {
      const updated = await adminUpdateUser(target.id, payload)
      setUsers((previous) => previous.map((u) => (u.id === updated.id ? updated : u)))
      setStats(await adminGetStats())
    } catch (err) {
      // The server refuses some changes the UI cannot know about in advance --
      // locking yourself out, or locking another administrator. Show its reason
      // rather than a generic failure.
      setError(apiErrorMessage(err, 'Không cập nhật được tài khoản.'))
    } finally {
      setSavingId(null)
    }
  }

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
      <AdminTabs />

      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-text-primary dark:text-text-primary-dark">
          Quản trị tài khoản
        </h1>
        <p className="mt-1 text-sm text-text-secondary dark:text-text-secondary-dark">
          Khoá tài khoản bằng cách tắt trạng thái hoạt động — bản ghi và lịch sử phiên vẫn được giữ nguyên.
        </p>
      </header>

      {stats && (
        <section className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: 'Tổng tài khoản', value: stats.total_users },
            { label: 'Đang hoạt động', value: stats.active_users },
            { label: 'Đã khoá', value: stats.inactive_users },
            { label: 'Tổng số phiên', value: stats.total_sessions },
          ].map(({ label, value }) => (
            <div
              key={label}
              className="rounded-xl border border-border dark:border-border-dark bg-surface dark:bg-surface-dark p-4"
            >
              <div className="text-2xl font-semibold text-text-primary dark:text-text-primary-dark">
                {value}
              </div>
              <div className="mt-0.5 text-xs text-text-secondary dark:text-text-secondary-dark">
                {label}
              </div>
            </div>
          ))}
        </section>
      )}

      {stats && (
        <p className="mb-4 text-xs text-text-muted dark:text-text-muted-dark">
          Người học: {stats.learners} · Giảng viên: {stats.lecturers} · Quản trị viên: {stats.admins}
          {' · '}Đã xác minh: {stats.verified_users}
        </p>
      )}

      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <MagnifyingGlass className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted dark:text-text-muted-dark" />
          <input
            type="search"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(0)
            }}
            placeholder="Tìm theo email hoặc họ tên…"
            className="w-full rounded-lg border border-border dark:border-border-dark bg-surface dark:bg-surface-dark py-2.5 pl-9 pr-3 text-sm text-text-primary dark:text-text-primary-dark outline-none focus:border-accent"
          />
        </div>

        <select
          value={roleFilter}
          onChange={(e) => {
            setRoleFilter(e.target.value as UserRole | '')
            setPage(0)
          }}
          aria-label="Lọc theo vai trò"
          className="rounded-lg border border-border dark:border-border-dark bg-surface dark:bg-surface-dark px-3 py-2.5 text-sm text-text-primary dark:text-text-primary-dark outline-none focus:border-accent"
        >
          <option value="">Mọi vai trò</option>
          <option value="learner">Người học</option>
          <option value="lecturer">Giảng viên</option>
        </select>

        <select
          value={activeFilter}
          onChange={(e) => {
            setActiveFilter(e.target.value as '' | 'true' | 'false')
            setPage(0)
          }}
          aria-label="Lọc theo trạng thái"
          className="rounded-lg border border-border dark:border-border-dark bg-surface dark:bg-surface-dark px-3 py-2.5 text-sm text-text-primary dark:text-text-primary-dark outline-none focus:border-accent"
        >
          <option value="">Mọi trạng thái</option>
          <option value="true">Đang hoạt động</option>
          <option value="false">Đã khoá</option>
        </select>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 flex items-start gap-2 rounded-lg bg-error-light px-3 py-2.5 text-sm text-error"
        >
          <Warning className="mt-0.5 h-4 w-4 shrink-0" weight="fill" />
          <span>{error}</span>
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border border-border dark:border-border-dark">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="bg-surface-elevated dark:bg-surface-elevated-dark">
            <tr className="text-xs uppercase tracking-wide text-text-muted dark:text-text-muted-dark">
              <th className="px-4 py-3 font-medium">Tài khoản</th>
              <th className="px-4 py-3 font-medium">Vai trò</th>
              <th className="px-4 py-3 font-medium">Xác minh</th>
              <th className="px-4 py-3 font-medium">Trạng thái</th>
              <th className="px-4 py-3 font-medium">Đăng nhập gần nhất</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border dark:divide-border-dark bg-surface dark:bg-surface-dark">
            {loading && (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center">
                  <SpinnerGap className="mx-auto h-6 w-6 animate-spin text-text-muted dark:text-text-muted-dark" weight="bold" />
                </td>
              </tr>
            )}

            {!loading && users.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-text-secondary dark:text-text-secondary-dark">
                  Không có tài khoản nào khớp bộ lọc.
                </td>
              </tr>
            )}

            {!loading &&
              users.map((u) => {
                const isSelf = u.id === currentUser?.id
                const busy = savingId === u.id
                return (
                  <tr key={u.id} className={cn(busy && 'opacity-60')}>
                    <td className="px-4 py-3">
                      <div className="font-medium text-text-primary dark:text-text-primary-dark">
                        {u.full_name || '(chưa đặt tên)'}
                        {isSelf && (
                          <span className="ml-2 rounded bg-accent-light dark:bg-accent-light-dark px-1.5 py-0.5 text-xs text-accent">
                            bạn
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-text-muted dark:text-text-muted-dark">{u.email}</div>
                    </td>

                    <td className="px-4 py-3">
                      {u.is_admin ? (
                        // No control: admin rights are granted only by the CLI,
                        // so offering a dropdown here would imply otherwise.
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-accent-light dark:bg-accent-light-dark px-2.5 py-1 text-xs font-medium text-accent">
                          <SealCheck className="h-3.5 w-3.5" weight="fill" />
                          Quản trị viên
                        </span>
                      ) : (
                        <select
                          value={u.role}
                          disabled={busy}
                          onChange={(e) => applyChange(u, { role: e.target.value as UserRole })}
                          aria-label={`Vai trò của ${u.email}`}
                          className="rounded-lg border border-border dark:border-border-dark bg-surface dark:bg-surface-dark px-2 py-1.5 text-xs text-text-primary dark:text-text-primary-dark outline-none focus:border-accent"
                        >
                          <option value="learner">Người học</option>
                          <option value="lecturer">Giảng viên</option>
                        </select>
                      )}
                    </td>

                    <td className="px-4 py-3">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => applyChange(u, { is_verified: !u.is_verified })}
                        className={cn(
                          'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-colors',
                          u.is_verified
                            ? 'bg-success-light text-success'
                            : 'bg-surface-elevated dark:bg-surface-elevated-dark text-text-muted dark:text-text-muted-dark'
                        )}
                      >
                        <CheckCircle className="h-3.5 w-3.5" weight={u.is_verified ? 'fill' : 'regular'} />
                        {u.is_verified ? 'Đã xác minh' : 'Chưa xác minh'}
                      </button>
                    </td>

                    <td className="px-4 py-3">
                      <button
                        type="button"
                        disabled={busy || isSelf || u.is_admin}
                        onClick={() => applyChange(u, { is_active: !u.is_active })}
                        title={
                          isSelf
                            ? 'Không thể tự khoá tài khoản của chính mình.'
                            : u.is_admin
                              ? 'Quyền quản trị chỉ thu hồi được bằng lệnh tại máy chủ.'
                              : undefined
                        }
                        className={cn(
                          'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                          u.is_active ? 'bg-success-light text-success' : 'bg-error-light text-error'
                        )}
                      >
                        {u.is_active ? (
                          <LockOpen className="h-3.5 w-3.5" weight="fill" />
                        ) : (
                          <Lock className="h-3.5 w-3.5" weight="fill" />
                        )}
                        {u.is_active ? 'Hoạt động' : 'Đã khoá'}
                      </button>
                    </td>

                    <td className="px-4 py-3 text-xs text-text-muted dark:text-text-muted-dark">
                      {u.last_login_at
                        ? new Date(u.last_login_at).toLocaleString('vi-VN')
                        : 'Chưa đăng nhập'}
                    </td>
                  </tr>
                )
              })}
          </tbody>
        </table>
      </div>

      {total > PAGE_SIZE && (
        <div className="mt-4 flex items-center justify-between text-sm">
          <span className="text-text-secondary dark:text-text-secondary-dark">
            {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} trên {total}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
              className="rounded-lg border border-border dark:border-border-dark px-3 py-1.5 disabled:opacity-40"
            >
              Trước
            </button>
            <button
              type="button"
              disabled={page + 1 >= pageCount}
              onClick={() => setPage((p) => p + 1)}
              className="rounded-lg border border-border dark:border-border-dark px-3 py-1.5 disabled:opacity-40"
            >
              Sau
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
