import { useCallback, useState } from "react";
import { TodayPanel } from "./components/TodayPanel";
import { NewsPanel } from "./components/NewsPanel";
import { AlertsPanel } from "./components/AlertsPanel";
import { BriefingArchive } from "./components/BriefingArchive";
import { CompliancePanel } from "./components/CompliancePanel";
import { TriggerRun } from "./components/TriggerRun";
import "./App.css";

function App() {
  const [refreshKey, setRefreshKey] = useState(0);
  const bumpRefresh = useCallback(() => setRefreshKey(k => k + 1), []);

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header-inner">
          <div>
            <h1>Treasury Intelligence</h1>
            <p className="subtitle">Daily FX, forwards, alerts &amp; morning briefing</p>
          </div>
          <TriggerRun onRunComplete={bumpRefresh} />
        </div>
      </header>

      <main className="app-main" key={refreshKey}>
        <TodayPanel />
        <CompliancePanel />
        <NewsPanel />
        <AlertsPanel />
        <BriefingArchive />
      </main>

      <footer className="app-footer">
        Sources: Frankfurter.dev · OpenAI web search · Interest Rate Parity
      </footer>
    </div>
  );
}

export default App;
