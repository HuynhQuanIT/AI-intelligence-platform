import { useEffect, useState } from 'react';
import { Check, Info, RefreshCw, UserX } from 'lucide-react';
import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import Panel from '../components/Panel';
import UserDetailPanel from './UserDetailPanel';
import type { PlatformData, Role, User } from '../types';

type Props = Pick<PlatformData, 'setErr'>;

export default function UserManagement({ setErr }: Props) {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [busyId, setBusyId] = useState('');
  const [selectedId, setSelectedId] = useState('');

  async function load() {
    try {
      setUsers(await api('/users'));
      setErr('');
    } catch (error: any) {
      setErr('Không tải được danh sách người dùng: ' + error.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function act(id: string, path: string, body?: object) {
    setBusyId(id);
    try {
      await api(`/users/${encodeURIComponent(id)}/${path}`, {
        method: 'POST',
        body: body ? JSON.stringify(body) : undefined,
      });
      await load();
    } catch (error: any) {
      setErr(error.message);
    } finally {
      setBusyId('');
    }
  }

  const pending = users.filter((u) => !u.is_active);

  return (
    <>
      {pending.length > 0 && (
        <p className="note">Có {pending.length} tài khoản đang chờ duyệt hoặc đã bị vô hiệu hóa.</p>
      )}

      <Panel title={`Người dùng (${users.length})`}>
        <button className="secondary" onClick={load}>
          <RefreshCw size={15} />
          Tải lại
        </button>

        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>Email</th>
                <th>Vai trò</th>
                <th>Trạng thái</th>
                <th>Đăng nhập gần nhất</th>
                <th></th>
              </tr>
            </thead>

            <tbody>
              {users.map((u) => {
                const self = u.id === me?.id;
                return (
                  <tr key={u.id}>
                    <td>
                      {u.email}
                      {self && <small> (bạn)</small>}
                    </td>
                    <td>
                      <select
                        value={u.role}
                        disabled={self || busyId === u.id}
                        onChange={(e) => act(u.id, 'role', { role: e.target.value as Role })}
                      >
                        <option value="user">user</option>
                        <option value="admin">admin</option>
                      </select>
                    </td>
                    <td>
                      <em>{u.is_active ? 'Hoạt động' : 'Chờ duyệt / vô hiệu'}</em>
                    </td>
                    <td>{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : '—'}</td>
                    <td>
                      <button className="secondary" onClick={() => setSelectedId(u.id)}>
                        <Info size={15} />
                        Chi tiết
                      </button>
                      {!u.is_active && (
                        <button className="secondary" disabled={busyId === u.id} onClick={() => act(u.id, 'approve')}>
                          <Check size={15} />
                          Duyệt
                        </button>
                      )}
                      {u.is_active && !self && (
                        <button
                          className="secondary"
                          disabled={busyId === u.id}
                          onClick={() => {
                            if (window.confirm(`Vô hiệu hóa ${u.email}? Họ sẽ bị đăng xuất ngay.`)) {
                              act(u.id, 'deactivate');
                            }
                          }}
                        >
                          <UserX size={15} />
                          Vô hiệu hóa
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {selectedId && (
        <UserDetailPanel
          userId={selectedId}
          isSelf={selectedId === me?.id}
          onClose={() => setSelectedId('')}
          onChanged={load}
        />
      )}
    </>
  );
}
