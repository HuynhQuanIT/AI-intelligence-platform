import { BrainCircuit, Zap } from 'lucide-react';
import Panel from '../components/Panel';

export default function ModelRouting() {
  return (
    <Panel title="Model provider configuration">
      <div className="row">
        <BrainCircuit />

        <div>
          <b>Mock Local Provider</b>
          <small>Works without API key</small>
        </div>

        <em>Active</em>
      </div>

      <div className="row">
        <Zap />

        <div>
          <b>OpenAI-compatible provider</b>
          <small>Set LLM_PROVIDER=openai and OPENAI_API_KEY in .env</small>
        </div>

        <em>Configurable</em>
      </div>

      <h3>Routing policy</h3>

      <div className="kv">
        Simple requests <b>Small / low-cost model</b>
      </div>

      <div className="kv">
        Complex requests <b>High-capability model</b>
      </div>

      <div className="kv">
        Fallback <b>Mock provider</b>
      </div>
    </Panel>
  );
}
