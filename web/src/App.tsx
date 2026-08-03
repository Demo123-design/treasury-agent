import { useCallback, useState } from "react";
import logo from "./assets/skillnexus-logo.png";
import { TodayPanel } from "./components/TodayPanel";
import { NewsPanel } from "./components/NewsPanel";
import { AlertsPanel } from "./components/AlertsPanel";
import { BriefingArchive } from "./components/BriefingArchive";
import { CompliancePanel } from "./components/CompliancePanel";
import { KpiPanel } from "./components/KpiPanel";
import { ChatDrawer } from "./components/ChatDrawer";
import { TriggerRun } from "./components/TriggerRun";
import "./App.css";

function App() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [chatOpen, setChatOpen] = useState(false);
  const bumpRefresh = useCallback(() => setRefreshKey(k => k + 1), []);

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header-inner">
          <div className="app-brand">
            <img src={logo} alt="SkillNexus India Consulting" className="app-logo-img" />
            <span className="app-logo">Treasury Intelligence</span>
            <span className="app-tag">Daily Briefing</span>
          </div>
          <div className="header-ctas">
            <TriggerRun onRunComplete={bumpRefresh} />
          </div>
        </div>
      </header>

      <main className="app-main" key={refreshKey}>
        <KpiPanel />
        <TodayPanel />
        <CompliancePanel />
        <NewsPanel />
        <AlertsPanel />
        <BriefingArchive />
      </main>

      <footer className="app-footer">
        Sources — Frankfurter · OpenAI web search · Interest Rate Parity · Internal documents (Doc1–14)
      </footer>

      {!chatOpen && (
        <button className="chat-fab" onClick={() => setChatOpen(true)} aria-label="Open assistant">
          <span className="chat-fab-dot" />
          Ask the Treasury Assistant
        </button>
      )}
      {chatOpen && <ChatDrawer onClose={() => setChatOpen(false)} />}
    </div>
  );
}

export default App;
