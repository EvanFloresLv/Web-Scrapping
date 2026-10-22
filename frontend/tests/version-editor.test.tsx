import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { createElement, type ReactElement, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'

/**
 * Component-level regression for spec 0009 AC-13.
 *
 * `/check verify` found that a 422 `workflow.validation_error` from Save
 * was silently swallowed. `/debug` added `mapValidationErrors` and wired it
 * into the editor's mutation `onError`. This test drives the real
 * `VersionEditor` through a mocked 422 and asserts the banner above the
 * output_schema pane renders (the spec wording is "dialog-level error above
 * the pane since CodeMirror has no RHF binding").
 *
 * Mocked seams: fetch (so no real backend needed), the TanStack router
 * (useNavigate/useBlocker/Link), sonner (so toast calls don't error in
 * jsdom), and `@uiw/react-codemirror` (swapped for a plain textarea so the
 * pane renders deterministically without CodeMirror's DOM layer).
 */

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
  Toaster: () => null,
}))

vi.mock('@tanstack/react-router', async () => {
  const actual =
    await vi.importActual<typeof import('@tanstack/react-router')>('@tanstack/react-router')
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useBlocker: () => ({ status: 'idle', proceed: vi.fn(), reset: vi.fn() }),
    Link: ({ children, className }: { children: ReactNode; className?: string }) =>
      createElement('a', { href: '#', className }, children),
  }
})

vi.mock('@uiw/react-codemirror', () => ({
  default: ({ value, onChange }: { value: string; onChange?: (v: string) => void }) =>
    createElement('textarea', {
      'aria-label': 'json pane',
      value,
      onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => onChange?.(e.target.value),
    }),
}))

const WORKFLOW_ID = '11111111-1111-7111-8111-111111111111'
const WORKFLOW = {
  id: WORKFLOW_ID,
  website_id: '22222222-2222-7222-8222-222222222222',
  name: 'Verify screens wf',
  description: null,
  status: 'active' as const,
  current_version_id: null,
  created_at: '2026-10-21T12:00:00Z',
  updated_at: '2026-10-21T12:00:00Z',
  deleted_at: null,
}

type FetchFn = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function problemResponse(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/problem+json' },
  })
}

function withClient(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

async function loadEditor() {
  const mod = await import('@/components/version-editor')
  return mod.VersionEditor
}

describe('VersionEditor Save error routing', () => {
  beforeEach(() => {
    useAuthStore.setState({ apiKey: 'test-key', isSignedIn: true })
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.resetModules()
  })

  it('renders a 422 output_schema coherence error above the pane (AC-13)', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn<FetchFn>(async (input, init) => {
      const url = typeof input === 'string' ? input : input.toString()
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith(`/api/v1/workflows/${WORKFLOW_ID}`)) {
        return jsonResponse(WORKFLOW)
      }
      if (method === 'POST' && url.endsWith(`/api/v1/workflows/${WORKFLOW_ID}/versions`)) {
        return problemResponse(422, {
          type: 'about:blank',
          title: 'Workflow Validation Error',
          status: 422,
          detail: 'output_schema does not cover every field',
          code: 'workflow.validation_error',
          correlation_id: 'cid-test',
          errors: [
            {
              code: 'workflow.validation_error',
              loc: ['output_schema', 'price'],
              message: 'missing key for declared field',
            },
          ],
        })
      }
      // Any targets lookup from the Preview panel: empty list is fine.
      if (method === 'GET' && url.includes('/targets')) {
        return jsonResponse({ items: [], total: 0, page: 1, page_size: 200 })
      }
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)

    const VersionEditor = await loadEditor()
    render(withClient(<VersionEditor mode={{ kind: 'new', workflowId: WORKFLOW_ID }} />))

    // Edit the seeded field name so the output_schema will no longer cover it,
    // which also makes the form dirty and enables Save.
    const nameInput = await screen.findByLabelText('Name')
    await user.clear(nameInput)
    await user.type(nameInput, 'price')

    const save = await screen.findByRole('button', { name: /save/i })
    await waitFor(() => expect(save).not.toBeDisabled())
    await user.click(save)

    const banner = await screen.findByRole('alert')
    expect(banner.textContent).toContain('missing key for declared field')

    // The banner sits above the output_schema pane textarea.
    const pane = screen.getByLabelText('json pane') as HTMLTextAreaElement
    expect(banner.compareDocumentPosition(pane) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})
