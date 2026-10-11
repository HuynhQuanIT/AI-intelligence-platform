import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { UserUsage } from '../types';
import './extras.css';

type Mode = 'usage' | 'security';

// Bảng thống kê theo người dùng (admin). mode=usage: request/token/chi phí/hạn mức; mode=security: bị chặn, lỗi, sự kiện.
export default function UserUsageTable({ mode, reloadKey = 0 }: { mode: Mode; reloadKey?: number }) {
  const [rows, setRows] = useState<UserUsage[] | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api('/metrics/users')
      .then((data) => {
        setRows(data);
        setError('');
      })
      .catch((e: Error) => setError(e.message));
  }, [reloadKey]);

  if (error) return <p className="auth-error">Không tải được thống kê theo người dùng: {error}</p>;
  if (!rows) return <p className="muted">Đang tải…</p>;
  if (!rows.length) return <p className="muted">Chưa có người dùng.</p>;

  const visible = mode === 'security' ? rows.filter((r) => r.blocked || r.errors || r.security_events) : rows;
  if (!visible.length) return <p className="muted">Chưa có người dùng nào bị chặn hoặc gây sự kiện bảo mật.</p>;

  return (
    <div className="tablewrap">
      <table>
        <thead>
          {mode === 'usage' ? (
            <tr>
              <th>Người dùng</th><th>Yêu cầu</th><th>Hôm nay</th><th>Hạn mức</th><th>Token</th><th>Chi phí</th><th>Gần nhất</th>
            </tr>
          ) : (
            <tr>
              <th>Người dùng</th><th>Bị chặn</th><th>Lỗi</th><th>Sự kiện bảo mật</th><th>Yêu cầu</th>
            </tr>
          )}
        </thead>
        <tbody>
          {visible.map((r) =>
            mode === 'usage' ? (
              <tr key={r.id}>
                <td>{r.email}{!r.is_active && <small> (vô hiệu)</small>}</td>
                <td>{r.requests}</td>
                <td>{r.today}</td>
                <td>{r.quota_limit === null ? 'Không giới hạn' : r.quota_limit}</td>
                <td>{r.tokens.toLocaleString()}</td>
                <td>${r.cost_usd.toFixed(4)}</td>
                <td>{r.last_at ? new Date(r.last_at).toLocaleString() : '—'}</td>
              </tr>
            ) : (
              <tr key={r.id}>
                <td>{r.email}</td>
                <td>{r.blocked}</td>
                <td>{r.errors}</td>
                <td>{r.security_events}</td>
                <td>{r.requests}</td>
              </tr>
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}
