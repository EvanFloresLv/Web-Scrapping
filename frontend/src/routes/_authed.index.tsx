import { createFileRoute, redirect } from '@tanstack/react-router'

// `/` under the authed shell: send the user to the real landing page.
export const Route = createFileRoute('/_authed/')({
  beforeLoad: () => {
    throw redirect({ to: '/websites' })
  },
})
