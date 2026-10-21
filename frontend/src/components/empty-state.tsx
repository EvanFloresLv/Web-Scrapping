import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

/**
 * Empty state card (spec 0009 AC-19). Every list and every empty detail
 * area in the admin UI uses this: a title, a one line description, and a
 * primary action button that opens the matching create Sheet or triggers the
 * `+ New draft` navigation.
 */
export function EmptyState({
  title,
  description,
  action,
  className,
}: {
  title: string
  description: string
  action?: {
    label: string
    onClick: () => void
    icon?: ReactNode
  }
  className?: string
}) {
  return (
    <Card className={cn('border-dashed', className)}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      {action ? (
        <CardContent>
          <Button type="button" onClick={action.onClick}>
            {action.icon}
            {action.label}
          </Button>
        </CardContent>
      ) : null}
    </Card>
  )
}
