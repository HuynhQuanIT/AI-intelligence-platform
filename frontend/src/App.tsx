import { useAuth } from './auth/AuthContext';
import AuthScreen from './pages/auth/AuthScreen';
import Workspace from './Workspace';

// Chưa đăng nhập thì chỉ thấy màn hình đăng nhập/đăng ký; đã đăng nhập thì vào không gian làm việc.
export default function App() {
  const { user, loading } = useAuth();

  if (loading) return <div className="splash">Đang tải…</div>;
  if (!user) return <AuthScreen />;

  // key: đổi người dùng thì dựng lại toàn bộ trạng thái, không để lọt dữ liệu của người trước.
  return <Workspace key={user.id} user={user} />;
}
