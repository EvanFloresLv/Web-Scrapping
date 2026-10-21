import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import { TanStackRouterVite } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Spec 0008 AC-1: proxy every reserved backend path to uvicorn on :8000.
// The list mirrors AC-10's reserved SPA fallthrough prefixes, so a path that
// works in dev also works in production.
const BACKEND = 'http://localhost:8000'

export default defineConfig({
  plugins: [
    TanStackRouterVite({ target: 'react', autoCodeSplitting: true }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: false },
      '/health': { target: BACKEND, changeOrigin: false },
      '/docs': { target: BACKEND, changeOrigin: false },
      '/redoc': { target: BACKEND, changeOrigin: false },
      '/openapi.json': { target: BACKEND, changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
