import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '^/api/v1/meetings/[^/]+/stream$': { target: 'ws://127.0.0.1:8002', ws: true, xfwd: true },
      '/api': 'http://127.0.0.1:8001',
    },
  },
})
