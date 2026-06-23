import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@client': fileURLToPath(new URL('./client/src', import.meta.url)) },
  },
  test: {
    name: 'client',
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.{ts,tsx}'],
    environmentOptions: { jsdom: { url: 'http://localhost:3000' } },
  },
});
