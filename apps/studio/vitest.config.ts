import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Contract tests for server-truth rendering (product-truth suite).
// No engine, no network: fixtures only.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    // The fork pool repeatedly failed to resolve generated /tmp source-module
    // paths in the isolated runner; the thread pool passes the full suite.
    pool: 'threads',
    include: ['src/**/*.contract.test.{ts,tsx}'],
  },
});
