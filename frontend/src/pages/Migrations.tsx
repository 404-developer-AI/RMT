import { useQuery } from "@tanstack/react-query"
import { ArrowRight, History } from "lucide-react"
import { Link } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ApiError, api, type MigrationPlan } from "@/lib/api"

function StateBadge({ state }: { state: MigrationPlan["state"] }) {
  if (state === "COMPLETED") return <Badge variant="success">{state}</Badge>
  if (state === "FAILED" || state === "CANCELLED") return <Badge variant="destructive">{state}</Badge>
  return <Badge variant="outline">{state}</Badge>
}

export default function Migrations() {
  const query = useQuery({
    queryKey: ["migrations", { limit: 100 }],
    queryFn: () => api.migrations.list(100),
  })

  if (query.error) {
    const message = query.error instanceof ApiError ? query.error.message : "unknown error"
    return (
      <Card className="border-destructive/40">
        <CardContent className="py-4 text-sm text-destructive">
          Could not load migrations: {message}
        </CardContent>
      </Card>
    )
  }

  const rows = query.data ?? []

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">Migrations</h2>
          <p className="text-sm text-muted-foreground">
            Everything ever started — newest first. Click a row to open the wizard.
          </p>
        </div>
        <Button asChild>
          <Link to="/domains">
            Start a new migration <ArrowRight />
          </Link>
        </Button>
      </div>

      {rows.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <History className="size-5" />
              No migrations yet
            </CardTitle>
            <CardDescription>
              Pick a domain from the source-registrar list to kick off a plan.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left">Domain</th>
                <th className="px-4 py-2 text-left">Type</th>
                <th className="px-4 py-2 text-left">State</th>
                <th className="px-4 py-2 text-left">Created</th>
                <th className="px-4 py-2 text-left">Confirmed</th>
                <th className="px-4 py-2 text-right">Open</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id} className="border-t">
                  <td className="px-4 py-2 font-mono">{p.domain}</td>
                  <td className="px-4 py-2">
                    <Badge variant="outline" className="font-mono text-xs">{p.migration_type}</Badge>
                  </td>
                  <td className="px-4 py-2"><StateBadge state={p.state} /></td>
                  <td className="px-4 py-2 text-xs">{p.created_at.slice(0, 19)}</td>
                  <td className="px-4 py-2 text-xs">{p.confirmed_at?.slice(0, 19) ?? "—"}</td>
                  <td className="px-4 py-2 text-right">
                    <Button asChild variant="outline" size="sm">
                      <Link to={`/migrations/${p.id}`}>Open</Link>
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
