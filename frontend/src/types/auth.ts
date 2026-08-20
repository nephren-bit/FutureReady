// Mirrors the account schemas in `models/auth_models.py`.
//
// `UserRole` deliberately has no `admin` member, exactly as the backend enum
// does not. Administrator is the separate `is_admin` flag, and it is granted
// only by `scripts/create_admin.py` at the machine — never by anything the
// browser can send. Adding 'admin' here would suggest a request could ask for
// it, and the server would reject that request with a 422.

export type UserRole = 'learner' | 'lecturer'

export interface User {
  id: string
  email: string
  full_name: string
  role: UserRole
  is_admin: boolean
  is_verified: boolean
  is_active: boolean
  preferred_language: string
  recording_consent_ack_at: string | null
  created_at: string | null
  last_login_at: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in_minutes: number
  user: User
}

export interface UserListResponse {
  total: number
  items: User[]
}

export interface AdminStats {
  total_users: number
  active_users: number
  inactive_users: number
  verified_users: number
  learners: number
  lecturers: number
  admins: number
  total_sessions: number
}

export interface RegisterPayload {
  email: string
  password: string
  full_name?: string
  role?: UserRole
  preferred_language?: string
}

export interface AdminUserFilters {
  search?: string
  role?: UserRole
  is_active?: boolean
  is_admin?: boolean
  limit?: number
  offset?: number
}

/** How a role should read in the interface, admin flag taking precedence. */
export function roleLabel(user: Pick<User, 'role' | 'is_admin'>): string {
  if (user.is_admin) return 'Quản trị viên'
  return user.role === 'lecturer' ? 'Giảng viên' : 'Người học'
}

// ---------------------------------------------------------------------------
// Learning-resource catalog (permission matrix row 12)
// ---------------------------------------------------------------------------

// Mirrors `SkillTag` in models/resource_models.py. A controlled vocabulary,
// not free text: the Recommendation Engine matches these against a session's
// weakest sub-scores, so a tag it does not know matches nothing.
export type SkillTag =
  | 'speaking'
  | 'confidence'
  | 'presentation'
  | 'critical_thinking'
  | 'interview'
  | 'general'

export type ResourceType = 'video' | 'article' | 'course' | 'exercise'

export const SKILL_TAG_LABELS: Record<SkillTag, string> = {
  speaking: 'Nói',
  confidence: 'Tự tin',
  presentation: 'Thuyết trình',
  critical_thinking: 'Tư duy phản biện',
  interview: 'Phỏng vấn',
  general: 'Chung',
}

export const RESOURCE_TYPE_LABELS: Record<ResourceType, string> = {
  video: 'Video',
  article: 'Bài viết',
  course: 'Khoá học',
  exercise: 'Bài tập',
}

export interface LearningResource {
  id: string
  title: string
  url: string
  resource_type: ResourceType
  platform: string | null
  language: string | null
  speaker: string | null
  source: string | null
  description: string | null
  skill_tags: SkillTag[]
  category_label: string | null
  is_active: boolean
  created_at: string | null
  /** How many recommendations point here — why hiding exists instead of deleting. */
  recommendation_count: number
}

export interface ResourceListResponse {
  total: number
  items: LearningResource[]
}

export interface ResourceStats {
  total: number
  active: number
  hidden: number
  by_type: Record<string, number>
  by_skill_tag: Record<string, number>
  untagged: number
}

export interface ResourceFilters {
  search?: string
  resource_type?: ResourceType
  skill_tag?: SkillTag
  language?: string
  is_active?: boolean
  limit?: number
  offset?: number
}

export interface ResourceInput {
  title: string
  url: string
  resource_type: ResourceType
  platform?: string | null
  language?: string | null
  speaker?: string | null
  source?: string | null
  description?: string | null
  skill_tags: SkillTag[]
  category_label?: string | null
  is_active?: boolean
}
