import './styles.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Placeholder bootstrap. M3 replaces this with the TanStack Router + Query setup.
const root = document.getElementById('root')
if (!root) {
  throw new Error('root element missing')
}

createRoot(root).render(
  <StrictMode>
    <main className="flex min-h-screen items-center justify-center bg-background text-foreground">
      <div className="text-center">
        <h1 className="text-2xl font-semibold">Scraping Platform Admin</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Scaffold ready. Milestone 3 wires the shell.
        </p>
      </div>
    </main>
  </StrictMode>,
)
