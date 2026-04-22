import { useQuery } from "@tanstack/react-query"

import { api } from "@/lib/api"

const REFRESH_MS = 5000

export function useHealthz() {
  return useQuery({
    queryKey: ["healthz"],
    queryFn: api.healthz,
    refetchInterval: REFRESH_MS,
    staleTime: 0,
  })
}

export function useReadyz() {
  return useQuery({
    queryKey: ["readyz"],
    queryFn: api.readyz,
    refetchInterval: REFRESH_MS,
    staleTime: 0,
  })
}
