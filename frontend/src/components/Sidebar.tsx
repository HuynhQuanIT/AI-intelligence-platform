import { BrainCircuit } from 'lucide-react';
import { GROUPS, NAV_ITEMS } from '../config/navigation';
import type { Page } from '../types';

type Props = { page: Page; onSelect: (page: Page) => void };

export default function Sidebar({ page, onSelect }: Props) {
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

      <div className="workspace">Q　 Workspace Demo</div>

      {GROUPS.map((group) => (
        <section className="navgroup" key={group}>
          <label>{group}</label>

          {NAV_ITEMS.filter((item) => item.group === group).map(({ name, icon: Icon }) => (
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
      ))}

      <div className="status">● All systems operational</div>
    </aside>
  );
}
