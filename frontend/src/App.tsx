import { useState } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import Sidebar from './components/Sidebar';
import { PAGE_DESCRIPTIONS } from './config/navigation';
import { usePlatformData } from './hooks/usePlatformData';
import AgentStudio from './pages/AgentStudio';
import CostOptimization from './pages/CostOptimization';
import Dashboard from './pages/Dashboard';
import KnowledgeCenter from './pages/KnowledgeCenter';
import ModelRouting from './pages/ModelRouting';
import Monitoring from './pages/Monitoring';
import Playground from './pages/Playground';
import SecurityCenter from './pages/SecurityCenter';
import type { Page } from './types';

// Khung ứng dụng: thanh bên, tiêu đề, thông báo lỗi chung và chọn trang.
export default function App() {
  const [page, setPage] = useState<Page>('Dashboard');
  const { metrics, agents, docs, traces, events, err, setErr, refresh } = usePlatformData();

  return (
    <div className="app">
      <Sidebar page={page} onSelect={setPage} />

      <main>
        <header>
          <span>
            Workspace　›　<b>{page}</b>
          </span>

          <span className="env">● DEMO ENVIRONMENT</span>
        </header>

        <article>
          <div className="heading">
            <div>
              <small>AI INTELLIGENCE PLATFORM / {page.toUpperCase()}</small>

              <h1>{page}</h1>

              <p>{PAGE_DESCRIPTIONS[page]}</p>
            </div>

            <button className="secondary" onClick={refresh}>
              <RefreshCw size={15} />
              Refresh
            </button>
          </div>

          {err && (
            <div className="error">
              <AlertTriangle size={16} />
              {err}
            </div>
          )}

          {page === 'Dashboard' && (
            <Dashboard metrics={metrics} agents={agents} traces={traces} onNavigate={setPage} />
          )}
          {page === 'Agent Studio' && <AgentStudio agents={agents} />}
          {page === 'Knowledge Center' && <KnowledgeCenter docs={docs} refresh={refresh} setErr={setErr} />}
          {page === 'AI Playground' && <Playground refresh={refresh} setErr={setErr} />}
          {page === 'Model Routing' && <ModelRouting />}
          {page === 'Cost Optimization' && <CostOptimization metrics={metrics} />}
          {page === 'LLMOps Monitoring' && <Monitoring traces={traces} />}
          {page === 'Security Center' && (
            <SecurityCenter events={events} refresh={refresh} setErr={setErr} />
          )}
        </article>
      </main>
    </div>
  );
}
