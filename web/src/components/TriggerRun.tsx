import { useEffect, useState } from "react";
import { api, type Health, type RunState, type StageName } from "../api";

const STAGES: { key: StageName; label: string }[] = [
  { key: "forex", label: "Forex" },
  { key: "news", label: "News" },
  { key: "briefing", label: "Briefing" },
  { key: "delivery", label: "Delivery" },
];

type Props = { onRunComplete?: () => void };

function StageBar({ state }: { state: RunState | null }) {
  if (!state) return null;
  return (
    <div className="stage-bar">
      {STAGES.map(({ key, label }, idx) => {
        const st = state.stage_status?.[key] ?? "pending";
        return (
          <div key={key} className={`stage-cell stage-${st}`}>
            <div className="stage-index">{idx + 1}</div>
            <div className="stage-label">{label}</div>
            <div className="stage-state">
              {st === "done" && "✓"}
              {st === "active" && <span className="stage-spinner" />}
              {st === "error" && "✗"}
              {st === "skipped" && "–"}
              {st === "pending" && ""}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function TriggerRun({ onRunComplete }: Props) {
  const [health, setHealth] = useState<Health | null>(null);
  const [state, setState] = useState<RunState | null>(null);
  const [busy, setBusy] = useState(false);
  const [polling, setPolling] = useState(false);

  useEffect(() => {
    void api.health().then(setHealth).catch(() => {});
    void api.runStatus().then(setState).catch(() => {});
  }, []);

  useEffect(() => {
    if (!polling) return;
    const iv = window.setInterval(async () => {
      try {
        const s = await api.runStatus();
        setState(s);
        if (s.status !== "running") {
          setPolling(false);
          setBusy(false);
          onRunComplete?.();
        }
      } catch {
        // ignore poll errors
      }
    }, 1000);
    return () => window.clearInterval(iv);
  }, [polling, onRunComplete]);

  async function trigger(dryRun: boolean) {
    setBusy(true);
    try {
      const r = await api.run(dryRun);
      if (!r.accepted) {
        alert(r.reason ?? "not accepted");
        setBusy(false);
        return;
      }
      setPolling(true);
    } catch (e) {
      alert((e as Error).message);
      setBusy(false);
    }
  }

  const status = state?.status ?? "idle";
  const isRunning = status === "running";
  const badge =
    status === "running" ? "running" :
    status === "success" ? "success" :
    status === "error" ? "error" : "idle";

  return (
    <div className="trigger">
      <div className="trigger-status">
        <span className={`status-badge ${badge}`}>{status}</span>
        {state?.finished_at && status !== "running" && (
          <span className="muted small">
            last: {state.dry_run ? "dry-run" : "live"} @ {state.finished_at}
            {state.error ? ` · ${state.error}` : ""}
          </span>
        )}
        {health && !health.has_openai_key && (
          <span className="muted small keys">openai key missing</span>
        )}
      </div>

      {(isRunning || (state && Object.values(state.stage_status ?? {}).some(s => s !== "pending"))) && (
        <StageBar state={state} />
      )}

      <div className="trigger-buttons">
        <button
          className="btn primary"
          disabled={busy}
          onClick={() => void trigger(true)}
        >
          Run pipeline (dry-run)
        </button>
        <button
          className="btn"
          disabled={busy || !health?.has_sendgrid_key}
          title={!health?.has_sendgrid_key ? "SendGrid key not configured" : ""}
          onClick={() => {
            if (confirm("Run the pipeline and send a LIVE email?")) void trigger(false);
          }}
        >
          Run & send live
        </button>
      </div>
    </div>
  );
}
