import { useState, type FormEvent } from 'react';
import { BrainCircuit } from 'lucide-react';
import { useAuth } from '../../auth/AuthContext';
import OtpFlow from './OtpFlow';
import PasswordInput from '../../components/PasswordInput';

type Mode = 'login' | 'register' | 'forgot';

// Màn hình hiển thị khi chưa đăng nhập: đăng nhập, đăng ký, quên mật khẩu.
export default function AuthScreen() {
  const { login } = useAuth();
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await login(email, password);
    } catch (e: any) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <div className="auth-brand">
        <div className="logo">
          <BrainCircuit />
        </div>
        <b>
          AI Intelligence
          <small>PLATFORM</small>
        </b>
      </div>

      {mode === 'login' && (
        <form className="auth-card" onSubmit={submit}>
          <h2>Đăng nhập</h2>

          {error && <div className="error">{error}</div>}

          <label>Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="example@gmail.com"
            autoComplete="username"
            autoFocus
          />

          <label>Mật khẩu</label>
          <PasswordInput
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />

          <button className="primary" disabled={busy || !email.trim() || !password}>
            {busy ? 'Đang đăng nhập...' : 'Đăng nhập'}
          </button>

          <div className="auth-links">
            <button type="button" className="link" onClick={() => setMode('forgot')}>
              Quên mật khẩu?
            </button>
            <button type="button" className="link" onClick={() => setMode('register')}>
              Tạo tài khoản
            </button>
          </div>
        </form>
      )}

      {mode === 'register' && <OtpFlow kind="register" onBack={() => setMode('login')} />}
      {mode === 'forgot' && <OtpFlow kind="forgot" onBack={() => setMode('login')} />}
    </div>
  );
}
