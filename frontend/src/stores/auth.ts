import { create } from 'zustand'

/**
 * Spec 0008 AC-19: hydrated synchronously at module load (not via async
 * `persist` middleware), so `beforeLoad` can gate on `isHydrated === true`
 * on the very first render without racing an async rehydrate.
 *
 * Spec 0008 AC-4: `isRedirecting` is a single shot flag. The global 401
 * handler fires `signOut()` and navigates to `/login` once; the flag is
 * reset inside `signIn()` and on `router.subscribe('onLoad')` so a later
 * legitimate 401 still redirects.
 */

const STORAGE_KEY = 'admin.apiKey'

export type AuthState = {
  apiKey: string | null
  isSignedIn: boolean
  isHydrated: boolean
  isRedirecting: boolean
  signIn: (key: string) => void
  signOut: () => void
  markRedirecting: () => boolean
  resetRedirecting: () => void
}

function readKeyFromStorage(): string | null {
  if (typeof window === 'undefined') return null
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    return value?.trim() ? value : null
  } catch {
    return null
  }
}

export const useAuthStore = create<AuthState>((set, get) => {
  const initial = readKeyFromStorage()
  return {
    apiKey: initial,
    isSignedIn: initial !== null,
    isHydrated: true,
    isRedirecting: false,
    signIn: (key: string) => {
      try {
        window.localStorage.setItem(STORAGE_KEY, key)
      } catch {
        // storage disabled; still keep in memory
      }
      set({ apiKey: key, isSignedIn: true, isRedirecting: false })
    },
    signOut: () => {
      try {
        window.localStorage.removeItem(STORAGE_KEY)
      } catch {
        // ignore
      }
      set({ apiKey: null, isSignedIn: false })
    },
    markRedirecting: () => {
      if (get().isRedirecting) return false
      set({ isRedirecting: true })
      return true
    },
    resetRedirecting: () => set({ isRedirecting: false }),
  }
})

export const authStorageKey = STORAGE_KEY
