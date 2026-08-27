// Reads/writes the account session in localStorage (Nhóm B, Task 12 / Plans.md
// B5 -- httpOnly cookies were considered and rejected for this MVP, see
// Plans.md's "Quyết định đã chốt"; the XSS trade-off is accepted there, not
// silently ignored here).

import type { User } from '../types'

const TOKEN_KEY = 'futureready_token'
const USER_KEY = 'futureready_user'

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getStoredUser(): User | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as User
  } catch {
    return null
  }
}

export function setAuth(token: string, user: User): void {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

// Fired by lib/api.ts's response interceptor when a request comes back 401
// (token missing/expired/revoked) so AuthContext can drop its in-memory user
// even though the failure didn't go through login()/logout().
export const AUTH_LOGOUT_EVENT = 'futureready:auth-logout'
