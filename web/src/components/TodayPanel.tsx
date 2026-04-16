import { useEffect, useRef, useState } from "react";
import { api, type MarketLatest, type SpotDelta } from "../api";

const TENORS = ["1M", "3M", "6M", "12M"] as const;
const PAIRS = [
  { key: "USDINR", label: "USD/INR" },
  { key: "EURINR", label: "EUR/INR" },
] as const;
const REFRESH_MS = 30_000;

function verdictClass(v: string | undefined) {
  if (v === "CHEAP") return "verdict cheap";
  if (v === "EXPENSIVE") return "verdict expensive";
  return "verdict fair";
}

function fmt(n: number | null | undefined, d = 4) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(d);
}

function pct(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  return `${(n * 100).toFixed(2)}%`;
}

function DeltaBadge({ abs, pct: pctVal, label }: { abs: number | null; pct: number | null; label: string }) {
  if (abs === null || pctVal === null) {
    return <span className="delta muted">{label}: —</span>;
  }
  const up = abs > 0;
  const cls = up ? "delta up" : abs < 0 ? "delta down" : "delta flat";
  const sign = up ? "+" : "";
  return (
    <span className={cls}>
      {label}: {sign}{abs.toFixed(4)} ({sign}{pctVal.toFixed(2)}%)
    </span>
  );
}

function SpotCell({ spot, delta }: { spot: number | undefined; delta: SpotDelta | undefined }) {
  return (
    <div className="spot-cell">
      <div className="spot-big">{fmt(spot)}</div>
      {delta && (
        <div className="spot-deltas">
          <DeltaBadge abs={delta.d1_abs} pct={delta.d1_pct} label="1d" />
          <DeltaBadge abs={delta.d30_abs} pct={delta.d30_pct} label="30d avg" />
        </div>
      )}
    </div>
  );
}

export function TodayPanel() {
  const [data, setData] = useState<MarketLatest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const intervalRef = useRef<number | null>(null);

  async function load(silent = false) {
    if (!silent) setLoading(true);
    setRefreshing(true);
    setError(null);
    try {
      const d = await api.marketLatest();
      setData(d);
      setLastRefresh(new Date());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      if (!silent) setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void load();
    intervalRef.current = window.setInterval(() => void load(true), REFRESH_MS);
    return () => {
      if (intervalRef.current !== null) window.clearInterval(intervalRef.current);
    };
  }, []);

  if (loading) return <section className="panel"><h2>Today's Market</h2><p className="muted">Loading…</p></section>;
  if (error) return <section className="panel"><h2>Today's Market</h2><p className="error">{error}</p></section>;
  if (!data) return null;

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <h2>Today's Market <span className="muted small">({data.date})</span></h2>
          {lastRefresh && (
            <div className="muted small refresh-meta">
              {refreshing ? "Refreshing…" : `last refresh ${lastRefresh.toLocaleTimeString()}`} · auto every 30s
            </div>
          )}
        </div>
        <button className="link-btn" onClick={() => void load()}>Refresh now</button>
      </div>

      <table className="market-table">
        <thead>
          <tr>
            <th>Pair</th>
            <th>Spot</th>
            {TENORS.map(t => <th key={t}>{t} Fwd</th>)}
            <th>6M</th>
          </tr>
        </thead>
        <tbody>
          {PAIRS.map(({ key, label }) => {
            const spot = data.spot_rates[key]?.rate;
            const delta = data.spot_deltas?.[key];
            const curve = data.forward_curves[key] ?? [];
            const byTenor = new Map(curve.map(p => [p.tenor, p]));
            const hedge = data.hedging_assessment[key];
            return (
              <tr key={key}>
                <td className="pair">{label}</td>
                <td><SpotCell spot={spot} delta={delta} /></td>
                {TENORS.map(t => {
                  const p = byTenor.get(t);
                  return (
                    <td key={t}>
                      <div>{fmt(p?.forward_rate)}</div>
                      <div className="bps">
                        {p ? `${p.forward_premium_bps >= 0 ? "+" : ""}${p.forward_premium_bps.toFixed(1)}bps` : "—"}
                      </div>
                    </td>
                  );
                })}
                <td>
                  <span className={verdictClass(hedge?.verdict)}>{hedge?.verdict ?? "—"}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <p className="muted small rates-footer">
        Forward rates via Interest Rate Parity. RBI Repo: {pct(data.interest_rates.RBI_REPO)} |
        {" "}Fed Funds: {pct(data.interest_rates.FED_FUNDS)} |
        {" "}ECB Deposit: {pct(data.interest_rates.ECB_DEPOSIT)}
      </p>
    </section>
  );
}
