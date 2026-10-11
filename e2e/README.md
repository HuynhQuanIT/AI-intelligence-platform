# Kiểm thử giao diện tự động (Playwright)

Chạy trình duyệt thật qua toàn bộ chuỗi `Vite preview -> ASP.NET gateway -> ai-service -> PostgreSQL`:
đăng ký + OTP, duyệt tài khoản, cookie refresh httpOnly, tải lại trang, đổi/quên mật khẩu, hạn mức,
nhóm và phân quyền tài liệu, admin đổi email/xóa tài khoản.

CI chạy tự động (job `e2e` trong `.github/workflows/ci.yml`). Chạy tay trên máy bạn:

1. `docker compose up -d postgres`, rồi chạy ai-service với `MAIL_BACKEND=console` và ghi log ra file
   (OTP nằm trong log): xem các lệnh trong job `e2e` của `ci.yml`.
2. `cd e2e && npm ci && npx playwright install chromium && npx playwright test`

Biến môi trường: `E2E_BASE_URL` (mặc định http://localhost:5173), `E2E_ADMIN_EMAIL`, `E2E_ADMIN_PASSWORD`,
`E2E_AI_LOG` (đường dẫn log ai-service), `PW_CHROMIUM` (đường dẫn trình duyệt có sẵn, tùy chọn).
