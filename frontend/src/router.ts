import { createRouter } from '@tanstack/react-router'

import { setRedirectNavigate } from '@/lib/api'
import { createRouterContext } from '@/routes/__root'
import { routeTree } from '@/routeTree.gen'
import { useAuthStore } from '@/stores/auth'

const context = createRouterContext()

export const router = createRouter({
  routeTree,
  context,
  defaultPreload: 'intent',
  defaultPreloadStaleTime: 0,
})

// Spec 0008 AC-4: reset the single shot redirecting flag on every nav so a
// later legitimate 401 still redirects.
router.subscribe('onLoad', () => {
  useAuthStore.getState().resetRedirecting()
})

// Give `apiFetch` a navigate function so it can bounce on a global 401
// without importing the router (would be a cycle).
setRedirectNavigate((to) => {
  void router.navigate({ to })
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
