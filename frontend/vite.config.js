import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwind from '@tailwindcss/vite'
import mockApi from './mock/plugin.js'

// The build output is served directly by FastAPI from backend/app/static.
export default defineConfig({
  plugins: [react(), tailwind(), mockApi()],
  build: {
    outDir: '../backend/app/static',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    // The dev server may be reached through a proxied preview hostname.
    allowedHosts: true,
    proxy: process.env.ZONEAPP_MOCK
      ? undefined
      : { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
})
