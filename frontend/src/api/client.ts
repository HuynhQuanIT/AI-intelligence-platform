// Gọi ASP.NET gateway (/api/platform), nginx/Vite chuyển tiếp tới backend.

export const API = '/api/platform';

export async function api(path: string, opts?: RequestInit) {
  const response = await fetch(API + path, {
    headers: {
      'Content-Type': 'application/json',
    },
    ...opts,
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json();
}
