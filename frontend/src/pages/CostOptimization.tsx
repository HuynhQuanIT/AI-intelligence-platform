import { Activity, CircleDollarSign, Gauge, Zap } from 'lucide-react';
import Panel from '../components/Panel';
import Stat from '../components/Stat';
import type { Metrics } from '../types';

const CONTROLS = [
  ['Usage tracking', 'Implemented'],
  ['Exact response cache', 'Planned'],
  ['Semantic cache', 'Planned'],
  ['Prompt compression', 'Planned'],
  ['Model routing', 'Basic config'],
];

export default function CostOptimization({ metrics }: { metrics: Metrics }) {
  const total = metrics.totals || {};

  return (
    <>
      <div className="stats">
        <Stat icon={CircleDollarSign} label="Estimated cost" value={'$' + Number(total.cost_usd || 0).toFixed(4)} />
        <Stat icon={Zap} label="Requests" value={total.requests || 0} />
        <Stat icon={Gauge} label="Avg latency" value={(total.avg_latency_ms || 0) + ' ms'} />
        <Stat icon={Activity} label="Total tokens" value={total.total_tokens || 0} />
      </div>

      <Panel title="Optimization controls">
        {CONTROLS.map(([name, status]) => (
          <div className="kv" key={name}>
            {name}
            <em>{status}</em>
          </div>
        ))}
      </Panel>
    </>
  );
}
