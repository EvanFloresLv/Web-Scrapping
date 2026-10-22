import { render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { describe, expect, it, vi } from 'vitest'

/**
 * covers: AC-7 (remaining placeholders only)
 *
 * `/targets` renders the empty state card for the backend gap documented
 * in the scope. (`/workflows` and `/executions` are real screens now,
 * covered by their own test suites.)
 */

vi.mock('@tanstack/react-router', async () => {
  const actual =
    await vi.importActual<typeof import('@tanstack/react-router')>('@tanstack/react-router')
  return {
    ...actual,
    createFileRoute: () => (opts: unknown) => opts,
  }
})

describe('placeholder routes (AC-7)', () => {
  it('/targets renders the empty state card and makes no API call', async () => {
    const spy = vi.spyOn(window, 'fetch').mockImplementation(() => {
      throw new Error('targets placeholder should not call fetch')
    })
    const mod = (await import('@/routes/_authed.targets')) as unknown as {
      Route: { component: () => ReactElement }
    }
    const Page = mod.Route.component
    render(<Page />)
    expect(screen.getByRole('heading', { name: 'Targets' })).toBeInTheDocument()
    expect(screen.getByText(/No targets to list here yet/i)).toBeInTheDocument()
    expect(spy).not.toHaveBeenCalled()
    spy.mockRestore()
  })
})
