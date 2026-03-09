import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  base: '/ui/',
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    port: 5173,
    proxy: {
      '/v1': 'http://127.0.0.1:8100',
      '/ws': {
        target: 'ws://127.0.0.1:8100',
        ws: true,
      }
    }
  }
})
