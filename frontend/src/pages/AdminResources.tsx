import { useCallback, useEffect, useState } from 'react'
import {
  ArrowSquareOut,
  Eye,
  EyeSlash,
  MagnifyingGlass,
  Plus,
  SpinnerGap,
  Warning,
  X,
} from '@phosphor-icons/react'
import {
  adminCreateResource,
  adminGetResourceStats,
  adminListResources,
  adminUpdateResource,
  apiErrorMessage,
} from '../lib/api'
import AdminTabs from '../components/AdminTabs'
import { cn } from '../lib/utils'
import type {
  LearningResource,
  ResourceInput,
  ResourceStats,
  ResourceType,
  SkillTag,
} from '../types/auth'
import { RESOURCE_TYPE_LABELS, SKILL_TAG_LABELS } from '../types/auth'

const PAGE_SIZE = 25
const ALL_TAGS = Object.keys(SKILL_TAG_LABELS) as SkillTag[]
const ALL_TYPES = Object.keys(RESOURCE_TYPE_LABELS) as ResourceType[]

const EMPTY_FORM: ResourceInput = {
  title: '',
  url: '',
  resource_type: 'video',
  platform: '',
  language: 'vi',
  speaker: '',
  source: '',
  description: '',
  skill_tags: [],
  category_label: '',
  is_active: true,
}

/**
 * Learning-resource catalog — permission matrix row 12: add, edit, hide,
 * and tag with skills.
 *
 * There is no delete control, because the API has no delete endpoint:
 * recommendations point at these rows, so retiring one means hiding it. Each
 * row shows how many recommendations depend on it, so that decision is made
 * with the consequence visible rather than guessed at.
 */
