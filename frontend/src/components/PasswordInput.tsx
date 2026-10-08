import { useState, type InputHTMLAttributes } from 'react';
import { Eye, EyeOff } from 'lucide-react';

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, 'type'>;

// Ô nhập mật khẩu có nút con mắt bên phải để hiện/ẩn nội dung.
export default function PasswordInput(props: Props) {
  const [visible, setVisible] = useState(false);
  const label = visible ? 'Ẩn mật khẩu' : 'Hiện mật khẩu';

  return (
    <div className="password-field">
      <input {...props} type={visible ? 'text' : 'password'} />
      <button
        type="button"
        className="password-toggle"
        onClick={() => setVisible((v) => !v)}
        aria-label={label}
        title={label}
        aria-pressed={visible}
        tabIndex={0}
      >
        {visible ? <EyeOff size={16} /> : <Eye size={16} />}
      </button>
    </div>
  );
}
