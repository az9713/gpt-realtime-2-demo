import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/v1': {
        target: process.env.VITE_CORE_URL ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      '/voice': {
        target: process.env.VITE_EDGE_URL ?? 'http://localhost:8080',
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
