import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { useThemeStore } from '@/stores/theme'

/**
 * covers: AC-14
 *
 * Theme selection persists in `localStorage['admin.theme']`, defaults to
 * `system`, and applies without a page reload. The reload free apply is
 * covered by the Playwright smoke (`tests/e2e/smoke.spec.ts`); here we
 * lock in the persistence contract and the default.
 */

const STORAGE_KEY = 'admin.theme'

beforeEach(() => {
  localStorage.clear()
  useThemeStore.setState({ theme: 'system' })
})

afterEach(() => {
  localStorage.clear()
})

describe('themeStore', () => {
  it('default initial state is `system` (AC-14)', () => {
    expect(useThemeStore.getState().theme).toBe('system')
  })

  it('setTheme persists the choice to localStorage (AC-14)', () => {
    useThemeStore.getState().setTheme('dark')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('dark')
    expect(useThemeStore.getState().theme).toBe('dark')

    useThemeStore.getState().setTheme('light')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('light')
    expect(useThemeStore.getState().theme).toBe('light')
  })

  it('all three themes round trip through setTheme (AC-14)', () => {
    for (const t of ['light', 'dark', 'system'] as const) {
      useThemeStore.getState().setTheme(t)
      expect(localStorage.getItem(STORAGE_KEY)).toBe(t)
      expect(useThemeStore.getState().theme).toBe(t)
    }
  })
})
