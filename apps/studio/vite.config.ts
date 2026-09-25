import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The Studio gateway is a separate FastAPI process. In development Vite
// proxies `/gw` to it so the browser has same-origin calls; set
// VITE_GATEWAY_URL to call a deployed gateway directly.
const GATEWAY = process.env.VERITX_GATEWAY_URL ?? 'http://localhost:8123';
const proxy = {
  '/gw': {
    target: GATEWAY,
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/gw/, ''),
  },
};

const entry = (name: string): string =>
  fileURLToPath(new URL(`./${name}`, import.meta.url));

export default defineConfig({
  plugins: [react()],
  server: { proxy },
  preview: { proxy },
  build: {
    outDir: 'dist',
    sourcemap: false,
    // Two surfaces ship from this app: the console (index.html) and the
    // marketing landing page (landing.html).
    rollupOptions: {
      input: {
        main: entry('index.html'),
        landing: entry('landing.html'),
      },
    },
  },
});
