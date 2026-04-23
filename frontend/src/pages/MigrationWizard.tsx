import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ClipboardCheck,
  Download,
  Info,
  Loader2,
  Play,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react"
import { useMemo, useState } from "react"
import { Link, useParams } from "react-router-dom"

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
import { useMigration } from "@/hooks/useMigration"
import {
  ApiError,
  api,
  type MigrationPlan,
  type MigrationTypeInfo,
  type PreflightReport,
  type PreflightResult,
} from "@/lib/api"
import { priceFor } from "@/lib/pricing"
import { cn } from "@/lib/utils"

type StepKey = "check" | "confirm" | "status"

function StateBadge({ state }: { state: MigrationPlan["state"] }) {
  const variant: Parameters<typeof Badge>[0]["variant"] =
    state === "COMPLETED"
      ? "success"
      : state === "FAILED" || state === "CANCELLED"
        ? "destructive"
        : "outline"
  return <Badge variant={variant}>{state}</Badge>
}

function formatError(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return "unknown error"
}

function authCodeHint(
  types: MigrationTypeInfo[] | undefined,
  migrationType: string,
  domain: string,
): string {
  const t = types?.find((x) => x.key === migrationType)
  if (!t) return ""
  const tld = domain.toLowerCase().split(".").pop() ?? ""
  return t.auth_code_hints[tld] ?? t.auth_code_hints[""] ?? ""
}

function maskBeAuthCode(raw: string): string {
  const digits = raw.replace(/\D/g, "").slice(0, 15)
  const groups: string[] = []
  for (let i = 0; i < digits.length; i += 3) groups.push(digits.slice(i, i + 3))
  return groups.join("-")
}

