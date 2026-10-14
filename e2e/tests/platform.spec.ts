import { expect, test } from '@playwright/test';
import {
  ADMIN_EMAIL, ADMIN_PASSWORD, login, loginAs, loginForm, logout, newSession, openPage, readOtp, register,
  uniqueEmail, userRow,
} from '../helpers';

// Một kịch bản liền mạch theo vòng đời thật của một người dùng. Chạy tuần tự, dùng chung trạng thái.
test.describe.configure({ mode: 'serial' });

const PASSWORD = 'Mat-khau-e2e-123';
const NEW_PASSWORD = 'Mat-khau-moi-456';
const email = uniqueEmail('nguoidung');
const groupName = 'Nhóm E2E ' + Date.now().toString(36);
const docTitle = 'Tài liệu mật ' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

test('đăng ký, chờ duyệt, admin duyệt, người dùng thường chỉ thấy trang của mình', async ({ browser }) => {
  const { page: guest } = await newSession(browser);
  await register(guest, email, PASSWORD);

  // Chưa được duyệt thì không đăng nhập được.
  await login(guest, email, PASSWORD);
  await expect(guest.locator('.error')).toContainText('chờ quản trị viên duyệt');

  const { page: admin } = await newSession(browser);
  await loginAs(admin, ADMIN_EMAIL, ADMIN_PASSWORD);
  await openPage(admin, 'User Management');
  await userRow(admin, email).getByRole('button', { name: 'Duyệt' }).click();
  await expect(userRow(admin, email).getByRole('button', { name: 'Duyệt' })).toHaveCount(0);

  await loginAs(guest, email, PASSWORD);
  await expect(guest.locator('article h1')).toHaveText('AI Playground');
  const nav = guest.locator('aside');
  await expect(nav.getByRole('button', { name: 'Dashboard', exact: true })).toHaveCount(0);
  await expect(nav.getByRole('button', { name: 'User Management', exact: true })).toHaveCount(0);
  await expect(nav.getByRole('button', { name: 'My Account', exact: true })).toBeVisible();
});

test('phiên: refresh token trong cookie httpOnly, tải lại trang vẫn đăng nhập, đăng xuất thu hồi phiên', async ({ browser }) => {
  const { context, page } = await newSession(browser);
  await loginAs(page, email, PASSWORD);

  // Access token không nằm trong localStorage; cookie refresh là httpOnly và JavaScript không đọc được.
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }));
  expect(stored).not.toMatch(/eyJ/);
  const cookie = (await context.cookies()).find((c) => c.name === 'aip_refresh');
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe('Strict');
  expect(cookie?.path).toBe('/api/platform/auth');
  expect(await page.evaluate(() => document.cookie)).not.toContain('aip_refresh');

  // Tải lại: access token trong bộ nhớ mất, cookie refresh khôi phục phiên.
  await page.reload();
  await expect(page.locator('aside .workspace')).toContainText(email);

  // Refresh thiếu header chống CSRF bị từ chối.
  const noHeader = await page.request.post('/api/platform/auth/refresh');
  expect(noHeader.status()).toBe(403);

  await logout(page);
  await page.reload();
  await expect(loginForm(page)).toBeVisible(); // đăng xuất đã thu hồi cookie
});

