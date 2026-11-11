import { memo, useDeferredValue, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";

let mermaidSeq = 0;

/** 代码块：带语言标签 + 复制按钮，流式输出时用 useDeferredValue 让高亮“追赶”而非阻塞。 */
const CodeBlock = memo(function CodeBlock({ language, code }: { language: string; code: string }) {
  const deferredCode = useDeferredValue(code);
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* 剪贴板不可用则忽略 */
    }
  }

  return (
    <div className="codeblock">
      <div className="codeblock-head">
        <span>{language || "text"}</span>
        <button type="button" onClick={() => void copy()}>{copied ? "已复制" : "复制"}</button>
      </div>
      <SyntaxHighlighter
        language={language || "text"}
        style={oneLight}
        wrapLongLines
        customStyle={{ margin: 0, background: "transparent", fontSize: "13px", lineHeight: "1.6" }}
      >
        {deferredCode}
      </SyntaxHighlighter>
    </div>
  );
});

/** Mermaid 流程图：流式期间未闭合/解析失败时回退为源码，闭合后再渲染成图。 */
const Mermaid = memo(function Mermaid({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const id = `mmd-${++mermaidSeq}`;
    const timer = window.setTimeout(async () => {
      try {
        const { default: mermaid } = await import("mermaid");
        if (cancelled) return;
        mermaid.initialize({ startOnLoad: false, theme: "default", securityLevel: "strict" });
        const { svg } = await mermaid.render(id, code);
        if (cancelled) return;
        if (containerRef.current) containerRef.current.innerHTML = svg;
        setFailed(false);
      } catch {
        if (!cancelled) {
          if (containerRef.current) containerRef.current.innerHTML = "";
          setFailed(true);
        }
      }
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [code]);

  return (
    <div className="mermaid-wrap">
      {failed && (
        <div className="mermaid-fallback">
          <span>Mermaid 图表源码</span>
          <pre><code>{code}</code></pre>
        </div>
      )}
      <div className="mermaid" ref={containerRef} />
    </div>
  );
});

const components: Components = {
  // 代码块外层 <pre> 仅透传子节点，让 CodeBlock 的 div 成为真正的块元素。
  pre({ children }) {
    return <>{children}</>;
  },
  code({ className, children }) {
    const match = /language-([\w+-]+)/.exec(className || "");
    const raw = String(children).replace(/\n$/, "");
    const isBlock = Boolean(match) || raw.includes("\n");
    if (!isBlock) {
      return <code className="md-inline-code">{children}</code>;
    }
    const lang = match ? match[1].toLowerCase() : "";
    if (lang === "mermaid") return <Mermaid code={raw} />;
    return <CodeBlock language={lang} code={raw} />;
  },
};

export default memo(function Markdown({ content }: { content: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
});
