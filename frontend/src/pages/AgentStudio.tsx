import { Bot } from 'lucide-react';
import Panel from '../components/Panel';
import type { Agent } from '../types';

export default function AgentStudio({ agents }: { agents: Agent[] }) {
  return (
    <Panel title="LangGraph multi-agent workflow">
      <div className="flow">
        <div className="node">
          ◈　<b>User Request</b>
        </div>

        <span>↓</span>

        <div className="node purple">
          ◉　<b>Supervisor Agent</b>
          <small>Task routing &amp; orchestration</small>
        </div>

        <span>↓</span>

        <div className="agents">
          {agents
            .filter((agent) => agent.id !== 'supervisor')
            .map((agent) => (
              <div className="node" key={agent.id}>
                <Bot />
                <b>{agent.name}</b>
                <small>{agent.description}</small>
              </div>
            ))}
        </div>

        <span>↓</span>

        <div className="node green">
          ✓　<b>Final Response</b>
        </div>
      </div>

      <p className="note">
        Current workflow is a sequential LangGraph pipeline. Conditional routing, retries and human approval are
        extension points.
      </p>
    </Panel>
  );
}
