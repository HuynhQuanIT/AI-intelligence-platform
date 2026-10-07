// Kiểu dữ liệu dùng chung giữa các trang.

export type Page =
  | 'Dashboard'
  | 'Agent Studio'
  | 'Knowledge Center'
  | 'AI Playground'
  | 'Model Routing'
  | 'Cost Optimization'
  | 'LLMOps Monitoring'
  | 'Security Center';

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
  };
};

export type Agent = { id: string; name: string; description: string };

export type DocumentRow = {
  id: string;
  title: string;
  filename: string;
  status: string;
  created_at: string;
  size_bytes?: number | null;
  has_file?: boolean;
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
};
