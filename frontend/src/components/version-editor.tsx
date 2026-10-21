import { json as cmJson } from '@codemirror/lang-json'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useBlocker, useNavigate } from '@tanstack/react-router'
import CodeMirror from '@uiw/react-codemirror'
import { Plus, Save, Trash2 } from 'lucide-react'
import { useEffect, useMemo } from 'react'
import { Controller, useFieldArray, useForm } from 'react-hook-form'
import { toast } from 'sonner'

import { queryKeys } from '@/api/queryKeys'
import type { components } from '@/api/schema'
import { PreviewPanel } from '@/components/preview-panel'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { type ApiError, apiFetch } from '@/lib/api'
import { cn } from '@/lib/utils'

type WorkflowVersionRead = components['schemas']['WorkflowVersionRead']
type WorkflowConfig = components['schemas']['WorkflowConfig']
type WorkflowRead = components['schemas']['WorkflowRead']

/**
 * Version editor shared by `/versions/new` and `/versions/:vid` (spec 0009 M5,
 * AC-10 through AC-13). Owns one React Hook Form instance seeded from the
 * pinned `WorkflowConfig` literal (new) or the fetched row's `config` (edit).
 * Save issues a full-config POST (new) or PATCH (existing) per spec 0004
 * AC-9's write-once-at-publish contract. Non-draft rows render read only.
 *
 * The right pane is a Preview placeholder; the actual Preview panel lands in
 * milestone 6 (spec 0009 AC-17, AC-18).
 */

/**
 * The pinned seed `WorkflowConfig` for a brand new draft (spec 0009 AC-9).
 * Kept here so the editor and any future test setup share one source.
 */
export const SEED_CONFIG: WorkflowConfig = {
  container_selector: 'body',
  fields: [
    {
      name: 'placeholder',
      selector: 'body',
      type: 'string',
      required: true,
      transforms: [],
    },
  ],
  output_schema: {
    type: 'object',
    properties: { placeholder: { type: 'string' } },
    required: ['placeholder'],
  },
}

/** Pagination seed inserted by the "Add pagination" button (spec 0009 AC-11). */
const PAGINATION_SEED_TEXT = JSON.stringify({ next_selector: '', max_pages: 1 }, null, 2)

/**
 * The five fallback `type` values from spec 0005. The gen'd OpenAPI schema
 * surfaces `type` as a bare string, so we hardcode the pinned set here.
 */
const FIELD_TYPES = ['string', 'integer', 'decimal', 'boolean', 'url'] as const

type FieldRow = {
  name: string
  selector: string
  type: string
  required: boolean
  transforms: string[]
}

type FormValues = {
  config: {
    container_selector: string
    fields: FieldRow[]
    output_schema_text: string
    pagination_text: string | null
  }
}

function configToFormValues(config: WorkflowConfig): FormValues {
  const fields: FieldRow[] = (config.fields ?? []).map((f) => ({
    name: f.name,
    selector: f.selector,
    type: f.type,
    required: f.required ?? true,
    transforms: Array.isArray(f.transforms) ? f.transforms : [],
  }))
  return {
    config: {
      container_selector: config.container_selector ?? '',
      fields,
      output_schema_text: JSON.stringify(config.output_schema ?? {}, null, 2),
      pagination_text: config.pagination ? JSON.stringify(config.pagination, null, 2) : null,
    },
  }
}

type SaveMode =
  | { kind: 'new'; workflowId: string }
  | { kind: 'edit'; workflowId: string; version: WorkflowVersionRead }

