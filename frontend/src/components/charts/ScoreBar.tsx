import { cn } from '../../lib/utils'

function barColor(score: number): string {
  if (score > 70) return 'bg-success'
  if (score > 40) return 'bg-warning'
  return 'bg-error'
}

function textColor(score: number): string {
  if (score > 70) return 'text-success'
  if (score > 40) return 'text-warning'
  return 'text-error'
}

interface ScoreBarProps {
  label: string
  score: number
  color?: string
}

export default function ScoreBar({ label, score, color }: ScoreBarProps) {
  const clamped = Math.max(0, Math.min(100, score))
  const fill = color ?? barColor(clamped)

  return (
    <div className="flex items-center gap-3">
      <span className="w-36 shrink-0 text-sm font-medium text-text-secondary truncate">
        {label}
      </span>
      <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-neutral-100">
        <div
          className={cn('absolute inset-y-0 left-0 rounded-full transition-all duration-500', fill)}
          style={{ width: `${clamped}%` }}
        />
      </div>
      <span className={cn('w-10 text-right text-sm font-semibold tabular-nums', textColor(clamped))}>
        {clamped}
      </span>
    </div>
  )
}
