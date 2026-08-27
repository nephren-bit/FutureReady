import { useCallback, useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { LockKey, LockKeyOpen, MagnifyingGlass, ShieldCheck, Warning } from '@phosphor-icons/react'
import { listAdminUsers, setUserActive } from '../lib/api'
import type { AdminUser } from '../types'

function formatDate(iso: string | null): string {
  if (!iso) return '--'
  return new Intl.DateTimeFormat('vi-VN', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(iso))
}

export default function AdminUsers() {
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [query, setQuery] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pendingId, setPendingId] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setUsers(await listAdminUsers())
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Không thể tải danh sách tài khoản.')
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleToggle(user: AdminUser) {
    setError(null)
    setPendingId(user.id)
    try {
      const updated = await setUserActive(user.id, !user.is_active)
      setUsers(prev => prev?.map(u => (u.id === updated.id ? updated : u)) ?? prev)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Không thể cập nhật trạng thái tài khoản.')
    } finally {
      setPendingId(null)
    }
  }

  // Small enough account volume for this MVP that filtering the already-
  // fetched list client-side is simpler than a search query param.
  const filtered = users?.filter(u => u.email.toLowerCase().includes(query.trim().toLowerCase()))

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mb-8">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-6 w-6 text-accent" weight="fill" />
          <h1 className="text-2xl font-semibold text-text-primary">Quản trị tài khoản</h1>
        </div>
        <p className="mt-2 text-sm text-text-secondary">
          Khoá/mở khoá tài khoản qua <code>is_active</code>. Không có xoá -- lịch sử luyện tập của tài
          khoản bị khoá vẫn còn nguyên.
        </p>
      </motion.div>

      {error && (
        <div className="mb-6 rounded-xl border border-error/20 bg-error-light p-4 flex items-center gap-3">
          <Warning className="h-5 w-5 text-error shrink-0" weight="bold" />
          <p className="text-sm text-text-primary">{error}</p>
        </div>
      )}

      <div className="mb-4 relative">
        <MagnifyingGlass className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-text-muted" />
        <input
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Tìm theo email..."
          className="w-full rounded-lg border border-border bg-surface py-2 pl-9 pr-3 text-sm text-text-primary"
        />
      </div>

      <div className="overflow-x-auto rounded-xl border border-border bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-text-muted">
              <th className="px-4 py-3 font-medium">Email</th>
              <th className="px-4 py-3 font-medium">Họ tên</th>
              <th className="px-4 py-3 font-medium">Vai trò</th>
              <th className="px-4 py-3 font-medium">Đăng nhập gần nhất</th>
              <th className="px-4 py-3 font-medium">Trạng thái</th>
              <th className="px-4 py-3 font-medium" />
            </tr>
          </thead>
          <tbody>
            {filtered?.map(user => (
              <tr key={user.id} className="border-b border-border last:border-0">
                <td className="px-4 py-3 text-text-primary">{user.email}</td>
                <td className="px-4 py-3 text-text-secondary">{user.full_name || '--'}</td>
                <td className="px-4 py-3 text-text-secondary">{user.is_admin ? 'Admin' : 'Thành viên'}</td>
                <td className="px-4 py-3 text-text-secondary">{formatDate(user.last_login_at)}</td>
                <td className="px-4 py-3">
                  <span
                    className={
                      user.is_active
                        ? 'rounded-full bg-success-light px-2.5 py-1 text-xs font-medium text-success'
                        : 'rounded-full bg-error-light px-2.5 py-1 text-xs font-medium text-error'
                    }
                  >
                    {user.is_active ? 'Đang hoạt động' : 'Đã khoá'}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    type="button"
                    onClick={() => handleToggle(user)}
                    disabled={pendingId === user.id}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-elevated disabled:opacity-50"
                  >
                    {user.is_active ? (
                      <LockKey className="h-3.5 w-3.5" weight="bold" />
                    ) : (
                      <LockKeyOpen className="h-3.5 w-3.5" weight="bold" />
                    )}
                    {user.is_active ? 'Khoá' : 'Mở khoá'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {users !== null && filtered?.length === 0 && (
          <p className="p-6 text-center text-sm text-text-muted">Không tìm thấy tài khoản nào khớp.</p>
        )}
      </div>
    </div>
  )
}
