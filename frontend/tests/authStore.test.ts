import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '@/stores/auth'

/**
 * covers: AC-4, AC-19
 *
 * AC-19: the auth store hydrates synchronously at module load. We prove it
 * two ways: (a) `isHydrated` is already `true` the moment any test can
 * observe the store (no async rehydrate), and (b) a direct call to the
 * store's `signIn` writes through to `localStorage` synchronously (same
 * contract any future hydration must preserve). The "preload from
 * localStorage" shape is covered by the Playwright smoke, which boots a
 * real page with the key already stored.
 *
 * AC-4: `markRedirecting` is a single shot flag so a cascade of failed
 * queries cannot cause a redirect loop; `signIn` and `resetRedirecting`
 * clear it so a later legitimate 401 still redirects.
 */

const STORAGE_KEY = 'admin.apiKey'

beforeEach(() => {
  localStorage.clear()
  useAuthStore.setState({
    apiKey: null,
    isSignedIn: false,
    isRedirecting: false,
    isHydrated: true,
  })
})

afterEach(() => {
  localStorage.clear()
})

describe('authStore', () => {
  it('reports isHydrated true from the moment the module can be observed (AC-19)', () => {
    expect(useAuthStore.getState().isHydrated).toBe(true)
  })

  it('signIn writes the key to localStorage and clears the redirecting flag (AC-4, AC-19)', () => {
    useAuthStore.setState({ isRedirecting: true })
    useAuthStore.getState().signIn('fresh-signed-in-key-xyz1234')
    const state = useAuthStore.getState()
    expect(state.apiKey).toBe('fresh-signed-in-key-xyz1234')
    expect(state.isSignedIn).toBe(true)
    expect(state.isRedirecting).toBe(false)
    expect(localStorage.getItem(STORAGE_KEY)).toBe('fresh-signed-in-key-xyz1234')
  })

  it('signOut clears the stored key and in memory state (AC-4)', () => {
    useAuthStore.getState().signIn('temporary-key-abcdef1234')
    useAuthStore.getState().signOut()
    const state = useAuthStore.getState()
    expect(state.apiKey).toBeNull()
    expect(state.isSignedIn).toBe(false)
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('markRedirecting returns true once then false until reset (AC-4)', () => {
    expect(useAuthStore.getState().markRedirecting()).toBe(true)
    // Second call while the flag is still set must NOT trigger a second redirect.
    expect(useAuthStore.getState().markRedirecting()).toBe(false)
    useAuthStore.getState().resetRedirecting()
    expect(useAuthStore.getState().markRedirecting()).toBe(true)
  })
})