test('chat có hạn mức, admin đổi hạn mức và thấy thống kê theo người dùng', async ({ browser }) => {
  const { page: user } = await newSession(browser);
  await loginAs(user, email, PASSWORD);
  await expect(user.locator('.quota-text')).toContainText('Hôm nay');

  await user.getByPlaceholder('Message your AI assistant...').fill('Xin chào, bạn là ai?');
  await user.locator('.compose button.primary').click();
  await expect(user.locator('.bubble.ai .message-meta').last()).toBeVisible({ timeout: 30_000 });
  await expect(user.locator('.quota-text')).toContainText('1/50');

  const { page: admin } = await newSession(browser);
  await loginAs(admin, ADMIN_EMAIL, ADMIN_PASSWORD);

  // Thống kê theo người dùng trên Dashboard.
  await openPage(admin, 'Dashboard');
  await admin.getByRole('button', { name: 'Refresh' }).click();
  await expect(admin.locator('tbody tr', { hasText: email })).toBeVisible();

  // Đặt hạn mức 1: tin nhắn tiếp theo bị từ chối vì đã dùng 1.
  await openPage(admin, 'User Management');
  await userRow(admin, email).getByRole('button', { name: 'Chi tiết' }).click();
  await admin.getByLabel('Hạn mức tin nhắn mỗi ngày').fill('1');
  await admin.getByRole('button', { name: 'Đặt hạn mức' }).click();
  await expect(admin.getByText('Đã cập nhật hạn mức.')).toBeVisible();

  await user.getByPlaceholder('Message your AI assistant...').fill('Câu thứ hai');
  await user.locator('.compose button.primary').click();
  await expect(user.locator('.error')).toContainText('Bạn đã dùng hết 1 tin nhắn');

  // Trả về không giới hạn.
  await admin.getByRole('button', { name: 'Không giới hạn' }).click();
  await expect(admin.getByText('Đã cập nhật hạn mức.')).toBeVisible();
});

test('nhóm và phân quyền tài liệu: người ngoài nhóm không thấy, vào nhóm thì thấy', async ({ browser }) => {
  const { page: admin } = await newSession(browser);
  await loginAs(admin, ADMIN_EMAIL, ADMIN_PASSWORD);

  await openPage(admin, 'Knowledge Center');
  await admin.getByPlaceholder('Product handbook').fill(docTitle);
  await admin.getByPlaceholder('Paste document text...').fill(`Nội dung nội bộ chỉ dành cho nhóm được cấp quyền. Mã ${docTitle}.`);
  await admin.getByRole('button', { name: 'Index document' }).click();
  await expect(admin.getByText(docTitle, { exact: true })).toBeVisible();

  await openPage(admin, 'Groups');
  await admin.getByPlaceholder('Phòng Kế toán').fill(groupName);
  await admin.getByRole('button', { name: 'Tạo nhóm' }).click();
  await expect(admin.getByRole('heading', { name: 'Nhóm: ' + groupName })).toBeVisible();

  await openPage(admin, 'Knowledge Center');
  const docRow = admin.locator('.row', { hasText: docTitle });
  await docRow.getByRole('button', { name: 'Quyền xem' }).click();
  await admin.locator('.doc-groups label', { hasText: groupName }).locator('input').check();
  await admin.getByRole('button', { name: 'Lưu quyền xem' }).click();
  await expect(docRow.locator('.chip', { hasText: groupName })).toBeVisible();

  // Người dùng chưa vào nhóm: không thấy tài liệu.
  const { page: user } = await newSession(browser);
  await loginAs(user, email, PASSWORD);
  await openPage(user, 'Knowledge Center');
  await expect(user.getByText(docTitle, { exact: true })).toHaveCount(0);

  // Admin thêm người dùng vào nhóm.
  await openPage(admin, 'Groups');
  await admin.locator('.group-item', { hasText: groupName }).click();
  await admin.locator('.checklist label', { hasText: email }).locator('input').check();
  await admin.getByRole('button', { name: 'Lưu thành viên' }).click();
  await expect(admin.getByText('Đã lưu thành viên.')).toBeVisible();

  await user.reload();
  // Người dùng biết mình vừa vào nhóm: banner, chip ở thanh bên và nhãn trên tài liệu.
  await expect(user.locator('.group-banner')).toContainText(groupName);
  await expect(user.locator('aside .chip', { hasText: groupName })).toBeVisible();
  await openPage(user, 'Knowledge Center');
  await expect(user.getByText(docTitle, { exact: true })).toBeVisible();
  await expect(user.locator('.row', { hasText: docTitle }).locator('.chip', { hasText: groupName })).toBeVisible();
  // Chatbot trích dẫn nguồn kèm nhãn nhóm của tài liệu.
  await openPage(user, 'AI Playground');
  await user.getByPlaceholder('Message your AI assistant...').fill('nội bộ dành cho nhóm được cấp quyền');
  await user.locator('.compose button.primary').click();
  const sources = user.locator('.sources .source', { hasText: docTitle });
  await expect(sources).toBeVisible({ timeout: 20000 });
  await expect(sources.locator('.chip', { hasText: groupName })).toBeVisible();
  await openPage(user, 'Knowledge Center');
  await user.getByRole('button', { name: 'Của nhóm tôi' }).click();
  await expect(user.getByText(docTitle, { exact: true })).toBeVisible();
  await user.getByRole('button', { name: 'Công khai', exact: true }).click();
  await expect(user.getByText(docTitle, { exact: true })).toHaveCount(0);

  // Không xóa được nhóm đang là nhóm duy nhất của tài liệu.
  admin.once('dialog', (dialog) => dialog.accept());
  await admin.getByRole('button', { name: 'Xóa nhóm' }).click();
  await expect(admin.locator('.error')).toContainText('nhóm duy nhất');
});

