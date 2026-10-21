import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'

/**
 * Create / edit side Sheet (spec 0009 AC-2, AC-4, AC-6, M1).
 *
 * Every CRUD action in the admin UI opens one of these: it owns the open
 * state, the title / description, the form body supplied by the caller, and
 * the shared Save / Cancel footer. The form is a plain `<form>` the caller
 * wires to React Hook Form, so RHF stays the only path to field state and
 * `apiFetch` stays the only path to the backend.
 */

export type CrudSheetProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  mode: 'create' | 'edit'
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void
  /** Disables the submit button; set from RHF `formState.isSubmitting`. */
  isSubmitting?: boolean
  /** Submit label override; defaults depend on `mode`. */
  submitLabel?: string
  children: ReactNode
}

export function CrudSheet({
  open,
  onOpenChange,
  title,
  description,
  mode,
  onSubmit,
  isSubmitting,
  submitLabel,
  children,
}: CrudSheetProps) {
  const label = submitLabel ?? (mode === 'create' ? 'Create' : 'Save changes')
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col gap-6 sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          {description ? <SheetDescription>{description}</SheetDescription> : null}
        </SheetHeader>
        <form onSubmit={onSubmit} className="flex flex-1 flex-col gap-4 overflow-y-auto">
          <div className="flex flex-1 flex-col gap-4">{children}</div>
          <SheetFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? 'Saving…' : label}
            </Button>
          </SheetFooter>
        </form>
      </SheetContent>
    </Sheet>
  )
}
