import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true, // needed for the Live Practice WebSocket (/api/practice/stream)
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