function PreflightList({ report }: { report: PreflightReport }) {
  const order: PreflightResult["severity"][] = ["blocking", "warning"]
  const sorted = [...report.results].sort(
    (a, b) => order.indexOf(a.severity) - order.indexOf(b.severity),
  )
  return (
    <div className="space-y-2">
      {sorted.map((r) => (
        <div
          key={r.key}
          className={cn(
            "flex items-start gap-2 rounded-md border px-3 py-2 text-sm",
            r.ok
              ? "border-emerald-500/30 bg-emerald-500/5"
              : r.severity === "blocking"
                ? "border-destructive/40 bg-destructive/5"
                : "border-amber-500/40 bg-amber-500/5",
          )}
        >
          {r.ok ? (
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
          ) : r.severity === "blocking" ? (
            <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" />
          ) : (
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
          )}
          <div>
            <div className="font-medium">{r.key}</div>
            <div className="text-muted-foreground">{r.message}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

export default function MigrationWizard() {
  const { id } = useParams<{ id: string }>()
  const planId = id ? Number(id) : undefined
  const qc = useQueryClient()

  const planQuery = useMigration(planId)
  const plan = planQuery.data

  const typesQuery = useQuery({
    queryKey: ["migration-types"],
    queryFn: api.migrationTypes,
  })

  const [useMock, setUseMock] = useState(false)
  const [authCode, setAuthCode] = useState("")
  const [typedDomain, setTypedDomain] = useState("")
  const [error, setError] = useState<string | null>(null)

  const previewMutation = useMutation({
    mutationFn: () => api.migrations.preview(planId!, { mock: useMock }),
    onSuccess: () => {
      setError(null)
      void qc.invalidateQueries({ queryKey: ["migration", planId] })
    },
    onError: (err) => setError(formatError(err)),
  })

  const confirmMutation = useMutation({
    mutationFn: () =>
      api.migrations.confirm(
        planId!,
        { auth_code: authCode.trim(), typed_domain: typedDomain.trim() },
        { mock: useMock },
      ),
    onSuccess: () => {
      setError(null)
      setAuthCode("")
      setTypedDomain("")
      void qc.invalidateQueries({ queryKey: ["migration", planId] })
    },
    onError: (err) => setError(formatError(err)),
  })

  const pollMutation = useMutation({
    mutationFn: () => api.migrations.poll(planId!, { mock: useMock }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["migration", planId] })
    },
    onError: (err) => setError(formatError(err)),
  })

  const cancelMutation = useMutation({
    mutationFn: () => api.migrations.cancel(planId!, "Cancelled from the wizard."),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["migration", planId] })
    },
  })

  const hint = useMemo(
    () =>
      plan ? authCodeHint(typesQuery.data, plan.migration_type, plan.domain) : "",
    [typesQuery.data, plan],
  )

  const isBe = plan?.domain.toLowerCase().endsWith(".be") ?? false

  const currentStep: StepKey = useMemo(() => {
    if (!plan) return "check"
    if (plan.state === "DRAFT") return "check"
    if (plan.state === "PREVIEWED") return "confirm"
    return "status"
  }, [plan])

  if (!planId || Number.isNaN(planId)) {
    return (
      <Card className="border-destructive/40">
        <CardContent className="py-4 text-sm text-destructive">Invalid migration id.</CardContent>
      </Card>
    )
  }

  if (planQuery.isLoading || !plan) {
    return <Card><CardContent className="py-6 text-sm text-muted-foreground">Loading migration plan…</CardContent></Card>
  }

  const preflight = plan.diff?.preflight
  const diffSummary = plan.diff?.zone_diff
  const price = priceFor(plan.domain)

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold">Migrate</h2>
            <code className="font-mono text-sm">{plan.domain}</code>
            <StateBadge state={plan.state} />
          </div>
          <p className="text-sm text-muted-foreground">
            {plan.migration_type} · plan #{plan.id} · correlation {plan.correlation_id}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={useMock}
              onChange={(e) => setUseMock(e.target.checked)}
              disabled={plan.state !== "DRAFT" && plan.state !== "PREVIEWED"}
            />
            Mock mode
          </label>
          <Button variant="outline" size="sm" asChild>
            <Link to="/migrations">All migrations</Link>
          </Button>
        </div>
      </div>

      <StepIndicator step={currentStep} />

      {error && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="flex items-start gap-2 py-3 text-sm text-destructive">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <span>{error}</span>
          </CardContent>
        </Card>
      )}

      {/* STEP 1 — check domain + pre-flight + preview diff */}
      {(currentStep === "check" || preflight) && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="size-5" />
              Pre-flight
            </CardTitle>
            <CardDescription>
              Reads the current state from the source registrar, writes a snapshot backup, and checks if a transfer can start cleanly.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Button
              onClick={() => previewMutation.mutate()}
              disabled={previewMutation.isPending}
            >
              {previewMutation.isPending ? (
                <Loader2 className="animate-spin" />
              ) : (
                <RefreshCw />
              )}
              {preflight ? "Re-check" : "Check domein"}
            </Button>

            {preflight && <PreflightList report={preflight} />}

            {diffSummary && (
              <div className="grid gap-2 rounded-md border bg-muted/30 p-3 text-xs md:grid-cols-4">
                <DiffStat label="To create" value={diffSummary.to_create.length} />
                <DiffStat label="To update" value={diffSummary.to_update.length} />
                <DiffStat label="To delete" value={diffSummary.to_delete.length} />
                <DiffStat label="Skipped" value={diffSummary.skipped.length} />
              </div>
            )}

            {plan.diff?.snapshot_id && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Download className="size-3" />
                <a
                  href={api.migrations.snapshotDownloadUrl(plan.id)}
                  target="_blank"
                  rel="noreferrer"
                  className="underline"
                >
                  Download snapshot (JSON)
                </a>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* STEP 2 — auth code + typed confirmation */}
      {currentStep === "confirm" && preflight?.passed && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ClipboardCheck className="size-5" />
              Confirm transfer
            </CardTitle>
            <CardDescription>
              {hint || "Paste the auth code from the source registrar."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="auth-code">Auth code</Label>
              <Input
                id="auth-code"
                value={authCode}
                onChange={(e) =>
                  setAuthCode(isBe ? maskBeAuthCode(e.target.value) : e.target.value)
                }
                placeholder={isBe ? "123-456-789-012-345" : "Auth code"}
                autoComplete="off"
                className="font-mono"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="typed-domain">
                Type the domain to confirm (<code>{plan.domain}</code>)
              </Label>
              <Input
                id="typed-domain"
                value={typedDomain}
                onChange={(e) => setTypedDomain(e.target.value)}
                placeholder={plan.domain}
                autoComplete="off"
              />
            </div>

            {price && (
              <div className="flex items-start gap-2 rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
                <Info className="mt-0.5 size-3 shrink-0" />
                <span>
                  Combell renewal for <code>.{price.tld}</code> is approximately €{price.eurPerYear}/year.
                  A transfer typically includes one year's renewal. Final pricing confirmed on the Combell invoice.
                </span>
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              <Button
                onClick={() => confirmMutation.mutate()}
                disabled={
                  confirmMutation.isPending ||
                  !authCode.trim() ||
                  typedDomain.trim().toLowerCase() !== plan.domain.toLowerCase()
                }
              >
                {confirmMutation.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <ArrowRight />
                )}
                Submit transfer
              </Button>
              <Button
                variant="outline"
                onClick={() => cancelMutation.mutate()}
                disabled={cancelMutation.isPending}
              >
                Cancel plan
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* STEP 3 — live status */}
      {(plan.state === "AWAITING_TRANSFER" ||
        plan.state === "POPULATING_DNS" ||
        plan.state === "COMPLETED" ||
        plan.state === "FAILED" ||
        plan.state === "CANCELLED") && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Play className="size-5" />
              Status
            </CardTitle>
            <CardDescription>
              {plan.state === "AWAITING_TRANSFER"
                ? "Waiting for Combell's provisioning job. ICANN transfers can take 5–7 days; .be transfers typically minutes."
                : plan.state === "POPULATING_DNS"
                  ? "Transfer accepted. Bulk-loading DNS records at Combell."
                  : plan.state === "COMPLETED"
                    ? "Migration complete. Zone verified against the snapshot."
                    : plan.state === "FAILED"
                      ? "Migration failed — see the message below and the audit log for details."
                      : "Migration was cancelled."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <dl className="grid gap-2 text-sm md:grid-cols-2">
              <StatusRow label="State"><StateBadge state={plan.state} /></StatusRow>
              <StatusRow label="Provisioning job">
                <code className="font-mono text-xs">{plan.provisioning_job_id ?? "—"}</code>
              </StatusRow>
              <StatusRow label="Confirmed at">{plan.confirmed_at ?? "—"}</StatusRow>
              <StatusRow label="Last polled">{plan.last_polled_at ?? "—"}</StatusRow>
              <StatusRow label="Completed">{plan.completed_at ?? "—"}</StatusRow>
            </dl>

            {plan.error_message && (
              <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
                {plan.error_message}
              </div>
            )}

            {plan.state === "AWAITING_TRANSFER" || plan.state === "POPULATING_DNS" ? (
              <Button
                variant="outline"
                onClick={() => pollMutation.mutate()}
                disabled={pollMutation.isPending}
              >
                {pollMutation.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                Poll now
              </Button>
            ) : null}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function StepIndicator({ step }: { step: StepKey }) {
  const steps: { key: StepKey; label: string }[] = [
    { key: "check", label: "Check" },
    { key: "confirm", label: "Confirm" },
    { key: "status", label: "Status" },
  ]
  const index = steps.findIndex((s) => s.key === step)
  return (
    <div className="flex items-center gap-2 text-xs">
      {steps.map((s, i) => (
        <div key={s.key} className="flex items-center gap-2">
          <span
            className={cn(
              "inline-flex items-center gap-2 rounded-full border px-3 py-1",
              i === index
                ? "border-primary bg-primary/10 font-medium text-primary"
                : i < index
                  ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                  : "border-muted bg-muted/30 text-muted-foreground",
            )}
          >
            {i + 1}. {s.label}
          </span>
          {i < steps.length - 1 && <ArrowRight className="size-3 text-muted-foreground" />}
        </div>
      ))}
    </div>
  )
}

function DiffStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="font-mono text-sm">{value}</span>
    </div>
  )
}

function StatusRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <dt className="w-40 text-xs uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}
