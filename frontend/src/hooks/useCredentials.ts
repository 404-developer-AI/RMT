import { useQuery } from "@tanstack/react-query"

import { api } from "@/lib/api"

export function useCredentials() {
  return useQuery({
    queryKey: ["credentials"],
    queryFn: api.credentials.list,
  })
}
