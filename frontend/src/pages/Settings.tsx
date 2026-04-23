import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  CheckCircle2,
  KeyRound,
  Pencil,
  Plug,
  Plus,
  Trash2,
  X,
  XCircle,
} from "lucide-react"
import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import {
  ApiError,
  api,
  type Credential,
  type CredentialCreate,
  type CredentialUpdate,
  type ProviderInfo,
  type TestConnectionResult,
} from "@/lib/api"

type FormState = {
  provider: string
  label: string
  api_base: string
  api_key: string
  api_secret: string
}

const EMPTY_FORM: FormState = {
  provider: "",
  label: "",
  api_base: "",
  api_key: "",
  api_secret: "",
}

const DEFAULT_API_BASE: Record<string, string> = {
  godaddy: "https://api.godaddy.com",
  combell: "https://api.combell.com",
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function TestResultBadge({ result }: { result: TestConnectionResult | undefined }) {
  if (!result) return null
  return result.ok ? (
    <Badge variant="success" className="whitespace-normal">
      <CheckCircle2 />
      Connected
    </Badge>
  ) : (
    <Badge variant="destructive" className="whitespace-normal">
      <XCircle />
      {result.error ?? "Failed"}
    </Badge>
  )
}

function CredentialForm({
  providers,
  initial,
  editingId,
  onSubmit,
  onCancel,
  submitting,
  submitError,
}: {
  providers: ProviderInfo[]
  initial: FormState
  editingId: number | null
  onSubmit: (state: FormState) => void
  onCancel: () => void
  submitting: boolean
  submitError: string | null
}) {
  const [state, setState] = useState<FormState>(initial)

  const setField = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setState((s) => ({ ...s, [key]: value }))

  const selectProvider = (key: string) => {
    setField("provider", key)
    if (!editingId && !state.api_base && DEFAULT_API_BASE[key]) {
      setField("api_base", DEFAULT_API_BASE[key])
    }
  }

  const canSubmit = Boolean(
    state.provider &&
      state.label &&
      state.api_base &&
      (editingId ? true : state.api_key),
  )

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault()
        if (canSubmit) onSubmit(state)
      }}
    >
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="cred-provider">Provider</Label>
          <Select
            id="cred-provider"
            value={state.provider}
            onChange={(e) => selectProvider(e.target.value)}
            disabled={editingId !== null}
            required
          >
            <option value="" disabled>
              Select a provider…
            </option>
            {providers.map((p) => (
              <option key={p.key} value={p.key}>
                {p.key}
                {p.adapter_installed ? "" : " (adapter not yet installed)"}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cred-label">Label</Label>
          <Input
            id="cred-label"
            value={state.label}
            onChange={(e) => setField("label", e.target.value)}
            placeholder="e.g. primary"
            required
          />
        </div>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="cred-base">API base URL</Label>
        <Input
          id="cred-base"
          type="url"
          value={state.api_base}
          onChange={(e) => setField("api_base", e.target.value)}
          placeholder="https://api.example.com"
          required
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="cred-key">
            API key {editingId && <span className="text-xs text-muted-foreground">(leave blank to keep)</span>}
          </Label>
          <Input
            id="cred-key"
            type="password"
            autoComplete="off"
            value={state.api_key}
            onChange={(e) => setField("api_key", e.target.value)}
            placeholder={editingId ? "••••••••" : "API key"}
            required={!editingId}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cred-secret">
            API secret <span className="text-xs text-muted-foreground">(optional)</span>
          </Label>
          <Input
            id="cred-secret"
            type="password"
            autoComplete="off"
            value={state.api_secret}
            onChange={(e) => setField("api_secret", e.target.value)}
            placeholder={editingId ? "••••••••" : "API secret"}
          />
        </div>
      </div>

      {submitError && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>{submitError}</span>
        </div>
      )}

      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          <X />
          Cancel
        </Button>
        <Button type="submit" disabled={!canSubmit || submitting}>
          {editingId ? "Save changes" : "Create credential"}
        </Button>
      </div>
    </form>
  )
}

function CredentialRow({
  credential,
  onEdit,
  onTest,
  onDelete,
  testResult,
  testing,
  deleting,
}: {
  credential: Credential
  onEdit: () => void
  onTest: () => void
  onDelete: () => void
  testResult: TestConnectionResult | undefined
  testing: boolean
  deleting: boolean
}) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4 md:flex-row md:items-center md:justify-between">
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="font-medium">{credential.label}</span>
          <Badge variant="outline" className="font-mono text-xs">
            {credential.provider}
          </Badge>
        </div>
        <div className="text-xs text-muted-foreground">
          <span className="font-mono">{credential.api_base}</span>
          {" · "}
          key <span className="font-mono">{credential.masked_hint}</span>
          {credential.has_api_secret ? " · secret stored" : " · no secret"}
          {" · updated "}
          {formatDate(credential.updated_at)}
        </div>
        {testResult && (
          <div className="pt-1">
            <TestResultBadge result={testResult} />
          </div>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={onTest} disabled={testing}>
          <Plug />
          {testing ? "Testing…" : "Test"}
        </Button>
        <Button variant="outline" size="sm" onClick={onEdit}>
          <Pencil />
          Update
        </Button>
        <Button
          variant="destructive"
          size="sm"
          onClick={onDelete}
          disabled={deleting}
        >
          <Trash2 />
          Delete
        </Button>
      </div>
    </div>
  )
}

function apiErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return fallback
}

