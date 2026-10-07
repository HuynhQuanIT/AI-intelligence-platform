import Panel from '../components/Panel';
import TraceTable from '../components/TraceTable';
import type { TraceRow } from '../types';

export default function Monitoring({ traces }: { traces: TraceRow[] }) {
  return (
    <Panel title="Execution traces">
      <TraceTable rows={traces} />

      {!traces.length && <p className="muted">Send a message in AI Playground to create traces.</p>}
    </Panel>
  );
}
