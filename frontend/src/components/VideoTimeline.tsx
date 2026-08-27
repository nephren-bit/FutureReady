import { cn } from '../lib/utils'
import type { PeerNote, PresentationEvent, SelfNote } from '../types'

interface VideoTimelineProps {
  durationSec: number
  currentSec: number
  events: PresentationEvent[]
  notes: SelfNote[]
  // Peer marks (Nhom C) render as their own row, visually distinct from
  // self-notes -- a friend's blind mark and the owner's own journal entry
  // are never the same kind of thing (see models/peer_review.py). Rows
  // with mark_sec === null (the rubric submission) are filtered out here,
  // not by the caller -- they have nowhere on a timeline to sit.
  peerNotes?: PeerNote[]
  onSeek: (sec: number) => void
}

// A distinct color per event type keeps the strip readable once several
// kinds fire close together, without implying any of them is "worse" --
// this is a location index, not a severity scale (see plan.md's "no
// diagnosis" rule, which applies to color the same way it applies to text).
const EVENT_COLORS: Record<string, string> = {
  E_HEAD_DOWN: 'bg-warning',
  E_STATIC: 'bg-accent',
  E_PACING: 'bg-accent',
  E_TURNED_AWAY: 'bg-warning',
  E_CLOSED_POSTURE: 'bg-warning',
  E_STABLE_SEGMENT: 'bg-success',
}

function pct(sec: number, durationSec: number): number {
  if (durationSec <= 0) return 0
  return Math.min(100, Math.max(0, (sec / durationSec) * 100))
}

/**
 * A clickable strip below the video player: machine-detected events as
 * colored bars, self-notes as small markers above them, and a moving
 * playhead. Clicking anywhere jumps `videoRef.currentTime` there (see
 * `SessionReview.tsx`) -- this component only reports the seek, it never
 * touches the `<video>` element itself.
 */
export default function VideoTimeline({
  durationSec,
  currentSec,
  events,
  notes,
  peerNotes = [],
  onSeek,
}: VideoTimelineProps) {
  function handleClick(e: React.MouseEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect()
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width))
    onSeek(ratio * durationSec)
  }

  const peerMarks = peerNotes.filter((note): note is PeerNote & { mark_sec: number } => note.mark_sec !== null)

  return (
    <div className="select-none">
      {/* Peer mark row (Nhom C) -- only rendered when there's at least one completed review to show. */}
      {peerMarks.length > 0 && (
        <div className="relative h-4">
          {peerMarks.map(note => (
            <button
              key={note.note_id}
              type="button"
              title={note.text || 'Mốc từ bạn chấm hộ'}
              onClick={() => onSeek(note.mark_sec)}
              className="absolute -translate-x-1/2 text-warning hover:opacity-80"
              style={{ left: `${pct(note.mark_sec, durationSec)}%` }}
            >
              ▾
            </button>
          ))}
        </div>
      )}

      {/* Note markers */}
      <div className="relative h-4">
        {notes.map(note => (
          <button
            key={note.note_id}
            type="button"
            title={note.text || 'Ghi chú'}
            onClick={() => onSeek(note.mark_sec)}
            className="absolute -translate-x-1/2 text-accent hover:text-accent-hover"
            style={{ left: `${pct(note.mark_sec, durationSec)}%` }}
          >
            ▾
          </button>
        ))}
      </div>

      {/* Event track + playhead */}
      <div
        onClick={handleClick}
        className="relative h-3 w-full cursor-pointer rounded-full bg-surface-elevated"
      >
        {events.map(event => (
          <div
            key={event.event_id}
            title={event.label}
            className={cn('absolute top-0 h-full rounded-full opacity-80', EVENT_COLORS[event.type] ?? 'bg-text-muted')}
            style={{
              left: `${pct(event.start_sec, durationSec)}%`,
              width: `${Math.max(0.6, pct(event.duration_sec, durationSec))}%`,
            }}
          />
        ))}
        <div
          className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 bg-text-primary"
          style={{ left: `${pct(currentSec, durationSec)}%` }}
        />
      </div>
    </div>
  )
}
