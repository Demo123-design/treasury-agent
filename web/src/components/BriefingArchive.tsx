import { useEffect, useState } from "react";
import { api, type BriefingSummary, type BriefingDetail, type BriefingSections } from "../api";

function fmt(n: number | null | undefined, d = 4) {
  if (n === null || n === undefined) return "—";
  return n.toFixed(d);
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="brief-card">
      <h3 className="brief-card-title">{title}</h3>
      <div className="brief-card-body">{children}</div>
    </div>
  );
}

function SectionsView({ sections }: { sections: BriefingSections }) {
  return (
    <div className="brief-sections">
      {sections.overnight_highlights && sections.overnight_highlights.length > 0 && (
        <SectionCard title="Overnight Highlights">
          <ul className="bullets">
            {sections.overnight_highlights.map((h, i) => <li key={i}>{h}</li>)}
          </ul>
        </SectionCard>
      )}

      {sections.rbi_update && (
        <SectionCard title="RBI & Policy Update">
          <p>{sections.rbi_update}</p>
        </SectionCard>
      )}

      {sections.forward_premium_analysis && (
        <SectionCard title="Forward Premium Analysis">
          <p>{sections.forward_premium_analysis}</p>
        </SectionCard>
      )}

      {sections.macro_watch && (
        <SectionCard title="Macro Watch">
          <p>{sections.macro_watch}</p>
        </SectionCard>
      )}

      {sections.action_items && sections.action_items.length > 0 && (
        <SectionCard title="Action Items">
          <ol className="numbered">
            {sections.action_items.map((a, i) => <li key={i}>{a}</li>)}
          </ol>
        </SectionCard>
      )}

      {sections._fallback && (
        <p className="muted small">Briefing was generated from raw data only (LLM unavailable at the time).</p>
      )}
    </div>
  );
}

function ForexSnapshot({ detail }: { detail: BriefingDetail }) {
  if (detail.forward_rates.length === 0) return null;

  const byPair = new Map<string, typeof detail.forward_rates>();
  for (const f of detail.forward_rates) {
    const list = byPair.get(f.pair) ?? [];
    list.push(f);
    byPair.set(f.pair, list);
  }

  return (
    <div className="brief-snapshot">
      <h4>Forex snapshot</h4>
      <table className="market-table compact">
        <thead>
          <tr>
            <th>Pair</th>
            <th>Spot</th>
            <th>1M</th><th>3M</th><th>6M</th><th>12M</th>
          </tr>
        </thead>
        <tbody>
          {Array.from(byPair.entries()).map(([pair, rows]) => {
            const spot = detail.spot_rates.find(s => s.pair === pair)?.spot_rate;
            const byTenor = new Map(rows.map(r => [r.tenor, r]));
            const label = pair === "USDINR" ? "USD/INR" : pair === "EURINR" ? "EUR/INR" : pair;
            return (
              <tr key={pair}>
                <td className="pair">{label}</td>
                <td>{fmt(spot)}</td>
                {(["1M", "3M", "6M", "12M"] as const).map(t => {
                  const r = byTenor.get(t);
                  return (
                    <td key={t}>
                      <div>{fmt(r?.forward_rate)}</div>
                      <div className="bps">
                        {r ? `${r.forward_premium_bps >= 0 ? "+" : ""}${r.forward_premium_bps.toFixed(1)}bps` : "—"}
                      </div>
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function BriefingArchive() {
  const [list, setList] = useState<BriefingSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<BriefingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);

  async function loadList() {
    setLoading(true);
    setError(null);
    try {
      const items = await api.briefings(50);
      setList(items);
      if (items.length > 0 && !selected) {
        setSelected(items[0].date);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function loadDetail(date: string) {
    setDetailLoading(true);
    try {
      setDetail(await api.briefing(date));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDetailLoading(false);
    }
  }

  useEffect(() => { void loadList(); }, []);
  useEffect(() => {
    if (selected) void loadDetail(selected);
  }, [selected]);

  return (
    <section className="panel archive">
      <div className="panel-header">
        <h2>Briefing Archive</h2>
        <button className="link-btn" onClick={() => void loadList()}>Refresh</button>
      </div>

      {loading && <p className="muted">Loading…</p>}
      {error && <p className="error">{error}</p>}

      <div className="archive-layout">
        <ul className="archive-list">
          {list.map(b => (
            <li key={b.date}>
              <button
                className={`archive-item ${selected === b.date ? "active" : ""}`}
                onClick={() => setSelected(b.date)}
              >
                <div className="archive-date">{b.date}</div>
                <div className="archive-meta">
                  USD/INR {fmt(b.usdinr)} · EUR/INR {fmt(b.eurinr)}
                </div>
                <div className="archive-meta">
                  {b.delivered ? "delivered" : "draft"}
                  {b.alerts_count > 0 && ` · ${b.alerts_count} alert${b.alerts_count === 1 ? "" : "s"}`}
                </div>
              </button>
            </li>
          ))}
          {!loading && list.length === 0 && (
            <li className="muted" style={{ padding: "12px" }}>No briefings yet. Click "Run pipeline" above.</li>
          )}
        </ul>

        <div className="archive-detail">
          {detailLoading && <p className="muted">Loading briefing…</p>}
          {detail && (
            <>
              <div className="archive-detail-meta">
                <div>
                  <strong>{detail.date}</strong> · generated {detail.generated_at}
                  {detail.delivered ? " · delivered" : " · not delivered"}
                </div>
                <button className="link-btn" onClick={() => setShowRaw(v => !v)}>
                  {showRaw ? "Show parsed view" : "Show raw email"}
                </button>
              </div>

              {detail.alerts.length > 0 && (
                <div className="archive-alerts">
                  {detail.alerts.map((a, i) => (
                    <div key={i} className="alert-item compact">
                      <div className="alert-type">{a.alert_type}</div>
                      <div className="alert-msg">{a.message}</div>
                    </div>
                  ))}
                </div>
              )}

              {showRaw ? (
                selected && (
                  <iframe
                    className="briefing-frame"
                    src={api.briefingHtmlUrl(selected)}
                    title={`Briefing ${selected}`}
                  />
                )
              ) : (
                <>
                  {detail.sections ? (
                    <SectionsView sections={detail.sections} />
                  ) : (
                    <p className="muted">
                      No parsed sections for this briefing. Click "Show raw email" to view the HTML.
                    </p>
                  )}
                  <ForexSnapshot detail={detail} />
                </>
              )}
            </>
          )}
          {!detailLoading && !detail && !selected && (
            <p className="muted">Select a briefing from the list.</p>
          )}
        </div>
      </div>
    </section>
  );
}