test('người dùng tự đổi mật khẩu; thiết bị khác bị đăng xuất; mật khẩu cũ hết hiệu lực', async ({ browser }) => {
  const { page: phone } = await newSession(browser);
  await loginAs(phone, email, PASSWORD);
  const { page: laptop } = await newSession(browser);
  await loginAs(laptop, email, PASSWORD);

  await openPage(laptop, 'My Account');
  const fields = laptop.locator('form.form-stack input[type=password]');
  await fields.nth(0).fill('sai-mat-khau-123');
  await fields.nth(1).fill(NEW_PASSWORD);
  await fields.nth(2).fill(NEW_PASSWORD);
  await laptop.getByRole('button', { name: 'Đổi mật khẩu' }).click();
  await expect(laptop.getByRole('alert')).toContainText('Mật khẩu hiện tại không đúng');

  await fields.nth(0).fill(PASSWORD);
  await laptop.getByRole('button', { name: 'Đổi mật khẩu' }).click();
  await expect(laptop.getByRole('status')).toContainText('Đã đổi mật khẩu');
  await expect(laptop.locator('aside .workspace')).toContainText(email); // thiết bị này vẫn đăng nhập

  // Thiết bị kia: access token cũ và refresh cookie đều đã bị thu hồi.
  await phone.reload();
  await expect(loginForm(phone)).toBeVisible();

  await login(phone, email, PASSWORD);
  await expect(phone.locator('.error')).toContainText('Email hoặc mật khẩu không đúng');
  await loginAs(phone, email, NEW_PASSWORD);
});

test('quên mật khẩu bằng OTP', async ({ browser }) => {
  const { page } = await newSession(browser);
  await page.goto('/');
  await page.getByRole('button', { name: 'Quên mật khẩu?' }).click();
  await page.getByPlaceholder('example@gmail.com').fill(email);
  await page.getByRole('button', { name: 'Gửi mã OTP' }).click();
  await expect(page.getByText('Mã OTP (6 số)')).toBeVisible();
  await page.waitForTimeout(500);
  await page.getByPlaceholder('123456').fill(readOtp(email));
  await page.getByRole('button', { name: 'Xác nhận' }).click();
  const fields = page.locator('input[type=password]');
  await fields.nth(0).fill(PASSWORD);
  await fields.nth(1).fill(PASSWORD);
  await page.getByRole('button', { name: 'Đặt lại mật khẩu' }).click();
  await expect(page.locator('.safe')).toContainText('Đã đặt lại mật khẩu');
  await page.getByRole('button', { name: 'Về trang đăng nhập' }).click();
  await loginAs(page, email, PASSWORD);
});

