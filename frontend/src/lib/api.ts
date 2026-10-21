import type { UseFormSetError } from 'react-hook-form'
import { toast } from 'sonner'

import { useAuthStore } from '@/stores/auth'

/**
 * Shared `apiFetch` wrapper (spec 0008 AC-3, AC-4, AC-8).
 *
 * One place to:
 * - inject `X-API-Key` from the Zustand `authStore`
 * - parse `application/problem+json` into `ApiError`
 * - route a validation style error (`errors[]`) to RHF `setError`
 * - route everything else to a Sonner toast with the `correlation_id`
 * - trigger the gated single shot 401 redirect
 *
 * No request bypasses this wrapper; every page uses it (or a TanStack Query
 * loader that uses it). Keeping the auth boundary single also means Feature
 * 26 can swap the mechanism without a UI sweep.
 */

export type ApiProblemFieldError = {
  code: string
  loc: Array<string | number>
  message: string
  meta?: Record<string, unknown>
}

export type ApiProblem = {
  type?: string
  title: string
  status: number
  detail?: string
  code?: string
  correlation_id?: string
  errors?: ApiProblemFieldError[]
  checks?: Record<string, string>
}

export class ApiError extends Error {
  readonly status: number
  readonly code?: string
  readonly title: string
  readonly detail?: string
  readonly errors: ApiProblemFieldError[]
  readonly correlationId?: string

  constructor(problem: ApiProblem) {
    super(problem.detail ?? problem.title)
    this.name = 'ApiError'
    this.status = problem.status
    this.code = problem.code
    this.title = problem.title
    this.detail = problem.detail
    this.errors = problem.errors ?? []
    this.correlationId = problem.correlation_id
  }
}

export type ApiFetchOptions = RequestInit & {
  /** If provided, `errors[].loc` entries are mapped to field errors here. */
  rhfSetError?: UseFormSetError<Record<string, unknown>>
  /** Suppress the toast for the global unexpected error path. */
  silent?: boolean
  /** Opt out of the global 401 redirect; `/login` uses this. */
  skip401Redirect?: boolean
}

type NavigateFn = (path: string) => void
let navigate: NavigateFn | null = null

/**
 * Called once from the router bootstrap so the global 401 handler can
 * navigate without pulling the router module here (would be a cycle).
 */
export function setRedirectNavigate(fn: NavigateFn) {
  navigate = fn
}

function problemFromUnknown(status: number): ApiProblem {
  return {
    title: 'Request failed',
    status,
    detail: `The server returned ${status} with no Problem Details body.`,
  }
}

async function parseProblem(response: Response): Promise<ApiProblem> {
  const contentType = response.headers.get('content-type') ?? ''
  if (
    contentType.includes('application/problem+json') ||
    contentType.includes('application/json')
  ) {
    try {
      return (await response.json()) as ApiProblem
    } catch {
      return problemFromUnknown(response.status)
    }
  }
  return problemFromUnknown(response.status)
}

function toastForError(error: ApiError) {
  const parts = [error.title, error.detail].filter(Boolean).join(': ')
  const suffix = error.correlationId ? `  (correlation ${error.correlationId})` : ''
  toast.error(`${parts}${suffix}`)
}

function handleFieldErrors(
  error: ApiError,
  setError: UseFormSetError<Record<string, unknown>>,
): boolean {
  let mappedAny = false
  const unmapped: ApiProblemFieldError[] = []
  for (const entry of error.errors) {
    // Backend `errors[].loc` begins with "body" / "query" / "path"; the field
    // name is the last string segment. Strip the leading transport scope so
    // RHF can resolve the field path.
    const scoped = [...entry.loc]
    if (
      scoped.length > 0 &&
      (scoped[0] === 'body' || scoped[0] === 'query' || scoped[0] === 'path')
    ) {
      scoped.shift()
    }
    const name = scoped.map(String).join('.')
    if (!name) {
      unmapped.push(entry)
      continue
    }
    setError(name, { type: entry.code, message: entry.message })
    mappedAny = true
  }
  if (unmapped.length > 0) {
    toast.error(`${error.title}: ${unmapped.map((u) => u.message).join('; ')}`)
  }
  return mappedAny
}

export async function apiFetch<T = unknown>(
  path: string,
  { rhfSetError, silent, skip401Redirect, ...init }: ApiFetchOptions = {},
): Promise<T> {
  const store = useAuthStore.getState()
  const headers = new Headers(init.headers ?? {})
  if (store.apiKey) {
    headers.set('X-API-Key', store.apiKey)
  }
  if (init.body !== undefined && !headers.has('content-type')) {
    headers.set('content-type', 'application/json')
  }

  const response = await fetch(path, { ...init, headers })

  if (response.status === 401 && !skip401Redirect) {
    // Spec 0008 AC-4: only the global handler fires when the user was signed
    // in. On a cold load with a tampered key, the beforeLoad guard handled
    // routing; here we clear state and bounce exactly once.
    if (store.isSignedIn && store.markRedirecting()) {
      store.signOut()
      if (navigate) {
        navigate('/login')
      } else if (typeof window !== 'undefined') {
        window.location.assign('/login')
      }
    }
  }

  if (!response.ok) {
    const problem = await parseProblem(response)
    const error = new ApiError({ ...problem, status: response.status })
    if (rhfSetError && error.errors.length > 0) {
      const mapped = handleFieldErrors(error, rhfSetError)
      if (mapped) {
        throw error
      }
    }
    if (!silent) {
      toastForError(error)
    }
    throw error
  }

  if (response.status === 204) {
    return undefined as T
  }
  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) {
    return (await response.json()) as T
  }
  return (await response.text()) as unknown as T
}
