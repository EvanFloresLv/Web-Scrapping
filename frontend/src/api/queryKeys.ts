/**
 * TanStack Query key convention for the admin UI (spec 0009 AC-20).
 *
 * Every query key is a tuple whose first element is the resource name and
 * whose remaining elements narrow the scope (filters, id, nested resource).
 * Mutations invalidate by passing the matching prefix tuple so lists and
 * details refetch in one place.
 *
 *   Websites list                           ['websites', filters]
 *   One website                             ['websites', id]
 *   Targets under a website                 ['websites', id, 'targets', filters]
 *   One target                              ['targets', id]
 *   Workflows list                          ['workflows', filters]
 *   One workflow                            ['workflows', id]
 *   Versions under a workflow               ['workflows', id, 'versions', filters]
 *   One version                             ['workflows', id, 'versions', vid]
 *
 * `filters` is a stable object (the parsed, defaulted search params object);
 * TanStack Query hashes it structurally so prop order is irrelevant.
 */

export type Filters = Readonly<Record<string, unknown>>

export const queryKeys = {
  websites: {
    all: ['websites'] as const,
    list: (filters: Filters) => ['websites', filters] as const,
    detail: (id: string) => ['websites', id] as const,
    targets: {
      list: (websiteId: string, filters: Filters) =>
        ['websites', websiteId, 'targets', filters] as const,
    },
  },
  targets: {
    all: ['targets'] as const,
    detail: (id: string) => ['targets', id] as const,
  },
  workflows: {
    all: ['workflows'] as const,
    list: (filters: Filters) => ['workflows', filters] as const,
    detail: (id: string) => ['workflows', id] as const,
    versions: {
      list: (workflowId: string, filters: Filters) =>
        ['workflows', workflowId, 'versions', filters] as const,
      detail: (workflowId: string, versionId: string) =>
        ['workflows', workflowId, 'versions', versionId] as const,
    },
  },
} as const
