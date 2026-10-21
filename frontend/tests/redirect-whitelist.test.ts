import { describe, expect, it } from 'vitest'

/**
 * covers: AC-2
 *
 * `/login`'s `redirect` search param accepts same origin paths only. Shape:
 * `^/[a-zA-Z0-9/_-]*$`. Any other value falls back to `/websites` on login
 * success. This test locks in the pattern so an accidental loosening (that
 * would admit `//evil.com` or `javascript:...`) is caught at commit time.
 *
 * The regex is intentionally duplicated here from the two call sites
 * (`src/routes/login.tsx` and `src/routes/_authed.tsx`). If you ever
 * refactor it into a shared helper, point this test at that helper.
 */

const REDIRECT_SHAPE = /^\/[a-zA-Z0-9/_-]*$/

describe('redirect param whitelist (AC-2)', () => {
  it('admits ordinary same origin paths', () => {
    for (const path of ['/websites', '/targets', '/workflows/42', '/a_b/c-d', '/']) {
      expect(REDIRECT_SHAPE.test(path)).toBe(true)
    }
  })

  it('rejects protocol relative URLs (open redirect vector)', () => {
    expect(REDIRECT_SHAPE.test('//evil.com')).toBe(false)
    expect(REDIRECT_SHAPE.test('//evil.com/websites')).toBe(false)
  })

  it('rejects absolute URLs with a scheme', () => {
    expect(REDIRECT_SHAPE.test('http://evil.com/')).toBe(false)
    expect(REDIRECT_SHAPE.test('https://evil.com/x')).toBe(false)
    expect(REDIRECT_SHAPE.test('javascript:alert(1)')).toBe(false)
    expect(REDIRECT_SHAPE.test('data:text/html,x')).toBe(false)
  })

  it('rejects paths with query strings or fragments or spaces', () => {
    expect(REDIRECT_SHAPE.test('/websites?x=1')).toBe(false)
    expect(REDIRECT_SHAPE.test('/websites#frag')).toBe(false)
    expect(REDIRECT_SHAPE.test('/websites x')).toBe(false)
  })

  it('rejects paths that do not start with a single slash', () => {
    expect(REDIRECT_SHAPE.test('websites')).toBe(false)
    expect(REDIRECT_SHAPE.test('')).toBe(false)
  })
})