export function VersionEditor({ mode }: { mode: SaveMode }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const readOnly = mode.kind === 'edit' && mode.version.status !== 'draft'

  const initial = useMemo<FormValues>(
    () =>
      mode.kind === 'new'
        ? configToFormValues(SEED_CONFIG)
        : configToFormValues(mode.version.config as WorkflowConfig),
    [mode],
  )

  const form = useForm<FormValues>({
    defaultValues: initial,
    mode: 'onBlur',
  })
  const {
    control,
    register,
    handleSubmit,
    formState,
    setValue,
    watch,
    reset,
    setError,
    clearErrors,
  } = form

  const fieldsArray = useFieldArray({ control, name: 'config.fields' })

  // Parent workflow powers the Preview panel's target picker: it reads the
  // workflow's `website_id` from here (spec 0009 AC-17).
  const workflow = useQuery<WorkflowRead, ApiError>({
    queryKey: queryKeys.workflows.detail(mode.workflowId),
    queryFn: ({ signal }) =>
      apiFetch<WorkflowRead>(`/api/v1/workflows/${mode.workflowId}`, { signal, silent: true }),
    retry: false,
  })

  // Reset when switching to another version row (edit mode) so the editor
  // re-seeds without a stale dirty flag.
  useEffect(() => {
    reset(initial)
  }, [initial, reset])

  const isDirty = formState.isDirty
  const paginationText = watch('config.pagination_text')
  const outputSchemaText = watch('config.output_schema_text')
  const watchedFields = watch('config.fields')

  const duplicateNames = useMemo(() => {
    const counts = new Map<string, number>()
    for (const f of watchedFields ?? []) {
      const key = (f.name ?? '').trim()
      if (!key) continue
      counts.set(key, (counts.get(key) ?? 0) + 1)
    }
    const dupes = new Set<string>()
    for (const [name, count] of counts) {
      if (count > 1) dupes.add(name)
    }
    return dupes
  }, [watchedFields])

  const schemaCoverageGaps = useMemo(() => {
    let parsed: unknown
    try {
      parsed = JSON.parse(outputSchemaText || '{}')
    } catch {
      return [] as string[]
    }
    const schemaKeys = new Set(
      parsed && typeof parsed === 'object' && 'properties' in parsed
        ? Object.keys((parsed as { properties?: Record<string, unknown> }).properties ?? {})
        : [],
    )
    const gaps: string[] = []
    for (const f of watchedFields ?? []) {
      const key = (f.name ?? '').trim()
      if (!key) continue
      if (!schemaKeys.has(key)) gaps.push(key)
    }
    return gaps
  }, [outputSchemaText, watchedFields])

  const mutation = useMutation<WorkflowVersionRead, ApiError, WorkflowConfig>({
    mutationFn: async (config) => {
      if (mode.kind === 'new') {
        return apiFetch<WorkflowVersionRead>(`/api/v1/workflows/${mode.workflowId}/versions`, {
          method: 'POST',
          body: JSON.stringify({ config }),
          rhfSetError: setError as never,
        })
      }
      return apiFetch<WorkflowVersionRead>(
        `/api/v1/workflows/${mode.workflowId}/versions/${mode.version.id}`,
        {
          method: 'PATCH',
          body: JSON.stringify({ config }),
          rhfSetError: setError as never,
        },
      )
    },
    onSuccess: (created) => {
      toast.success(mode.kind === 'new' ? 'Draft created.' : 'Draft saved.')
      queryClient.invalidateQueries({ queryKey: ['workflows', mode.workflowId, 'versions'] })
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows.detail(mode.workflowId) })
      if (mode.kind === 'new') {
        navigate({
          to: '/workflows/$workflowId/versions/$versionId',
          params: { workflowId: mode.workflowId, versionId: created.id },
          replace: true,
        })
      } else {
        reset(configToFormValues(created.config as WorkflowConfig))
      }
    },
  })

  const onSubmit = handleSubmit((values) => {
    clearErrors()
    const parsedConfig = parseFormToConfig(values)
    if (!parsedConfig.ok) {
      setError(parsedConfig.path as never, { type: 'manual', message: parsedConfig.message })
      return
    }
    mutation.mutate(parsedConfig.config)
  })

  // Cmd/Ctrl+S save shortcut (AC-12).
  useEffect(() => {
    if (readOnly) return
    const handler = (event: KeyboardEvent) => {
      const isSave = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's'
      if (!isSave) return
      event.preventDefault()
      if (isDirty && !mutation.isPending) {
        onSubmit()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isDirty, mutation.isPending, onSubmit, readOnly])

  // Nav guard: block router navigation while dirty, show our confirm dialog.
  const blocker = useBlocker({
    shouldBlockFn: () => isDirty && !mutation.isPending,
    enableBeforeUnload: () => isDirty && !mutation.isPending,
    withResolver: true,
  })

  const outputSchemaBannerError = formState.errors.config?.output_schema_text?.message as
    | string
    | undefined
  const paginationBannerError = formState.errors.config?.pagination_text?.message as
    | string
    | undefined

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b bg-background px-6 py-4">
        <div className="flex items-baseline gap-3">
          <h2 className="text-lg font-semibold">
            {mode.kind === 'new'
              ? 'New draft'
              : `v${mode.version.version_number} (${mode.version.status})`}
          </h2>
          {isDirty && !readOnly ? (
            <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-300">
              Dirty
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() =>
              navigate({
                to: '/workflows/$workflowId/versions',
                params: { workflowId: mode.workflowId },
                search: { page: 1, page_size: 50, with_deleted: false, status: undefined },
              })
            }
          >
            Back to versions
          </Button>
          {!readOnly ? (
            <Button
              type="button"
              onClick={() => onSubmit()}
              disabled={!isDirty || mutation.isPending}
              aria-label="Save draft"
            >
              <Save /> {mutation.isPending ? 'Saving…' : 'Save'}
            </Button>
          ) : null}
        </div>
      </header>

      {readOnly ? (
        <div
          className="border-b bg-amber-500/10 px-6 py-3 text-sm text-amber-900 dark:text-amber-200"
          role="status"
        >
          This version is {mode.version.status}; create a new draft to make changes.
        </div>
      ) : null}

      <div className="grid flex-1 min-h-0 gap-0 md:grid-cols-2">
        <section className="flex min-h-0 flex-col gap-4 overflow-y-auto border-b p-6 md:border-r md:border-b-0">
          <div className="flex flex-col gap-2">
            <Label htmlFor="container-selector">Container selector</Label>
            <Input
              id="container-selector"
              disabled={readOnly}
              {...register('config.container_selector', {
                required: 'Container selector is required',
              })}
            />
            {formState.errors.config?.container_selector ? (
              <p className="text-xs text-destructive" role="alert">
                {formState.errors.config.container_selector.message as string}
              </p>
            ) : null}
          </div>

          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold">Fields</h3>
              {!readOnly ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    fieldsArray.append({
                      name: '',
                      selector: '',
                      type: 'string',
                      required: true,
                      transforms: [],
                    })
                  }
                >
                  <Plus /> Add field
                </Button>
              ) : null}
            </div>
            <div className="flex flex-col gap-3">
              {fieldsArray.fields.map((f, index) => {
                const row = watchedFields?.[index]
                const nameKey = (row?.name ?? '').trim()
                const isDupName = nameKey.length > 0 && duplicateNames.has(nameKey)
                const nameError = formState.errors.config?.fields?.[index]?.name
                const selectorError = formState.errors.config?.fields?.[index]?.selector
                return (
                  <div
                    key={f.id}
                    className={cn(
                      'rounded-md border p-3',
                      isDupName ? 'border-destructive bg-destructive/5' : 'border-border',
                    )}
                  >
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="flex flex-col gap-1">
                        <Label htmlFor={`field-${index}-name`}>Name</Label>
                        <Input
                          id={`field-${index}-name`}
                          disabled={readOnly}
                          aria-invalid={isDupName || Boolean(nameError)}
                          className={cn(isDupName && 'border-destructive')}
                          {...register(`config.fields.${index}.name`, {
                            required: 'Name is required',
                          })}
                        />
                        {nameError ? (
                          <p className="text-xs text-destructive" role="alert">
                            {nameError.message as string}
                          </p>
                        ) : null}
                        {isDupName ? (
                          <p className="text-xs text-destructive" role="alert">
                            Duplicate field name
                          </p>
                        ) : null}
                      </div>
                      <div className="flex flex-col gap-1">
                        <Label htmlFor={`field-${index}-selector`}>Selector</Label>
                        <Input
                          id={`field-${index}-selector`}
                          disabled={readOnly}
                          {...register(`config.fields.${index}.selector`, {
                            required: 'Selector is required',
                          })}
                        />
                        {selectorError ? (
                          <p className="text-xs text-destructive" role="alert">
                            {selectorError.message as string}
                          </p>
                        ) : null}
                      </div>
                      <div className="flex flex-col gap-1">
                        <Label htmlFor={`field-${index}-type`}>Type</Label>
                        <select
                          id={`field-${index}-type`}
                          disabled={readOnly}
                          className="h-9 rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                          {...register(`config.fields.${index}.type`)}
                        >
                          {FIELD_TYPES.map((t) => (
                            <option key={t} value={t}>
                              {t}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="flex flex-col gap-1">
                        <Label htmlFor={`field-${index}-transforms`}>
                          Transforms (comma separated)
                        </Label>
                        <Controller
                          control={control}
                          name={`config.fields.${index}.transforms`}
                          render={({ field }) => (
                            <Input
                              id={`field-${index}-transforms`}
                              disabled={readOnly}
                              value={field.value.join(', ')}
                              onChange={(e) => {
                                const parts = e.target.value
                                  .split(',')
                                  .map((s) => s.trim())
                                  .filter((s) => s.length > 0)
                                field.onChange(parts)
                              }}
                            />
                          )}
                        />
                      </div>
                      <label className="flex items-center gap-2 text-sm sm:col-span-2">
                        <input
                          type="checkbox"
                          disabled={readOnly}
                          {...register(`config.fields.${index}.required`)}
                        />
                        <span>Required</span>
                      </label>
                    </div>
                    {!readOnly ? (
                      <div className="mt-3 flex justify-end">
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          onClick={() => fieldsArray.remove(index)}
                          disabled={fieldsArray.fields.length === 1}
                          aria-label={`Remove field ${index + 1}`}
                        >
                          <Trash2 /> Remove
                        </Button>
                      </div>
                    ) : null}
                  </div>
                )
              })}
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold">Output schema</h3>
            </div>
            {schemaCoverageGaps.length > 0 ? (
              <div
                className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-900 dark:text-amber-200"
                role="status"
              >
                These field names are missing from <code>output_schema.properties</code>:{' '}
                {schemaCoverageGaps.map((k) => (
                  <code key={k} className="mx-1">
                    {k}
                  </code>
                ))}
              </div>
            ) : null}
            {outputSchemaBannerError ? (
              <div
                className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive"
                role="alert"
              >
                {outputSchemaBannerError}
              </div>
            ) : null}
            <Controller
              control={control}
              name="config.output_schema_text"
              render={({ field }) => (
                <CodeMirror
                  value={field.value}
                  height="220px"
                  extensions={[cmJson()]}
                  readOnly={readOnly}
                  onChange={(value) => field.onChange(value)}
                  basicSetup={{ lineNumbers: true }}
                />
              )}
            />
          </div>

          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold">Pagination (optional)</h3>
              {!readOnly ? (
                paginationText === null ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      setValue('config.pagination_text', PAGINATION_SEED_TEXT, {
                        shouldDirty: true,
                      })
                    }
                  >
                    <Plus /> Add pagination
                  </Button>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setValue('config.pagination_text', null, { shouldDirty: true })}
                  >
                    <Trash2 /> Remove pagination
                  </Button>
                )
              ) : null}
            </div>
            {paginationBannerError ? (
              <div
                className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive"
                role="alert"
              >
                {paginationBannerError}
              </div>
            ) : null}
            {paginationText !== null ? (
              <Controller
                control={control}
                name="config.pagination_text"
                render={({ field }) => (
                  <CodeMirror
                    value={field.value ?? ''}
                    height="140px"
                    extensions={[cmJson()]}
                    readOnly={readOnly}
                    onChange={(value) => field.onChange(value)}
                    basicSetup={{ lineNumbers: true }}
                  />
                )}
              />
            ) : (
              <p className="text-xs text-muted-foreground">
                No pagination configured. Add one if the target walks multiple pages.
              </p>
            )}
          </div>
        </section>

        <section className="flex min-h-0 flex-col gap-3 overflow-y-auto p-6">
          <h3 className="text-sm font-semibold">Preview</h3>
          <PreviewPanel
            workflowId={mode.workflowId}
            versionId={mode.kind === 'edit' ? mode.version.id : undefined}
            websiteId={workflow.data?.website_id}
            outputSchemaText={outputSchemaText}
            isDirty={isDirty}
          />
        </section>
      </div>

      {blocker.status === 'blocked' ? (
        <AlertDialog open>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Unsaved changes</AlertDialogTitle>
              <AlertDialogDescription>
                You have unsaved changes. Discard them and leave this version?
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel onClick={() => blocker.reset()}>Keep editing</AlertDialogCancel>
              <AlertDialogAction onClick={() => blocker.proceed()}>Discard</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      ) : null}
    </div>
  )
}

