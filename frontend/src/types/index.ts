// ---------------------------------------------------------------------------
// Self Practice (specs/in-class-analysis) -- the product's sole entry point.
// No total score, ever. `PoseMetric`/`PoseFeature` mirror
// `models.features.PoseFeature`; `measured: false` means the camera framing
// couldn't see what it needed, never a real zero.
//
// (This file used to also define types for a larger upload-and-score
// evaluation pipeline -- Session/PracticeSession/ScoreBreakdown/etc. --
// removed along with that pipeline.)
// ---------------------------------------------------------------------------

export type SelfPracticeProfile = 'presentation_solo' | 'interview_solo'

// Mirrors `db.models.SelfPracticeState`.
export type SelfPracticeState = 'processing' | 'completed' | 'failed'

export interface PoseMetric {
  value: number | null
  measured: boolean
  unit: string
  reason?: string | null
}

export interface PoseFeature {
  profile: string
  profile_version: string
  frames_analyzed: number
  pose_detected_ratio: number
  sampling_rate_hz: number
  sampling_warning?: string | null
  source_fps: number
  head_up_ratio: PoseMetric
  postural_sway: PoseMetric
  movement_range: PoseMetric
  gesture_rate: PoseMetric
  closed_posture_ratio: PoseMetric
  shoulder_tilt: PoseMetric
  turned_away_ratio: PoseMetric
}

// Mirrors `models.events.PresentationEvent` -- what the machine found.
// `label` describes only the measurement, never an inferred cause.
export interface PresentationEvent {
  event_id: string
  session_id: string
  profile: string
  type: string
  start_sec: number
  duration_sec: number
  measured_value: number
  unit: string
  label: string
  rule_version: string
  detected_at: string
}

// Mirrors `models.notes.SelfNote` -- what the person marked themselves.
// Edits persist over the same row, so `note_id` never changes across edits.
export interface SelfNote {
  note_id: string
  session_id: string
  mark_sec: number
  text: string
  created_at: string
  updated_at: string
}

export interface SelfPracticeSession {
  id: string
  profile: SelfPracticeProfile
  state: SelfPracticeState
  error_message?: string | null
  pose_feature: PoseFeature | null
  events: PresentationEvent[]
  notes: SelfNote[]
  // Only ever populated from COMPLETED peer-review invites (Nhom C, Task 17).
  peer_notes: PeerNote[]
  created_at: string
  updated_at: string
}

// One row of `GET /self-practice` -- the dashboard's session list.
export interface SelfPracticeSessionSummary {
  id: string
  profile: SelfPracticeProfile
  state: SelfPracticeState
  created_at: string
}

// ---------------------------------------------------------------------------
// Accounts (Nhóm B) -- register/login, JWT kept in localStorage.
// ---------------------------------------------------------------------------

export interface User {
  id: string
  email: string
  full_name: string
  is_admin: boolean
  created_at: string
}

// Mirrors `models.auth_models.TokenResponse`.
export interface AuthResponse {
  access_token: string
  token_type: string
  user: User
}

// Mirrors `models.auth_models.AdminUserResponse` -- the admin-only view
// (`GET /admin/users`) that also carries `is_active`/`last_login_at`.
export interface AdminUser {
  id: string
  email: string
  full_name: string
  is_admin: boolean
  is_active: boolean
  created_at: string
  last_login_at: string | null
}

// ---------------------------------------------------------------------------
// Peer review ("nhờ bạn chấm hộ", Nhom C) -- the plan's only independent-
// judgment data source. PeerNote is a separate concept from SelfNote: it's
// someone else's blind mark, not the owner's own journal entry.
// ---------------------------------------------------------------------------

export type PeerReviewStatus = 'pending' | 'completed' | 'expired' | 'revoked'

// Mirrors `models.peer_review.RUBRIC_CRITERIA` -- fixed, no freeform criteria.
export const RUBRIC_CRITERIA = ['clarity', 'confidence', 'engagement'] as const
export type RubricCriterion = (typeof RUBRIC_CRITERIA)[number]
export type RubricScores = Record<RubricCriterion, number>

export const RUBRIC_LABELS: Record<RubricCriterion, string> = {
  clarity: 'Rõ ràng',
  confidence: 'Tự tin',
  engagement: 'Thu hút',
}

export interface PeerReviewInvite {
  invite_id: string
  token: string
  status: PeerReviewStatus
  created_at: string
  expires_at: string
}

// One row of a rater's blind review: a moment mark (mark_sec set, empty
// rubric_scores) or the final rubric row (mark_sec null, rubric_scores filled).
export interface PeerNote {
  note_id: string
  session_id: string
  mark_sec: number | null
  rubric_scores: Partial<RubricScores>
  text: string | null
  created_at: string
}

// Response for GET /peer-review/invites/{token}. Shape depends on status --
// pose_feature/events are only ever populated once status === 'completed'.
export interface PeerReviewState {
  status: PeerReviewStatus
  session_id: string
  profile: SelfPracticeProfile
  pose_feature: PoseFeature | null
  events: PresentationEvent[]
  own_marks: PeerNote[]
}

// ---------------------------------------------------------------------------
// Detection-quality dashboard (Nhom B Task 14 / Nhom C Task 18) -- admin-only,
// read-only. `precision`/`miss_rate`/`invite_completion_rate` are `null`,
// never `0`, when there isn't enough data yet to measure them at all.
// ---------------------------------------------------------------------------

export interface EventTypeQuality {
  profile: string
  event_type: string
  system_events: number
  system_matched: number
  precision: number | null
}

export interface QualityReport {
  generated_at: string
  tolerance_sec: number
  by_event_type: EventTypeQuality[]
  peer_marks_total: number
  peer_marks_missed: number
  miss_rate: number | null
  invites_total: number
  invites_completed: number
  invite_completion_rate: number | null
  sessions_with_peer_review: number
}

export const SELF_PRACTICE_METRIC_LABELS: Record<string, string> = {
  head_up_ratio: 'Tỷ lệ ngẩng đầu',
  postural_sway: 'Độ lắc lư tư thế',
  movement_range: 'Phạm vi di chuyển',
  gesture_rate: 'Tần suất cử chỉ tay',
  closed_posture_ratio: 'Tỷ lệ tư thế khép kín',
  shoulder_tilt: 'Độ nghiêng vai',
  turned_away_ratio: 'Tỷ lệ quay người đi',
}
