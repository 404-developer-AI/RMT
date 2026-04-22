import { Moon, Sun } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useTheme } from "@/hooks/useTheme"

export function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const nextLabel = theme === "dark" ? "Switch to light mode" : "Switch to dark mode"

  return (
    <Button
      variant="outline"
      size="icon"
      onClick={toggle}
      aria-label={nextLabel}
      title={nextLabel}
    >
      <Sun className="size-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
      <Moon className="absolute size-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
      <span className="sr-only">{nextLabel}</span>
    </Button>
  )
}
