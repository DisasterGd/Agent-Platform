import { useCallback, useEffect, useState } from "react";
import { api } from "./services/api";
import type { Conversation, Message } from "./types/chat";

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const items = await api.listConversations();
    setConversations(items);
    return items;
  }, []);

  const load = useCallback(async (id: number) => {
    setActiveId(id);
    setMessages(await api.listMessages(id));
  }, []);

  useEffect(() => {
    void refresh().then(items => {
      if (items.length) return load(items[0].id);
    }).catch((e: unknown) => setError(e instanceof Error ? e.message : "连接后端失败"));
  }, [refresh, load]);

  async function createChat() {
    try {
      setError("");
      const item = await api.createConversation();
      await refresh();
      await load(item.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建会话失败");
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
        const item = await api.createConversation();
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
      await api.streamMessage(id, content, delta => {
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

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><b className="mark">A</b><div><strong>Agent Platform</strong><small>本地智能体工作台</small></div></div>
      <button className="new" onClick={() => void createChat()}>＋ 新建会话</button>
      <div className="section-label">最近会话</div>
      <nav>{conversations.map(c =>
        <button key={c.id} className={`chat-link ${activeId === c.id ? "selected" : ""}`}
          onClick={() => void load(c.id)}>◦　{c.title}</button>
      )}</nav>
      <div className="side-foot">● 本地开发环境</div>
    </aside>
    <main className="main">
      <header><div><small>WORKSPACE</small><h1>智能体对话</h1></div><span className="version">v0.1 · Prototype</span></header>
      <section className="chat-area">
        {messages.length === 0
          ? <div className="welcome"><div className="spark">✳</div><h2>从一个想法开始</h2>
              <p>这里将逐步加入模型调用、工具执行、任务规划与知识库能力。</p>
              <span>当前版本使用本地演示回复，尚未连接真实大模型。</span></div>
          : <div className="messages">{messages.map(m =>
              <article className="message" key={m.id}>
                <b className={m.role === "user" ? "avatar user" : "avatar"}>{m.role === "user" ? "你" : "AI"}</b>
                <div><small>{m.role === "user" ? "你" : "Agent"}</small><p>{m.content || (busy ? "正在思考…" : "")}</p></div>
              </article>
            )}</div>}
      </section>
      <div className="composer-wrap">
        {error && <div className="error">{error}</div>}
        <div className="composer">
          <textarea rows={2} value={input} disabled={busy} placeholder="向 Agent 发送消息…（Enter 发送，Shift + Enter 换行）"
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} />
          <div className="composer-bottom"><small>演示模式 · 消息保存到本地 MySQL</small>
            <button disabled={busy || !input.trim()} onClick={() => void send()}>{busy ? "生成中…" : "发送　↑"}</button></div>
        </div>
        <p className="disclaimer">Agent 可能生成不准确的信息。重要内容请自行核实。</p>
      </div>
    </main>
  </div>;
}