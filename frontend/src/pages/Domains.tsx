import { useMutation, useQuery } from "@tanstack/react-query"
import {
  CheckCircle2,
  Lock,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
  Unlock,
} from "lucide-react"
import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"

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
import { useCredentials } from "@/hooks/useCredentials"
import {
  ApiError,
  api,
  type DomainSummary,
  type MigrationTypeInfo,
} from "@/lib/api"

function isEligible(domain: DomainSummary, nowMs: number): boolean {
  if (domain.locked) return false
  if (domain.privacy) return false
  if (!domain.expires_at) return true
  const days = (new Date(domain.expires_at).getTime() - nowMs) / 86400000
  return days > 15
}

function ExpiryCell({ iso, nowMs }: { iso: string | null; nowMs: number }) {
  if (!iso) return <span className="text-muted-foreground">—</span>
  const d = new Date(iso)
  const days = Math.round((d.getTime() - nowMs) / 86400000)
  const warn = days < 30
  return (
    <span className={warn ? "text-amber-600 dark:text-amber-400" : undefined}>
      {d.toISOString().slice(0, 10)} <span className="text-muted-foreground">({days}d)</span>
    </span>
  )
}

export default function Domains() {
  const navigate = useNavigate()
  const credentials = useCredentials()
  const [filter, setFilter] = useState("")
  const [useMock, setUseMock] = useState(false)

  const typesQuery = useQuery({
    queryKey: ["migration-types"],
    queryFn: api.migrationTypes,
  })

  const migrationType = typesQuery.data?.[0]?.key

  const domainsQuery = useQuery({
    queryKey: ["domains", migrationType, useMock],
    queryFn: () =>
      api.domains.list({ migrationType, mock: useMock }),
    enabled: Boolean(migrationType) && (credentials.data?.length ?? 0) > 0,
    retry: 0,
  })

  const startMigration = useMutation({
    mutationFn: async ({ domain, migrationTypeKey }: { domain: string; migrationTypeKey: string }) => {
      const plan = await api.migrations.create({
        domain,
        migration_type: migrationTypeKey,
      })
      return plan
    },
    onSuccess: (plan) => {
      navigate(`/migrations/${plan.id}`)
    },
  })

  const rows = useMemo(() => {
    const items = domainsQuery.data?.domains ?? []
    const needle = filter.trim().toLowerCase()
    if (!needle) return items
    return items.filter((d) => d.name.toLowerCase().includes(needle))
  }, [domainsQuery.data, filter])

  const nowMs = domainsQuery.dataUpdatedAt || 0

  if (credentials.isLoading) {
    return <Card><CardContent className="py-6 text-sm text-muted-foreground">Loading…</CardContent></Card>
  }

  if ((credentials.data?.length ?? 0) === 0) {
    return (
      <Card className="border-amber-500/40 bg-amber-500/5">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldAlert className="size-5 text-amber-600 dark:text-amber-400" />
            Configure registrar credentials first
          </CardTitle>
          <CardDescription>
            No GoDaddy or Combell credentials are stored yet. The domain list reads directly from the source registrar.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => navigate("/settings")}>Go to Settings</Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">Domains at the source registrar</h2>
          <p className="text-sm text-muted-foreground">
            Pick a domain to start a migration. Rows show lock, privacy, expiry and transfer-eligibility.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={useMock}
              onChange={(e) => setUseMock(e.target.checked)}
            />
            Use mock data
          </label>
          <Button
            variant="outline"
            size="sm"
            onClick={() => domainsQuery.refetch()}
            disabled={domainsQuery.isFetching}
          >
            <RefreshCw className={domainsQuery.isFetching ? "animate-spin" : undefined} />
            Refresh
          </Button>
        </div>
      </div>

      <MigrationTypePill types={typesQuery.data ?? []} />

      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by domain name…"
            className="pl-9"
          />
        </div>
      </div>

      {domainsQuery.error ? (
        <Card className="border-destructive/40">
          <CardContent className="py-4 text-sm text-destructive">
            Could not load domains: {formatError(domainsQuery.error)}
          </CardContent>
        </Card>
      ) : domainsQuery.isLoading ? (
        <Card><CardContent className="py-6 text-sm text-muted-foreground">Loading domains from the source registrar…</CardContent></Card>
      ) : rows.length === 0 ? (
        <Card><CardContent className="py-6 text-sm text-muted-foreground">No domains match the current filter.</CardContent></Card>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left">Domain</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-left">Lock</th>
                <th className="px-4 py-2 text-left">Privacy</th>
                <th className="px-4 py-2 text-left">Expires</th>
                <th className="px-4 py-2 text-left">Eligible</th>
                <th className="px-4 py-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => {
                const eligible = isEligible(d, nowMs)
                return (
                  <tr key={d.name} className="border-t">
                    <td className="px-4 py-2 font-mono">{d.name}</td>
                    <td className="px-4 py-2">
                      <Badge variant="outline">{d.status}</Badge>
                    </td>
                    <td className="px-4 py-2">
                      {d.locked ? (
                        <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400">
                          <Lock className="size-4" /> locked
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-muted-foreground">
                          <Unlock className="size-4" /> unlocked
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      {d.privacy ? (
                        <Badge variant="outline" className="text-amber-600 dark:text-amber-400">on</Badge>
                      ) : (
                        <Badge variant="outline">off</Badge>
                      )}
                    </td>
                    <td className="px-4 py-2"><ExpiryCell iso={d.expires_at} nowMs={nowMs} /></td>
                    <td className="px-4 py-2">
                      {eligible ? (
                        <Badge variant="success"><CheckCircle2 /> ready</Badge>
                      ) : (
                        <Badge variant="destructive">blocked</Badge>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!migrationType || startMigration.isPending}
                        onClick={() =>
                          migrationType &&
                          startMigration.mutate({
                            domain: d.name,
                            migrationTypeKey: migrationType,
                          })
                        }
                      >
                        <Sparkles />
                        Migrate
                      </Button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function MigrationTypePill({ types }: { types: MigrationTypeInfo[] }) {
  if (types.length === 0) return null
  const t = types[0]
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 text-xs">
      <span className="uppercase tracking-wide text-muted-foreground">Migration</span>
      <Badge variant="outline" className="font-mono">{t.label}</Badge>
      <span className="text-muted-foreground">{t.description}</span>
    </div>
  )
}

function formatError(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return "unknown error"
}
