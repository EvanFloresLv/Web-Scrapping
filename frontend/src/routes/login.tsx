import { zodResolver } from '@hookform/resolvers/zod'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError, apiFetch } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

const REDIRECT_SHAPE = /^\/[a-zA-Z0-9/_-]*$/

const searchSchema = z.object({
  redirect: z.string().optional(),
})

export const Route = createFileRoute('/login')({
  validateSearch: (search) => searchSchema.parse(search),
  component: LoginPage,
})

const formSchema = z.object({
  apiKey: z.string().min(1, 'API key is required'),
})

type FormValues = z.infer<typeof formSchema>

function LoginPage() {
  const { redirect: rawRedirect } = Route.useSearch()
  const navigate = useNavigate()
  const signIn = useAuthStore((s) => s.signIn)

  const target = rawRedirect && REDIRECT_SHAPE.test(rawRedirect) ? rawRedirect : '/websites'

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: { apiKey: '' },
  })

  async function onSubmit(values: FormValues) {
    try {
      // Probe the key with a cheap authenticated read BEFORE storing it,
      // so a wrong key never lands in `localStorage` (spec 0008 AC-3).
      await apiFetch('/api/v1/websites?limit=1', {
        headers: { 'X-API-Key': values.apiKey },
        silent: true,
        skip401Redirect: true,
      })
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        form.setError('apiKey', { type: 'rejected', message: 'Key rejected' })
        return
      }
      form.setError('apiKey', {
        type: 'network',
        message: error instanceof Error ? error.message : 'Could not reach the backend.',
      })
      return
    }
    signIn(values.apiKey)
    navigate({ to: target })
  }

  const apiKeyError = form.formState.errors.apiKey

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
          <CardDescription>
            Paste your `ADMIN_API_KEY`. The key never leaves your browser except as the `X-API-Key`
            header on your own requests to this backend.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4" noValidate>
            <div className="space-y-2">
              <Label htmlFor="apiKey">API key</Label>
              <Input
                id="apiKey"
                type="password"
                autoComplete="current-password"
                aria-invalid={apiKeyError ? true : undefined}
                {...form.register('apiKey')}
              />
              {apiKeyError ? (
                <p className="text-sm text-destructive" role="alert">
                  {apiKeyError.message}
                </p>
              ) : null}
            </div>
            <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting ? 'Checking…' : 'Sign in'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
