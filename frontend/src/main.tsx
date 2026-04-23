import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"

import App from "./App.tsx"
import AuditLog from "./pages/AuditLog.tsx"
import Dashboard from "./pages/Dashboard.tsx"
import Domains from "./pages/Domains.tsx"
import MigrationWizard from "./pages/MigrationWizard.tsx"
import Migrations from "./pages/Migrations.tsx"
import Settings from "./pages/Settings.tsx"
import "./index.css"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<App />}>
            <Route index element={<Dashboard />} />
            <Route path="domains" element={<Domains />} />
            <Route path="migrations" element={<Migrations />} />
            <Route path="migrations/:id" element={<MigrationWizard />} />
            <Route path="audit" element={<AuditLog />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
