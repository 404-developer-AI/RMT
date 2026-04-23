const API_BASE = "/api"

export type HealthResponse = {
  status: string
  version: string
}

export type ReadyzResponse = {
  status: string
  version: string
  checks: {
    database: string
    [key: string]: string
  }
}

export type ProviderInfo = {
  key: string
  adapter_installed: boolean
}

export type MigrationTypeInfo = {
  key: string
  label: string
  source_provider: string
  destination_provider: string
  description: string
  auth_code_hints: Record<string, string>
}

export type Credential = {
  id: number
  provider: string
  label: string
  api_base: string
  masked_hint: string
  has_api_secret: boolean
  created_at: string
  updated_at: string
}

export type CredentialCreate = {
  provider: string
  label: string
  api_base: string
  api_key: string
  api_secret?: string | null
}

export type CredentialUpdate = {
  label?: string
  api_base?: string
  api_key?: string
  api_secret?: string
}

export type TestConnectionResult = {
  ok: boolean
  error: string | null
}

export type DomainSummary = {
  name: string
  status: string
  expires_at: string | null
  locked: boolean | null
  privacy: boolean | null
}

export type DomainListResponse = {
  migration_type: string
  source_provider: string
  destination_provider: string
  domains: DomainSummary[]
}

export type DnsRecord = {
  type: string
  name: string
  data: string
  ttl: number
  priority: number | null
}

export type PreflightResult = {
  key: string
  severity: "blocking" | "warning"
  ok: boolean
  message: string
}

export type PreflightReport = {
  domain: string
  tld: string
  ruleset: string
  passed: boolean
  results: PreflightResult[]
}

export type ZoneDiff = {
  to_create: DnsRecord[]
  to_update: DnsRecord[]
  to_delete: DnsRecord[]
  skipped: DnsRecord[]
}

export type MigrationState =
  | "DRAFT"
  | "PREVIEWED"
  | "CONFIRMED"
  | "AWAITING_TRANSFER"
  | "POPULATING_DNS"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"

export type MigrationPlan = {
  id: number
  correlation_id: string
  domain: string
  migration_type: string
  state: MigrationState
  provisioning_job_id: string | null
  last_polled_at: string | null
  confirmed_at: string | null
  completed_at: string | null
  error_message: string | null
  diff: {
    preflight?: PreflightReport
    zone_diff?: ZoneDiff
    populated?: ZoneDiff
    verify?: ZoneDiff
    snapshot_id?: number
  } | null
  created_at: string
  updated_at: string
}

export type PreviewResponse = {
  plan: MigrationPlan
  snapshot: {
    id: number
    migration_plan_id: number
    correlation_id: string
    domain: string
    source_provider: string
    snapshot: Record<string, unknown>
    created_at: string
  }
  diff_summary: {
    to_create: number
    to_update: number
    to_delete: number
    skipped: number
  }
}

export type AuditEvent = {
  id: number
  ts: string
  correlation_id: string
  actor: string
  action: string
  target: Record<string, unknown>
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  result: string
  duration_ms: number | null
  registrar: string | null
}

