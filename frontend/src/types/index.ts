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

export const SELF_PRACTICE_METRIC_LABELS: Record<string, string> = {
  head_up_ratio: 'Tỷ lệ ngẩng đầu',
  postural_sway: 'Độ lắc lư tư thế',
  movement_range: 'Phạm vi di chuyển',
  gesture_rate: 'Tần suất cử chỉ tay',
  closed_posture_ratio: 'Tỷ lệ tư thế khép kín',
  shoulder_tilt: 'Độ nghiêng vai',
  turned_away_ratio: 'Tỷ lệ quay người đi',
}
