const BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export type Health = {
  status: string;
  has_openai_key: boolean;
  has_sendgrid_key: boolean;
};

export type SpotRate = { rate: number; date: string };

export type SpotDelta = {
  prev_rate: number | null;
  d1_abs: number | null;
  d1_pct: number | null;
  d30_abs: number | null;
  d30_pct: number | null;
};

export type ForwardPoint = {
  tenor: string;
  tenor_months: number;
  forward_rate: number;
  forward_premium_bps: number;
  annualized_premium_pct: number;
};

export type HedgingAssessment = {
  tenor: string;
  current_premium_bps: number;
  avg_30d_premium_bps: number | null;
  verdict: "CHEAP" | "FAIR" | "EXPENSIVE";
};

export type MarketLatest = {
  date: string;
  spot_rates: Record<string, SpotRate>;
  spot_deltas: Record<string, SpotDelta>;
  forward_curves: Record<string, ForwardPoint[]>;
  "30d_avg_spot": Record<string, number | null>;
  hedging_assessment: Record<string, HedgingAssessment>;
  interest_rates: Record<string, number>;
  alerts: Array<{ type: string; message: string; threshold: string; actual: string }>;
};

export type Alert = {
  id: number;
  date: string;
  alert_type: string;
  message: string;
  threshold: string;
  actual_value: string;
  triggered_at: string;
};

export type BriefingSummary = {
  date: string;
  generated_at: string;
  delivered: number;
  delivery_error: string | null;
  usdinr: number | null;
  eurinr: number | null;
  alerts_count: number;
};

export type BriefingSections = {
  overnight_highlights?: string[];
  rbi_update?: string;
  forward_premium_analysis?: string;
  macro_watch?: string;
  action_items?: string[];
  _fallback?: boolean;
};

export type NewsItem = {
  category: string;
  headline: string | null;
  summary: string | null;
  relevance: string | null;
  source_url: string | null;
};

export type BriefingDetail = {
  date: string;
  generated_at: string;
  delivered: number;
  delivery_error: string | null;
  sections: BriefingSections | null;
  spot_rates: Array<{ pair: string; spot_rate: number; source: string; fetched_at: string; quote_date: string }>;
  forward_rates: Array<{ pair: string; tenor: string; forward_rate: number; forward_premium_bps: number; india_rate: number; foreign_rate: number }>;
  alerts: Array<Omit<Alert, "id" | "date">>;
  news: NewsItem[];
};

export type StageName = "forex" | "news" | "briefing" | "delivery";
export type StageState = "pending" | "active" | "done" | "skipped" | "error";

export type RunState = {
  status: "idle" | "running" | "success" | "error";
  stage: StageName | "complete" | null;
  stage_status: Record<StageName, StageState>;
  started_at: string | null;
  finished_at: string | null;
  dry_run: boolean | null;
  error: string | null;
  html_path: string | null;
  briefing_date: string | null;
};

export type EvidenceTable = {
  source: string;
  file: string;
  type: "table";
  headers: string[];
  rows: string[][];
};

export type EvidenceText = {
  source: string;
  file: string;
  type: "text";
  content: string;
};

export type EvidenceMetric = {
  source: string;
  file: string;
  type: "metric";
  items: Array<{ label: string; value: string }>;
};

export type Evidence = EvidenceTable | EvidenceText | EvidenceMetric;

export type ComplianceInsight = {
  severity: string;
  category: string;
  title: string;
  description: string;
  affected_docs: string;
  recommended_action: string;
  evidence: Evidence[];
};

export type ComplianceScan = {
  scan_date: string;
  total_insights: number;
  by_severity: Record<string, number>;
  by_category: Record<string, number>;
  insights: ComplianceInsight[];
};

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${path} -> HTTP ${r.status}`);
  return (await r.json()) as T;
}

async function post<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { method: "POST" });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`${path} -> HTTP ${r.status}: ${body}`);
  }
  return (await r.json()) as T;
}

export const api = {
  health: () => get<Health>("/api/health"),
  marketLatest: () => get<MarketLatest>("/api/market/latest"),
  alerts: (limit = 20) => get<Alert[]>(`/api/alerts?limit=${limit}`),
  briefings: (limit = 50) => get<BriefingSummary[]>(`/api/briefings?limit=${limit}`),
  briefing: (date: string) => get<BriefingDetail>(`/api/briefings/${date}`),
  briefingHtmlUrl: (date: string) => `${BASE}/api/briefings/${date}/html`,
  run: (dryRun = true) => post<{ accepted: boolean; dry_run?: boolean; reason?: string }>(`/api/run?dry_run=${dryRun}`),
  runStatus: () => get<RunState>("/api/run/status"),
  compliance: () => get<ComplianceScan>("/api/compliance"),
  complianceLatest: () => get<ComplianceScan>("/api/compliance/latest"),
};
