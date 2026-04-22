import { useCallback, useEffect, useState } from "react";
import type { Kpi, KpiSnapshot, KpiStatus } from "../api";
import { api } from "../api";

const STATUS_ORDER: KpiStatus[] = ["GREEN", "AMBER", "RED", "NA"];
const STATUS_LABEL: Record<KpiStatus, string> = {
  GREEN: "On-target",
  AMBER: "Watch",
  RED: "Breach",
  NA: "Pending input",
};

function KpiRow({ kpi }: { kpi: Kpi }) {
  return (
    <div className={`kpi-row kpi-status-${kpi.status}`}>
      <div className="kpi-row-status">
        <span className="kpi-dot" />
        <span className="kpi-status-badge">{kpi.status}</span>
      </div>
      <div className="kpi-row-id">{kpi.id}</div>
      <div className="kpi-row-name">{kpi.name}</div>
      <div className="kpi-row-value">{kpi.value_display}</div>
      <div className="kpi-row-target">{kpi.target}</div>
      <div className="kpi-row-narr">{kpi.narrative}</div>
    </div>
  );
}

export function KpiPanel() {
  const [data, setData] = useState<KpiSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.kpis());
    } catch (e: any) {
      setError(e.message || "KPI fetch failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return (
    <section className="panel kpi-panel">
      <div className="panel-head">
        <div className="panel-head-copy">
          <h2>Headline KPIs</h2>
          <p className="panel-sub">
            Fifteen metrics across liquidity, FX, debt, compliance, and counterparty risk
          </p>
        </div>
        <div className="panel-head-actions">
          {data && <span className="muted small">As of {data.as_of}</span>}
          <button className="btn" onClick={load} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && !data && (
        <div className="kpi-loading">
          <div className="spinner" />
          <span>Computing KPIs from internal documents…</span>
        </div>
      )}

      {data && (
        <>
          <div className="kpi-hero">
            <p className="kpi-hero-lede">{data.one_liner}</p>
            <div className="kpi-hero-stats">
              {STATUS_ORDER.map(s => {
                const n = data.by_status[s] || 0;
                if (!n && s === "NA") return null;
                return (
                  <div key={s} className={`kpi-hero-stat ${s.toLowerCase()}`}>
                    <span className="kpi-hero-stat-n">{n}</span>
                    <span className="kpi-hero-stat-lbl">{STATUS_LABEL[s]}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {data.missing_inputs > 0 && (
            <p className="kpi-note">
              <strong>{data.missing_inputs}</strong> KPI(s) awaiting input files.
              Drop the expected Excel templates into <code>Internal Document (Dummy)/</code> to populate them.
            </p>
          )}

          <div className="kpi-groups">
            {data.categories.map(cat => {
              const rows = data.kpis.filter(k => k.category === cat);
              if (rows.length === 0) return null;
              return (
                <div key={cat} className="kpi-group">
                  <h3 className="kpi-group-title">{cat}</h3>
                  <div className="kpi-table">
                    <div className="kpi-row kpi-row-head">
                      <div className="kpi-row-status">Status</div>
                      <div className="kpi-row-id">ID</div>
                      <div className="kpi-row-name">KPI</div>
                      <div className="kpi-row-value">Value</div>
                      <div className="kpi-row-target">Target</div>
                      <div className="kpi-row-narr">Narrative</div>
                    </div>
                    {rows.map(k => <KpiRow key={k.id} kpi={k} />)}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}
