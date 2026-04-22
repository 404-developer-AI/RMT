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

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json" },
  })
  // /readyz intentionally returns HTTP 503 with a structured body when the
  // database is unreachable — still parse and return it so the UI can react.
  if (!res.ok && res.status !== 503) {
    throw new Error(`${res.status} ${res.statusText}`)
  }
  return (await res.json()) as T
}

export const api = {
  healthz: () => fetchJson<HealthResponse>("/healthz"),
  readyz: () => fetchJson<ReadyzResponse>("/readyz"),
}
