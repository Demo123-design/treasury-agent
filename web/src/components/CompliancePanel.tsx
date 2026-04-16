import { useCallback, useEffect, useState } from "react";
import type { ComplianceScan, ComplianceInsight, Evidence } from "../api";
import { api } from "../api";

/* ── constants ──────────────────────────────────────────────── */

const SEV: Record<string, { bg: string; fg: string; border: string; dot: string }> = {
  CRITICAL: { bg: "#fdecea", fg: "#a71d2a", border: "#c0392b", dot: "#c0392b" },
  HIGH:     { bg: "#fff3e0", fg: "#b8560b", border: "#e67e22", dot: "#e67e22" },
  MEDIUM:   { bg: "#fff8e1", fg: "#7a6200", border: "#d4a800", dot: "#d4a800" },
  LOW:      { bg: "#eef4fb", fg: "#1a5ec5", border: "#3498db", dot: "#3498db" },
  INFO:     { bg: "#f4f6f8", fg: "#6b7680", border: "#bdc3c7", dot: "#95a5a6" },
};

const SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];

const CAT: Record<string, string> = {
  FEMA: "FEMA",
  CONCENTRATION: "Concentration",
  RATE_DIVERGENCE: "Rate Divergence",
  POLICY_GAP: "Policy Gap",
  UNHEDGED_EXPOSURE: "Unhedged Exposure",
  TENOR_LIMIT: "Tenor Limit",
  MTM_STOPLOSS: "MTM Stop-Loss",
  ACTION_OVERDUE: "Action Overdue",
  ACTION_DUE: "Action Due",
  QUOTE_ANOMALY: "Quote Anomaly",
  DATA_DISCREPANCY: "Data Mismatch",
  FORECAST_RISK: "Forecast Risk",
  REGULATORY: "Regulatory",
  CONTRACT_MATURITY: "Maturity",
};

/* ── severity bar ───────────────────────────────────────────── */

function SeverityBar({ data }: { data: ComplianceScan }) {
  const total = data.total_insights || 1;
  return (
    <div className="csev-bar-wrap">
      <div className="csev-bar">
        {SEV_ORDER.map(s => {
          const n = data.by_severity[s] || 0;
          if (!n) return null;
          const pct = Math.max((n / total) * 100, 6);
          const c = SEV[s];
          return (
            <div
              key={s}
              className="csev-segment"
              style={{ width: `${pct}%`, background: c.border }}
              title={`${n} ${s}`}
            />
          );
        })}
      </div>
      <div className="csev-legend">
        {SEV_ORDER.map(s => {
          const n = data.by_severity[s] || 0;
          if (!n) return null;
          return (
            <span key={s} className="csev-legend-item">
              <span className="csev-dot" style={{ background: SEV[s].dot }} />
              <strong>{n}</strong> {s}
            </span>
          );
        })}
        <span className="csev-legend-total">{total} findings</span>
      </div>
    </div>
  );
}

/* ── evidence renderers ─────────────────────────────────────── */

