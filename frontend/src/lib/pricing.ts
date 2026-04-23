// Combell does not expose a pricing endpoint — V1 ships a hardcoded table
// so the confirm dialog can surface the expected annual cost. Update here
// when renewal prices change; the operator sees an "approximate" label in
// the UI so we never pretend this is authoritative.

export type PriceEntry = { tld: string; eurPerYear: number }

export const COMBELL_PRICING: PriceEntry[] = [
  { tld: "be", eurPerYear: 19 },
  { tld: "com", eurPerYear: 15 },
  { tld: "net", eurPerYear: 15 },
  { tld: "org", eurPerYear: 15 },
  { tld: "eu", eurPerYear: 15 },
  { tld: "nl", eurPerYear: 15 },
]

export function priceFor(domain: string): PriceEntry | null {
  const tld = domain.toLowerCase().split(".").pop()
  return COMBELL_PRICING.find((p) => p.tld === tld) ?? null
}
