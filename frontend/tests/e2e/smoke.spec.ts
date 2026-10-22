import { expect, test } from '@playwright/test'

/**
 * Spec 0008 AC-12 and AC-18 (frontend half). The suite stubs the backend
 * with `page.route` so it runs standalone against the Vite dev server (no
 * uvicorn or Postgres needed in CI). The same interceptor redacts the
 * `X-API-Key` header out of the recorded trace, so a captured trace never
 * carries the dev key.
 */

const DEV_KEY = 'test-admin-api-key-0123456789'

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const headers: Record<string, string> = { ...request.headers() }
    // AC-18: scrub the key out of the trace copy of this request.
    if ('x-api-key' in headers) headers['x-api-key'] = '<redacted>'
    if ('authorization' in headers) headers.authorization = '<redacted>'

    const url = new URL(request.url())
    if (url.pathname.endsWith('/api/v1/websites')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0, page: 1, page_size: 50 }),
        headers,
      })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })
})

test('sign in, see websites, toggle theme, sign out', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()

  await page.getByLabel('API key').fill(DEV_KEY)
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page).toHaveURL(/\/websites/)
  await expect(page.getByText(/No websites registered yet/i)).toBeVisible()

  // Toggle theme to dark.
  await page.getByRole('button', { name: /Theme/i }).click()
  await page.getByRole('menuitem', { name: /Dark/i }).click()
  await expect(page.locator('html.dark')).toHaveCount(1)

  // Sign out.
  await page.getByRole('button', { name: /Sign out/i }).click()
  await expect(page).toHaveURL(/\/login/)
})
