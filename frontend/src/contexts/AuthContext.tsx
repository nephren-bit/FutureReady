import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { changePassword as apiChangePassword, loginAccount, registerAccount } from '../lib/api'
import { AUTH_LOGOUT_EVENT, clearAuth, getStoredUser, setAuth } from '../lib/auth'
import type { User } from '../types'

interface AuthContextValue {
  user: User | null
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, fullName: string) => Promise<void>
  changePassword: (oldPassword: string, newPassword: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => getStoredUser())

  // A request elsewhere in the app can fail with 401 (token expired, or
  // revoked by a password change) without ever calling logout() itself --
  // lib/api.ts's response interceptor clears storage and fires this event so
  // the React tree drops the stale user too.
  useEffect(() => {
    function handleAuthLogout() {
      setUser(null)
    }
    window.addEventListener(AUTH_LOGOUT_EVENT, handleAuthLogout)
    return () => window.removeEventListener(AUTH_LOGOUT_EVENT, handleAuthLogout)
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const response = await loginAccount(email, password)
    setAuth(response.access_token, response.user)
    setUser(response.user)
  }, [])

  const register = useCallback(async (email: string, password: string, fullName: string) => {
    const response = await registerAccount(email, password, fullName)
    setAuth(response.access_token, response.user)
    setUser(response.user)
  }, [])

  // Rotates the token too (routers/auth.py revokes every token issued
  // before the change), so the caller must be re-armed with the fresh one
  // or their very next request would 401 them out.
  const changePassword = useCallback(async (oldPassword: string, newPassword: string) => {
    const response = await apiChangePassword(oldPassword, newPassword)
    setAuth(response.access_token, response.user)
    setUser(response.user)
  }, [])

  const logout = useCallback(() => {
    clearAuth()
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider
      value={{ user, isAuthenticated: user !== null, login, register, changePassword, logout }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
