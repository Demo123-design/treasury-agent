import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Shared markdown renderer. Used for news summaries and chat assistant replies.
 * GFM plugin enables tables, task lists, strikethrough, autolinks.
 */
export function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: (props) => <a {...props} target="_blank" rel="noopener noreferrer" />,
        // Collapse heading levels — markdown headings from LLM output shouldn't
        // compete with the app's section titles.
        h1: (props) => <h4 {...props} />,
        h2: (props) => <h4 {...props} />,
        h3: (props) => <h4 {...props} />,
      }}
    >
      {children}
    </ReactMarkdown>
  );
}
