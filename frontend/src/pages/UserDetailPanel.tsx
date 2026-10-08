import { useEffect, useRef, useState, type FormEvent } from 'react';
import { KeyRound, Wand2, X } from 'lucide-react';
import { api } from '../api/client';
import PasswordInput from '../components/PasswordInput';
import Panel from '../components/Panel';
import './UserDetailPanel.css';
import type { UserDetail } from '../types';

type Props = {
  userId: string;
  isSelf: boolean;
  onClose: () => void;
  onChanged: () => void;
};

const fmt = (value: string | null) => (value ? new Date(value).toLocaleString() : '—');

// Mật khẩu ngẫu nhiên 16 ký tự, bỏ ký tự dễ nhầm (0/O, 1/l/I) và không dùng "$" để khỏi hỏng khi dán vào .env.
function randomPassword(): string {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789-_!';
  const bytes = crypto.getRandomValues(new Uint32Array(16));
  return Array.from(bytes, (n) => chars[n % chars.length]).join('');
}

export default function UserDetailPanel({ userId, isSelf, onClose, onChanged }: Props) {
  const [detail, setDetail] = useState<UserDetail | null>(null);
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState('');
  const top = useRef<HTMLDivElement>(null);

  async function load() {
    try {
      setDetail(await api(`/users/${encodeURIComponent(userId)}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Có lỗi xảy ra.');
    }
  }

  useEffect(() => {
    setDetail(null);
    setPassword('');
    setError('');
    setDone('');
    load();
    top.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [userId]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!detail) return;
    if (!window.confirm(`Đặt lại mật khẩu cho ${detail.email}? Họ sẽ bị đăng xuất khỏi mọi thiết bị.`)) return;
    setBusy(true);
    setError('');
    setDone('');
    try {
      await api(`/users/${encodeURIComponent(userId)}/password`, {
        method: 'POST',
        body: JSON.stringify({ password }),
      });
      setDone('Đã đặt lại mật khẩu. Hãy gửi mật khẩu mới cho người dùng qua kênh an toàn.');
      setPassword('');
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Có lỗi xảy ra.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Chi tiết người dùng">
      <div ref={top} />
      <button className="secondary" onClick={onClose} style={{ alignSelf: 'flex-end' }}>
        <X size={15} />
        Đóng
      </button>

      {!detail && !error && <p className="note">Đang tải…</p>}

      {detail && (
        <>
          <div className="kv"><span>Email</span><b>{detail.email}</b></div>
          <div className="kv"><span>Vai trò</span><b>{detail.role}</b></div>
          <div className="kv"><span>Trạng thái</span><b>{detail.is_active ? 'Hoạt động' : 'Chờ duyệt / vô hiệu'}</b></div>
          <div className="kv"><span>Ngày tạo</span><b>{fmt(detail.created_at)}</b></div>
          <div className="kv"><span>Xác minh email</span><b>{fmt(detail.email_verified_at)}</b></div>
          <div className="kv"><span>Đăng nhập gần nhất</span><b>{fmt(detail.last_login_at)}</b></div>
          <div className="kv">
            <span>Khóa tạm do nhập sai</span>
            <b>{detail.is_locked ? `Đang khóa đến ${fmt(detail.locked_until)}` : `Không (sai ${detail.failed_attempts} lần)`}</b>
          </div>
          <div className="kv"><span>Hội thoại / tin nhắn</span><b>{detail.conversation_count} / {detail.message_count}</b></div>
          <div className="kv"><span>Số yêu cầu AI</span><b>{detail.request_count} (gần nhất: {fmt(detail.last_request_at)})</b></div>
          <div className="kv"><span>Tổng token</span><b>{detail.total_tokens.toLocaleString()}</b></div>
          <p className="note">Nội dung hội thoại là riêng tư nên quản trị viên chỉ thấy số lượng.</p>

          <h4 className="subhead">Đặt lại mật khẩu</h4>
          {isSelf ? (
            <p className="note">Đây là tài khoản của bạn. Hãy đăng xuất và dùng "Quên mật khẩu" để đổi.</p>
          ) : (
            <form onSubmit={submit} className="admin-pw-form">
              <label>Mật khẩu mới (tối thiểu 10 ký tự)</label>
              <PasswordInput
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
              />
              <div className="admin-pw-actions">
                <button type="button" className="secondary" onClick={() => setPassword(randomPassword())}>
                  <Wand2 size={15} />
                  Tạo ngẫu nhiên
                </button>
                <button className="primary" disabled={busy || password.length < 10}>
                  <KeyRound size={15} />
                  {busy ? 'Đang lưu...' : 'Đặt lại mật khẩu'}
                </button>
              </div>
            </form>
          )}
        </>
      )}

      {error && <p className="auth-error">{error}</p>}
      {done && <p className="note">{done}</p>}
    </Panel>
  );
}
