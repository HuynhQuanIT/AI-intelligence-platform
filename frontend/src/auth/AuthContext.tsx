import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  api, logoutRequest, refreshSession, setSessionHandler, setToken, setUnauthorizedHandler, type Session,
} from '../api/client';
import type { User } from '../types';

type AuthState = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  // Dùng sau khi đổi mật khẩu: server trả phiên mới cho thiết bị này.
  applySession: (session: Session) => void;
  // Nạp lại thông tin (hạn mức hôm nay...) của chính người dùng.
  refreshUser: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const clearLocal = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  const logout = useCallback(async () => {
    await logoutRequest();
    clearLocal();
  }, [clearLocal]);

  // Mở lại trang: access token (trong bộ nhớ) đã mất, nên dùng cookie refresh để khôi phục phiên.
  // Hết hạn ở bất kỳ request nào (và không làm mới được) thì quay về màn hình đăng nhập.
  useEffect(() => {
    setUnauthorizedHandler(clearLocal);
    setSessionHandler((session) => setUser(session.user));

    let active = true;
    refreshSession().then((session) => {
      if (!active) return;
      if (session) setUser(session.user);
      setLoading(false);
    });

    return () => {
      active = false;
      setUnauthorizedHandler(null);
      setSessionHandler(null);
    };
  }, [clearLocal]);

  const login = useCallback(async (email: string, password: string) => {
    const result = await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    setToken(result.access_token);
    setUser(result.user);
  }, []);

  const applySession = useCallback((session: Session) => {
    setToken(session.access_token);
    setUser(session.user);
  }, []);

  const refreshUser = useCallback(async () => {
    try {
      setUser(await api('/auth/me'));
    } catch {
      /* hết phiên đã được apiFetch xử lý */
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, logout, applySession, refreshUser }),
    [user, loading, login, logout, applySession, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
