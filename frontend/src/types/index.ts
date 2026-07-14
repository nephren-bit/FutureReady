export type EvaluationMode = 'presentation' | 'interview'

// Mirrors `db.models.SessionState` (values are the exact strings the API
// serializes, e.g. `SessionState.EMPTY.value == "empty"`).
export type SessionState =
  | 'empty'
  | 'slide_uploaded'
  | 'slide_analyzing'
  | 'slide_analyzed'
  | 'slide_scoring'
  | 'slide_reasoning'
  | 'slide_evaluated'
  | 'resume_uploaded'
  | 'resume_analyzing'
  | 'resume_analyzed'
  | 'resume_scoring'
  | 'resume_reasoning'
  | 'resume_evaluated'
  | 'waiting_for_video'
  | 'video_uploaded'
  | 'video_analyzing'
  | 'video_analyzed'
  | 'video_scoring'
  | 'video_reasoning'
  | 'video_evaluated'
  | 'feature_fusion'
  | 'scoring'
  | 'prompt_building'
  | 'reasoning'
  | 'report_generated'
  | 'recommending'
  | 'completed'
  | 'failed'

export interface Session {
  id: string
  mode: EvaluationMode
  state: SessionState
  language: string
  has_resume: boolean
  has_slide: boolean
  has_video: boolean
  // Events the client may legally trigger next (e.g. `["upload_video"]`);
  // empty once the session reaches a terminal state. See
  // `services/session_state_machine.py::legal_events`.
  legal_next_events: string[]
  failed_state?: string
  error_message?: string
  created_at: string
  updated_at: string
}

export interface ScoreBreakdown {
  overall_score: number
  resume_score?: number | null
  slide_score?: number | null
  speech_score?: number | null
  transcript_score?: number | null
  emotion_score?: number | null
  eye_contact_score?: number | null
  voice_confidence_score?: number | null
  presentation_score?: number | null
  communication_score?: number | null
}

export interface DerivedFeatures {
  professionalism: number
  presentation_density: number
  communication_confidence: number
  visual_engagement: number
  voice_confidence: number
  presentation_readiness: number
}

export interface ReasoningPayload {
  strengths: string[]
  weaknesses: string[]
  improvement_plan: string[]
  presentation_feedback?: string
  interview_feedback?: string
  interview_questions?: string[]
  suggestions: string[]
}

export interface EvaluationReport {
  session_id: string
  scores: ScoreBreakdown
  derived_features?: DerivedFeatures
  reasoning?: ReasoningPayload
  raw_features?: Record<string, unknown>
}

export interface PreliminaryEvaluation {
  session_id: string
  stage: string
  scores: ScoreBreakdown
  reasoning: ReasoningPayload
  scoring_engine_version: string
  reasoning_engine_name: string
  reasoning_engine_version?: string
  generated_at: string
}

// Mirrors `db.models.PracticeSessionState` (see routers/practice.py).
export type PracticeSessionState = 'connecting' | 'streaming' | 'finalizing' | 'completed' | 'failed'

export interface PracticeSession {
  id: string
  mode?: EvaluationMode | null
  language: string
  state: PracticeSessionState
  has_slide: boolean
  has_resume: boolean
  transcript_so_far: string
  error_message?: string | null
  started_at?: string | null
  ended_at?: string | null
  created_at: string
}

// Same field shape as `PreliminaryEvaluation`, just keyed by `practice_session_id`
// instead of `session_id`/`stage` -- see models/practice_models.py.
export interface PracticeEvaluation {
  practice_session_id: string
  scores: ScoreBreakdown
  reasoning: ReasoningPayload
  scoring_engine_version: string
  reasoning_engine_name: string
  reasoning_engine_version?: string
  generated_at: string
}

export interface SessionCreateRequest {
  mode: EvaluationMode
  language?: string
}

export interface SessionCreateResponse {
  id: string
  mode: EvaluationMode
  state: SessionState
  message: string
}

export const STATE_PROGRESS: Record<SessionState, number> = {
  empty: 0,
  slide_uploaded: 5,
  slide_analyzing: 10,
  slide_analyzed: 15,
  slide_scoring: 20,
  slide_reasoning: 25,
  slide_evaluated: 30,
  resume_uploaded: 5,
  resume_analyzing: 10,
  resume_analyzed: 15,
  resume_scoring: 20,
  resume_reasoning: 25,
  resume_evaluated: 30,
  waiting_for_video: 32,
  video_uploaded: 35,
  video_analyzing: 45,
  video_analyzed: 55,
  video_scoring: 62,
  video_reasoning: 68,
  video_evaluated: 75,
  feature_fusion: 80,
  scoring: 85,
  prompt_building: 90,
  reasoning: 95,
  report_generated: 97,
  recommending: 99,
  completed: 100,
  failed: -1,
}

export const STATE_LABELS: Record<SessionState, string> = {
  empty: 'Chưa tải lên',
  slide_uploaded: 'Đã tải slide',
  slide_analyzing: 'Đang phân tích slide',
  slide_analyzed: 'Đã phân tích slide',
  slide_scoring: 'Đang chấm điểm slide',
  slide_reasoning: 'AI đang đánh giá slide',
  slide_evaluated: 'Đã đánh giá slide',
  resume_uploaded: 'Đã tải CV',
  resume_analyzing: 'Đang phân tích CV',
  resume_analyzed: 'Đã phân tích CV',
  resume_scoring: 'Đang chấm điểm CV',
  resume_reasoning: 'AI đang đánh giá CV',
  resume_evaluated: 'Đã đánh giá CV',
  waiting_for_video: 'Chờ tải video',
  video_uploaded: 'Đã tải video',
  video_analyzing: 'Đang phân tích video',
  video_analyzed: 'Đã phân tích video',
  video_scoring: 'Đang chấm điểm video',
  video_reasoning: 'AI đang đánh giá video',
  video_evaluated: 'Đã đánh giá video',
  feature_fusion: 'Đang tổng hợp đặc trưng',
  scoring: 'Đang tính điểm tổng',
  prompt_building: 'Đang chuẩn bị dữ liệu AI',
  reasoning: 'AI đang tổng hợp đánh giá',
  report_generated: 'Đã tạo báo cáo',
  recommending: 'Đang gợi ý tài nguyên học tập',
  completed: 'Hoàn tất',
  failed: 'Thất bại',
}
