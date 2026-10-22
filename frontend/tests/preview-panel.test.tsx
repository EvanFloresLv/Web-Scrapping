import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PreviewPanel } from '@/components/preview-panel'
import { useAuthStore } from '@/stores/auth'

/**
 * covers:
 *  - AC-18: `Run preview` is disabled when the editor form is dirty (tooltip
 *    "Save first; Run preview sends the server stored config.") and when the
 *    picker has no selection.
 *  - AC-17: Cancel aborts the in-flight fetch via `AbortController` and the
 *    panel exits the in-flight state without crashing.
 */

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
  Toaster: () => null,
}))

const WORKFLOW_ID = '11111111-1111-7111-8111-111111111111'
const VERSION_ID = 'vvvvvvvv-vvvv-7vvv-8vvv-vvvvvvvvvvvv'
const WEBSITE_ID = 'wwwwwwww-wwww-7www-8www-wwwwwwwwwwww'
const TARGET = {
  id: 'tttttttt-tttt-7ttt-8ttt-tttttttttttt',
  website_id: WEBSITE_ID,
  url: 'https://example.com/products/1',
  label: 'Example product',
  status: 'active' as const,
  created_at: '2026-10-21T12:00:00Z',
  updated_at: '2026-10-21T12:00:00Z',
}
const SCHEMA_TEXT = JSON.stringify(
  { type: 'object', properties: { title: { type: 'string' } } },
  null,
  2,
)

function withClient(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe('PreviewPanel', () => {
  beforeEach(() => {
    useAuthStore.setState({ apiKey: 'test-key', isSignedIn: true })
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.resetModules()
  })

  it('disables Run preview when the editor form is dirty (AC-18)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ items: [TARGET], total: 1, page: 1, page_size: 200 }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    )
    const user = userEvent.setup()

    render(
      withClient(
        <PreviewPanel
          workflowId={WORKFLOW_ID}
          versionId={VERSION_ID}
          websiteId={WEBSITE_ID}
          outputSchemaText={SCHEMA_TEXT}
          isDirty={true}
        />,
      ),
    )

    await waitFor(() =>
      expect(screen.getByRole('option', { name: /Example product/i })).toBeInTheDocument(),
    )
    await user.selectOptions(screen.getByLabelText('Target'), TARGET.url)

    const runButton = screen.getByRole('button', { name: /Run preview/i })
    expect(runButton).toBeDisabled()
    expect(runButton.getAttribute('title')).toMatch(/Save first/i)
  })

  it('aborts the in-flight fetch when Cancel is clicked (AC-17)', async () => {
    let abortSignal: AbortSignal | null = null
    const previewPromise: { resolve?: (r: Response) => void; reject?: (e: unknown) => void } = {}

    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === 'string' ? input : input.toString()
        if (url.endsWith('/preview')) {
          abortSignal = init?.signal ?? null
          return new Promise<Response>((resolve, reject) => {
            previewPromise.resolve = resolve
            previewPromise.reject = reject
            init?.signal?.addEventListener('abort', () => {
              reject(new DOMException('aborted', 'AbortError'))
            })
          })
        }
        return Promise.resolve(
          new Response(JSON.stringify({ items: [TARGET], total: 1, page: 1, page_size: 200 }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }),
        )
      }),
    )

    const user = userEvent.setup()
    render(
      withClient(
        <PreviewPanel
          workflowId={WORKFLOW_ID}
          versionId={VERSION_ID}
          websiteId={WEBSITE_ID}
          outputSchemaText={SCHEMA_TEXT}
          isDirty={false}
        />,
      ),
    )

    await waitFor(() =>
      expect(screen.getByRole('option', { name: /Example product/i })).toBeInTheDocument(),
    )
    await user.selectOptions(screen.getByLabelText('Target'), TARGET.url)

    const runButton = screen.getByRole('button', { name: /Run preview/i })
    expect(runButton).not.toBeDisabled()
    await user.click(runButton)

    const cancelButton = await screen.findByRole('button', { name: /Cancel/i })
    await user.click(cancelButton)

    await waitFor(() => expect(abortSignal?.aborted).toBe(true))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Run preview/i })).toBeInTheDocument(),
    )
  })
})
