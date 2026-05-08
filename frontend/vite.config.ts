import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      // Core HTTP API proxy. The frontend container reaches the core via
      // the docker network, not via the published host port — VITE_CORE_URL
      // is read at server startup and resolves to e.g. http://core:8000.
      '/v1': {
        target: process.env.VITE_CORE_URL ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      // NOTE: no '/voice' proxy. The browser connects DIRECTLY to the edge
      // via VITE_EDGE_URL for the WebSocket (see TalkPage.tsx). Adding a
      // '/voice' prefix rule here would ALSO capture client-side routes
      // that happen to start with /voice — e.g. /voicemails — and proxy
      // them away from React Router (causing a 500 from ECONNREFUSED).
    },
  },
});
