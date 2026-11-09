import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// In development the browser talks only to Vite; /api is forwarded to FastAPI.
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    // Local Apache site (deploy/apache/local.vedquant.com.conf) forwards this host to Vite.
    allowedHosts: ['local.vedquant.com'],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true, // live quotes WebSocket (/api/ws/quotes)
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
