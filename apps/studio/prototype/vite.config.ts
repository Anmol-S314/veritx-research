import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
// Read-only proxy to the repository gateway. Point VERITX_GATEWAY at another host to override.
const GATEWAY = process.env.VERITX_GATEWAY ?? 'http://127.0.0.1:8099';
const proxy = { '/gw': { target: GATEWAY, changeOrigin: true, rewrite: (path: string) => path.replace(/^\/gw/, '') } };
export default defineConfig({
  root: fileURLToPath(new URL('.', import.meta.url)),
  publicDir: fileURLToPath(new URL('./public', import.meta.url)),
  plugins: [react()],
  server: {
    proxy,
    // Native build trees and Python environments can contain hundreds of thousands
    // of files. They never participate in frontend hot reload.
    watch: { ignored: ['**/.desktop-build/**', '**/.desktop-venv/**', '**/src-tauri/**'] },
  },
  preview: { proxy },
  build: { outDir: 'dist', emptyOutDir: true },
});
