// Gọi ASP.NET gateway (/api/platform), nginx/Vite chuyển tiếp tới backend.
// Access token (JWT ngắn hạn, 15 phút) chỉ nằm trong bộ nhớ trang - không ghi vào localStorage nên
// XSS không lấy được phiên dài hạn. Phiên dài hạn là refresh token trong cookie httpOnly: JavaScript
// không đọc được, trình duyệt tự gửi tới /auth/refresh để lấy access token mới.

import type { User } from '../types';

export const API = '/api/platform';

// Header bắt buộc trên /auth/refresh và /auth/logout (chống CSRF; kết hợp cookie SameSite=Strict).
const CSRF_HEADERS = { 'X-Requested-With': 'aip' };

export type Session = { access_token: string; expires_in: number; user: User };

let accessToken: string | null = null;

export function getToken(): string | null {
  return accessToken;
}

export function setToken(token: string | null) {
  accessToken = token;
}

// Bản cũ lưu token trong localStorage: xóa đi để không còn token dài hạn nằm trong trình duyệt.
try {
  localStorage.removeItem('aip_token');
} catch {
  /* trình duyệt chặn localStorage: bỏ qua */
}

let onUnauthorized: (() => void) | null = null;
let onSession: ((session: Session) => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

// Gọi khi access token được làm mới ngầm (để giao diện cập nhật vai trò/hạn mức mới nhất).
export function setSessionHandler(handler: ((session: Session) => void) | null) {
  onSession = handler;
}

let refreshing: Promise<Session | null> | null = null;

// Đổi cookie refresh lấy access token mới. Nhiều request cùng gặp 401 chỉ gọi một lần (single-flight).
export function refreshSession(): Promise<Session | null> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const response = await fetch(API + '/auth/refresh', {
          method: 'POST',
          credentials: 'include',
          headers: CSRF_HEADERS,
        });
        if (!response.ok) return null;
        const session = (await response.json()) as Session;
        accessToken = session.access_token;
        return session;
      } catch {
        return null;
      }
    })().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

// Đăng xuất phía server: thu hồi refresh token và xóa cookie. Lỗi mạng không chặn việc đăng xuất cục bộ.
export async function logoutRequest(): Promise<void> {
  try {
    await fetch(API + '/auth/logout', { method: 'POST', credentials: 'include', headers: CSRF_HEADERS });
  } catch {
    /* ignore */
  }
}

// Các endpoint không dùng access token: 401 ở đây là sai thông tin, không phải hết phiên.
const NO_REFRESH = /^\/auth\/(login|register|forgot|refresh|logout)/;

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Lấy câu thông báo từ phản hồi lỗi {"detail": "..."} của server.
async function errorFrom(response: Response): Promise<ApiError> {
  const text = await response.text();
  let message = text;
  try {
    const body = JSON.parse(text);
    if (typeof body?.detail === 'string') message = body.detail;
    else if (Array.isArray(body?.detail)) message = 'Dữ liệu không hợp lệ.';
  } catch {
    /* không phải JSON */
  }
  return new ApiError(response.status, message || `HTTP ${response.status}`);
}

// fetch có gắn token; dùng cho SSE, upload và tải file (nơi api() không phù hợp).
// Gặp 401 thì thử làm mới phiên một lần rồi gửi lại; vẫn 401 thì coi như hết phiên.
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const send = (token: string | null) => {
    const headers = new Headers(init.headers);
    if (token) headers.set('Authorization', 'Bearer ' + token);
    return fetch(API + path, { ...init, headers, credentials: 'include' });
  };

  const used = accessToken;
  let response = await send(used);

  if (response.status === 401 && !NO_REFRESH.test(path)) {
    const session = await refreshSession();
    if (session) {
      onSession?.(session);
      response = await send(session.access_token);
    } else if (used && onUnauthorized) {
      onUnauthorized();
    }
  }

  return response;
}

export async function api(path: string, opts: RequestInit = {}) {
  const headers = new Headers(opts.headers);
  if (!headers.has('Content-Type') && !(opts.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await apiFetch(path, { ...opts, headers });

  if (!response.ok) {
    throw await errorFrom(response);
  }

  return response.json();
}

export async function errorMessageOf(response: Response): Promise<string> {
  return (await errorFrom(response)).message;
}

// Tải file gốc của tài liệu: thẻ <a href> không gửi được token nên phải tải bằng fetch.
export async function downloadDocument(id: string, filename: string) {
  const response = await apiFetch(`/documents/${encodeURIComponent(id)}/file`);
  if (!response.ok) throw await errorFrom(response);

  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = filename || 'document';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
