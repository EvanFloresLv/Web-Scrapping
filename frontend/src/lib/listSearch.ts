import { z } from 'zod'

/**
 * Shared Zod schemas for the admin UI's list route search params
 * (spec 0009 AC-1, AC-20).
 *
 * Every list route exposes its filters in the URL via a Zod schema parsed in
 * TanStack Router's `validateSearch`. Invalid or out of range values fall back
 * to the defaults rather than throwing, so a tampered or stale URL still
 * renders the default page.
 */

export const PAGE_SIZE_OPTIONS = [25, 50, 100] as const
export type PageSize = (typeof PAGE_SIZE_OPTIONS)[number]

/** Coerce `?page=abc` back to 1 instead of crashing the route. */
export const pageSchema = z.coerce.number().int().min(1).catch(1).default(1)

/** Only three sizes are allowed; anything else collapses to the default. */
export const pageSizeSchema = z
  .union([z.literal(25), z.literal(50), z.literal(100)])
  .catch(50 as PageSize)
  .default(50 as PageSize)

export const statusSchema = z
  .union([z.literal('active'), z.literal('inactive')])
  .optional()
  .catch(undefined)

/** `?with_deleted=true` / `?with_deleted=false`; anything else is false. */
export const withDeletedSchema = z
  .union([
    z.literal(true),
    z.literal(false),
    z.literal('true').transform(() => true),
    z.literal('false').transform(() => false),
  ])
  .catch(false)
  .default(false)

/**
 * The base search param shape every list route (Websites, Targets, Workflows,
 * Versions) reuses. Routes extend this with additional filters by composing
 * the schema (see spec 0009 AC-5 for the Workflows `website_id` filter).
 */
export const listSearchSchema = z.object({
  page: pageSchema,
  page_size: pageSizeSchema,
  status: statusSchema,
  with_deleted: withDeletedSchema,
})

export type ListSearch = z.infer<typeof listSearchSchema>

/**
 * Build the backend `?page=…&page_size=…&status=…&with_deleted=…` query
 * string from a parsed `ListSearch` object. Keeps the serialization in one
 * place so every list route produces identical URLs.
 */
export function listSearchToQuery(filters: ListSearch): string {
  const params = new URLSearchParams()
  params.set('page', String(filters.page))
  params.set('page_size', String(filters.page_size))
  if (filters.status) {
    params.set('status', filters.status)
  }
  if (filters.with_deleted) {
    params.set('with_deleted', 'true')
  }
  return params.toString()
}