export type AuditFilters = {
  domain?: string
  correlation_id?: string
  action_prefix?: string
  since?: string
  until?: string
  limit?: number
}

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown) {
    const message =
      typeof detail === "object" && detail !== null && "detail" in detail
        ? String((detail as { detail: unknown }).detail)
        : typeof detail === "string"
          ? detail
          : `HTTP ${status}`
    super(message)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(
  path: string,
  init: RequestInit & { allow503?: boolean } = {},
): Promise<T> {
  const { allow503, ...rest } = init
  const res = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: {
      Accept: "application/json",
      ...(rest.body ? { "Content-Type": "application/json" } : {}),
      ...(rest.headers ?? {}),
    },
  })
  if (res.status === 204) {
    return undefined as T
  }
  if (!res.ok && !(allow503 && res.status === 503)) {
    // Read text once, then try JSON.parse — Response body streams can only
    // be consumed once, so calling res.json() then res.text() as a fallback
    // throws "body stream already read".
    const text = await res.text()
    let detail: unknown = text
    try {
      detail = JSON.parse(text)
    } catch {
      // Not JSON — leave detail as the raw text.
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

export const api = {
  healthz: () => request<HealthResponse>("/healthz"),
  readyz: () => request<ReadyzResponse>("/readyz", { allow503: true }),

  providers: () => request<ProviderInfo[]>("/providers"),
  migrationTypes: () => request<MigrationTypeInfo[]>("/migration-types"),

  credentials: {
    list: () => request<Credential[]>("/credentials"),
    create: (body: CredentialCreate) =>
      request<Credential>("/credentials", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    update: (id: number, body: CredentialUpdate) =>
      request<Credential>(`/credentials/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    remove: (id: number) =>
      request<void>(`/credentials/${id}`, { method: "DELETE" }),
    test: (id: number) =>
      request<TestConnectionResult>(`/credentials/${id}/test`, {
        method: "POST",
      }),
  },

  domains: {
    list: (opts: { migrationType?: string; mock?: boolean } = {}) => {
      const params = new URLSearchParams()
      if (opts.migrationType) params.set("migration_type", opts.migrationType)
      if (opts.mock) params.set("mock", "true")
      const qs = params.toString() ? `?${params}` : ""
      return request<DomainListResponse>(`/domains${qs}`)
    },
  },

  migrations: {
    list: (limit = 50) => request<MigrationPlan[]>(`/migrations?limit=${limit}`),
    get: (id: number) => request<MigrationPlan>(`/migrations/${id}`),
    create: (body: { domain: string; migration_type: string }) =>
      request<MigrationPlan>("/migrations", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    preview: (id: number, opts: { mock?: boolean } = {}) => {
      const qs = opts.mock ? "?mock=true" : ""
      return request<PreviewResponse>(`/migrations/${id}/preview${qs}`, {
        method: "POST",
      })
    },
    confirm: (
      id: number,
      body: { auth_code: string; typed_domain: string },
      opts: { mock?: boolean } = {},
    ) => {
      const qs = opts.mock ? "?mock=true" : ""
      return request<MigrationPlan>(`/migrations/${id}/confirm${qs}`, {
        method: "POST",
        body: JSON.stringify(body),
      })
    },
    poll: (id: number, opts: { mock?: boolean } = {}) => {
      const qs = opts.mock ? "?mock=true" : ""
      return request<MigrationPlan>(`/migrations/${id}/poll${qs}`, {
        method: "POST",
      })
    },
    cancel: (id: number, reason?: string) =>
      request<MigrationPlan>(`/migrations/${id}/cancel`, {
        method: "POST",
        body: JSON.stringify({ reason: reason ?? null }),
      }),
    snapshot: (id: number) =>
      request<{
        id: number
        domain: string
        snapshot: Record<string, unknown>
        created_at: string
      }>(`/migrations/${id}/snapshot`),
    snapshotDownloadUrl: (id: number) => `${API_BASE}/migrations/${id}/snapshot`,
  },

  audit: {
    list: (filters: AuditFilters = {}) => {
      const params = new URLSearchParams()
      for (const [k, v] of Object.entries(filters)) {
        if (v !== undefined && v !== "") params.set(k, String(v))
      }
      const qs = params.toString() ? `?${params}` : ""
      return request<AuditEvent[]>(`/audit${qs}`)
    },
    exportUrl: (filters: AuditFilters = {}) => {
      const params = new URLSearchParams()
      for (const [k, v] of Object.entries(filters)) {
        if (v !== undefined && v !== "") params.set(k, String(v))
      }
      const qs = params.toString() ? `?${params}` : ""
      return `${API_BASE}/audit/export.csv${qs}`
    },
  },
}
