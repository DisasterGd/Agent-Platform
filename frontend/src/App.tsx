import { useCallback, useEffect, useRef, useState } from "react";
import { chatApi } from "./services/chat";
import Markdown from "./components/Markdown";
import SettingsModal from "./components/SettingsModal";
import type { Artifact, Attachment, Conversation, Message } from "./types/chat";

const TOOL_LABELS: Record<string, string> = {
  web_search: "联网搜索",
  generate_file: "生成文件",
};

type ToolEntry = { name: string; state: "running" | "done" };

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [toolLog, setToolLog] = useState<ToolEntry[]>([]);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const cancelRename = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    try { return (localStorage.getItem("theme") as "light" | "dark") || "light"; }
    catch { return "light"; }
  });
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("theme", theme); } catch { /* 忽略存储失败 */ }
  }, [theme]);

  const refresh = useCallback(async () => {
    const items = await chatApi.listConversations();
    setConversations(items);
    return items;
  }, []);

  const load = useCallback(async (id: number) => {
    setActiveId(id);
    setMessages(await chatApi.listMessages(id));
  }, []);

  useEffect(() => {
    void refresh().then(items => {
      if (items.length) return load(items[0].id);
    }).catch((e: unknown) => setError(e instanceof Error ? e.message : "连接后端失败"));
  }, [refresh, load]);

  async function createChat() {
    try {
      setError("");
      const item = await chatApi.createConversation();
      await refresh();
      await load(item.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建会话失败");
    }
  }

  function startEdit(c: Conversation) {
    cancelRename.current = false;
    setEditingId(c.id);
    setDraftTitle(c.title);
  }

  async function rename(id: number, title: string) {
    setEditingId(null);
    const doCancel = cancelRename.current;
    cancelRename.current = false;
    if (doCancel) return;

    const next = title.trim();
    if (!next || next === conversations.find(c => c.id === id)?.title) return;
    try {
      setError("");
      await chatApi.renameConversation(id, next);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "重命名失败");
    }
  }

  async function attachFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setError("");
    try {
      for (const file of Array.from(files)) {
        const att = await chatApi.uploadFile(file);
        setAttachments(cur => [...cur, att]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "上传失败");
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function removeAttachment(index: number) {
    setAttachments(cur => cur.filter((_, i) => i !== index));
  }

  async function send() {
    const content = input.trim();
    if (!content || busy) return;
    setError("");
    setBusy(true);
    setToolLog([]);
    let id = activeId;
    try {
      if (id === null) {
        const item = await chatApi.createConversation();
        id = item.id;
        setActiveId(id);
        await refresh();
      }
      const sentAttachments = [...attachments];
      const userMessage: Message = {
        id: Date.now(), conversation_id: id, role: "user",
        content, created_at: new Date().toISOString(),
        attachments: sentAttachments.length ? sentAttachments : undefined,
      };
      const assistantId = Date.now() + 1;
      const assistantMessage: Message = {
        id: assistantId, conversation_id: id, role: "assistant",
        content: "", created_at: new Date().toISOString(), artifacts: [],
      };
      setMessages(current => [...current, userMessage, assistantMessage]);
      setInput("");
      setAttachments([]);
      await chatApi.streamMessage(id, content, sentAttachments, {
        onDelta: delta => {
          setMessages(current => current.map(m =>
            m.id === assistantId ? { ...m, content: m.content + delta } : m
          ));
        },
        onToolStart: name => {
          setToolLog(log => [...log, { name, state: "running" as const }]);
        },
        onToolEnd: () => {
          setToolLog(log => {
            const idx = log.reduce<number>((acc, t, i) => (t.state === "running" ? i : acc), -1);
            if (idx < 0) return log;
            return log.map((t, i) => (i === idx ? { ...t, state: "done" as const } : t));
          });
        },
        onArtifact: (artifact: Artifact) => {
          setMessages(current => current.map(m =>
            m.id === assistantId ? { ...m, artifacts: [...(m.artifacts || []), artifact] } : m
          ));
        },
      });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "发送消息失败");
      if (id !== null) {
        try { await load(id); } catch { /* keep original error */ }
      }
    } finally {
      setBusy(false);
    }
  }

  function jumpTo(id: number) {
    document.getElementById(`msg-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  const questions = messages.filter(m => m.role === "user" && m.content.trim());
  const activeConv = conversations.find(c => c.id === activeId);

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><b className="mark">◉</b><div className="brand-word"><strong>Agent</strong><span>工作台</span></div></div>
      <button className="new" onClick={() => void createChat()}>新建会话</button>
      <div className="section-label">会话</div>
      <nav className="conv-list">{conversations.map(c =>
        editingId === c.id ? (
          <input key={c.id} className="rename-input" autoFocus value={draftTitle}
            onChange={e => setDraftTitle(e.target.value)}
            onBlur={() => void rename(c.id, draftTitle)}
            onKeyDown={e => {
              if (e.key === "Enter") { e.preventDefault(); (e.currentTarget as HTMLInputElement).blur(); }
              if (e.key === "Escape") { cancelRename.current = true; setEditingId(null); }
            }} />
        ) : (
          <div key={c.id} className={`conv-item ${activeId === c.id ? "selected" : ""}`}>
            <button className="conv-title" title={c.title}
              onClick={() => void load(c.id)}
              onDoubleClick={() => startEdit(c)}>{c.title}</button>
            <button className="conv-edit" title="重命名" onClick={() => startEdit(c)}>✎</button>
          </div>
        )
      )}</nav>
      <div className="side-foot"><span className="led" />本地运行</div>
    </aside>

    <main className="main">
      <header className="topbar">
        <div className="topbar-title">{activeConv?.title ?? "新会话"}</div>
        <div className="topbar-meta">
          <span className="meta-item">模型 <b>DeepSeek</b></span>
          <span className="meta-item">v0.2</span>
          <span className="meta-item"><span className="led" />就绪</span>
          <button className="settings-btn" onClick={() => setSettingsOpen(true)}>设置</button>
        </div>
      </header>

      {questions.length > 0 && (
        <aside className="index">
          <div className="index-head"><span>问题索引</span><em>{questions.length}</em></div>
          <div className="index-list">
            {questions.map((q, i) => (
              <button key={q.id} className="index-item" title={q.content} onClick={() => jumpTo(q.id)}>
                <span className="index-num">{i + 1}</span>
                <span className="index-label">{q.content.replace(/\s+/g, " ").trim().slice(0, 18) || "…"}</span>
              </button>
            ))}
          </div>
        </aside>
      )}

      <section className="chat-area">
        {messages.length === 0
          ? <div className="welcome">
              <div className="welcome-mark">◉</div>
              <h2>从一个想法开始</h2>
              <p>输入一句话，Agent 会<b>联网搜索</b>最新信息，或<b>生成文档</b>（Word / PDF / Markdown）。</p>
              <div className="panel">
                <div className="panel-cell"><span>模型</span><b>DeepSeek</b></div>
                <div className="panel-cell"><span>工具</span><b>搜索 · 文档</b></div>
                <div className="panel-cell"><span>状态</span><b>就绪</b></div>
              </div>
            </div>
          : <div className="messages">{messages.map(m =>
              <article id={`msg-${m.id}`} className={`message ${m.role}`} key={m.id}>
                <div className="msg-meta">
                  <span className="msg-who">{m.role === "user" ? "你" : "AGENT"}</span>
                  <span className="msg-time">{fmtTime(m.created_at)}</span>
                </div>
                <div className="body">
                  {m.role === "user"
                    ? (<>
                        {m.content && <p className="user-text">{m.content}</p>}
                        {m.attachments && m.attachments.length > 0 && (
                          <div className="attachments">
                            {m.attachments.map((a, i) => a.content_type.startsWith("image/")
                              ? <a key={i} className="attachment-image" href={a.url} target="_blank" rel="noreferrer"><img src={a.url} alt={a.name} /></a>
                              : <a key={i} className="attachment-file" href={a.url} target="_blank" rel="noreferrer">📄 {a.name}</a>
                            )}
                          </div>
                        )}
                      </>)
                    : (<>
                        {m.content ? <Markdown content={m.content} />
                          : <span className="thinking">{busy ? "正在思考…" : ""}</span>}
                        {m.artifacts && m.artifacts.length > 0 && (
                          <div className="artifacts">
                            {m.artifacts.map((a, i) => (
                              <a key={i} className="artifact" href={a.url} download={a.filename} target="_blank" rel="noreferrer">
                                <span className="artifact-icon">📄</span>
                                <span className="artifact-name">{a.filename}</span>
                                <span className="artifact-dl">下载</span>
                              </a>
                            ))}
                          </div>
                        )}
                      </>)}
                </div>
              </article>
            )}</div>}
      </section>

      <div className="composer-wrap">
        {toolLog.length > 0 && (
          <div className="instrument">
            <div className="instrument-list">
              {toolLog.map((t, i) => (
                <span key={i} className={`instrument-item ${t.state}`}>
                  <span className="dot" />
                  {TOOL_LABELS[t.name] || t.name}
                  <span className="state">{t.state === "running" ? "进行中" : "已完成"}</span>
                </span>
              ))}
            </div>
          </div>
        )}
        {error && <div className="error">{error}</div>}
        <div className="composer">
          {attachments.length > 0 && (
            <div className="attachment-chips">
              {attachments.map((a, i) => (
                <span className="chip" key={i}>
                  {a.content_type.startsWith("image/")
                    ? <img src={a.url} alt={a.name} />
                    : <span className="chip-file">📄 {a.name}</span>}
                  <button type="button" title="移除" onClick={() => removeAttachment(i)}>×</button>
                </span>
              ))}
            </div>
          )}
          <textarea className="composer-input" rows={2} value={input} disabled={busy}
            placeholder="向 Agent 发送消息…（Enter 发送，Shift + Enter 换行）"
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} />
          <div className="composer-bottom">
            <div className="composer-tools">
              <input ref={fileInputRef} type="file" multiple hidden
                accept="image/*,.pdf,.doc,.docx,.md,.txt,.csv,.json,.xlsx,.pptx"
                onChange={e => void attachFiles(e.target.files)} />
              <button className="attach-btn" type="button" title="上传文件或图片"
                onClick={() => fileInputRef.current?.click()}>＋</button>
              <span className="hint">支持联网搜索与文档生成</span>
            </div>
            <button className="send-btn" disabled={busy || !input.trim()} onClick={() => void send()}>{busy ? "生成中…" : "发送　↑"}</button>
          </div>
        </div>
        <p className="disclaimer">Agent 可能生成不准确的信息。重要内容请自行核实。</p>
      </div>
    </main>

    {settingsOpen && (
      <SettingsModal theme={theme} onThemeChange={setTheme} onClose={() => setSettingsOpen(false)} />
    )}
  </div>;
}
