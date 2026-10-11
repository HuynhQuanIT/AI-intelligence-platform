import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// /api đi tới ASP.NET gateway (cổng 5000). `preview` dùng cùng proxy để chạy được bản build trong test e2e.
const proxy = { '/api': { target: 'http://localhost:5000', changeOrigin: true } };

export default defineConfig({
  plugins: [react()],
  server: { proxy },
  preview: { proxy },
});
