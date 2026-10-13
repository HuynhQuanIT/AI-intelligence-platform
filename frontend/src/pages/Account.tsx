import { useState, type FormEvent } from 'react';
import { KeyRound, Monitor, Moon, Sun } from 'lucide-react';
import { api, type Session } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import Panel from '../components/Panel';
import PasswordInput from '../components/PasswordInput';
import QuotaBar from '../components/QuotaBar';
import { useTheme, type ThemePreference } from '../theme';
import '../components/extras.css';

const MIN_LENGTH = 10;

const THEMES: { id: ThemePreference; label: string; hint: string; icon: typeof Sun }[] = [
  { id: 'light', label: 'Sáng', hint: 'Nền sáng, chữ tối', icon: Sun },
  { id: 'dark', label: 'Tối', hint: 'Nền tối, dịu mắt khi dùng ban đêm', icon: Moon },
  { id: 'system', label: 'Theo hệ thống', hint: 'Tự đổi theo cài đặt của thiết bị', icon: Monitor },
];

// Đổi là áp dụng ngay cho toàn bộ trang và nhớ cho lần mở sau (lưu trên trình duyệt này).
function ThemePicker() {
  const { pref, setPref } = useTheme();
  return (
    <div className="theme-options" role="radiogroup" aria-label="Giao diện">
      {THEMES.map(({ id, label, hint, icon: Icon }) => (
        <label key={id} className={'theme-option' + (pref === id ? ' selected' : '')}>
          <input type="radio" name="theme" value={id} checked={pref === id} onChange={() => setPref(id)} />
          <Icon size={18} />
          <span><b>{label}</b><small>{hint}</small></span>
        </label>
      ))}
    </div>
  );
}

// Tài khoản của chính mình: xem hạn mức hôm nay và tự đổi mật khẩu.
export default function Account() {
  const { user, applySession } = useAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState('');

  if (!user) return null;

  const mismatch = confirm.length > 0 && next !== confirm;
  const canSubmit = current.length > 0 && next.length >= MIN_LENGTH && next === confirm && !busy;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setDone('');
    try {
      const result = await api('/auth/password', {
        method: 'POST',
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      applySession(result as Session); // thiết bị này nhận phiên mới; các thiết bị khác bị đăng xuất
      setCurrent('');
      setNext('');
      setConfirm('');
      setDone(result.message || 'Đã đổi mật khẩu.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Có lỗi xảy ra.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="cols">
      <Panel title="Thông tin tài khoản">
        <div className="kv"><span>Email</span><b>{user.email}</b></div>
        <div className="kv"><span>Vai trò</span><b>{user.role === 'admin' ? 'Quản trị viên' : 'Người dùng'}</b></div>
        <div className="kv">
          <span>Đăng nhập gần nhất</span>
          <b>{user.last_login_at ? new Date(user.last_login_at).toLocaleString() : '—'}</b>
        </div>

        <h4 className="subhead">Nhóm của tôi</h4>
        {user.role === 'admin' ? (
          <p className="note">Quản trị viên xem được toàn bộ tài liệu, không cần thuộc nhóm.</p>
        ) : user.access?.groups.length ? (
          <div className="my-group-list">
            {user.access.groups.map((g) => (
              <div className="my-group" key={g.id}>
                <b>{g.name}</b>
                <small>{g.description || 'Không có mô tả'} · {g.document_count} tài liệu</small>
              </div>
            ))}
            <p className="note">
              Bạn xem được {user.access.visible_documents} tài liệu: tài liệu công khai và tài liệu của các nhóm trên.
            </p>
          </div>
        ) : (
          <p className="note">
            Bạn chưa thuộc nhóm nào, nên chỉ xem được {user.access?.visible_documents ?? 0} tài liệu công khai. Hãy
            nhờ quản trị viên thêm bạn vào nhóm nếu cần xem thêm.
          </p>
        )}

        <h4 className="subhead">Hạn mức tin nhắn hôm nay</h4>
        <QuotaBar quota={user.quota} />
        <p className="note">Chỉ tin nhắn được trả lời thành công mới tính vào hạn mức.</p>
      </Panel>

      <Panel title="Giao diện">
        <ThemePicker />
        <p className="note">Lựa chọn được lưu trên trình duyệt này, không ảnh hưởng thiết bị khác.</p>
      </Panel>

      <Panel title="Đổi mật khẩu">
        <form onSubmit={submit} className="form-stack">
          <label>Mật khẩu hiện tại</label>
          <PasswordInput
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
            name="current-password"
          />

          <label>Mật khẩu mới (tối thiểu {MIN_LENGTH} ký tự)</label>
          <PasswordInput
            value={next}
            onChange={(e) => setNext(e.target.value)}
            autoComplete="new-password"
            name="new-password"
          />

          <label>Nhập lại mật khẩu mới</label>
          <PasswordInput
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            name="confirm-password"
          />
          {mismatch && <p className="auth-error">Hai mật khẩu mới chưa khớp.</p>}

          <button className="primary" disabled={!canSubmit}>
            <KeyRound size={15} />
            {busy ? 'Đang lưu...' : 'Đổi mật khẩu'}
          </button>
        </form>

        <p className="note">Sau khi đổi, các thiết bị khác sẽ bị đăng xuất; thiết bị này vẫn đăng nhập.</p>
        {error && <p className="auth-error" role="alert">{error}</p>}
        {done && <p className="success-note" role="status">{done}</p>}
      </Panel>
    </div>
  );
}
