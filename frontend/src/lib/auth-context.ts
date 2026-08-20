import { createContext, useContext } from 'react'
import type { RegisterPayload, User } from '../types/auth'

/**
 * The shape of the auth context, kept apart from `auth.tsx`.
 *
 * Fast Refresh only preserves component state for modules whose exports are
 * all components, so the provider lives alone in `auth.tsx` and the context
 * plus its hook live here. Purely an editing-experience concern -- it changes
 * nothing at runtime.
 */
export interface AuthState {
  user: User | null
  /** True until the stored token has been checked, so guards do not redirect too early. */
  loading: boolean
  signIn: (email: string, password: string) => Promise<User>
  signUp: (payload: RegisterPayload) => Promise<User>
  signOut: () => void
  /** Replace the cached user after a profile or role change. */
  setUser: (user: User) => void
  isAdmin: boolean
  isLecturer: boolean
}

export const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth phải được dùng bên trong <AuthProvider>.')
  return context
}
