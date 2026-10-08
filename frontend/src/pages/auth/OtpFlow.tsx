import { useEffect, useState, type FormEvent } from 'react';
import { api } from '../../api/client';
import PasswordInput from '../../components/PasswordInput';

// Luồng 3 bước dùng chung cho Đăng ký và Quên mật khẩu: email -> mã OTP -> mật khẩu mới.
type Kind = 'register' | 'forgot';

const TEXT = {
  register: {
    title: 'Đăng ký tài khoản',
    emailHint: 'Chúng tôi sẽ gửi mã OTP 6 số tới email này để xác thực.',
    passwordLabel: 'Đặt mật khẩu (tối thiểu 10 ký tự)',
    submit: 'Tạo tài khoản',
    tokenField: 'registration_token',
    finish: '/auth/register/complete',
  },
  forgot: {
    title: 'Quên mật khẩu',
    emailHint: 'Nhập email đã đăng ký, chúng tôi sẽ gửi mã OTP 6 số để đặt lại mật khẩu.',
    passwordLabel: 'Mật khẩu mới (tối thiểu 10 ký tự)',
    submit: 'Đặt lại mật khẩu',
    tokenField: 'reset_token',
    finish: '/auth/forgot/reset',
  },
} as const;

type Props = { kind: Kind; onBack: () => void };

export default function OtpFlow({ kind, onBack }: Props) {
  const t = TEXT[kind];
  const [step, setStep] = useState<'email' | 'otp' | 'password' | 'done'>('email');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [token, setToken] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [cooldown, setCooldown] = useState(0);
  const [doneMessage, setDoneMessage] = useState('');

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function sendCode() {
    const result = await api(`/auth/${kind}/start`, {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
    setInfo(result.message);
    setCooldown(60);
    setStep('otp');
  }

  function submitEmail(event: FormEvent) {
    event.preventDefault();
    run(sendCode);
  }

  function submitCode(event: FormEvent) {
    event.preventDefault();
    run(async () => {
      const result = await api(`/auth/${kind}/verify`, {
        method: 'POST',
        body: JSON.stringify({ email, code }),
      });
      setToken(result[t.tokenField]);
      setStep('password');
    });
  }

  function submitPassword(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setError('Hai mật khẩu không khớp.');
      return;
    }
    run(async () => {
      const result = await api(t.finish, {
        method: 'POST',
        body: JSON.stringify({ token, password }),
      });
      setDoneMessage(result.message);
      setStep('done');
    });
  }

  return (
    <div className="auth-card">
      <h2>{t.title}</h2>

      {error && <div className="error">{error}</div>}

      {step === 'email' && (
        <form onSubmit={submitEmail}>
          <p className="muted">{t.emailHint}</p>
          <label>Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="example@gmail.com"
            autoComplete="email"
            autoFocus
          />
          <button className="primary" disabled={busy || !email.trim()}>
            {busy ? 'Đang gửi...' : 'Gửi mã OTP'}
          </button>
        </form>
      )}

      {step === 'otp' && (
        <form onSubmit={submitCode}>
          {info && <p className="note">{info}</p>}
          <label>Mã OTP (6 số)</label>
          <input
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            placeholder="123456"
            inputMode="numeric"
            autoComplete="one-time-code"
            autoFocus
          />
          <button className="primary" disabled={busy || code.length !== 6}>
            {busy ? 'Đang kiểm tra...' : 'Xác nhận'}
          </button>
          <button
            type="button"
            className="link"
            disabled={busy || cooldown > 0}
            onClick={() => run(sendCode)}
          >
            {cooldown > 0 ? `Gửi lại mã sau ${cooldown}s` : 'Gửi lại mã'}
          </button>
        </form>
      )}

      {step === 'password' && (
        <form onSubmit={submitPassword}>
          <label>{t.passwordLabel}</label>
          <PasswordInput
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            autoFocus
          />
          <label>Nhập lại mật khẩu</label>
          <PasswordInput
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
          />
          <button className="primary" disabled={busy || password.length < 10 || !confirm}>
            {busy ? 'Đang xử lý...' : t.submit}
          </button>
        </form>
      )}

      {step === 'done' && (
        <>
          <div className="safe">{doneMessage}</div>
          <button className="primary" onClick={onBack}>
            Về trang đăng nhập
          </button>
        </>
      )}

      {step !== 'done' && (
        <button type="button" className="link" onClick={onBack}>
          ← Quay lại đăng nhập
        </button>
      )}
    </div>
  );
}
