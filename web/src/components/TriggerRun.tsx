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
  const [_, setHealth] = useState<Health | null>(null);
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

  async function refresh() {
    setBusy(true);
    try {
      const r = await api.run(true);
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

  return (
    <div className="trigger">
      {(isRunning || (state && Object.values(state.stage_status ?? {}).some(s => s !== "pending"))) && (
        <StageBar state={state} />
      )}

      <button
        className="btn btn-primary"
        disabled={busy}
        onClick={() => void refresh()}
      >
        {isRunning ? "Refreshing…" : "Refresh data"}
      </button>
    </div>
  );
}
