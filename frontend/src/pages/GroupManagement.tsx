import { useEffect, useState, type FormEvent } from 'react';
import { Plus, Save, Trash2 } from 'lucide-react';
import { api } from '../api/client';
import Panel from '../components/Panel';
import '../components/extras.css';
import type { Group, GroupDetail, PlatformData, User } from '../types';

type Props = Pick<PlatformData, 'setErr' | 'refresh'>;

// Quản lý nhóm: tạo/xóa nhóm và chọn thành viên. Gán nhóm cho tài liệu làm ở Knowledge Center.
// Quy tắc: tài liệu không thuộc nhóm nào thì mọi người đều xem; thuộc nhóm thì chỉ thành viên (và admin) xem.
export default function GroupManagement({ setErr, refresh }: Props) {
  const [groups, setGroups] = useState<Group[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [selected, setSelected] = useState<GroupDetail | null>(null);
  const [members, setMembers] = useState<Set<string>>(new Set());
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [search, setSearch] = useState('');

  async function load(selectId?: string) {
    try {
      const [g, u] = await Promise.all([api('/groups'), api('/users')]);
      setGroups(g);
      setUsers(u);
      const id = selectId ?? selected?.id;
      if (id && g.some((x: Group) => x.id === id)) await open(id);
      else setSelected(null);
      setErr('');
    } catch (error: any) {
      setErr('Không tải được nhóm: ' + error.message);
    }
  }

  async function open(id: string) {
    const detail: GroupDetail = await api(`/groups/${encodeURIComponent(id)}`);
    setSelected(detail);
    setSearch('');
    setMembers(new Set(detail.members.map((m) => m.id)));
  }

  useEffect(() => {
    load();
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const created: GroupDetail = await api('/groups', {
        method: 'POST',
        body: JSON.stringify({ name, description }),
      });
      setName('');
      setDescription('');
      await load(created.id);
    } catch (error: any) {
      setErr(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function saveMembers() {
    if (!selected) return;
    setBusy(true);
    try {
      await api(`/groups/${encodeURIComponent(selected.id)}/members`, {
        method: 'PUT',
        body: JSON.stringify({ ids: [...members] }),
      });
      setNote('Đã lưu thành viên.');
      await load(selected.id);
    } catch (error: any) {
      setErr(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!selected) return;
    if (!window.confirm(`Xóa nhóm "${selected.name}"?`)) return;
    setBusy(true);
    try {
      await api(`/groups/${encodeURIComponent(selected.id)}`, { method: 'DELETE' });
      setSelected(null);
      await load();
      await refresh();
    } catch (error: any) {
      setErr(error.message); // ví dụ: nhóm đang là nhóm duy nhất của một tài liệu
    } finally {
      setBusy(false);
    }
  }

  function toggle(id: string) {
    setMembers((current) => {
      const copy = new Set(current);
      if (copy.has(id)) copy.delete(id);
      else copy.add(id);
      return copy;
    });
  }

  return (
    <div className="group-page">
    <div className="howto">
      <div><b><span className="step">1</span>Tạo nhóm</b>Ví dụ "Phòng Kế toán". Nhóm chỉ là một danh sách người dùng.</div>
      <div><b><span className="step">2</span>Thêm thành viên</b>Chọn những người được phép đọc tài liệu của nhóm rồi bấm Lưu thành viên.</div>
      <div><b><span className="step">3</span>Gán tài liệu</b>Vào Knowledge Center, bấm "Quyền xem" ở tài liệu và chọn nhóm. Tài liệu không gán nhóm thì ai cũng xem được.</div>
    </div>
    <div className="group-layout">
      <div>
        <Panel title={`Nhóm (${groups.length})`}>
          {groups.map((g) => (
            <button
              key={g.id}
              className={'group-item' + (selected?.id === g.id ? ' active' : '')}
              onClick={() => {
                setNote('');
                open(g.id).catch((e) => setErr(e.message));
              }}
            >
              <b>{g.name}</b>
              <small>{g.member_count} người · {g.document_count} tài liệu</small>
            </button>
          ))}
          {!groups.length && <p className="muted">Chưa có nhóm nào.</p>}
        </Panel>

        <Panel title="Tạo nhóm mới">
          <form onSubmit={create} className="form-stack">
            <label>Tên nhóm</label>
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="Phòng Kế toán" />
            <label>Mô tả (không bắt buộc)</label>
            <input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} />
            <button className="primary" disabled={busy || !name.trim()}>
              <Plus size={15} />
              Tạo nhóm
            </button>
          </form>
        </Panel>
      </div>

      <Panel title={selected ? `Nhóm: ${selected.name}` : 'Chi tiết nhóm'}>
        {!selected && <p className="muted">Chọn một nhóm để chỉnh thành viên.</p>}

        {selected && (
          <>
            {selected.description && <p className="note">{selected.description}</p>}

            <h4 className="subhead">Thành viên</h4>
            <div className="search-row">
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Tìm theo email..."
                aria-label="Tìm người dùng"
              />
              <small>Đã chọn {members.size}/{users.length} người</small>
            </div>
            <div className="checklist">
              {users
                .filter((u) => u.email.toLowerCase().includes(search.trim().toLowerCase()))
                .map((u) => (
                  <label key={u.id}>
                    <input type="checkbox" checked={members.has(u.id)} onChange={() => toggle(u.id)} />
                    <span className="grow">{u.email}</span>
                    {u.role === 'admin' && <span className="role-chip" title="Admin xem được mọi tài liệu">admin</span>}
                  </label>
                ))}
            </div>

            <div className="inline-form" style={{ marginTop: 14 }}>
              <button className="primary" onClick={saveMembers} disabled={busy}>
                <Save size={15} />
                Lưu thành viên
              </button>
              <button className="danger" onClick={remove} disabled={busy}>
                <Trash2 size={15} />
                Xóa nhóm
              </button>
            </div>
            {note && <p className="success-note" role="status">{note}</p>}

            <h4 className="subhead">Tài liệu của nhóm ({selected.documents.length})</h4>
            {selected.documents.length ? (
              selected.documents.map((d) => <span className="chip" key={d.id} style={{ fontSize: 13 }}>{d.title}</span>)
            ) : (
              <p className="muted">Chưa có tài liệu. Gán nhóm cho tài liệu ở Knowledge Center.</p>
            )}
          </>
        )}
      </Panel>
    </div>
    </div>
  );
}