type ParseResult =
  | { ok: true; config: WorkflowConfig }
  | { ok: false; path: string; message: string }

function parseFormToConfig(values: FormValues): ParseResult {
  let outputSchema: Record<string, unknown>
  try {
    const parsed: unknown = JSON.parse(values.config.output_schema_text)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return {
        ok: false,
        path: 'config.output_schema_text',
        message: 'Output schema must be a JSON object.',
      }
    }
    outputSchema = parsed as Record<string, unknown>
  } catch (err) {
    const detail = err instanceof Error ? err.message : 'invalid JSON'
    return {
      ok: false,
      path: 'config.output_schema_text',
      message: `Output schema is not valid JSON: ${detail}.`,
    }
  }

  let pagination: WorkflowConfig['pagination'] = null
  if (values.config.pagination_text !== null) {
    try {
      const parsed: unknown = JSON.parse(values.config.pagination_text)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return {
          ok: false,
          path: 'config.pagination_text',
          message: 'Pagination must be a JSON object.',
        }
      }
      pagination = parsed as WorkflowConfig['pagination']
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'invalid JSON'
      return {
        ok: false,
        path: 'config.pagination_text',
        message: `Pagination is not valid JSON: ${detail}.`,
      }
    }
  }

  const config: WorkflowConfig = {
    container_selector: values.config.container_selector,
    fields: values.config.fields.map((f) => ({
      name: f.name,
      selector: f.selector,
      type: f.type,
      required: f.required,
      transforms: f.transforms,
    })),
    output_schema: outputSchema,
    pagination,
  }
  return { ok: true, config }
}
