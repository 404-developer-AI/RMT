import { useQueryClient } from "@tanstack/react-query"
import { Activity, Database, KeyRound, RefreshCw, ShieldAlert } from "lucide-react"
import { Link } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useCredentials } from "@/hooks/useCredentials"
import { useHealthz, useReadyz } from "@/hooks/useHealth"

function StatusBadge({
  ok,
  loading,
  error,
  okLabel,
  downLabel,
}: {
  ok: boolean
  loading: boolean
  error: boolean
  okLabel: string
  downLabel: string
}) {
  if (error) return <Badge variant="destructive">Unreachable</Badge>
  if (loading) return <Badge variant="outline">Checking…</Badge>
  return ok ? (
    <Badge variant="success">{okLabel}</Badge>
  ) : (
    <Badge variant="destructive">{downLabel}</Badge>
  )
}

function formatTime(ts: number | undefined) {
  if (!ts) return "—"
  return new Date(ts).toLocaleTimeString()
}

function CredentialGate() {
  const credentials = useCredentials()
  if (credentials.isLoading) return null
  if (credentials.isError) return null
  const count = credentials.data?.length ?? 0

  if (count === 0) {
    return (
      <Card className="border-amber-500/40 bg-amber-500/5">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldAlert className="size-5 text-amber-600 dark:text-amber-400" />
            No registrar credentials configured
          </CardTitle>
          <CardDescription>
            Migrations are blocked until at least a source and a destination credential are stored.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild>
            <Link to="/settings">
              <KeyRound />
              Configure credentials
            </Link>
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="size-5" />
            Registrar credentials
          </CardTitle>
          <Badge variant="outline">{count} configured</Badge>
        </div>
        <CardDescription>
          Rotate or add credentials from the settings page. Secrets are encrypted at rest.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button variant="outline" asChild>
          <Link to="/settings">Manage credentials</Link>
        </Button>
      </CardContent>
    </Card>
  )
}

export default function Dashboard() {
  const healthz = useHealthz()
  const readyz = useReadyz()
  const qc = useQueryClient()

  const apiOk = healthz.isSuccess && healthz.data.status === "ok"
  const dbOk = readyz.isSuccess && readyz.data.checks.database === "ok"

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["healthz"] })
    void qc.invalidateQueries({ queryKey: ["readyz"] })
    void qc.invalidateQueries({ queryKey: ["credentials"] })
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">System health</h2>
          <p className="text-sm text-muted-foreground">
            Live status of the backend and its database. Auto-refreshes every 5 seconds.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refresh}>
          <RefreshCw />
          Refresh
        </Button>
      </div>

      <CredentialGate />

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <Activity className="size-5" />
                API service
              </CardTitle>
              <StatusBadge
                ok={apiOk}
                loading={healthz.isLoading}
                error={!!healthz.error}
                okLabel="Online"
                downLabel="Down"
              />
            </div>
            <CardDescription>
              FastAPI backend reachable at <code className="font-mono text-xs">/api/healthz</code>
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-1 text-sm text-muted-foreground">
            <div>
              Last checked:{" "}
              <span className="font-mono text-foreground">
                {formatTime(healthz.dataUpdatedAt)}
              </span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <Database className="size-5" />
                Database
              </CardTitle>
              <StatusBadge
                ok={dbOk}
                loading={readyz.isLoading}
                error={!!readyz.error}
                okLabel="Connected"
                downLabel="Down"
              />
            </div>
            <CardDescription>
              PostgreSQL reachable via <code className="font-mono text-xs">SELECT 1</code> probe
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-1 text-sm text-muted-foreground">
            <div>
              Reported by:{" "}
              <span className="font-mono text-foreground">/api/readyz</span>
            </div>
            <div>
              Last checked:{" "}
              <span className="font-mono text-foreground">
                {formatTime(readyz.dataUpdatedAt)}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
