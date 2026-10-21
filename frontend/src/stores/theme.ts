import { useEffect } from 'react'
import { create } from 'zustand'

/**
 * Spec 0008 AC-14: theme toggle persists in `localStorage['admin.theme']`,
 * defaults to `system`, and applies without a page reload. `system` resolves
 * to light/dark via `prefers-color-scheme`.
 */

const STORAGE_KEY = 'admin.theme'

export type Theme = 'light' | 'dark' | 'system'

type ThemeState = {
  theme: Theme
  setTheme: (t: Theme) => void
}

function readTheme(): Theme {
  if (typeof window === 'undefined') return 'system'
  try {
    const v = window.localStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch {
    // ignore
  }
  return 'system'
}

export const useThemeStore = create<ThemeState>((set) => ({
  theme: readTheme(),
  setTheme: (t: Theme) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, t)
    } catch {
      // ignore
    }
    set({ theme: t })
  },
}))

function applyTheme(theme: Theme) {
  const root = document.documentElement
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
  const effective = theme === 'system' ? (prefersDark ? 'dark' : 'light') : theme
  root.classList.toggle('dark', effective === 'dark')
}

export function ThemeApplier() {
  const theme = useThemeStore((s) => s.theme)
  useEffect(() => {
    applyTheme(theme)
    if (theme !== 'system') return
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const listener = () => applyTheme('system')
    mql.addEventListener('change', listener)
    return () => mql.removeEventListener('change', listener)
  }, [theme])
  return null
}

export const themeStorageKey = STORAGE_KEY
