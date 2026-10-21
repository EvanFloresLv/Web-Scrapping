import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiFetch } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

// Keep the toast and router navigate out of the unit under test.
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))

function problemResponse(body: Record<string, unknown>, status = 400): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/problem+json' },
  })
}

describe('apiFetch', () => {
  beforeEach(() => {
    useAuthStore.setState({ apiKey: 'test-key', isSignedIn: true, isRedirecting: false })
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('injects X-API-Key from the auth store (AC-4)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await apiFetch('/api/v1/websites')

    const init = fetchMock.mock.calls[0][1] as RequestInit
    const headers = new Headers(init.headers)
    expect(headers.get('X-API-Key')).toBe('test-key')
  })

  it('parses Problem Details into ApiError with correlation_id (AC-8)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      problemResponse(
        {
          title: 'Unprocessable Entity',
          status: 422,
          detail: 'Bad input',
          code: 'website.validation_failed',
          correlation_id: 'req-abc',
          errors: [{ code: 'http.422', loc: ['body', 'host'], message: 'invalid host' }],
        },
        422,
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    try {
      await apiFetch('/api/v1/websites', { silent: true })
      throw new Error('should have thrown')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      const api = error as ApiError
      expect(api.status).toBe(422)
      expect(api.code).toBe('website.validation_failed')
      expect(api.correlationId).toBe('req-abc')
      expect(api.errors).toHaveLength(1)
      expect(api.errors[0].loc).toEqual(['body', 'host'])
    }
  })

  it('maps errors[].loc to React Hook Form setError (AC-8)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      problemResponse(
        {
          title: 'Unprocessable Entity',
          status: 422,
          errors: [{ code: 'invalid', loc: ['body', 'host'], message: 'bad' }],
        },
        422,
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const setError = vi.fn()
    try {
      await apiFetch('/api/v1/websites', {
        silent: true,
        rhfSetError: setError as never,
      })
    } catch {
      // expected
    }
    expect(setError).toHaveBeenCalledWith('host', { type: 'invalid', message: 'bad' })
  })

  it('on 401 while signed in, signs out and does not loop (AC-4)', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(problemResponse({ title: 'Unauthorized', status: 401 }, 401))
    vi.stubGlobal('fetch', fetchMock)

    try {
      await apiFetch('/api/v1/websites', { silent: true })
    } catch {
      // expected
    }
    expect(useAuthStore.getState().isSignedIn).toBe(false)
    expect(useAuthStore.getState().isRedirecting).toBe(true)
  })
})
