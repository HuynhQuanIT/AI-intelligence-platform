import { readFileSync } from 'node:fs';
import { expect, type Browser, type Page } from '@playwright/test';

export const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? 'admin@e2e.local';
export const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? 'Admin-e2e-pass-123';

// Ai-service chạy với MAIL_BACKEND=console nên mã OTP nằm trong file log (E2E_AI_LOG).
export function readOtp(email: string): string {
  const log = readFileSync(process.env.E2E_AI_LOG ?? 'ai-service.log', 'utf8');
  const marker = `email tới ${email} |`;
  const at = log.lastIndexOf(marker);
  if (at < 0) throw new Error(`Không thấy thư gửi tới ${email} trong log ai-service`);
  const code = /\b(\d{6})\b/.exec(log.slice(at, at + 400));
  if (!code) throw new Error(`Không thấy mã OTP trong thư gửi tới ${email}`);
  return code[1];
}

export function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}@e2e.test`;
}

export const loginForm = (page: Page) => page.locator('form.auth-card');

export async function login(page: Page, email: string, password: string) {
  await page.goto('/');
  await page.getByPlaceholder('example@gmail.com').fill(email);
  await page.locator('input[type=password]').fill(password);
  await loginForm(page).getByRole('button', { name: 'Đăng nhập', exact: true }).click();
}

export async function loginAs(page: Page, email: string, password: string) {
  await login(page, email, password);
  await expect(page.locator('aside .workspace')).toContainText(email);
}

export async function logout(page: Page) {
  await page.getByRole('button', { name: 'Đăng xuất' }).click();
  await expect(loginForm(page)).toBeVisible();
}

export async function openPage(page: Page, name: string) {
  await page.locator('aside').getByRole('button', { name, exact: true }).click();
  await expect(page.locator('article h1')).toHaveText(name);
}

export async function newSession(browser: Browser) {
  const context = await browser.newContext();
  return { context, page: await context.newPage() };
}

// Đăng ký bằng OTP: email -> mã -> mật khẩu. Kết thúc ở màn hình "Về trang đăng nhập".
export async function register(page: Page, email: string, password: string) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Tạo tài khoản' }).click();
  await page.getByPlaceholder('example@gmail.com').fill(email);
  await page.getByRole('button', { name: 'Gửi mã OTP' }).click();
  await expect(page.getByText('Mã OTP (6 số)')).toBeVisible();
  await page.waitForTimeout(500); // thư gửi nền: chờ log được ghi
  await page.getByPlaceholder('123456').fill(readOtp(email));
  await page.getByRole('button', { name: 'Xác nhận' }).click();
  const passwords = page.locator('input[type=password]');
  await passwords.nth(0).fill(password);
  await passwords.nth(1).fill(password);
  await page.getByRole('button', { name: 'Tạo tài khoản' }).click();
  await expect(page.locator('.safe')).toContainText('Đăng ký thành công');
}

export function userRow(page: Page, email: string) {
  return page.locator('tbody tr', { hasText: email });
}
