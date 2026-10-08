// Gọi ASP.NET gateway (/api/platform), nginx/Vite chuyển tiếp tới backend.
// Token đăng nhập (JWT) gắn vào mọi request; gặp 401 thì coi như hết phiên.

export const API = '/api/platform';

const TOKEN_KEY = 'aip_token';

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* trình duyệt chặn localStorage: bỏ qua, phiên chỉ còn trong bộ nhớ trang */
  }
}

let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

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
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set('Authorization', 'Bearer ' + token);

  const response = await fetch(API + path, { ...init, headers });

  if (response.status === 401 && token && onUnauthorized) onUnauthorized();
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
