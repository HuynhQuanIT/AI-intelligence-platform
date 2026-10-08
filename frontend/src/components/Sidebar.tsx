import { BrainCircuit, LogOut } from 'lucide-react';
import { GROUPS, pagesFor } from '../config/navigation';
import type { Page, User } from '../types';

type Props = { page: Page; onSelect: (page: Page) => void; user: User; onLogout: () => void };

export default function Sidebar({ page, onSelect, user, onLogout }: Props) {
  const items = pagesFor(user.role);

  return (
    <aside>
      <div className="brand">
        <div className="logo">
          <BrainCircuit />
        </div>

        <b>
          AI Intelligence
          <small>PLATFORM</small>
        </b>
      </div>

      <div className="workspace" title={user.email}>
        {user.email}
        <small className="role-badge">{user.role === 'admin' ? 'Admin' : 'User'}</small>
      </div>

      {GROUPS.map((group) => {
        const inGroup = items.filter((item) => item.group === group);
        if (!inGroup.length) return null;

        return (
          <section className="navgroup" key={group}>
            <label>{group}</label>

            {inGroup.map(({ name, icon: Icon }) => (
              <button
                className={page === name ? 'nav active' : 'nav'}
                onClick={() => onSelect(name)}
                key={name}
              >
                <Icon size={17} />
                {name}
              </button>
            ))}
          </section>
        );
      })}

      <button className="nav logout" onClick={onLogout}>
        <LogOut size={17} />
        Đăng xuất
      </button>

      <div className="status">● All systems operational</div>
    </aside>
  );
}
