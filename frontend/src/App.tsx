import { useQueryClient } from "@tanstack/react-query"
import { Activity, Database, RefreshCw } from "lucide-react"

import { ThemeToggle } from "@/components/theme-toggle"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
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

export default function App() {
  const healthz = useHealthz()
  const readyz = useReadyz()
  const qc = useQueryClient()

  const apiOk = healthz.isSuccess && healthz.data.status === "ok"
  const dbOk = readyz.isSuccess && readyz.data.checks.database === "ok"
  const version = healthz.data?.version ?? readyz.data?.version

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["healthz"] })
    void qc.invalidateQueries({ queryKey: ["readyz"] })
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">RMT</h1>
            <p className="text-sm text-muted-foreground">
              Registrar Migration Tool
            </p>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <Button variant="outline" size="sm" onClick={refresh}>
              <RefreshCw />
              Refresh
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-6 px-6 py-8">
        <div>
          <h2 className="text-lg font-semibold">System health</h2>
          <p className="text-sm text-muted-foreground">
            Live status of the backend and its database. Auto-refreshes every 5 seconds.
          </p>
        </div>

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
                Version:{" "}
                <span className="font-mono text-foreground">
                  {version ?? "—"}
                </span>
              </div>
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
      </main>
    </div>
  )
}
