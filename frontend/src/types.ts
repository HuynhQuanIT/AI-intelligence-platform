// Kiểu dữ liệu dùng chung giữa các trang.

export type Page =
  | 'Dashboard'
  | 'Agent Studio'
  | 'Knowledge Center'
  | 'AI Playground'
  | 'Model Routing'
  | 'Cost Optimization'
  | 'LLMOps Monitoring'
  | 'Security Center'
  | 'User Management'
  | 'Groups'
  | 'My Account';

export type Role = 'admin' | 'user';

export type Quota = {
  limit: number | null; // null = không giới hạn
  used: number;
  remaining: number | null;
  is_default: boolean;
  resets_at: string;
};

export type GroupRef = { id: string; name: string };

export type MyGroup = {
  id: string;
  name: string;
  description: string;
  document_count: number;
  added_at: string | null;
};

// Người dùng xem được gì: nhóm của mình, tổng tài liệu xem được, số tài liệu thuộc các nhóm của mình.
export type Access = { groups: MyGroup[]; visible_documents: number; group_documents: number };

export type User = {
  id: string;
  email: string;
  role: Role;
  is_active: boolean;
  created_at: string | null;
  last_login_at: string | null;
  daily_message_quota?: number | null;
  quota?: Quota; // chỉ có ở /auth/me
  access?: Access; // chỉ có ở /auth/me
};

export type Group = {
  id: string;
  name: string;
  description: string;
  member_count: number;
  document_count: number;
};

export type GroupDetail = Group & {
  members: { id: string; email: string }[];
  documents: { id: string; title: string }[];
};

export type UserUsage = {
  id: string;
  email: string;
  role: Role;
  is_active: boolean;
  requests: number;
  blocked: number;
  errors: number;
  tokens: number;
  cost_usd: number;
  today: number;
  last_at: string | null;
  security_events: number;
  quota_limit: number | null;
};

export type UserDetail = User & {
  email_verified_at: string | null;
  updated_at: string | null;
  failed_attempts: number;
  locked_until: string | null;
  is_locked: boolean;
  conversation_count: number;
  message_count: number;
  request_count: number;
  total_tokens: number;
  total_cost_usd: number;
  last_request_at: string | null;
  quota: Quota;
  groups: GroupRef[];
};

export type Conversation = {
  id: string;
  title: string;
  updated_at: string;
};

export type LiveStep = { step: string; status: string; detail: string };

export type ChatMessage = {
  role: 'user' | 'ai';
  text: string;
  streaming?: boolean;
  meta?: {
    model?: string;
    latency_ms?: number;
    input_tokens?: number;
    output_tokens?: number;
    cost_usd?: number;
    blocked?: boolean;
    sources?: SourceRef[];
  };
};

// Một đoạn tài liệu chatbot đã dùng để trả lời, kèm nhãn quyền của tài liệu đó.
export type SourceRef = {
  document_id?: string | null;
  title?: string | null;
  chunk_index?: number | null;
  similarity?: number | null;
  snippet?: string;
  content?: string;
  scope?: 'public' | 'group';
  groups?: GroupRef[];
};

export type Agent = { id: string; name: string; description: string };

export type DocumentRow = {
  id: string;
  title: string;
  filename: string;
  status: 'processing' | 'processed' | 'failed' | string;
  error?: string | null; // lý do khi status = failed (chỉ admin nhận)
  created_at: string;
  size_bytes?: number | null;
  has_file?: boolean;
  groups?: GroupRef[]; // admin: mọi nhóm; user: chỉ nhóm của mình. Admin rỗng = công khai
  scope?: 'public' | 'group'; // chỉ user thường nhận
};

export type DocumentDetail = {
  id: string;
  title: string;
  filename: string;
  status: string;
  chunks?: { chunk_index: number; content: string }[];
};

export type TraceRow = {
  id: number;
  request_id: string;
  step: string;
  status: string;
  created_at: string;
};

export type SecurityEvent = {
  id: number;
  event_type: string;
  severity: string;
  description: string;
  user_email?: string | null;
};

export type Totals = {
  requests?: number;
  cost_usd?: number;
  avg_latency_ms?: number;
  total_tokens?: number;
};

export type Metrics = { totals?: Totals };

// Dữ liệu dùng chung của nền tảng, do usePlatformData nạp và chuyền xuống các trang.
export type PlatformData = {
  metrics: Metrics;
  agents: Agent[];
  docs: DocumentRow[];
  traces: TraceRow[];
  events: SecurityEvent[];
  setErr: (message: string) => void;
  refresh: () => Promise<void>;
  refreshDocs: () => Promise<void>; // nạp riêng danh sách tài liệu (nhẹ), dùng khi chờ xử lý nền
};
