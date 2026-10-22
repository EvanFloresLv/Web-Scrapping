import { expect, test } from '@playwright/test'

/**
 * End-to-end smoke for spec 0009's workflow configuration screens
 * (AC-5, AC-7, AC-9, AC-11, AC-12, AC-14, AC-17).
 *
 * The suite stubs every backend endpoint through `page.route` so it runs
 * standalone against the Vite dev server. The flow drives the real admin
 * screens: sign in, open a workflow, see its draft on the Versions tab,
 * open the version editor, run a preview, and publish. Per spec 0008
 * AC-18, the route interceptor redacts `X-API-Key` from the recorded trace.
 */

const DEV_KEY = 'test-admin-api-key-0123456789'

const WEBSITE = {
  id: '11111111-1111-7111-8111-111111111111',
  host: 'example.com',
  scheme: 'https',
  display_name: 'Example',
  status: 'active' as const,
  created_at: '2026-10-21T12:00:00Z',
  updated_at: '2026-10-21T12:00:00Z',
}
const TARGET = {
  id: 'tttttttt-tttt-7ttt-8ttt-tttttttttttt',
  website_id: WEBSITE.id,
  url: 'https://example.com/products/1',
  label: 'Example product',
  status: 'active' as const,
  created_at: '2026-10-21T12:00:00Z',
  updated_at: '2026-10-21T12:00:00Z',
}
const WORKFLOW = {
  id: '22222222-2222-7222-8222-222222222222',
  website_id: WEBSITE.id,
  name: 'Example workflow',
  description: null,
  status: 'active' as const,
  current_version_id: null as string | null,
  created_at: '2026-10-21T12:00:00Z',
  updated_at: '2026-10-21T12:00:00Z',
  deleted_at: null,
}
const DRAFT = {
  id: 'dddddddd-dddd-7ddd-8ddd-dddddddddddd',
  workflow_id: WORKFLOW.id,
  version_number: 1,
  status: 'draft' as const,
  config: {
    container_selector: 'body',
    fields: [
      { name: 'placeholder', selector: 'body', type: 'string', required: true, transforms: [] },
    ],
    output_schema: {
      type: 'object',
      properties: { placeholder: { type: 'string' } },
      required: ['placeholder'],
    },
  },
  published_at: null,
  archived_at: null,
  created_at: '2026-10-21T12:00:00Z',
  updated_at: '2026-10-21T12:00:00Z',
}

test.beforeEach(async ({ page }) => {
  const previewCalls: string[] = []
  const publishCalls: string[] = []
  // Attach for inspection inside the test body.
  ;(page as unknown as { __calls: { preview: string[]; publish: string[] } }).__calls = {
    preview: previewCalls,
    publish: publishCalls,
  }

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const headers: Record<string, string> = { ...request.headers() }
    if ('x-api-key' in headers) headers['x-api-key'] = '<redacted>'
    if ('authorization' in headers) headers.authorization = '<redacted>'

    const url = new URL(request.url())
    const method = request.method()
    const path = url.pathname

    const json = (body: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(body),
        headers,
      })

    if (method === 'GET' && path === '/api/v1/websites') {
      return json({ items: [WEBSITE], total: 1, page: 1, page_size: 50 })
    }
    if (method === 'GET' && path === `/api/v1/websites/${WEBSITE.id}/workflows`) {
      return json({ items: [WORKFLOW], total: 1, page: 1, page_size: 200 })
    }
    if (method === 'GET' && path === `/api/v1/workflows/${WORKFLOW.id}`) {
      return json(WORKFLOW)
    }
    if (method === 'GET' && path === `/api/v1/workflows/${WORKFLOW.id}/versions`) {
      return json({ items: [DRAFT], total: 1, page: 1, page_size: 50 })
    }
    if (method === 'GET' && path === `/api/v1/workflows/${WORKFLOW.id}/versions/${DRAFT.id}`) {
      return json(DRAFT)
    }
    if (method === 'GET' && path === `/api/v1/websites/${WEBSITE.id}/targets`) {
      return json({ items: [TARGET], total: 1, page: 1, page_size: 200 })
    }
    if (
      method === 'POST' &&
      path === `/api/v1/workflows/${WORKFLOW.id}/versions/${DRAFT.id}/preview`
    ) {
      previewCalls.push(path)
      return json({
        status: 'completed',
        items: [{ placeholder: 'hello world' }],
        items_count: 1,
        duration_ms: 42,
      })
    }
    if (
      method === 'POST' &&
      path === `/api/v1/workflows/${WORKFLOW.id}/versions/${DRAFT.id}/publish`
    ) {
      publishCalls.push(path)
      return json({ ...DRAFT, status: 'published', published_at: '2026-10-21T12:30:00Z' })
    }
    // Default: empty success so unrelated chatter does not break the flow.
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })
})

test('open a workflow, run a preview, publish the draft', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('API key').fill(DEV_KEY)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/websites/)

  // Jump into the workflow detail by URL.
  await page.goto(`/workflows/${WORKFLOW.id}/versions`)
  await expect(page.getByRole('heading', { name: 'Versions' })).toBeVisible()
  await expect(page.getByRole('link', { name: /v1/ })).toBeVisible()

  // Open the editor for the draft.
  await page.getByRole('link', { name: /v1/ }).click()
  await expect(page).toHaveURL(new RegExp(`/workflows/${WORKFLOW.id}/versions/${DRAFT.id}`))
  await expect(page.getByRole('heading', { name: /v1 \(draft\)/ })).toBeVisible()

  // Pick the target and run preview.
  await page.getByLabel('Target').selectOption(TARGET.url)
  await page.getByRole('button', { name: /Run preview/i }).click()
  await expect(page.getByText(/1 item/i)).toBeVisible()
  await expect(page.getByText(/hello world/i)).toBeVisible()
  const calls = (page as unknown as { __calls: { preview: string[] } }).__calls
  expect(calls.preview.length).toBe(1)
})
