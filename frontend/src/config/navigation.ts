import {
  Activity,
  Bot,
  CircleDollarSign,
  Database,
  LayoutDashboard,
  MessageSquare,
  ShieldCheck,
  Users,
  Workflow,
} from 'lucide-react';
import type { Page, Role } from '../types';

export const GROUPS = ['OVERVIEW', 'BUILD', 'OPTIMIZE', 'OBSERVE', 'ADMIN'] as const;

type NavItem = { name: Page; icon: typeof Bot; group: (typeof GROUPS)[number]; roles: Role[] };

const ALL: Role[] = ['admin', 'user'];

// roles: vai trò được thấy trang này. Server vẫn kiểm tra quyền; ẩn trang chỉ để giao diện gọn.
export const NAV_ITEMS: NavItem[] = [
  { name: 'Dashboard', icon: LayoutDashboard, group: 'OVERVIEW', roles: ['admin'] },
  { name: 'Agent Studio', icon: Bot, group: 'BUILD', roles: ['admin'] },
  { name: 'Knowledge Center', icon: Database, group: 'BUILD', roles: ALL },
  { name: 'AI Playground', icon: MessageSquare, group: 'BUILD', roles: ALL },
  { name: 'Model Routing', icon: Workflow, group: 'OPTIMIZE', roles: ['admin'] },
  { name: 'Cost Optimization', icon: CircleDollarSign, group: 'OPTIMIZE', roles: ['admin'] },
  { name: 'LLMOps Monitoring', icon: Activity, group: 'OBSERVE', roles: ['admin'] },
  { name: 'Security Center', icon: ShieldCheck, group: 'OBSERVE', roles: ['admin'] },
  { name: 'User Management', icon: Users, group: 'ADMIN', roles: ['admin'] },
];

export function pagesFor(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role));
}

export function homePageFor(role: Role): Page {
  return role === 'admin' ? 'Dashboard' : 'AI Playground';
}

export const PAGE_DESCRIPTIONS: Record<Page, string> = {
  Dashboard: 'Unified view of your AI platform.',
  'Agent Studio': 'Inspect the multi-agent execution workflow.',
  'Knowledge Center': 'Manage documents and AI context.',
  'AI Playground': 'Test prompts and run RAG-enabled assistant.',
  'Model Routing': 'Configure model providers and routing.',
  'Cost Optimization': 'Track tokens and estimated AI spend.',
  'LLMOps Monitoring': 'Inspect latency, usage and traces.',
  'Security Center': 'Scan suspicious prompts and review events.',
  'User Management': 'Approve accounts and manage roles.',
};
