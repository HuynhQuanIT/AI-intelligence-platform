import {
  Activity,
  Bot,
  CircleDollarSign,
  Database,
  LayoutDashboard,
  MessageSquare,
  ShieldCheck,
  Workflow,
} from 'lucide-react';
import type { Page } from '../types';

export const GROUPS = ['OVERVIEW', 'BUILD', 'OPTIMIZE', 'OBSERVE'] as const;

export const NAV_ITEMS: { name: Page; icon: typeof Bot; group: (typeof GROUPS)[number] }[] = [
  { name: 'Dashboard', icon: LayoutDashboard, group: 'OVERVIEW' },
  { name: 'Agent Studio', icon: Bot, group: 'BUILD' },
  { name: 'Knowledge Center', icon: Database, group: 'BUILD' },
  { name: 'AI Playground', icon: MessageSquare, group: 'BUILD' },
  { name: 'Model Routing', icon: Workflow, group: 'OPTIMIZE' },
  { name: 'Cost Optimization', icon: CircleDollarSign, group: 'OPTIMIZE' },
  { name: 'LLMOps Monitoring', icon: Activity, group: 'OBSERVE' },
  { name: 'Security Center', icon: ShieldCheck, group: 'OBSERVE' },
];

export const PAGE_DESCRIPTIONS: Record<Page, string> = {
  Dashboard: 'Unified view of your AI platform.',
  'Agent Studio': 'Inspect the multi-agent execution workflow.',
  'Knowledge Center': 'Manage documents and AI context.',
  'AI Playground': 'Test prompts and run RAG-enabled assistant.',
  'Model Routing': 'Configure model providers and routing.',
  'Cost Optimization': 'Track tokens and estimated AI spend.',
  'LLMOps Monitoring': 'Inspect latency, usage and traces.',
  'Security Center': 'Scan suspicious prompts and review events.',
};
