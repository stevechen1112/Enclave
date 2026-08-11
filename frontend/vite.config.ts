import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const pwaBuildId = process.env.VITE_PWA_BUILD_ID ?? Date.now().toString(36)

export default defineConfig({
  define: {
    __PWA_BUILD_ID__: JSON.stringify(pwaBuildId),
  },
  plugins: [react(), tailwindcss()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8005',
        changeOrigin: true,
      },
    },
  },
})
