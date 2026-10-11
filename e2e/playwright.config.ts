import { defineConfig } from '@playwright/test';

// Chạy giao diện thật (trình duyệt) qua toàn bộ chuỗi: Vite preview -> ASP.NET gateway -> ai-service -> PostgreSQL.
// Dịch vụ do CI (hoặc bạn) khởi động trước; xem .github/workflows/ci.yml và e2e/README.md.
export default defineConfig({
  testDir: './tests',
  timeout: 90_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
  },
});
