import { useCallback, useEffect, useRef, useState } from "react";
import { chatApi, type StreamHandlers } from "./services/chat";
import Markdown from "./components/Markdown";
import SettingsModal from "./components/SettingsModal";
import type { Artifact, Attachment, Conversation, Message } from "./types/chat";

const TOOL_LABELS: Record<string, string> = {
  web_search: "联网搜索",
  generate_file: "生成文件",
};

type ToolEntry = { name: string; state: "running" | "done" };

/** 版本链分组结果：同一 group 的多个消息变体合并为一个气泡，可左右翻页。 */
type Turn = { key: number; role: "user" | "assistant"; items: Message[] };

function buildTurns(msgs: Message[]): Turn[] {
  const order: Turn[] = [];
  const byKey = new Map<number, Turn>();
  for (const m of msgs) {
    const key = m.group_id ?? m.id;
    let turn = byKey.get(key);
    if (!turn) {
      turn = { key, role: m.role, items: [] };
      byKey.set(key, turn);
      order.push(turn);
    }
    turn.items.push(m);
  }
  for (const t of order) {
    t.items.sort((a, b) => (a.variant_index ?? 0) - (b.variant_index ?? 0) || a.id - b.id);
  }
  return order;
}

/** 该气泡当前选看的版本；默认（未翻页）为最新一版。 */
function selectedVersion(selMap: Record<number, number>, turn: Turn): number {
  const stored = selMap[turn.key];
  const last = turn.items.length - 1;
  if (stored === undefined || stored < 0) return last;
  return Math.min(stored, last);
}

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
  const [search, setSearch] = useState("");
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [editingMsgId, setEditingMsgId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [versionSel, setVersionSel] = useState<Record<number, number>>({});
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
    setVersionSel({});
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
      await chatApi.updateConversation(id, { title: next });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "重命名失败");
    }
  }

  async function pin(c: Conversation) {
    try {
      setError("");
      await chatApi.updateConversation(c.id, { pinned: !c.pinned });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "置顶失败");
    }
  }

  async function removeConv(c: Conversation) {
    if (!window.confirm(`删除会话「${c.title}」？此操作不可恢复。`)) return;
    try {
      setError("");
      await chatApi.deleteConversation(c.id);
      const items = await refresh();
      if (activeId === c.id) {
        if (items.length) await load(items[0].id);
        else { setActiveId(null); setMessages([]); }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除会话失败");
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

  function streamHandlers(assistantId: number): StreamHandlers {
    return {
      onDelta: delta => setMessages(current => current.map(m =>
        m.id === assistantId ? { ...m, content: m.content + delta } : m
      )),
      onToolStart: name => setToolLog(log => [...log, { name, state: "running" as const }]),
      onToolEnd: () => setToolLog(log => {
        const idx = log.reduce<number>((acc, t, i) => (t.state === "running" ? i : acc), -1);
        if (idx < 0) return log;
        return log.map((t, i) => (i === idx ? { ...t, state: "done" as const } : t));
      }),
      onArtifact: (artifact: Artifact) => setMessages(current => current.map(m =>
        m.id === assistantId ? { ...m, artifacts: [...(m.artifacts || []), artifact] } : m
      )),
    };
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
      await chatApi.streamMessage(id, content, sentAttachments, streamHandlers(assistantId));
      await load(id); // 用服务端权威数据回填 id / 版本链字段
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

  async function regenerate(userMessageId: number, newContent?: string) {
    if (busy || activeId === null) return;
    const raw = messages.find(m => m.id === userMessageId);
    if (!raw) return;
    const convId = activeId;
    const trimmed = newContent?.trim();
    const edited = trimmed !== undefined && trimmed !== "" && trimmed !== raw.content;
    setError("");
    setBusy(true);
    setToolLog([]);
    setEditingMsgId(null);
    setEditDraft("");

    // 乐观追加新版本行（同链 group_id），旧版本保留在链内可翻页；流结束后用服务端数据回填
    const turnsNow = buildTurns(messages);
    const lastTurn = turnsNow[turnsNow.length - 1];
    const asstTurn = lastTurn && lastTurn.role === "assistant" ? lastTurn : null;
    const maxIdx = (items: Message[]) => items.reduce((acc, m) => Math.max(acc, m.variant_index ?? 0), 0);
    const userGroup = raw.group_id ?? raw.id;
    const stamp = Date.now();
    const userVariant: Message | null = edited
      ? {
          id: stamp, conversation_id: convId, role: "user", content: trimmed!,
          created_at: new Date().toISOString(), attachments: raw.attachments,
          group_id: userGroup, variant_index: maxIdx(turnsNow.find(t => t.key === userGroup)?.items ?? []) + 1,
        }
      : null;
    const assistantId = stamp + 1;
    const assistantMessage: Message = {
      id: assistantId, conversation_id: convId, role: "assistant",
      content: "", created_at: new Date().toISOString(), artifacts: [],
      group_id: asstTurn?.key, variant_index: asstTurn ? maxIdx(asstTurn.items) + 1 : 0,
    };
    try {
      setMessages(current => [...current, ...(userVariant ? [userVariant] : []), assistantMessage]);
      setVersionSel({});
      await chatApi.regenerate(convId, userMessageId, newContent, streamHandlers(assistantId));
      await load(convId);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "重新生成失败");
      try { await load(convId); } catch { /* keep original error */ }
    } finally {
      setBusy(false);
    }
  }

  function startEditMessage(turn: Turn, row: Message) {
    setEditingMsgId(turn.key);
    setEditDraft(row.content);
  }

  function cancelEditMessage() {
    setEditingMsgId(null);
    setEditDraft("");
  }

  async function copyMessage(m: Message) {
    try {
      await navigator.clipboard.writeText(m.content);
      setCopiedId(m.id);
      window.setTimeout(() => setCopiedId(cur => (cur === m.id ? null : cur)), 1500);
    } catch {
      setError("复制失败，请手动选择文本");
    }
  }

  function jumpTo(id: number) {
    document.getElementById(`msg-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  const turns = buildTurns(messages);
  const questions = turns.filter(t => t.role === "user" && t.items[t.items.length - 1].content.trim());
  const activeConv = conversations.find(c => c.id === activeId);
  const lastUserTurn = [...turns].reverse().find(t => t.role === "user");
  const visible = conversations.filter(c => {
    const kw = search.trim().toLowerCase();
    return !kw || c.title.toLowerCase().includes(kw);
  });

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><b className="mark">◉</b><div className="brand-word"><strong>Agent</strong><span>工作台</span></div></div>
      <button className="new" onClick={() => void createChat()}>新建会话</button>
      <div className="section-label">会话</div>
      <input className="conv-search" placeholder="搜索会话…" value={search}
        onChange={e => setSearch(e.target.value)} />
      <nav className="conv-list">{visible.map(c =>
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
            <button className={`conv-pin ${c.pinned ? "on" : ""}`} title={c.pinned ? "取消置顶" : "置顶"}
              onClick={() => void pin(c)}>📌</button>
            <button className="conv-del" title="删除" onClick={() => void removeConv(c)}>✕</button>
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
          <span className="meta-item">v0.2.6</span>
          <span className="meta-item"><span className="led" />就绪</span>
          <button className="settings-btn" onClick={() => setSettingsOpen(true)}>设置</button>
        </div>
      </header>

      {questions.length > 0 && (
        <aside className="index">
          <div className="index-head"><span>问题索引</span><em>{questions.length}</em></div>
          <div className="index-list">
            {questions.map((q, i) => {
              const latest = q.items[q.items.length - 1];
              return (
              <button key={q.key} className="index-item" title={latest.content} onClick={() => jumpTo(q.key)}>
                <span className="index-num">{i + 1}</span>
                <span className="index-label">{latest.content.replace(/\s+/g, " ").trim().slice(0, 18) || "…"}</span>
              </button>
              );
            })}
          </div>
        </aside>
      )}

      <section className="chat-area">
        {turns.length === 0
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
          : <div className="messages">{turns.map((t, ti) => {
              const isLastTurn = ti === turns.length - 1;
              const sel = selectedVersion(versionSel, t);
              const row = t.items[sel];
              const hasVariants = t.items.length > 1;
              const isEditing = editingMsgId === t.key;
              // 版本翻页器：同一逻辑消息有多个版本（重新生成/编辑产生）时显示“‹ n/N ›”
              const pager = hasVariants && (
                <span className="msg-versions" title="该消息有多个版本，可左右翻页查看">
                  <button type="button" aria-label="上一版本" disabled={sel <= 0}
                    onClick={() => setVersionSel(v => ({ ...v, [t.key]: Math.max(0, selectedVersion(v, t) - 1) }))}>‹</button>
                  <em>{sel + 1}/{t.items.length}</em>
                  <button type="button" aria-label="下一版本" disabled={sel >= t.items.length - 1}
                    onClick={() => setVersionSel(v => ({ ...v, [t.key]: Math.min(t.items.length - 1, selectedVersion(v, t) + 1) }))}>›</button>
                </span>
              );
              return (
              <article id={`msg-${t.key}`} className={`message ${t.role}`} key={t.key}>
                <div className="msg-meta">
                  <span className="msg-who">{t.role === "user" ? "你" : "AGENT"}</span>
                  <span className="msg-time">{fmtTime(row.created_at)}</span>
                  {row.content && (
                    <button className="msg-copy" type="button" onClick={() => void copyMessage(row)}>
                      {copiedId === row.id ? "已复制" : "复制"}
                    </button>
                  )}
                </div>
                <div className="body">
                  {t.role === "user"
                    ? isEditing
                      ? (<div className="edit-box">
                          <textarea autoFocus value={editDraft}
                            onChange={e => setEditDraft(e.target.value)}
                            onKeyDown={e => { if (e.key === "Escape") cancelEditMessage(); }} />
                          <div className="edit-actions">
                            <button type="button" onClick={cancelEditMessage}>取消</button>
                            <button type="button" className="primary" disabled={busy || !editDraft.trim()}
                              onClick={() => void regenerate(row.id, editDraft.trim())}>保存并重新生成</button>
                          </div>
                        </div>)
                      : (<>
                          {row.content && <p className="user-text">{row.content}</p>}
                          {row.attachments && row.attachments.length > 0 && (
                            <div className="attachments">
                              {row.attachments.map((a, i) => a.content_type.startsWith("image/")
                                ? <a key={i} className="attachment-image" href={a.url} target="_blank" rel="noreferrer"><img src={a.url} alt={a.name} /></a>
                                : <a key={i} className="attachment-file" href={a.url} target="_blank" rel="noreferrer">📄 {a.name}</a>
                              )}
                            </div>
                          )}
                          {(hasVariants || (isLastTurn && !busy)) && (
                            <div className="msg-actions">
                              {pager}
                              {isLastTurn && !busy && (
                                <button className="msg-action" type="button" onClick={() => startEditMessage(t, row)}>编辑</button>
                              )}
                            </div>
                          )}
                        </>)
                    : (<>
                        {row.content ? <Markdown content={row.content} />
                          : <span className="thinking">{busy ? "正在思考…" : ""}</span>}
                        {row.artifacts && row.artifacts.length > 0 && (
                          <div className="artifacts">
                            {row.artifacts.map((a, i) => (
                              <a key={i} className="artifact" href={a.url} download={a.filename} target="_blank" rel="noreferrer">
                                <span className="artifact-icon">📄</span>
                                <span className="artifact-name">{a.filename}</span>
                                <span className="artifact-dl">下载</span>
                              </a>
                            ))}
                          </div>
                        )}
                        {(hasVariants || (isLastTurn && !busy && row.content && lastUserTurn)) && (
                          <div className="msg-actions">
                            {pager}
                            {isLastTurn && !busy && row.content && lastUserTurn && (
                              <button className="msg-action" type="button"
                                onClick={() => void regenerate(lastUserTurn.items[selectedVersion(versionSel, lastUserTurn)].id)}>重新生成</button>
                            )}
                          </div>
                        )}
                      </>)}
                </div>
              </article>
              );
            })}</div>}
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
