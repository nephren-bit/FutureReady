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