test('admin đổi email rồi xóa tài khoản', async ({ browser }) => {
  const { page: user } = await newSession(browser);
  await loginAs(user, email, PASSWORD);

  const { page: admin } = await newSession(browser);
  await loginAs(admin, ADMIN_EMAIL, ADMIN_PASSWORD);
  await openPage(admin, 'User Management');
  await userRow(admin, email).getByRole('button', { name: 'Chi tiết' }).click();

  const renamed = uniqueEmail('doiten');
  admin.once('dialog', (dialog) => dialog.accept());
  await admin.getByLabel('Email mới').fill(renamed);
  await admin.getByRole('button', { name: 'Đổi email', exact: true }).click();
  await expect(admin.getByText('Đã đổi email.')).toBeVisible();
  await expect(userRow(admin, renamed)).toBeVisible();

  // Phiên cũ của người dùng bị thu hồi.
  await user.reload();
  await expect(loginForm(user)).toBeVisible();
  await login(user, email, PASSWORD);
  await expect(user.locator('.error')).toContainText('Email hoặc mật khẩu không đúng');
  await loginAs(user, renamed, PASSWORD);
  await logout(user);

  // Xóa tài khoản: phải gõ lại email để xác nhận.
  admin.once('dialog', (dialog) => dialog.accept(renamed));
  await admin.getByRole('button', { name: 'Xóa tài khoản' }).click();
  await expect(userRow(admin, renamed)).toHaveCount(0);

  await login(user, renamed, PASSWORD);
  await expect(user.locator('.error')).toContainText('Email hoặc mật khẩu không đúng');
});


test('upload bất đồng bộ: trạng thái tự cập nhật, file hỏng báo lỗi và thử lại được', async ({ browser }) => {
  const { page: admin } = await newSession(browser);
  await loginAs(admin, ADMIN_EMAIL, ADMIN_PASSWORD);
  await openPage(admin, 'Knowledge Center');

  const stamp = Date.now().toString(36);
  await admin.locator('input[type=file]').setInputFiles({
    name: `tai-lieu-${stamp}.txt`, mimeType: 'text/plain',
    buffer: Buffer.from(`Tài liệu upload bất đồng bộ ${stamp}. `.repeat(60)),
  });
  await admin.getByRole('button', { name: /Upload/ }).click();
  await expect(admin.getByText('đang xử lý nền')).toBeVisible();
  const ok = admin.locator('.row', { hasText: `tai-lieu-${stamp}` });
  await expect(ok.locator('.status-badge.processed')).toBeVisible({ timeout: 20000 }); // tự cập nhật, không cần reload

  await admin.locator('input[type=file]').setInputFiles({
    name: `hong-${stamp}.pdf`, mimeType: 'application/pdf', buffer: Buffer.from(`%PDF-1.4 không phải pdf thật ${stamp}`),
  });
  await admin.getByRole('button', { name: /Upload/ }).click();
  const bad = admin.locator('.row', { hasText: `hong-${stamp}` });
  await expect(bad.locator('.status-badge.failed')).toBeVisible({ timeout: 20000 });
  await expect(bad.locator('.doc-error')).not.toBeEmpty();
  await bad.getByRole('button', { name: 'Thử lại' }).click();
  await expect(bad.locator('.status-badge.failed')).toBeVisible({ timeout: 20000 }); // file hỏng nên vẫn lỗi, nhưng đã chạy lại
});

