import { useCallback, useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { ChartLine, Warning } from '@phosphor-icons/react'
import { getQualityReport } from '../lib/api'
import type { QualityReport } from '../types'

function formatPercent(value: number | null): string {
  return value === null ? 'Chưa đủ dữ liệu' : `${Math.round(value * 100)}%`
}

const PROFILE_LABELS: Record<string, string> = {
  presentation_solo: 'Thuyết trình',
  interview_solo: 'Phỏng vấn',
}

/**
 * Read-only, admin-only (Nhom B Task 14 / Nhom C Task 18): the only data
 * source is PeerNote from completed, blind reviews -- SelfNote never
 * counts (see services/quality_tracking.py). A `null` rate here means
 * "not enough data yet", shown as such rather than as a misleading 0%/100%.
 */
export default function AdminQuality() {
  const [report, setReport] = useState<QualityReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setReport(await getQualityReport())
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Không thể tải bảng theo dõi chất lượng.')
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mb-8">
        <div className="flex items-center gap-2">
          <ChartLine className="h-6 w-6 text-accent" weight="fill" />
          <h1 className="text-2xl font-semibold text-text-primary">Theo dõi chất lượng phát hiện</h1>
        </div>
        <p className="mt-2 text-sm text-text-secondary">
          Đối chiếu sự kiện máy phát hiện với mốc đánh dấu mù của người chấm hộ (
          <code>PeerNote</code>, đã nộp trước khi thấy kết quả máy) -- ghi chú tự xem lại của chính chủ
          phiên không bao giờ được tính vào đây.
        </p>
      </motion.div>

      {error && (
        <div className="mb-6 rounded-xl border border-error/20 bg-error-light p-4 flex items-center gap-3">
          <Warning className="h-5 w-5 text-error shrink-0" weight="bold" />
          <p className="text-sm text-text-primary">{error}</p>
        </div>
      )}

      {report && (
        <>
          <div className="grid gap-4 sm:grid-cols-3 mb-6">
            <div className="rounded-xl border border-border bg-surface p-5">
              <p className="text-xs text-text-muted mb-1">Tỷ lệ bỏ sót tích luỹ</p>
              <p className="text-2xl font-semibold text-text-primary">{formatPercent(report.miss_rate)}</p>
              <p className="mt-1 text-xs text-text-muted">{report.peer_marks_total} mốc bạn bè đã đánh dấu</p>
            </div>
            <div className="rounded-xl border border-border bg-surface p-5">
              <p className="text-xs text-text-muted mb-1">Tỷ lệ lời mời hoàn thành</p>
              <p className="text-2xl font-semibold text-text-primary">
                {formatPercent(report.invite_completion_rate)}
              </p>
              <p className="mt-1 text-xs text-text-muted">
                {report.invites_completed}/{report.invites_total} lời mời
              </p>
            </div>
            <div className="rounded-xl border border-border bg-surface p-5">
              <p className="text-xs text-text-muted mb-1">Phiên có bạn bè chấm</p>
              <p className="text-2xl font-semibold text-text-primary">{report.sessions_with_peer_review}</p>
              <p className="mt-1 text-xs text-text-muted">Cửa sổ dung sai: {report.tolerance_sec}s</p>
            </div>
          </div>

          <div className="overflow-x-auto rounded-xl border border-border bg-surface">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-text-muted">
                  <th className="px-4 py-3 font-medium">Hồ sơ bối cảnh</th>
                  <th className="px-4 py-3 font-medium">Loại sự kiện</th>
                  <th className="px-4 py-3 font-medium text-right">Máy báo</th>
                  <th className="px-4 py-3 font-medium text-right">Báo đúng</th>
                  <th className="px-4 py-3 font-medium text-right">Tỷ lệ đúng</th>
                </tr>
              </thead>
              <tbody>
                {report.by_event_type.map(row => (
                  <tr key={`${row.profile}-${row.event_type}`} className="border-b border-border last:border-0">
                    <td className="px-4 py-3 text-text-secondary">{PROFILE_LABELS[row.profile] ?? row.profile}</td>
                    <td className="px-4 py-3 font-mono text-xs text-text-primary">{row.event_type}</td>
                    <td className="px-4 py-3 text-right text-text-secondary">{row.system_events}</td>
                    <td className="px-4 py-3 text-right text-text-secondary">{row.system_matched}</td>
                    <td className="px-4 py-3 text-right font-medium text-text-primary">
                      {formatPercent(row.precision)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {report.by_event_type.length === 0 && (
              <p className="p-6 text-center text-sm text-text-muted">
                Chưa có phiên nào vừa có sự kiện máy vừa có đánh giá bạn bè hoàn tất.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
