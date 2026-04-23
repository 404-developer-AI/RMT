import { FileSearch, Globe, KeyRound, LayoutDashboard, ListChecks } from "lucide-react"
import { NavLink, Outlet } from "react-router-dom"

import { ThemeToggle } from "@/components/theme-toggle"
import { useHealthz, useReadyz } from "@/hooks/useHealth"
import { cn } from "@/lib/utils"

function NavItem({
  to,
  icon,
  label,
}: {
  to: string
  icon: React.ReactNode
  label: string
}) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        cn(
          "inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
          isActive
            ? "bg-accent text-accent-foreground"
            : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
        )
      }
    >
      {icon}
      {label}
    </NavLink>
  )
}

export default function App() {
  const healthz = useHealthz()
  const readyz = useReadyz()
  const version = healthz.data?.version ?? readyz.data?.version

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="flex items-baseline gap-2 text-xl font-semibold tracking-tight">
              RMT
              <span className="font-mono text-sm font-normal text-muted-foreground">
                {version ? `v${version}` : ""}
              </span>
            </h1>
            <p className="text-sm text-muted-foreground">
              Registrar Migration Tool
            </p>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
          </div>
        </div>
        <div className="mx-auto flex max-w-5xl items-center gap-1 px-6 pb-3">
          <NavItem to="/" icon={<LayoutDashboard className="size-4" />} label="Dashboard" />
          <NavItem to="/domains" icon={<Globe className="size-4" />} label="Domains" />
          <NavItem to="/migrations" icon={<ListChecks className="size-4" />} label="Migrations" />
          <NavItem to="/audit" icon={<FileSearch className="size-4" />} label="Audit" />
          <NavItem to="/settings" icon={<KeyRound className="size-4" />} label="Settings" />
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-6 px-6 py-8">
        <Outlet />
      </main>
    </div>
  )
}
