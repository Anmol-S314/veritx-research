import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The Studio gateway is a separate FastAPI process. In development Vite
// proxies `/gw` to it so the browser has same-origin calls; set
// VITE_GATEWAY_URL to call a deployed gateway directly.
const GATEWAY = process.env.VERITX_GATEWAY_URL ?? 'http://localhost:8123';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/gw': {
        target: GATEWAY,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/gw/, ''),
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
