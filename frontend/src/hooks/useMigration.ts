import { useQuery } from "@tanstack/react-query"

import { api, type MigrationPlan } from "@/lib/api"

function tickIntervalFor(state: MigrationPlan["state"] | undefined): number | false {
  // While the transfer is being watched we poll the API once a minute.
  // The backend does its own long-interval polling against Combell; this
  // just keeps the UI in sync without slamming either side.
  if (!state) return false
  if (state === "AWAITING_TRANSFER" || state === "POPULATING_DNS") return 60_000
  return false
}

export function useMigration(id: number | undefined) {
  return useQuery({
    queryKey: ["migration", id],
    queryFn: () => api.migrations.get(id!),
    enabled: typeof id === "number" && Number.isFinite(id),
    refetchInterval: (query) => tickIntervalFor(query.state.data?.state),
  })
}

export function useMigrationList(limit = 50) {
  return useQuery({
    queryKey: ["migrations", { limit }],
    queryFn: () => api.migrations.list(limit),
  })
}
