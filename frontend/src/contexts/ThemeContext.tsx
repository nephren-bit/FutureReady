import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'

export type Theme = 'system' | 'light' | 'dark'

const STORAGE_KEY = 'futureready-theme'

interface ThemeContextValue {
  theme: Theme
  // What's actually painted right now -- 'system' resolved against the
  // OS preference, for anything that needs to render a Sun/Moon icon
  // rather than a Sun/Moon/Monitor tri-state.
  resolvedTheme: 'light' | 'dark'
  setTheme: (theme: Theme) => void
  cycleTheme: () => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored === 'light' || stored === 'dark' ? stored : 'system'
  } catch {
    return 'system'
  }
}

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

// Mirrors the `[data-theme]` contract in index.css: an explicit choice sets
// the attribute so `:root[data-theme="dark"]` wins over the OS; 'system'
// removes it entirely, falling back to `@media (prefers-color-scheme: dark)`.
function applyTheme(theme: Theme) {
  const root = document.documentElement
  if (theme === 'system') {
    root.removeAttribute('data-theme')
  } else {
    root.setAttribute('data-theme', theme)
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => getStoredTheme())
  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>(() =>
    getStoredTheme() === 'system' ? (systemPrefersDark() ? 'dark' : 'light') : (getStoredTheme() as 'light' | 'dark')
  )

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next)
    try {
      if (next === 'system') localStorage.removeItem(STORAGE_KEY)
      else localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Private browsing / storage disabled -- the choice just won't
      // survive a reload, which is a harmless degradation here.
    }
    applyTheme(next)
  }, [])

  const cycleTheme = useCallback(() => {
    setTheme(theme === 'system' ? 'light' : theme === 'light' ? 'dark' : 'system')
  }, [theme, setTheme])

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  // Keep resolvedTheme accurate both when 'system' is selected and the OS
  // flips, and when the person picks an explicit theme.
  useEffect(() => {
    if (theme !== 'system') {
      setResolvedTheme(theme)
      return
    }
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    setResolvedTheme(media.matches ? 'dark' : 'light')
    function handleChange(e: MediaQueryListEvent) {
      setResolvedTheme(e.matches ? 'dark' : 'light')
    }
    media.addEventListener('change', handleChange)
    return () => media.removeEventListener('change', handleChange)
  }, [theme])

  return (
    <ThemeContext.Provider value={{ theme, resolvedTheme, setTheme, cycleTheme }}>{children}</ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within a ThemeProvider')
  return ctx
}