function EvidenceBlock({ ev }: { ev: Evidence }) {
  const fileLabel = ev.file && !ev.file.includes("Feed")
    ? ev.file : null;

  return (
    <div className="cev-block">
      <div className="cev-source">
        <span className="cev-source-icon">&#128196;</span>
        <span className="cev-source-name">{ev.source}</span>
        {fileLabel && <span className="cev-file">{fileLabel}</span>}
      </div>

      {ev.type === "table" && (
        <div className="cev-table-wrap">
          <table className="cev-table">
            <thead>
              <tr>{ev.headers.map((h, i) => <th key={i}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {ev.rows.map((row, ri) => (
                <tr key={ri}>
                  {row.map((cell, ci) => <td key={ci}>{cell}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {ev.type === "text" && (
        <blockquote className="cev-quote">{ev.content}</blockquote>
      )}

      {ev.type === "metric" && (
        <div className="cev-metrics">
          {ev.items.map((m, i) => (
            <div key={i} className="cev-metric">
              <span className="cev-metric-label">{m.label}</span>
              <span className="cev-metric-value">{m.value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── insight card ───────────────────────────────────────────── */

function InsightCard({
  insight, expanded, onToggle,
}: {
  insight: ComplianceInsight;
  expanded: boolean;
  onToggle: () => void;
}) {
  const c = SEV[insight.severity] || SEV.INFO;
  const cat = CAT[insight.category] || insight.category;
  const hasEvidence = insight.evidence && insight.evidence.length > 0;

  return (
    <div className={`ci-card${expanded ? " ci-expanded" : ""}`} style={{ borderLeftColor: c.border }}>
      {/* header row */}
      <button className="ci-header" onClick={onToggle}>
        <div className="ci-header-left">
          <span className="ci-sev-badge" style={{ background: c.bg, color: c.fg, borderColor: c.border }}>
            {insight.severity}
          </span>
          <span className="ci-cat">{cat}</span>
        </div>
        <span className="ci-chevron">{expanded ? "\u25BE" : "\u25B8"}</span>
      </button>

      <h4 className="ci-title">{insight.title}</h4>

      {/* expanded body */}
      {expanded && (
        <div className="ci-body">
          <p className="ci-desc">{insight.description}</p>

          {/* document evidence */}
          {hasEvidence && (
            <div className="ci-evidence">
              <div className="ci-evidence-label">Document Evidence</div>
              {insight.evidence.map((ev, i) => (
                <EvidenceBlock key={i} ev={ev} />
              ))}
            </div>
          )}

          {/* action */}
          <div className="ci-action">
            <span className="ci-action-label">Recommended Action</span>
            <p className="ci-action-text">{insight.recommended_action}</p>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── main panel ─────────────────────────────────────────────── */

export function CompliancePanel() {
  const [data, setData] = useState<ComplianceScan | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [sevFilter, setSevFilter] = useState<string | null>(null);
  const [catFilter, setCatFilter] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.compliance();
      setData(result);
      // Auto-expand CRITICAL + HIGH
      const auto = new Set<number>();
      result.insights.forEach((ins, i) => {
        if (ins.severity === "CRITICAL" || ins.severity === "HIGH") auto.add(i);
      });
      setExpanded(auto);
    } catch (e: any) {
      setError(e.message || "Compliance scan failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const toggle = (idx: number) =>
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(idx) ? next.delete(idx) : next.add(idx);
      return next;
    });

  const insights = data?.insights ?? [];
  const categories = [...new Set(insights.map(i => i.category))];

  const filtered = insights.filter(i => {
    if (sevFilter && i.severity !== sevFilter) return false;
    if (catFilter && i.category !== catFilter) return false;
    return true;
  });

  return (
    <section className="panel cpanel">
      {/* header */}
      <div className="cpanel-header">
        <div>
          <h2>Compliance Scanner</h2>
          <p className="cpanel-sub">
            Internal documents vs market data &amp; regulations
          </p>
        </div>
        <div className="cpanel-actions">
          {data && <span className="muted small">Scan: {data.scan_date}</span>}
          <button className="cpanel-scan-btn" onClick={load} disabled={loading}>
            {loading ? "Scanning\u2026" : "Scan Now"}
          </button>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && !data && (
        <div className="cpanel-loading">
          <div className="cpanel-spinner" />
          <span>Parsing documents &amp; running compliance checks\u2026</span>
        </div>
      )}

      {data && (
        <>
          <SeverityBar data={data} />

          {/* filters */}
          <div className="cpanel-filters">
            <div className="cpanel-filter-row">
              <button className={`cpill${!sevFilter ? " active" : ""}`} onClick={() => setSevFilter(null)}>All</button>
              {SEV_ORDER.filter(s => data.by_severity[s]).map(s => (
                <button
                  key={s}
                  className={`cpill${sevFilter === s ? " active" : ""}`}
                  onClick={() => setSevFilter(sevFilter === s ? null : s)}
                >
                  <span className="cpill-dot" style={{ background: SEV[s].dot }} />
                  {s} <span className="cpill-n">({data.by_severity[s]})</span>
                </button>
              ))}
            </div>
            {categories.length > 2 && (
              <div className="cpanel-filter-row">
                <button className={`cpill cpill-cat${!catFilter ? " active" : ""}`} onClick={() => setCatFilter(null)}>All categories</button>
                {categories.map(c => (
                  <button
                    key={c}
                    className={`cpill cpill-cat${catFilter === c ? " active" : ""}`}
                    onClick={() => setCatFilter(catFilter === c ? null : c)}
                  >{CAT[c] || c}</button>
                ))}
              </div>
            )}
          </div>

          {/* insights list */}
          <div className="ci-list">
            {filtered.length === 0 && (
              <p className="muted" style={{ textAlign: "center", padding: 32 }}>
                {insights.length === 0 ? "No compliance issues detected." : "No matches for current filters."}
              </p>
            )}
            {filtered.map(ins => {
              const idx = insights.indexOf(ins);
              return (
                <InsightCard
                  key={idx}
                  insight={ins}
                  expanded={expanded.has(idx)}
                  onToggle={() => toggle(idx)}
                />
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}
