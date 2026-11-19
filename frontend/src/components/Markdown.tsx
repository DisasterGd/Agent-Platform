import { memo, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import katex from "katex";
import "katex/dist/katex.min.css";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";

let mermaidSeq = 0;

/** 把 LaTeX 标准定界符 \(...\) / \[...\] 归一化为 remark-math 认识的 $...$ / $$...$$。
 *  必须在 remark-math 解析前对原始文本做，否则转换后的 $ 不会被重新解析。 */
function normalizeLatex(content: string): string {
  return content
    .replace(/\\\[([\s\S]*?)\\\]/g, (_m: string, x: string) => `$$\n${x}\n$$`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_m: string, x: string) => `$${x}$`);
}

/** 段落级奇数 $ 保护：旧数据里失配的定界符会让 $ 跨句错位配对，把整段中文吞进一个数学节点，
 *  KaTeX 随即整段标红（ParseError: Can't use function '$' in math mode）。
 *  若某个以空行分隔的块内未转义 $ 的数量为奇数，则定界符必然失配——把段内 $ 全部转义为字面量，
 *  宁可退化为显示原始文本，也不让公式错误污染整段。围栏代码块不参与配对，须原样保留。 */
function guardUnbalancedDollars(content: string): string {
  const guardParagraphs = (text: string): string =>
    text
      .split(/\n{2,}/)
      .map(block => {
        let count = 0;
        for (let i = 0; i < block.length; i++) {
          if (block[i] === "$" && block[i - 1] !== "\\") count += 1;
        }
        return count % 2 === 1 ? block.replace(/(?<!\\)\$/g, "\\$") : block;
      })
      .join("\n\n");
  // 以 ``` 围栏切分：奇数段是代码块，原样保留（代码里的 $ 不参与公式配对）
  return content.split(/(```[\s\S]*?(?:```|$))/g).map((part, i) => (i % 2 === 1 ? part : guardParagraphs(part))).join("");
}

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
        customStyle={{ margin: 0, background: "transparent", fontSize: "13px", lineHeight: "1.6", fontFamily: '"IBM Plex Mono","SFMono-Regular",Consolas,monospace' }}
      >
        {deferredCode}
      </SyntaxHighlighter>
    </div>
  );
});

/** 独立公式块（```math 代码块）用 KaTeX 渲染成显示公式（兜底，通常由 rehype-katex 处理）。 */
const KatexBlock = memo(function KatexBlock({ tex }: { tex: string }) {
  const html = useMemo(() => {
    try {
      return katex.renderToString(tex, { displayMode: true, throwOnError: false });
    } catch {
      return "";
    }
  }, [tex]);
  if (!html) {
    return <pre className="mermaid-fallback"><code>{tex}</code></pre>;
  }
  return <div className="katex-block" dangerouslySetInnerHTML={{ __html: html }} />;
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
        mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "strict" });
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
    if (lang === "math" || lang === "latex" || lang === "tex") return <KatexBlock tex={raw} />;
    return <CodeBlock language={lang} code={raw} />;
  },
};

export default memo(function Markdown({ content }: { content: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, { throwOnError: false, errorColor: "#cc0000", strict: false }]]}
        components={components}
      >
        {guardUnbalancedDollars(normalizeLatex(content))}
      </ReactMarkdown>
    </div>
  );
});
