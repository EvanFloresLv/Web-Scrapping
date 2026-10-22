import { useQueries, useQuery } from '@tanstack/react-query'

import { apiFetch } from '@/lib/api'
import { type ListSearch, listSearchToQuery } from '@/lib/listSearch'

/**
 * Shape of a backend paginated list response (spec 0002 and 0004 both use
 * this envelope). Kept generic over `T` so each list route pins its own row
 * type from the generated OpenAPI schema.
 */
export type PaginatedResponse<T> = {
  items: T[]
  total: number
  page: number
  page_size: number
}

export type UseListQueryOptions = {
  /** Query key tuple from `queryKeys` (spec 0009 AC-20). */
  queryKey: readonly unknown[]
  /** Backend endpoint, no query string; `useListQuery` appends it. */
  endpoint: string
  /** Parsed, defaulted list search params from `validateSearch`. */
  filters: ListSearch
  /** Extra query params to merge into the URL (e.g. `website_id`). */
  extraParams?: Readonly<Record<string, string | undefined>>
  /** Skip the fetch when preconditions are not met. */
  enabled?: boolean
}

/**
 * TanStack Query hook for the admin UI's list routes (spec 0009 M1).
 *
 * Composes the shared list search params with the backend endpoint, so each
 * list route only names its endpoint and its row type. Mutations invalidate
 * the matching key family (see `queryKeys`).
 */
export function useListQuery<T>({
  queryKey,
  endpoint,
  filters,
  extraParams,
  enabled,
}: UseListQueryOptions) {
  const search = buildSearchString(filters, extraParams)
  const url = search ? `${endpoint}?${search}` : endpoint
  return useQuery({
    queryKey,
    queryFn: ({ signal }) => apiFetch<PaginatedResponse<T>>(url, { signal }),
    enabled,
  })
}

function buildSearchString(
  filters: ListSearch,
  extraParams?: Readonly<Record<string, string | undefined>>,
): string {
  const base = listSearchToQuery(filters)
  if (!extraParams) {
    return base
  }
  const params = new URLSearchParams(base)
  for (const [key, value] of Object.entries(extraParams)) {
    if (value !== undefined && value !== '') {
      params.set(key, value)
    }
  }
  return params.toString()
}

export type UseBatchedQueriesOptions = {
  /** Unique ids to fan out over (deduped by the caller). */
  ids: readonly string[]
  /** Builds the query key for one id (uses `queryKeys` by convention). */
  queryKey: (id: string) => readonly unknown[]
  /** Builds the endpoint URL for one id. */
  endpoint: (id: string) => string
  /** Skip the fan out when preconditions are not met. */
  enabled?: boolean
}

/**
 * `useQueries` fan out helper for the batched parent lookup pattern
 * (spec 0009 AC-5: per row `website` name and current version number).
 *
 * Returns a map of id → data (undefined while loading or on error) so a row
 * renderer can look up its parent synchronously without caring about query
 * state per cell.
 */
export function useBatchedQueries<T>({
  ids,
  queryKey,
  endpoint,
  enabled = true,
}: UseBatchedQueriesOptions): {
  map: Record<string, T | undefined>
  isPending: boolean
} {
  const results = useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKey(id),
      queryFn: ({ signal }: { signal: AbortSignal }) => apiFetch<T>(endpoint(id), { signal }),
      enabled,
    })),
  })
  const map: Record<string, T | undefined> = {}
  let isPending = false
  for (let i = 0; i < ids.length; i += 1) {
    const result = results[i]
    const id = ids[i]
    if (!id) continue
    map[id] = result?.data
    if (result?.isPending) {
      isPending = true
    }
  }
  return { map, isPending }
}
