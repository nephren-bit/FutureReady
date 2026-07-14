export type EvaluationMode = 'presentation' | 'interview'

export type SessionState =
  | 'CREATED'
  | 'PENDING_UPLOAD'
  | 'SLIDE_EXTRACTING'
  | 'SLIDE_ANALYZING'
  | 'SLIDE_SCORING'
  | 'SLIDE_REASONING'
  | 'SLIDE_EVALUATED'
  | 'RESUME_EXTRACTING'
  | 'RESUME_ANALYZING'
  | 'RESUME_SCORING'
  | 'RESUME_REASONING'
  | 'RESUME_EVALUATED'
  | 'VIDEO_EXTRACTING'
  | 'VIDEO_ANALYZING'
  | 'SPEECH_EXTRACTING'
  | 'SPEECH_ANALYZING'
  | 'EMOTION_ANALYZING'
  | 'FACE_MESH_ANALYZING'
  | 'TRANSCRIPT_ANALYZING'
  | 'VIDEO_SCORING'
  | 'VIDEO_REASONING'
  | 'VIDEO_EVALUATED'
  | 'FEATURE_FUSION'
  | 'SCORING'
  | 'PROMPT_BUILDING'
  | 'REASONING'
  | 'COMPLETED'
  | 'FAILED'

export interface Session {
  id: string
  mode: EvaluationMode
  state: SessionState
  language: string
  slide_path?: string
  resume_path?: string
  video_path?: string
  failed_state?: string
  error_message?: string
  created_at: string
  updated_at: string
}

export interface ScoreBreakdown {
  overall_score: number
  resume_score?: number | null
  slide_content_score?: number | null
  slide_visual_score?: number | null
  speech_delivery_score?: number | null
  transcript_quality_score?: number | null
  body_language_score?: number | null
  emotional_confidence_score?: number | null
  presentation_readiness?: number | null
  interview_readiness?: number | null
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
  score: number
  reasoning: string
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
  CREATED: 0,
  PENDING_UPLOAD: 5,
  SLIDE_EXTRACTING: 10,
  SLIDE_ANALYZING: 15,
  SLIDE_SCORING: 18,
  SLIDE_REASONING: 20,
  SLIDE_EVALUATED: 25,
  RESUME_EXTRACTING: 10,
  RESUME_ANALYZING: 15,
  RESUME_SCORING: 18,
  RESUME_REASONING: 20,
  RESUME_EVALUATED: 25,
  VIDEO_EXTRACTING: 30,
  VIDEO_ANALYZING: 35,
  SPEECH_EXTRACTING: 40,
  SPEECH_ANALYZING: 45,
  EMOTION_ANALYZING: 50,
  FACE_MESH_ANALYZING: 55,
  TRANSCRIPT_ANALYZING: 60,
  VIDEO_SCORING: 65,
  VIDEO_REASONING: 70,
  VIDEO_EVALUATED: 75,
  FEATURE_FUSING: 80,
  SCORING: 85,
  PROMPT_BUILDING: 90,
  REASONING: 95,
  COMPLETED: 100,
  FAILED: -1,
}

export const STATE_LABELS: Record<SessionState, string> = {
  CREATED: 'Created',
  PENDING_UPLOAD: 'Waiting for upload',
  SLIDE_EXTRACTING: 'Extracting slide data',
  SLIDE_ANALYZING: 'Analyzing slides',
  SLIDE_SCORING: 'Scoring slides',
  SLIDE_REASONING: 'AI reasoning on slides',
  SLIDE_EVALUATED: 'Slides evaluated',
  RESUME_EXTRACTING: 'Extracting resume data',
  RESUME_ANALYZING: 'Analyzing resume',
  RESUME_SCORING: 'Scoring resume',
  RESUME_REASONING: 'AI reasoning on resume',
  RESUME_EVALUATED: 'Resume evaluated',
  VIDEO_EXTRACTING: 'Extracting video data',
  VIDEO_ANALYZING: 'Analyzing video',
  SPEECH_EXTRACTING: 'Extracting speech',
  SPEECH_ANALYZING: 'Analyzing speech',
  EMOTION_ANALYZING: 'Analyzing emotions',
  FACE_MESH_ANALYZING: 'Analyzing face mesh',
  TRANSCRIPT_ANALYZING: 'Analyzing transcript',
  VIDEO_SCORING: 'Scoring video',
  VIDEO_REASONING: 'AI reasoning on video',
  VIDEO_EVALUATED: 'Video evaluated',
  FEATURE_FUSING: 'Fusing features',
  SCORING: 'Computing scores',
  PROMPT_BUILDING: 'Building prompts',
  REASONING: 'AI generating feedback',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
}
