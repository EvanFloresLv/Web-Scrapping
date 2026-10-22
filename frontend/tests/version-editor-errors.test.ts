import { describe, expect, it, vi } from 'vitest'

import { mapValidationErrors } from '@/components/version-editor'
import { ApiError } from '@/lib/api'

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

/**
 * Regression for spec 0009 AC-13.
 *
 * The backend's `WorkflowValidationError` (src/app/domains/workflows/service.py)
 * emits `loc: ["output_schema", <name>]` and `["fields", <name>]` without a
 * `body` prefix. apiFetch's generic `errors[].loc` wiring strips only
 * `body/query/path`, so these would fall through to a silent setError on a
 * nonexistent form path. The editor's `onError` now adapts them to the real
 * RHF paths; this file locks that routing in.
 */

function makeError(errors: Array<{ loc: (string | number)[]; code: string; message: string }>) {
  return new ApiError({
    type: 'about:blank',
    title: 'Workflow Validation Error',
    status: 422,
    detail: 'validation failed',
    code: 'workflow.validation_error',
    correlation_id: 'cid-test',
    errors,
    instance: '/',
  })
}

describe('mapValidationErrors (spec 0009 AC-13)', () => {
  it('routes an output_schema coherence error to the output_schema pane', () => {
    const setError = vi.fn()
    const err = makeError([
      {
        loc: ['output_schema', 'placeholder'],
        code: 'workflow.validation_error',
        message: 'missing key for declared field',
      },
    ])
    mapValidationErrors(err, setError, ['placeholder'])
    expect(setError).toHaveBeenCalledWith('config.output_schema_text', {
      type: 'workflow.validation_error',
      message: 'missing key for declared field',
    })
  })

  it('routes a duplicate field name error to the matching field row by name', () => {
    const setError = vi.fn()
    const err = makeError([
      {
        loc: ['fields', 'price'],
        code: 'workflow.validation_error',
        message: 'duplicate field name',
      },
    ])
    mapValidationErrors(err, setError, ['title', 'price', 'link'])
    expect(setError).toHaveBeenCalledWith(
      'config.fields.1.name',
      expect.objectContaining({
        message: 'duplicate field name',
      }),
    )
  })

  it('routes a Pydantic body loc to the matching form path and strips body/config', () => {
    const setError = vi.fn()
    const err = makeError([
      {
        loc: ['body', 'config', 'fields', 0, 'selector'],
        code: 'string_type',
        message: 'Input should be a valid string',
      },
    ])
    mapValidationErrors(err, setError, ['title'])
    expect(setError).toHaveBeenCalledWith(
      'config.fields.0.selector',
      expect.objectContaining({
        message: 'Input should be a valid string',
      }),
    )
  })

  it('routes container_selector and pagination errors to their panes', () => {
    const setError = vi.fn()
    const err = makeError([
      {
        loc: ['container_selector'],
        code: 'workflow.validation_error',
        message: 'invalid selector',
      },
      {
        loc: ['pagination', 'next_selector'],
        code: 'workflow.validation_error',
        message: 'invalid pagination',
      },
    ])
    mapValidationErrors(err, setError, [])
    expect(setError).toHaveBeenCalledWith('config.container_selector', expect.anything())
    expect(setError).toHaveBeenCalledWith('config.pagination_text', expect.anything())
  })

  it('falls back to a toast when there is nothing to map', async () => {
    const { toast } = await import('sonner')
    const setError = vi.fn()
    mapValidationErrors(makeError([]), setError, [])
    expect(setError).not.toHaveBeenCalled()
    expect(toast.error).toHaveBeenCalled()
  })
})
