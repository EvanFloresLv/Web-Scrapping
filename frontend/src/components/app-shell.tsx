import { Link, Outlet, useNavigate } from '@tanstack/react-router'
import { LogOut, Monitor, Moon, Sun } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'
import { type Theme, useThemeStore } from '@/stores/theme'

/**
 * Spec 0008 AC-5: persistent left sidebar with four nav items plus a top
 * header with a signed in indicator, a theme toggle (light/dark/system),
 * and a sign out action.
 */

const NAV_ITEMS = [
  { to: '/websites', label: 'Websites' },
  { to: '/targets', label: 'Targets' },
  { to: '/workflows', label: 'Workflows' },
  { to: '/executions', label: 'Executions' },
] as const

export function AppShell() {
  const navigate = useNavigate()
  const signOut = useAuthStore((s) => s.signOut)

  function handleSignOut() {
    signOut()
    navigate({ to: '/login' })
  }

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="hidden w-56 shrink-0 border-r bg-sidebar p-4 md:block">
        <div className="mb-6 px-2 text-sm font-semibold tracking-tight">Scraping Platform</div>
        <nav className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className={cn(
                'rounded-md px-3 py-2 text-sm text-sidebar-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
                '[&.active]:bg-sidebar-accent [&.active]:text-sidebar-accent-foreground',
              )}
              activeProps={{ className: 'active' }}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-end gap-3 border-b px-4">
          <SignedInIndicator />
          <ThemeToggle />
          <Separator orientation="vertical" className="h-6" />
          <Button variant="ghost" size="sm" onClick={handleSignOut} aria-label="Sign out">
            <LogOut aria-hidden /> Sign out
          </Button>
        </header>
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function SignedInIndicator() {
  const isSignedIn = useAuthStore((s) => s.isSignedIn)
  if (!isSignedIn) return null
  return (
    <span
      className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:text-emerald-300"
      title="Signed in"
    >
      Signed in
    </span>
  )
}

function ThemeToggle() {
  const theme = useThemeStore((s) => s.theme)
  const setTheme = useThemeStore((s) => s.setTheme)
  const Icon = theme === 'dark' ? Moon : theme === 'light' ? Sun : Monitor
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Theme: ${theme}`}>
          <Icon aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {(['light', 'dark', 'system'] as Theme[]).map((t) => (
          <DropdownMenuItem key={t} onSelect={() => setTheme(t)}>
            {t.charAt(0).toUpperCase() + t.slice(1)}
            {theme === t ? <span className="ml-auto text-xs">●</span> : null}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
