import { useEffect, useState } from "react";
import { api, type Alert } from "../api";

export function AlertsPanel() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setAlerts(await api.alerts(10));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Recent Alerts</h2>
        <button className="link-btn" onClick={() => void load()}>Refresh</button>
      </div>
      {loading && <p className="muted">Loading…</p>}
      {error && <p className="error">{error}</p>}
      {!loading && !error && alerts.length === 0 && (
        <p className="muted">No alerts on record.</p>
      )}
      {alerts.length > 0 && (
        <ul className="alert-list">
          {alerts.map(a => (
            <li key={a.id} className="alert-item">
              <div className="alert-type">{a.alert_type}</div>
              <div className="alert-msg">{a.message}</div>
              <div className="alert-meta">
                {a.date} · threshold {a.threshold} · actual {a.actual_value}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