export default function AdminResources() {
  const [resources, setResources] = useState<LearningResource[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<ResourceStats | null>(null)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<ResourceType | ''>('')
  const [tagFilter, setTagFilter] = useState<SkillTag | ''>('')
  const [activeFilter, setActiveFilter] = useState<'' | 'true' | 'false'>('')
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [savingId, setSavingId] = useState<string | null>(null)

  const [editing, setEditing] = useState<LearningResource | null>(null)
  const [form, setForm] = useState<ResourceInput>(EMPTY_FORM)
  const [formOpen, setFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [list, freshStats] = await Promise.all([
        adminListResources({
          search: search.trim() || undefined,
          resource_type: typeFilter || undefined,
          skill_tag: tagFilter || undefined,
          is_active: activeFilter === '' ? undefined : activeFilter === 'true',
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        }),
        adminGetResourceStats(),
      ])
      setResources(list.items)
      setTotal(list.total)
      setStats(freshStats)
    } catch (err) {
      setError(apiErrorMessage(err, 'Không tải được danh mục tài nguyên.'))
    } finally {
      setLoading(false)
    }
  }, [search, typeFilter, tagFilter, activeFilter, page])

  useEffect(() => {
    const timer = setTimeout(load, 250)
    return () => clearTimeout(timer)
  }, [load])

  function openCreate() {
    setEditing(null)
    setForm(EMPTY_FORM)
    setFormError(null)
    setFormOpen(true)
  }

  function openEdit(resource: LearningResource) {
    setEditing(resource)
    setForm({
      title: resource.title,
      url: resource.url,
      resource_type: resource.resource_type,
      platform: resource.platform ?? '',
      language: resource.language ?? 'vi',
      speaker: resource.speaker ?? '',
      source: resource.source ?? '',
      description: resource.description ?? '',
      skill_tags: resource.skill_tags,
      category_label: resource.category_label ?? '',
      is_active: resource.is_active,
    })
    setFormError(null)
    setFormOpen(true)
  }

  async function submitForm() {
    setFormError(null)
    setSubmitting(true)
    // Blank optional fields go as null rather than "", so the server stores an
    // absent value instead of an empty string that renders as a gap later.
    const payload: ResourceInput = {
      ...form,
      platform: form.platform || null,
      speaker: form.speaker || null,
      source: form.source || null,
      description: form.description || null,
      category_label: form.category_label || null,
    }
    try {
      if (editing) {
        await adminUpdateResource(editing.id, payload)
      } else {
        await adminCreateResource(payload)
      }
      setFormOpen(false)
      await load()
    } catch (err) {
      setFormError(apiErrorMessage(err, 'Không lưu được tài nguyên.'))
    } finally {
      setSubmitting(false)
    }
  }

  async function toggleVisibility(resource: LearningResource) {
    setSavingId(resource.id)
    setError(null)
    try {
      const updated = await adminUpdateResource(resource.id, { is_active: !resource.is_active })
      setResources((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))
      setStats(await adminGetResourceStats())
    } catch (err) {
      setError(apiErrorMessage(err, 'Không đổi được trạng thái hiển thị.'))
    } finally {
      setSavingId(null)
    }
  }

  function toggleTag(tag: SkillTag) {
    setForm((f) => ({
      ...f,
      skill_tags: f.skill_tags.includes(tag)
        ? f.skill_tags.filter((t) => t !== tag)
        : [...f.skill_tags, tag],
    }))
  }

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const inputClass =
    'w-full rounded-lg border border-border dark:border-border-dark bg-surface dark:bg-surface-dark px-3 py-2.5 text-sm text-text-primary dark:text-text-primary-dark outline-none focus:border-accent'

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
      <AdminTabs />

      <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-text-primary dark:text-text-primary-dark">
            Danh mục tài nguyên học tập
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-text-secondary dark:text-text-secondary-dark">
            Ẩn tài nguyên thay vì xoá — các phiên đã từng được gợi ý tài nguyên này vẫn giữ
            nguyên lịch sử. Cột “Đã gợi ý” cho biết có bao nhiêu phiên đang trỏ tới nó.
          </p>
        </div>
        <button
          type="button"
          onClick={openCreate}
          className="flex items-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-hover"
        >
          <Plus className="h-4 w-4" weight="bold" />
          Thêm tài nguyên
        </button>
      </header>

      {stats && (
        <>
          <section className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: 'Tổng tài nguyên', value: stats.total },
              { label: 'Đang hiển thị', value: stats.active },
              { label: 'Đã ẩn', value: stats.hidden },
              { label: 'Chưa gắn nhãn', value: stats.untagged },
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
          {stats.untagged > 0 && (
            <p className="mb-4 rounded-lg bg-warning-light px-3 py-2 text-xs text-warning">
              {stats.untagged} tài nguyên chưa gắn nhãn kỹ năng nào. Công cụ gợi ý khớp theo nhãn,
              nên những tài nguyên này sẽ không bao giờ được gợi ý cho ai.
            </p>
          )}
        </>
      )}

      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
        <div className="relative flex-1">
          <MagnifyingGlass className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted dark:text-text-muted-dark" />
          <input
            type="search"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(0)
            }}
            placeholder="Tìm theo tiêu đề, diễn giả, nguồn…"
            className={cn(inputClass, 'pl-9')}
          />
        </div>

        <select
          value={typeFilter}
          onChange={(e) => {
            setTypeFilter(e.target.value as ResourceType | '')
            setPage(0)
          }}
          aria-label="Lọc theo loại"
          className="rounded-lg border border-border dark:border-border-dark bg-surface dark:bg-surface-dark px-3 py-2.5 text-sm text-text-primary dark:text-text-primary-dark outline-none focus:border-accent"
        >
          <option value="">Mọi loại</option>
          {ALL_TYPES.map((t) => (
            <option key={t} value={t}>
              {RESOURCE_TYPE_LABELS[t]}
            </option>
          ))}
        </select>

        <select
          value={tagFilter}
          onChange={(e) => {
            setTagFilter(e.target.value as SkillTag | '')
            setPage(0)
          }}
          aria-label="Lọc theo nhãn kỹ năng"
          className="rounded-lg border border-border dark:border-border-dark bg-surface dark:bg-surface-dark px-3 py-2.5 text-sm text-text-primary dark:text-text-primary-dark outline-none focus:border-accent"
        >
          <option value="">Mọi nhãn</option>
          {ALL_TAGS.map((t) => (
            <option key={t} value={t}>
              {SKILL_TAG_LABELS[t]}
            </option>
          ))}
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
          <option value="true">Đang hiển thị</option>
          <option value="false">Đã ẩn</option>
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
        <table className="w-full min-w-[860px] text-left text-sm">
          <thead className="bg-surface-elevated dark:bg-surface-elevated-dark">
            <tr className="text-xs uppercase tracking-wide text-text-muted dark:text-text-muted-dark">
              <th className="px-4 py-3 font-medium">Tài nguyên</th>
              <th className="px-4 py-3 font-medium">Loại</th>
              <th className="px-4 py-3 font-medium">Nhãn kỹ năng</th>
              <th className="px-4 py-3 font-medium">Đã gợi ý</th>
              <th className="px-4 py-3 font-medium">Hiển thị</th>
              <th className="px-4 py-3 font-medium"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border dark:divide-border-dark bg-surface dark:bg-surface-dark">
            {loading && (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center">
                  <SpinnerGap
                    className="mx-auto h-6 w-6 animate-spin text-text-muted dark:text-text-muted-dark"
                    weight="bold"
                  />
                </td>
              </tr>
            )}

            {!loading && resources.length === 0 && (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-10 text-center text-text-secondary dark:text-text-secondary-dark"
                >
                  Không có tài nguyên nào khớp bộ lọc.
                </td>
              </tr>
            )}

            {!loading &&
              resources.map((r) => (
                <tr key={r.id} className={cn(savingId === r.id && 'opacity-60', !r.is_active && 'opacity-70')}>
                  <td className="max-w-sm px-4 py-3">
                    <div className="font-medium text-text-primary dark:text-text-primary-dark">
                      {r.title}
                    </div>
                    <a
                      href={r.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-0.5 inline-flex items-center gap-1 text-xs text-accent hover:underline"
                    >
                      <span className="max-w-xs truncate">{r.url}</span>
                      <ArrowSquareOut className="h-3 w-3 shrink-0" />
                    </a>
                    {(r.speaker || r.source) && (
                      <div className="mt-0.5 text-xs text-text-muted dark:text-text-muted-dark">
                        {[r.speaker, r.source].filter(Boolean).join(' · ')}
                      </div>
                    )}
                  </td>

                  <td className="px-4 py-3 text-xs text-text-secondary dark:text-text-secondary-dark">
                    {RESOURCE_TYPE_LABELS[r.resource_type] ?? r.resource_type}
                    {r.language && <div className="text-text-muted dark:text-text-muted-dark">{r.language}</div>}
                  </td>

                  <td className="px-4 py-3">
                    {r.skill_tags.length === 0 ? (
                      <span className="text-xs text-warning">chưa gắn nhãn</span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {r.skill_tags.map((tag) => (
                          <span
                            key={tag}
                            className="rounded bg-accent-light dark:bg-accent-light-dark px-1.5 py-0.5 text-xs text-accent"
                          >
                            {SKILL_TAG_LABELS[tag] ?? tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>

                  <td className="px-4 py-3 text-xs text-text-secondary dark:text-text-secondary-dark">
                    {r.recommendation_count > 0 ? `${r.recommendation_count} phiên` : '—'}
                  </td>

                  <td className="px-4 py-3">
                    <button
                      type="button"
                      disabled={savingId === r.id}
                      onClick={() => toggleVisibility(r)}
                      className={cn(
                        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-50',
                        r.is_active
                          ? 'bg-success-light text-success'
                          : 'bg-surface-elevated dark:bg-surface-elevated-dark text-text-muted dark:text-text-muted-dark'
                      )}
                    >
                      {r.is_active ? (
                        <Eye className="h-3.5 w-3.5" weight="fill" />
                      ) : (
                        <EyeSlash className="h-3.5 w-3.5" weight="fill" />
                      )}
                      {r.is_active ? 'Hiển thị' : 'Đã ẩn'}
                    </button>
                  </td>

                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => openEdit(r)}
                      className="rounded-lg border border-border dark:border-border-dark px-3 py-1.5 text-xs text-text-secondary dark:text-text-secondary-dark hover:bg-surface-elevated dark:hover:bg-surface-elevated-dark"
                    >
                      Sửa
                    </button>
                  </td>
                </tr>
              ))}
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

      {formOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 sm:p-8">
          <div className="w-full max-w-xl rounded-xl border border-border dark:border-border-dark bg-surface dark:bg-surface-dark p-5 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-text-primary dark:text-text-primary-dark">
                {editing ? 'Sửa tài nguyên' : 'Thêm tài nguyên'}
              </h2>
              <button
                type="button"
                onClick={() => setFormOpen(false)}
                aria-label="Đóng"
                className="rounded p-1.5 text-text-muted dark:text-text-muted-dark hover:bg-surface-elevated dark:hover:bg-surface-elevated-dark"
              >
                <X className="h-4 w-4" weight="bold" />
              </button>
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault()
                submitForm()
              }}
              className="flex flex-col gap-3"
            >
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium text-text-primary dark:text-text-primary-dark">
                  Tiêu đề
                </span>
                <input
                  required
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  className={inputClass}
                />
              </label>

              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium text-text-primary dark:text-text-primary-dark">
                  Đường dẫn
                </span>
                <input
                  required
                  type="url"
                  value={form.url}
                  onChange={(e) => setForm({ ...form, url: e.target.value })}
                  placeholder="https://…"
                  className={inputClass}
                />
              </label>

              <div className="grid grid-cols-2 gap-3">
                <label className="flex flex-col gap-1.5">
                  <span className="text-sm font-medium text-text-primary dark:text-text-primary-dark">
                    Loại
                  </span>
                  <select
                    value={form.resource_type}
                    onChange={(e) => setForm({ ...form, resource_type: e.target.value as ResourceType })}
                    className={inputClass}
                  >
                    {ALL_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {RESOURCE_TYPE_LABELS[t]}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="flex flex-col gap-1.5">
                  <span className="text-sm font-medium text-text-primary dark:text-text-primary-dark">
                    Ngôn ngữ
                  </span>
                  <select
                    value={form.language ?? 'vi'}
                    onChange={(e) => setForm({ ...form, language: e.target.value })}
                    className={inputClass}
                  >
                    <option value="vi">Tiếng Việt</option>
                    <option value="en">Tiếng Anh</option>
                  </select>
                </label>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <label className="flex flex-col gap-1.5">
                  <span className="text-sm font-medium text-text-primary dark:text-text-primary-dark">
                    Diễn giả
                  </span>
                  <input
                    value={form.speaker ?? ''}
                    onChange={(e) => setForm({ ...form, speaker: e.target.value })}
                    className={inputClass}
                  />
                </label>
                <label className="flex flex-col gap-1.5">
                  <span className="text-sm font-medium text-text-primary dark:text-text-primary-dark">
                    Nguồn
                  </span>
                  <input
                    value={form.source ?? ''}
                    onChange={(e) => setForm({ ...form, source: e.target.value })}
                    placeholder="TED, Youtube…"
                    className={inputClass}
                  />
                </label>
              </div>

              <fieldset className="flex flex-col gap-2">
                <legend className="mb-1 text-sm font-medium text-text-primary dark:text-text-primary-dark">
                  Nhãn kỹ năng
                </legend>
                <div className="flex flex-wrap gap-2">
                  {ALL_TAGS.map((tag) => (
                    <button
                      key={tag}
                      type="button"
                      onClick={() => toggleTag(tag)}
                      aria-pressed={form.skill_tags.includes(tag)}
                      className={cn(
                        'rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
                        form.skill_tags.includes(tag)
                          ? 'border-accent bg-accent-light dark:bg-accent-light-dark text-accent'
                          : 'border-border dark:border-border-dark text-text-secondary dark:text-text-secondary-dark hover:bg-surface-elevated dark:hover:bg-surface-elevated-dark'
                      )}
                    >
                      {SKILL_TAG_LABELS[tag]}
                    </button>
                  ))}
                </div>
                {form.skill_tags.length === 0 && (
                  <span className="text-xs text-warning">
                    Chưa có nhãn nào — công cụ gợi ý sẽ không bao giờ đề xuất tài nguyên này.
                  </span>
                )}
              </fieldset>

              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium text-text-primary dark:text-text-primary-dark">
                  Mô tả
                </span>
                <textarea
                  rows={3}
                  value={form.description ?? ''}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  className={cn(inputClass, 'resize-y')}
                />
              </label>

              {formError && (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-lg bg-error-light px-3 py-2.5 text-sm text-error"
                >
                  <Warning className="mt-0.5 h-4 w-4 shrink-0" weight="fill" />
                  <span>{formError}</span>
                </div>
              )}

              <div className="mt-1 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setFormOpen(false)}
                  className="rounded-lg border border-border dark:border-border-dark px-4 py-2 text-sm text-text-secondary dark:text-text-secondary-dark hover:bg-surface-elevated dark:hover:bg-surface-elevated-dark"
                >
                  Huỷ
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-60"
                >
                  {submitting && <SpinnerGap className="h-4 w-4 animate-spin" weight="bold" />}
                  {editing ? 'Lưu thay đổi' : 'Thêm vào danh mục'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
