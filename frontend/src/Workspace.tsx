import { useEffect, useState } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { useAuth } from './auth/AuthContext';
import Sidebar from './components/Sidebar';
import NewGroupBanner from './components/NewGroupBanner';
import { PAGE_DESCRIPTIONS, homePageFor, pagesFor } from './config/navigation';
import { usePlatformData } from './hooks/usePlatformData';
import AgentStudio from './pages/AgentStudio';
import CostOptimization from './pages/CostOptimization';
import Dashboard from './pages/Dashboard';
import KnowledgeCenter from './pages/KnowledgeCenter';
import ModelRouting from './pages/ModelRouting';
import Monitoring from './pages/Monitoring';
import Playground from './pages/Playground';
import SecurityCenter from './pages/SecurityCenter';
import Account from './pages/Account';
import GroupManagement from './pages/GroupManagement';
import UserManagement from './pages/UserManagement';
import type { Page, User } from './types';

// Khung ứng dụng sau khi đăng nhập: thanh bên theo vai trò, tiêu đề, thông báo lỗi và chọn trang.
export default function Workspace({ user }: { user: User }) {
  const { logout, refreshUser } = useAuth();
  const [page, setPage] = useState<Page>(homePageFor(user.role));
  const { metrics, agents, docs, traces, events, err, setErr, refresh, refreshDocs } = usePlatformData(user.role);
  const isAdmin = user.role === 'admin';

  // Đổi vai trò hoặc đăng nhập lại bằng người khác: về trang mặc định nếu trang hiện tại không còn được phép.
  useEffect(() => {
    if (!pagesFor(user.role).some((item) => item.name === page)) setPage(homePageFor(user.role));
  }, [user.role, page]);

  // Admin vừa thêm/bớt nhóm thì người dùng thấy ngay khi quay lại tab, không phải đăng nhập lại.
  useEffect(() => {
    if (isAdmin) return;
    const onFocus = () => { refreshUser().catch(() => undefined); };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [isAdmin, refreshUser]);

  return (
    <div className="app">
      <Sidebar page={page} onSelect={setPage} user={user} onLogout={logout} />

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

          {!isAdmin && <NewGroupBanner access={user.access} onOpen={setPage} />}

          {err && (
            <div className="error">
              <AlertTriangle size={16} />
              {err}
            </div>
          )}

          {page === 'Dashboard' && isAdmin && (
            <Dashboard metrics={metrics} agents={agents} traces={traces} onNavigate={setPage} />
          )}
          {page === 'Agent Studio' && isAdmin && <AgentStudio agents={agents} />}
          {page === 'Knowledge Center' && (
            <KnowledgeCenter docs={docs} refresh={refresh} refreshDocs={refreshDocs} setErr={setErr} canEdit={isAdmin} />
          )}
          {page === 'AI Playground' && <Playground refresh={refresh} setErr={setErr} />}
          {page === 'Model Routing' && isAdmin && <ModelRouting />}
          {page === 'Cost Optimization' && isAdmin && <CostOptimization metrics={metrics} />}
          {page === 'LLMOps Monitoring' && isAdmin && <Monitoring traces={traces} />}
          {page === 'Security Center' && isAdmin && (
            <SecurityCenter events={events} refresh={refresh} setErr={setErr} />
          )}
          {page === 'User Management' && isAdmin && <UserManagement setErr={setErr} />}
          {page === 'Groups' && isAdmin && <GroupManagement setErr={setErr} refresh={refresh} />}
          {page === 'My Account' && <Account />}
        </article>
      </main>
    </div>
  );
}
