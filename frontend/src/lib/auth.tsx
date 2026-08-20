import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  clearStoredToken,
  getCurrentUser,
  getStoredToken,
  login as apiLogin,
  register as apiRegister,
  storeToken,
} from './api'
import type { RegisterPayload, User } from '../types/auth'
import { AuthContext } from './auth-context'
import type { AuthState } from './auth-context'

/**
 * Who is signed in, for the whole app.
 *
 * The token lives in localStorage rather than in memory so a page reload does
 * not sign the user out. That does mean any script running on this origin can
 * read it — the standard trade for this approach. The alternative, an
 * httpOnly cookie, needs CSRF protection and a same-site story the current
 * dev-proxy setup does not have, so it is a deliberate choice rather than an
 * oversight, and worth revisiting before this is exposed publicly.
 *
 * On startup the stored token is verified against `/auth/me` instead of being
 * trusted. A token can be expired, signed with a rotated key, or belong to an
 * account an administrator has since locked, and in all three cases the local
 * copy still *looks* fine. Asking the server is the only way to know.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = getStoredToken()
    if (!token) {
      setLoading(false)
      return
    }
    let cancelled = false
    getCurrentUser()
      .then((fetched) => {
        if (!cancelled) setUserState(fetched)
      })
      .catch(() => {
        // Expired, revoked, or belonging to a locked account. The response
        // interceptor has already dropped the token on a 401.
        clearStoredToken()
        if (!cancelled) setUserState(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    const response = await apiLogin(email, password)
    storeToken(response.access_token)
    setUserState(response.user)
    return response.user
  }, [])

  const signUp = useCallback(async (payload: RegisterPayload) => {
    const response = await apiRegister(payload)
    storeToken(response.access_token)
    setUserState(response.user)
    return response.user
  }, [])

  const signOut = useCallback(() => {
    clearStoredToken()
    setUserState(null)
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      signIn,
      signUp,
      signOut,
      setUser: setUserState,
      isAdmin: Boolean(user?.is_admin),
      // Admins inherit lecturer rights, matching `require_lecturer` on the
      // server. The UI must not offer less than the API allows, or more.
      isLecturer: Boolean(user?.is_admin || user?.role === 'lecturer'),
    }),
    [user, loading, signIn, signUp, signOut]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
