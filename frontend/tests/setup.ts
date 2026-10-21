import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// happy-dom 21 ships `window.localStorage` as a broken getter that returns
// undefined, but `sessionStorage` works. Install a tiny in memory Storage
// polyfill on both `window` and `globalThis` so modules that read
// `window.localStorage` at import time (e.g. `src/stores/auth.ts`,
// `src/stores/theme.ts`) see a working Storage object. Scoped to tests only.
class MemoryStorage implements Storage {
  private store = new Map<string, string>()
  get length() {
    return this.store.size
  }
  clear(): void {
    this.store.clear()
  }
  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null
  }
  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null
  }
  removeItem(key: string): void {
    this.store.delete(key)
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value))
  }
}

const sharedLocalStorage = new MemoryStorage()
Object.defineProperty(window, 'localStorage', { value: sharedLocalStorage, writable: false })
Object.defineProperty(globalThis, 'localStorage', { value: sharedLocalStorage, writable: false })

afterEach(() => {
  cleanup()
  sharedLocalStorage.clear()
})
