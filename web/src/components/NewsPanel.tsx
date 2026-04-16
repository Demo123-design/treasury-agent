import { useEffect, useState } from "react";
import { api, type BriefingDetail, type NewsItem } from "../api";

const CATEGORY_LABEL: Record<string, string> = {
  RBI: "RBI & Policy",
  FED_EBC: "Fed / ECB",
  FED_ECB: "Fed / ECB",
  CRUDE: "Crude Oil",
  INDIA_MACRO: "India Macro",
  GLOBAL_RISK: "Global Risk",
};

const CATEGORY_ORDER = ["RBI", "FED_ECB", "CRUDE", "INDIA_MACRO", "GLOBAL_RISK"];

function relevanceClass(r: string | null): string {
  if (r === "HIGH") return "relevance high";
  if (r === "MEDIUM") return "relevance medium";
  if (r === "LOW") return "relevance low";
  return "relevance unknown";
}

function truncate(s: string | null, n = 420): string {
  if (!s) return "";
  if (s.length <= n) return s;
  return s.slice(0, n).trim() + "…";
}

function NewsCard({ item, expanded, onToggle }: { item: NewsItem; expanded: boolean; onToggle: () => void }) {
  const summary = item.summary || "";
  const isLong = summary.length > 420;
  return (
    <article className="news-card">
      <header className="news-card-head">
        <div className="news-category">{CATEGORY_LABEL[item.category] ?? item.category}</div>
        <span className={relevanceClass(item.relevance)}>{item.relevance ?? "—"}</span>
      </header>
      {item.headline && <h3 className="news-headline">{item.headline}</h3>}
      <div className="news-summary">
        {expanded || !isLong ? summary : truncate(summary)}
      </div>
      <footer className="news-card-foot">
        {isLong && (
          <button className="link-btn" onClick={onToggle}>
            {expanded ? "Collapse" : "Read more"}
          </button>
        )}
        {item.source_url && (
          <a href={item.source_url} target="_blank" rel="noopener noreferrer" className="source-link">
            Source ↗
          </a>
        )}
      </footer>
    </article>
  );
}

export function NewsPanel() {
  const [detail, setDetail] = useState<BriefingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const list = await api.briefings(1);
      if (list.length === 0) {
        setDetail(null);
        return;
      }
      setDetail(await api.briefing(list[0].date));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  const items = detail?.news ?? [];
  const ordered = [...items].sort(
    (a, b) => CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category)
  );
  const filtered = filter ? ordered.filter(n => n.category === filter) : ordered;
  const categories = Array.from(new Set(ordered.map(n => n.category)));

  function toggle(idx: number) {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <h2>Today's News</h2>
          {detail && (
            <div className="muted small refresh-meta">
              {detail.date} · {items.length} items
            </div>
          )}
        </div>
        <button className="link-btn" onClick={() => void load()}>Refresh</button>
      </div>

      {loading && <p className="muted">Loading news…</p>}
      {error && <p className="error">{error}</p>}
      {!loading && items.length === 0 && (
        <p className="muted">No news items on record. Run the pipeline to fetch today's news.</p>
      )}

      {categories.length > 1 && (
        <div className="news-filter">
          <button
            className={`filter-pill ${filter === null ? "active" : ""}`}
            onClick={() => setFilter(null)}
          >
            All
          </button>
          {categories.map(cat => (
            <button
              key={cat}
              className={`filter-pill ${filter === cat ? "active" : ""}`}
              onClick={() => setFilter(cat)}
            >
              {CATEGORY_LABEL[cat] ?? cat}
            </button>
          ))}
        </div>
      )}

      <div className="news-grid">
        {filtered.map((item, i) => (
          <NewsCard
            key={`${item.category}-${i}`}
            item={item}
            expanded={expanded.has(i)}
            onToggle={() => toggle(i)}
          />
        ))}
      </div>
    </section>
  );
}