test('tìm kiếm tài liệu theo nội dung, tô sáng từ khóa, bấm kết quả mở đúng đoạn', async ({ browser }) => {
  const { page: admin } = await newSession(browser);
  await loginAs(admin, ADMIN_EMAIL, ADMIN_PASSWORD);
  const token = 'tìmkiếm' + Date.now().toString(36);
  const title = 'Tài liệu tìm kiếm ' + token;
  await openPage(admin, 'Knowledge Center');
  await admin.getByPlaceholder('Product handbook').fill(title);
  await admin.getByPlaceholder('Paste document text...').fill(`Mở đầu. Nội dung bảo quản mẫu có từ khóa ${token} nằm ở giữa đoạn.`);
  await admin.getByRole('button', { name: 'Index document' }).click();
  await expect(admin.getByText(title, { exact: true })).toBeVisible();

  await openPage(admin, 'Document Search');
  await admin.getByLabel('Từ khóa tìm kiếm').fill(token);
  await admin.getByRole('button', { name: 'Từ khóa', exact: true }).click();
  await admin.getByRole('button', { name: 'Tìm', exact: true }).click();
  const hit = admin.locator('.search-result', { hasText: title });
  await expect(hit).toBeVisible();
  await expect(hit.locator('mark')).toHaveText(token);
  await hit.getByRole('button', { name: /^Chunk 0/ }).click();

  await expect(admin.locator('.document-chunk.focused')).toContainText(token);
});

test('chatbot: 👍/👎 lưu lại sau khi tải lại, sinh lại câu trả lời, đổi tên hội thoại, admin thấy 👎 ở trang Feedback', async ({ browser }) => {
  const { page } = await newSession(browser);
  await loginAs(page, ADMIN_EMAIL, ADMIN_PASSWORD);
  await openPage(page, 'AI Playground');

  const question = 'Câu hỏi đánh giá ' + Date.now().toString(36);
  await page.getByPlaceholder('Message your AI assistant...').fill(question);
  await page.getByRole('button', { name: 'Gửi', exact: true }).click();
  const answer = page.locator('.bubble.ai').last();
  await expect(answer.getByRole('button', { name: 'Câu trả lời tốt' })).toBeVisible({ timeout: 20000 });

  await answer.getByRole('button', { name: 'Câu trả lời tốt' }).click();
  await expect(answer.getByRole('button', { name: 'Câu trả lời tốt' })).toHaveAttribute('aria-pressed', 'true');
  await answer.getByRole('button', { name: 'Câu trả lời chưa tốt' }).click(); // đổi ý: 👎 thay cho 👍
  await expect(answer.getByRole('button', { name: 'Câu trả lời chưa tốt' })).toHaveAttribute('aria-pressed', 'true');
  await expect(answer.getByRole('button', { name: 'Câu trả lời tốt' })).toHaveAttribute('aria-pressed', 'false');

  // Đổi tên hội thoại rồi tải lại trang: tên mới và đánh giá vẫn còn.
  const renamed = 'Tên mới ' + Date.now().toString(36);
  await page.locator('.conv-item.active').getByRole('button', { name: 'Đổi tên hội thoại' }).click();
  await page.getByLabel('Tên hội thoại').fill(renamed);
  await page.getByLabel('Tên hội thoại').press('Enter');
  await expect(page.locator('.conv-item.active')).toContainText(renamed);
  await page.reload();
  await openPage(page, 'AI Playground');
  await page.locator('.conv-item', { hasText: renamed }).getByRole('button').first().click();
  const reloaded = page.locator('.bubble.ai').last();
  await expect(reloaded.getByRole('button', { name: 'Câu trả lời chưa tốt' })).toHaveAttribute('aria-pressed', 'true');

  // Sinh lại: vẫn đúng 1 câu hỏi + 1 câu trả lời, đánh giá cũ bị xóa cùng câu trả lời cũ.
  await reloaded.getByRole('button', { name: 'Sinh lại câu trả lời' }).click();
  await expect(page.locator('.bubble.ai').last().getByRole('button', { name: 'Câu trả lời tốt' })).toBeVisible({ timeout: 20000 });
  await expect(page.locator('.bubble.user')).toHaveCount(1);
  await expect(page.locator('.bubble.ai')).toHaveCount(1);
  await expect(page.locator('.bubble.ai').last().getByRole('button', { name: 'Câu trả lời chưa tốt' })).toHaveAttribute('aria-pressed', 'false');

  // Tải lại từ server: lượt cũ đã bị xóa thật (không còn 2 câu hỏi giống nhau trong DB).
  await page.reload();
  await openPage(page, 'AI Playground');
  await page.locator('.conv-item', { hasText: renamed }).getByRole('button').first().click();
  await expect(page.locator('.bubble.user')).toHaveCount(1);
  await expect(page.locator('.bubble.ai')).toHaveCount(1);

  // Đánh giá lại 👎 để admin thấy trong Feedback.
  await page.locator('.bubble.ai').last().getByRole('button', { name: 'Câu trả lời chưa tốt' }).click();
  await openPage(page, 'Feedback');
  await expect(page.locator('.fb-item', { hasText: question })).toBeVisible();
});

