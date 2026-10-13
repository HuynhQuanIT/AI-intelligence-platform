import { useEffect, useState } from 'react';

// Giao diện Sáng / Tối / Theo hệ thống. Lựa chọn lưu ở localStorage; "system" bám theo cài đặt của
// hệ điều hành và tự đổi khi hệ điều hành đổi. index.html có đoạn script nhỏ áp theme trước khi React
// chạy (không bị nháy màu khi tải lại); logic ở đây phải khớp với đoạn đó.
export type ThemePreference = 'light' | 'dark' | 'system';

export const THEME_KEY = 'aip-theme';
const QUERY = '(prefers-color-scheme: dark)';

export function readPreference(): ThemePreference {
  try {
    const value = localStorage.getItem(THEME_KEY);
    if (value === 'light' || value === 'dark' || value === 'system') return value;
  } catch {
    /* localStorage bị chặn (chế độ riêng tư...): dùng mặc định */
  }
  return 'system';
}

export function resolve(pref: ThemePreference): 'light' | 'dark' {
  if (pref !== 'system') return pref;
  return window.matchMedia?.(QUERY).matches === false ? 'light' : 'dark';
}

export function applyTheme(pref: ThemePreference) {
  document.documentElement.dataset.theme = resolve(pref);
}

export function savePreference(pref: ThemePreference) {
  try {
    localStorage.setItem(THEME_KEY, pref);
  } catch {
    /* không lưu được thì chỉ đổi cho phiên này */
  }
  applyTheme(pref);
  window.dispatchEvent(new Event('aip-theme'));
}

// Gọi một lần lúc khởi động: áp theme và theo dõi hệ điều hành khi đang ở chế độ "Theo hệ thống".
export function initTheme() {
  applyTheme(readPreference());
  window.matchMedia?.(QUERY).addEventListener?.('change', () => {
    if (readPreference() === 'system') applyTheme('system');
  });
}

export function useTheme() {
  const [pref, setPref] = useState<ThemePreference>(readPreference);
  useEffect(() => {
    const sync = () => setPref(readPreference());
    window.addEventListener('aip-theme', sync);
    return () => window.removeEventListener('aip-theme', sync);
  }, []);
  return { pref, setPref: savePreference };
}
