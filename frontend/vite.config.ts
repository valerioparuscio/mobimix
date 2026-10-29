import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The browser only talks to the Vite dev server; /api is proxied to the FastAPI backend.
// Override the target with MOBIMIX_API_URL if the backend runs elsewhere.
const apiTarget = process.env.MOBIMIX_API_URL ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
    },
  },
})
