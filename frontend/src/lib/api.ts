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
}