test('chatbot: nút Dừng hủy câu trả lời đang chạy và cho gửi lại', async ({ browser }) => {
  const { page } = await newSession(browser);
  await loginAs(page, ADMIN_EMAIL, ADMIN_PASSWORD);
  await openPage(page, 'AI Playground');

  // Treo yêu cầu stream để mô phỏng câu trả lời chậm.
  await page.route('**/chat/stream', () => { /* không trả lời */ });
  await page.getByPlaceholder('Message your AI assistant...').fill('Câu hỏi chạy rất lâu');
  await page.getByRole('button', { name: 'Gửi', exact: true }).click();
  const stop = page.getByRole('button', { name: 'Dừng trả lời' });
  await expect(stop).toBeVisible();
  await stop.click();

  await expect(page.getByRole('button', { name: 'Gửi', exact: true })).toBeVisible();
  await expect(page.locator('.error')).toHaveCount(0); // dừng chủ động không phải lỗi
  await expect(page.getByPlaceholder('Message your AI assistant...')).toBeEnabled();
  await page.unroute('**/chat/stream');
});

test('giao diện Sáng / Tối / Theo hệ thống: đổi ngay, nhớ sau khi tải lại', async ({ browser }) => {
  const { page } = await newSession(browser);
  await page.emulateMedia({ colorScheme: 'dark' });
  await loginAs(page, ADMIN_EMAIL, ADMIN_PASSWORD);
  await openPage(page, 'My Account');

  const theme = () => page.evaluate(() => document.documentElement.dataset.theme);
  const bodyBg = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const stored = () => page.evaluate(() => localStorage.getItem('aip-theme'));
  const group = page.getByRole('radiogroup', { name: 'Giao diện' });

  // Mặc định là "Theo hệ thống" (hệ thống đang tối).
  await expect(group.getByRole('radio', { name: /Theo hệ thống/ })).toBeChecked();
  expect(await theme()).toBe('dark');
  const darkBg = await bodyBg();

  await group.getByText('Sáng', { exact: true }).click();
  await expect.poll(theme).toBe('light');
  expect(await bodyBg()).not.toBe(darkBg); // màu nền đổi ngay, không cần tải lại
  expect(await stored()).toBe('light');

  await page.reload();
  expect(await theme()).toBe('light'); // nhớ lại lựa chọn
  await openPage(page, 'My Account');
  await expect(group.getByRole('radio', { name: /Sáng/ })).toBeChecked();

  await group.getByText('Tối', { exact: true }).click();
  await expect.poll(theme).toBe('dark');
  expect(await bodyBg()).toBe(darkBg);

  // "Theo hệ thống": bám theo hệ điều hành, kể cả khi hệ điều hành đổi lúc đang mở trang.
  await group.getByText('Theo hệ thống', { exact: true }).click();
  expect(await stored()).toBe('system');
  await page.emulateMedia({ colorScheme: 'light' });
  await expect.poll(theme).toBe('light');
  await page.emulateMedia({ colorScheme: 'dark' });
  await expect.poll(theme).toBe('dark');
});

