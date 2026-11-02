import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Browser requests stay same-origin (/api/*); Vite forwards them to FastAPI.
// Never put the user database or upstream API credentials into the frontend.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
             '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
})