export default function Settings() {
  const qc = useQueryClient()
  const credentialsQuery = useQuery({
    queryKey: ["credentials"],
    queryFn: api.credentials.list,
  })
  const providersQuery = useQuery({
    queryKey: ["providers"],
    queryFn: api.providers,
  })

  const [formState, setFormState] = useState<
    { mode: "create" } | { mode: "edit"; id: number; initial: FormState } | null
  >(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<
    Record<number, TestConnectionResult>
  >({})

  const createMutation = useMutation({
    mutationFn: (body: CredentialCreate) => api.credentials.create(body),
    onSuccess: () => {
      setFormState(null)
      setSubmitError(null)
      void qc.invalidateQueries({ queryKey: ["credentials"] })
    },
    onError: (err) =>
      setSubmitError(apiErrorMessage(err, "Failed to create credential.")),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: CredentialUpdate }) =>
      api.credentials.update(id, body),
    onSuccess: () => {
      setFormState(null)
      setSubmitError(null)
      void qc.invalidateQueries({ queryKey: ["credentials"] })
    },
    onError: (err) =>
      setSubmitError(apiErrorMessage(err, "Failed to update credential.")),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.credentials.remove(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["credentials"] })
    },
  })

  const testMutation = useMutation({
    mutationFn: (id: number) => api.credentials.test(id),
    onSuccess: (result, id) => {
      setTestResults((prev) => ({ ...prev, [id]: result }))
    },
    onError: (err, id) => {
      setTestResults((prev) => ({
        ...prev,
        [id]: {
          ok: false,
          error: apiErrorMessage(err, "Request failed."),
        },
      }))
    },
  })

  const providers = providersQuery.data ?? []
  const credentials = credentialsQuery.data ?? []

  const initialForm: FormState = useMemo(() => {
    if (formState?.mode === "edit") return formState.initial
    return EMPTY_FORM
  }, [formState])

  const openCreate = () => {
    setSubmitError(null)
    setFormState({ mode: "create" })
  }

  const openEdit = (c: Credential) => {
    setSubmitError(null)
    setFormState({
      mode: "edit",
      id: c.id,
      initial: {
        provider: c.provider,
        label: c.label,
        api_base: c.api_base,
        api_key: "",
        api_secret: "",
      },
    })
  }

  const handleSubmit = (state: FormState) => {
    if (formState?.mode === "create") {
      createMutation.mutate({
        provider: state.provider,
        label: state.label,
        api_base: state.api_base,
        api_key: state.api_key,
        api_secret: state.api_secret || null,
      })
    } else if (formState?.mode === "edit") {
      const body: CredentialUpdate = {
        label: state.label,
        api_base: state.api_base,
      }
      if (state.api_key) body.api_key = state.api_key
      if (state.api_secret) body.api_secret = state.api_secret
      updateMutation.mutate({ id: formState.id, body })
    }
  }

  const handleDelete = (c: Credential) => {
    const ok = window.confirm(
      `Delete credential "${c.label}" for ${c.provider}? The stored key is wiped — you will have to re-enter it to migrate.`,
    )
    if (!ok) return
    deleteMutation.mutate(c.id)
  }

  const submitting = createMutation.isPending || updateMutation.isPending
  const listLoadError: unknown = credentialsQuery.error
  const providersLoadError: unknown = providersQuery.error

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">Registrar credentials</h2>
          <p className="text-sm text-muted-foreground">
            API keys for each registrar account. Stored encrypted at rest; the UI only ever shows a masked hint.
          </p>
        </div>
        {!formState && (
          <Button onClick={openCreate}>
            <Plus />
            Add credential
          </Button>
        )}
      </div>

      {providersLoadError != null && (
        <Card className="border-destructive/40">
          <CardContent className="py-4 text-sm text-destructive">
            Could not load the provider list: {apiErrorMessage(providersLoadError, "unknown error")}
          </CardContent>
        </Card>
      )}

      {formState && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <KeyRound className="size-5" />
              {formState.mode === "create" ? "New credential" : "Update credential"}
            </CardTitle>
            <CardDescription>
              Plaintext keys are sent once and immediately encrypted server-side. They are never returned.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <CredentialForm
              providers={providers}
              initial={initialForm}
              editingId={formState.mode === "edit" ? formState.id : null}
              onSubmit={handleSubmit}
              onCancel={() => {
                setFormState(null)
                setSubmitError(null)
              }}
              submitting={submitting}
              submitError={submitError}
            />
          </CardContent>
        </Card>
      )}

      {credentialsQuery.isLoading ? (
        <Card>
          <CardContent className="py-6 text-sm text-muted-foreground">
            Loading credentials…
          </CardContent>
        </Card>
      ) : listLoadError != null ? (
        <Card className="border-destructive/40">
          <CardContent className="py-4 text-sm text-destructive">
            Could not load credentials: {apiErrorMessage(listLoadError, "unknown error")}
          </CardContent>
        </Card>
      ) : credentials.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center">
            <p className="text-sm text-muted-foreground">
              No credentials configured yet. Add one to enable migrations.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {credentials.map((c) => (
            <CredentialRow
              key={c.id}
              credential={c}
              onEdit={() => openEdit(c)}
              onTest={() => testMutation.mutate(c.id)}
              onDelete={() => handleDelete(c)}
              testResult={testResults[c.id]}
              testing={testMutation.isPending && testMutation.variables === c.id}
              deleting={
                deleteMutation.isPending && deleteMutation.variables === c.id
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}