test('đính kèm file trong chat: lưu riêng tư vào Knowledge Center, chatbot dùng file làm nguồn, xóa được', async ({ browser }) => {
  const { page } = await newSession(browser);
  await loginAs(page, ADMIN_EMAIL, ADMIN_PASSWORD);
  await openPage(page, 'AI Playground');

  const stamp = Date.now().toString(36);
  const name = `bao-cao-${stamp}.txt`;
  await page.getByLabel('Chọn file đính kèm').setInputFiles({
    name, mimeType: 'text/plain',
    buffer: Buffer.from(`Báo cáo nội bộ ${stamp}. Doanh thu quý ba đạt 420 triệu, tăng 12% so với quý hai. `.repeat(8)),
  });
  const chip = page.locator('.attach-bar .attach-chip');
  await expect(chip).toContainText(name, { timeout: 30000 });

  await page.getByRole('button', { name: 'Gửi', exact: true }).click(); // không gõ gì: dùng câu mặc định "tóm tắt"
  await expect(page.locator('.bubble.user .attach-chip.sent')).toContainText(name);
  const answer = page.locator('.bubble.ai').last();
  await expect(answer.locator('.chip.private')).toBeVisible({ timeout: 30000 }); // nguồn là file riêng tư
  await expect(page.locator('.attach-bar')).toHaveCount(0); // chip đã được dọn sau khi gửi

  // Mở lại hội thoại: chip file vẫn hiện trên câu hỏi.
  await page.reload();
  await openPage(page, 'AI Playground');
  await page.locator('.conv-item', { hasText: 'Hãy tóm tắt' }).getByRole('button').first().click();
  await expect(page.locator('.bubble.user .attach-chip.sent').last()).toContainText(name);

  // File nằm trong Knowledge Center, đánh dấu riêng tư, xóa được.
  await openPage(page, 'Knowledge Center');
  const row = page.locator('.row', { hasText: name });
  await expect(row.locator('.chip.private')).toBeVisible();
  page.once('dialog', (d) => d.accept());
  await row.getByRole('button', { name: 'Xóa' }).click();
  await expect(page.locator('.row', { hasText: name })).toHaveCount(0);
});

test('thêm tài liệu khi server chậm: nút bị khóa, bấm lại không tạo bản trùng, xóa xong không hiện lại', async ({ browser }) => {
  const { page } = await newSession(browser);
  await loginAs(page, ADMIN_EMAIL, ADMIN_PASSWORD);
  await openPage(page, 'Knowledge Center');

  // Làm chậm yêu cầu tạo tài liệu (như lúc Gemini tạo embedding lâu).
  await page.route('**/documents', async (route) => {
    if (route.request().method() === 'POST') await new Promise((r) => setTimeout(r, 2500));
    await route.continue();
  });
  const title = 'Tài liệu chậm ' + Date.now().toString(36);
  await page.getByPlaceholder('Product handbook').fill(title);
  await page.getByPlaceholder('Paste document text...').fill('Nội dung để thử bấm hai lần khi server chậm. '.repeat(3));
  const add = page.getByRole('button', { name: /Index document|Đang index/ });
  await add.click();
  await expect(add).toBeDisabled(); // không bấm thêm lần nữa được
  await expect(page.locator('.row', { hasText: title })).toHaveCount(1, { timeout: 20000 });
  await page.unroute('**/documents');

  page.once('dialog', (d) => d.accept());
  await page.locator('.row', { hasText: title }).getByRole('button', { name: 'Xóa' }).click();
  await expect(page.locator('.row', { hasText: title })).toHaveCount(0);
  await page.waitForTimeout(3500); // chờ: nếu còn request treo thì bản trùng sẽ hiện lại ở đây
  await page.getByRole('button', { name: 'Refresh' }).click();
  await page.waitForTimeout(1000);
  await expect(page.locator('.row', { hasText: title })).toHaveCount(0);
});
