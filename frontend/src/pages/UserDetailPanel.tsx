import { useEffect, useRef, useState, type FormEvent } from 'react';
import { AtSign, Gauge, KeyRound, Trash2, Wand2, X } from 'lucide-react';
import { api } from '../api/client';
import PasswordInput from '../components/PasswordInput';
import QuotaBar from '../components/QuotaBar';
import Panel from '../components/Panel';
import './UserDetailPanel.css';
import '../components/extras.css';
import type { UserDetail } from '../types';

type Props = {
  userId: string;
  isSelf: boolean;
  onClose: () => void;
  onChanged: () => void;
  onDeleted: () => void;
};

const fmt = (value: string | null) => (value ? new Date(value).toLocaleString() : '—');

// Mật khẩu ngẫu nhiên 16 ký tự, bỏ ký tự dễ nhầm (0/O, 1/l/I) và không dùng "$" để khỏi hỏng khi dán vào .env.
function randomPassword(): string {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789-_!';
  const bytes = crypto.getRandomValues(new Uint32Array(16));
  return Array.from(bytes, (n) => chars[n % chars.length]).join('');
}

export default function UserDetailPanel({ userId, isSelf, onClose, onChanged, onDeleted }: Props) {
  const [detail, setDetail] = useState<UserDetail | null>(null);
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState('');
  const [quotaInput, setQuotaInput] = useState('');
  const [emailInput, setEmailInput] = useState('');
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
    setQuotaInput('');
    setEmailInput('');
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

  // Chạy một thao tác của admin, hiện kết quả/ lỗi, rồi nạp lại.
  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    setError('');
    setDone('');
    try {
      await action();
      setDone(success);
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Có lỗi xảy ra.');
    } finally {
      setBusy(false);
    }
  }

  const post = (path: string, body: object) =>
    api(`/users/${encodeURIComponent(userId)}/${path}`, { method: 'POST', body: JSON.stringify(body) });

  function saveQuota(limit: number | null) {
    return run(() => post('quota', { limit }), 'Đã cập nhật hạn mức.');
  }

  function changeEmail(event: FormEvent) {
    event.preventDefault();
    if (!detail) return;
    if (!window.confirm(`Đổi email ${detail.email} thành ${emailInput.trim()}? Họ sẽ bị đăng xuất khỏi mọi thiết bị.`)) return;
    return run(async () => {
      await post('email', { email: emailInput.trim() });
      setEmailInput('');
    }, 'Đã đổi email. Hệ thống đã gửi thông báo tới cả hai địa chỉ.');
  }

  async function deleteAccount() {
    if (!detail) return;
    const typed = window.prompt(
      `Xóa vĩnh viễn tài khoản ${detail.email} cùng toàn bộ hội thoại của họ? Không thể hoàn tác.\nGõ lại email để xác nhận:`,
    );
    if (typed === null) return;
    if (typed.trim().toLowerCase() !== detail.email.toLowerCase()) {
      setError('Email xác nhận không khớp, chưa xóa gì.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await api(`/users/${encodeURIComponent(userId)}`, { method: 'DELETE' });
      onDeleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Có lỗi xảy ra.');
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
          <div className="kv">
            <span>Nhóm</span>
            <b>
              {detail.groups.length ? detail.groups.map((g) => <span className="chip" key={g.id}>{g.name}</span>) : '—'}
            </b>
          </div>
          <p className="note">Nội dung hội thoại là riêng tư nên quản trị viên chỉ thấy số lượng.</p>

          <h4 className="subhead">Hạn mức tin nhắn mỗi ngày</h4>
          <QuotaBar quota={detail.quota} />
          <div className="inline-form">
            <input
              type="number"
              min={1}
              max={1000000}
              value={quotaInput}
              onChange={(e) => setQuotaInput(e.target.value)}
              placeholder="Số tin nhắn/ngày"
              aria-label="Hạn mức tin nhắn mỗi ngày"
            />
            <button
              className="secondary"
              disabled={busy || !/^\d+$/.test(quotaInput) || Number(quotaInput) < 1}
              onClick={() => saveQuota(Number(quotaInput))}
            >
              <Gauge size={15} />
              Đặt hạn mức
            </button>
            <button className="secondary" disabled={busy} onClick={() => saveQuota(0)}>Không giới hạn</button>
            <button className="secondary" disabled={busy || detail.quota.is_default} onClick={() => saveQuota(null)}>
              Dùng mặc định
            </button>
          </div>

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

          <h4 className="subhead">Đổi email đăng nhập</h4>
          {isSelf ? (
            <p className="note">Không thể tự đổi email của chính bạn tại đây.</p>
          ) : (
            <form onSubmit={changeEmail} className="inline-form">
              <input
                type="email"
                value={emailInput}
                onChange={(e) => setEmailInput(e.target.value)}
                placeholder="email-moi@congty.com"
                aria-label="Email mới"
              />
              <button className="secondary" disabled={busy || !emailInput.includes('@')}>
                <AtSign size={15} />
                Đổi email
              </button>
            </form>
          )}

          <h4 className="subhead">Vùng nguy hiểm</h4>
          {isSelf ? (
            <p className="note">Bạn không thể tự xóa tài khoản của mình.</p>
          ) : (
            <div>
              <button className="danger" disabled={busy} onClick={deleteAccount}>
                <Trash2 size={15} />
                Xóa tài khoản
              </button>
              <p className="note">Xóa vĩnh viễn tài khoản và hội thoại. Nhật ký sử dụng được giữ lại để đối soát.</p>
            </div>
          )}
        </>
      )}

      {error && <p className="auth-error">{error}</p>}
      {done && <p className="note">{done}</p>}
    </Panel>
  );
}
