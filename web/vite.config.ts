import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api/dashboard': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/api/documents': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/api/settings': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
