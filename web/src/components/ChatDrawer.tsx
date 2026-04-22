import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage } from "../api";
import { api } from "../api";
import { Markdown } from "./Markdown";

const SUGGESTIONS = [
  "Summarize the 15 KPIs in a CFO-ready paragraph.",
  "Which RED items need attention this week, and why?",
  "Given our current hedge book vs live spot, is the hedge policy still optimal?",
  "What happens to F02 if USD/INR drops 2 rupees? Which KPIs shift?",
  "Draft an email to the Risk Committee on the EDPMS ageing and R01 breach.",
];

export function ChatDrawer({ onClose }: { onClose: () => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    const onEsc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [onClose]);

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [messages, sending]);

  const send = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || sending) return;

    const newHistory: ChatMessage[] = [...messages, { role: "user", content: trimmed }];
    setMessages(newHistory);
    setInput("");
    setSending(true);
    setError(null);

    try {
      const { reply } = await api.chat(newHistory);
      setMessages([...newHistory, { role: "assistant", content: reply }]);
    } catch (e: any) {
      setError(e.message || "Chat failed");
    } finally {
      setSending(false);
    }
  }, [messages, sending]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  };

  const autoResize = (el: HTMLTextAreaElement) => {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  };

  return (
    <>
      <div className="chat-backdrop" onClick={onClose} />
      <aside className="chat-drawer" role="dialog" aria-label="Treasury Assistant">
        <header className="chat-header">
          <div>
            <h3 className="chat-title">Treasury Assistant</h3>
            <p className="chat-subtitle">Grounded in live KPIs, market data, and internal documents</p>
          </div>
          <button className="chat-close" onClick={onClose} aria-label="Close">×</button>
        </header>

        <div className="chat-body" ref={bodyRef}>
          {messages.length === 0 && (
            <div className="chat-empty">
              <p className="chat-empty-title">How can I help?</p>
              <p>
                Ask about any of the 15 KPIs, the hedge book, FX positioning, covenants,
                or drafting communications. I see the same data the dashboard does.
              </p>
              <div className="chat-suggestions">
                {SUGGESTIONS.map(s => (
                  <button key={s} className="chat-suggestion" onClick={() => void send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} className={`chat-msg ${m.role}`}>
              <span className="chat-msg-role">{m.role === "user" ? "You" : "Assistant"}</span>
              <div className="chat-msg-body">
                {m.role === "assistant" ? <Markdown>{m.content}</Markdown> : m.content}
              </div>
            </div>
          ))}

          {sending && (
            <div className="chat-msg assistant">
              <span className="chat-msg-role">Assistant</span>
              <div className="chat-typing"><span /><span /><span /></div>
            </div>
          )}

          {error && <p className="error">{error}</p>}
        </div>

        <footer className="chat-footer">
          <div className="chat-input-wrap">
            <textarea
              ref={inputRef}
              className="chat-input"
              placeholder="Ask a question about the treasury position…"
              value={input}
              onChange={e => { setInput(e.target.value); autoResize(e.target); }}
              onKeyDown={onKeyDown}
              rows={1}
              disabled={sending}
            />
            <button
              className="chat-send"
              onClick={() => void send(input)}
              disabled={sending || !input.trim()}
              aria-label="Send"
            >
              ↵
            </button>
          </div>
          <p className="chat-hint">Enter to send · Shift+Enter for a new line · Esc to close</p>
        </footer>
      </aside>
    </>
  );
}
