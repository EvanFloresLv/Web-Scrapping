import { createFileRoute, Outlet, redirect } from '@tanstack/react-router'

import { useAuthStore } from '@/stores/auth'

/**
 * Spec 0008 AC-2 and AC-19: protected layout. `beforeLoad` reads the auth
 * store synchronously (hydrated at module load) and bounces to `/login`
 * with the current path as `redirect`. The accepted shape is
 * `^/[a-zA-Z0-9/_-]*$` (same origin only, no scheme, no `//`). Anything
 * else falls back to `/websites` on the login success path.
 */

const REDIRECT_SHAPE = /^\/[a-zA-Z0-9/_-]*$/

export const Route = createFileRoute('/_authed')({
  beforeLoad: ({ location }) => {
    const state = useAuthStore.getState()
    if (!state.isHydrated) {
      // Should not happen because the store hydrates synchronously at module
      // load, but kept as a defensive guard; see spec 0008 AC-19.
      return
    }
    if (!state.isSignedIn) {
      const next = REDIRECT_SHAPE.test(location.pathname) ? location.pathname : '/websites'
      throw redirect({ to: '/login', search: { redirect: next } })
    }
  },
  component: AuthedShell,
})

function AuthedShell() {
  // The real `AppShell` (sidebar + header + sign out) lands in M4; for M3
  // we render the Outlet raw so the protected gate itself can be verified
  // in isolation. The import graph intentionally stays small here.
  return <Outlet />
}
