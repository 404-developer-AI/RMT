import { useQuery } from "@tanstack/react-query"
import { Download, Filter, RefreshCw } from "lucide-react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ApiError, api, type AuditEvent, type AuditFilters } from "@/lib/api"

function formatTs(iso: string): string {
  return iso.replace("T", " ").slice(0, 19)
}

function ResultBadge({ result }: { result: string }) {
  if (result === "success") return <Badge variant="success">{result}</Badge>
  if (result === "failure") return <Badge variant="destructive">{result}</Badge>
  return <Badge variant="outline">{result}</Badge>
}

export default function AuditLog() {
  const [filters, setFilters] = useState<AuditFilters>({ limit: 200 })
  const [row, setRow] = useState<AuditEvent | null>(null)

  const query = useQuery({
    queryKey: ["audit", filters],
    queryFn: () => api.audit.list(filters),
  })

  const setFilter = <K extends keyof AuditFilters>(key: K, value: AuditFilters[K]) =>
    setFilters((f) => ({ ...f, [key]: value || undefined }))

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">Audit log</h2>
          <p className="text-sm text-muted-foreground">
            Every state transition and registrar call. Click a row to see full before/after context.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => query.refetch()}>
            <RefreshCw />
            Refresh
          </Button>
          <Button variant="outline" size="sm" asChild>
            <a href={api.audit.exportUrl(filters)}>
              <Download />
              Export CSV
            </a>
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Filter className="size-5" />
            Filters
          </CardTitle>
          <CardDescription>Empty fields apply no filter.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="flt-domain">Domain</Label>
            <Input
              id="flt-domain"
              placeholder="example.com"
              value={filters.domain ?? ""}
              onChange={(e) => setFilter("domain", e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="flt-corr">Correlation id</Label>
            <Input
              id="flt-corr"
              placeholder="mig_…"
              value={filters.correlation_id ?? ""}
              onChange={(e) => setFilter("correlation_id", e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="flt-action">Action prefix</Label>
            <Input
              id="flt-action"
              placeholder="migration."
              value={filters.action_prefix ?? ""}
              onChange={(e) => setFilter("action_prefix", e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="flt-limit">Limit</Label>
            <Input
              id="flt-limit"
              type="number"
              min={1}
              max={1000}
              value={filters.limit ?? 200}
              onChange={(e) => setFilter("limit", Number(e.target.value))}
            />
          </div>
        </CardContent>
      </Card>

      {query.error ? (
        <Card className="border-destructive/40">
          <CardContent className="py-4 text-sm text-destructive">
            Could not load audit events: {formatErr(query.error)}
          </CardContent>
        </Card>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">Time</th>
                <th className="px-3 py-2 text-left">Action</th>
                <th className="px-3 py-2 text-left">Domain</th>
                <th className="px-3 py-2 text-left">Result</th>
                <th className="px-3 py-2 text-left">Registrar</th>
                <th className="px-3 py-2 text-right">ms</th>
              </tr>
            </thead>
            <tbody>
              {(query.data ?? []).map((e) => (
                <tr
                  key={e.id}
                  className="cursor-pointer border-t hover:bg-muted/40"
                  onClick={() => setRow(e)}
                >
                  <td className="px-3 py-2 font-mono text-xs">{formatTs(e.ts)}</td>
                  <td className="px-3 py-2 font-mono text-xs">{e.action}</td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {typeof e.target === "object" && e.target && "domain" in e.target
                      ? String((e.target as { domain?: unknown }).domain ?? "")
                      : ""}
                  </td>
                  <td className="px-3 py-2"><ResultBadge result={e.result} /></td>
                  <td className="px-3 py-2 text-xs">{e.registrar ?? "—"}</td>
                  <td className="px-3 py-2 text-right font-mono text-xs">{e.duration_ms ?? "—"}</td>
                </tr>
              ))}
              {(query.data?.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-sm text-muted-foreground">
                    No events match the current filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {row && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setRow(null)}
        >
          <div
            className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-lg border bg-background p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between">
              <div>
                <div className="text-xs text-muted-foreground">{formatTs(row.ts)}</div>
                <div className="font-mono text-sm">{row.action}</div>
              </div>
              <Button variant="outline" size="sm" onClick={() => setRow(null)}>
                Close
              </Button>
            </div>
            <pre className="mt-4 overflow-x-auto rounded bg-muted/40 p-3 text-xs">
              {JSON.stringify(row, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}

function formatErr(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return "unknown error"
}
