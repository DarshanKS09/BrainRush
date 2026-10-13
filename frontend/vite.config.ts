import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Local dev: `npm run dev` proxies /api to the backend so no CORS setup is
// needed. Production builds call VITE_API_URL directly (see .env.example).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
  },
});
