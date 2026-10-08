import { Bot, Boxes, ChevronRight, CircleDollarSign, Gauge, Zap } from 'lucide-react';
import Panel from '../components/Panel';
import Stat from '../components/Stat';
import TraceTable from '../components/TraceTable';
import { NAV_ITEMS } from '../config/navigation';
import type { Page, PlatformData } from '../types';

type Props = Pick<PlatformData, 'metrics' | 'agents' | 'traces'> & { onNavigate: (page: Page) => void };

export default function Dashboard({ metrics, agents, traces, onNavigate }: Props) {
  const total = metrics.totals || {};

  return (
    <>
      <div className="stats">
        <Stat icon={Zap} label="Total requests" value={total.requests ?? 0} />
        <Stat icon={CircleDollarSign} label="Total AI cost" value={'$' + Number(total.cost_usd || 0).toFixed(4)} />
        <Stat icon={Gauge} label="Avg latency" value={(total.avg_latency_ms || 0) + ' ms'} />
        <Stat icon={Boxes} label="Tokens processed" value={total.total_tokens ?? 0} />
      </div>

      <div className="cols">
        <Panel title="Platform modules">
          {NAV_ITEMS.filter((item) => item.name !== 'Dashboard' && item.roles.includes('admin')).map(({ name, icon: Icon }) => (
            <button className="rowbtn" onClick={() => onNavigate(name)} key={name}>
              <Icon size={17} />
              {name}
              <ChevronRight size={15} />
            </button>
          ))}
        </Panel>

        <Panel title="Configured agents">
          {agents.map((agent) => (
            <div className="row" key={agent.id}>
              <Bot />

              <div>
                <b>{agent.name}</b>
                <small>{agent.description}</small>
              </div>

              <em>Active</em>
            </div>
          ))}
        </Panel>
      </div>

      <Panel title="Recent execution traces">
        <TraceTable rows={traces.slice(0, 8)} />
      </Panel>
    </>
  );
}
