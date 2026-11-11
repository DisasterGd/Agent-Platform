import { useCallback, useEffect, useRef, useState } from "react";
import { chatApi } from "./services/chat";
import Markdown from "./components/Markdown";
import type { Conversation, Message } from "./types/chat";

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const cancelRename = useRef(false);

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

  async function send() {
    const content = input.trim();
    if (!content || busy) return;
    setError("");
    setBusy(true);
    let id = activeId;
    try {
      if (id === null) {
        const item = await chatApi.createConversation();
        id = item.id;
        setActiveId(id);
        await refresh();
      }
      const userMessage: Message = {
        id: Date.now(), conversation_id: id, role: "user",
        content, created_at: new Date().toISOString()
      };
      const assistantId = Date.now() + 1;
      const assistantMessage: Message = {
        id: assistantId, conversation_id: id, role: "assistant",
        content: "", created_at: new Date().toISOString()
      };
      setMessages(current => [...current, userMessage, assistantMessage]);
      setInput("");
      await chatApi.streamMessage(id, content, delta => {
        setMessages(current => current.map(m =>
          m.id === assistantId ? { ...m, content: m.content + delta } : m
        ));
      });
      await load(id);
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

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><b className="mark">A</b><div><strong>Agent Platform</strong><small>本地智能体工作台</small></div></div>
      <button className="new" onClick={() => void createChat()}>＋ 新建会话</button>
      <div className="section-label">最近会话</div>
      <nav>{conversations.map(c =>
        editingId === c.id ? (
          <input key={c.id} className="rename-input" autoFocus value={draftTitle}
            onChange={e => setDraftTitle(e.target.value)}
            onBlur={() => void rename(c.id, draftTitle)}
            onKeyDown={e => {
              if (e.key === "Enter") { e.preventDefault(); (e.currentTarget as HTMLInputElement).blur(); }
              if (e.key === "Escape") { cancelRename.current = true; setEditingId(null); }
            }} />
        ) : (
          <div key={c.id} className={`chat-link ${activeId === c.id ? "selected" : ""}`}>
            <button className="chat-link-title" title={c.title}
              onClick={() => void load(c.id)}
              onDoubleClick={() => startEdit(c)}>◦　{c.title}</button>
            <button className="chat-link-edit" title="重命名" onClick={() => startEdit(c)}>✎</button>
          </div>
        )
      )}</nav>
      <div className="side-foot">● 本地开发环境</div>
    </aside>
    <main className="main">
      <header><div><small>WORKSPACE</small><h1>智能体对话</h1></div><span className="version">v0.1.5 · Prototype</span></header>

      {questions.length > 0 && (
        <aside className="locator">
          <div className="locator-head"><span>问题定位</span><em>{questions.length}</em></div>
          <div className="locator-list">
            {questions.map((q, i) => (
              <button key={q.id} className="locator-item" title={q.content} onClick={() => jumpTo(q.id)}>
                <span className="locator-num">{i + 1}</span>
                <span className="locator-label">{q.content.replace(/\s+/g, " ").trim().slice(0, 18) || "…"}</span>
              </button>
            ))}
          </div>
        </aside>
      )}

      <section className="chat-area">
        {messages.length === 0
          ? <div className="welcome"><div className="spark">✳</div><h2>从一个想法开始</h2>
              <p>输入一句话，与 DeepSeek 大模型开始对话，消息会自动保存到本地 MySQL。</p>
              <span>已连接 DeepSeek · 流式回复</span></div>
          : <div className="messages">{messages.map(m =>
              <article id={`msg-${m.id}`} className={`message ${m.role}`} key={m.id}>
                <b className={`avatar ${m.role}`}>{m.role === "user" ? "你" : "AI"}</b>
                <div className="bubble">
                  <small>{m.role === "user" ? "你" : "Agent"}</small>
                  {m.role === "user"
                    ? <p className="user-text">{m.content}</p>
                    : (m.content ? <Markdown content={m.content} /> : <span className="thinking">{busy ? "正在思考…" : ""}</span>)}
                </div>
              </article>
            )}</div>}
      </section>
      <div className="composer-wrap">
        {error && <div className="error">{error}</div>}
        <div className="composer">
          <textarea rows={2} value={input} disabled={busy} placeholder="向 Agent 发送消息…（Enter 发送，Shift + Enter 换行）"
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} />
          <div className="composer-bottom"><small>DeepSeek · 消息保存到本地 MySQL</small>
            <button disabled={busy || !input.trim()} onClick={() => void send()}>{busy ? "生成中…" : "发送　↑"}</button></div>
        </div>
        <p className="disclaimer">Agent 可能生成不准确的信息。重要内容请自行核实。</p>
      </div>
    </main>
  </div>;
}
