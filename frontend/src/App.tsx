import { useCallback, useEffect, useRef, useState } from "react";
import { chatApi, type StreamHandlers } from "./services/chat";
import { tasksApi } from "./services/tasks";
import Markdown from "./components/Markdown";
import SettingsModal from "./components/SettingsModal";
import ConfirmDialog, { type ConfirmState } from "./components/ConfirmDialog";
import TaskCard from "./components/TaskCard";
import type { Artifact, Attachment, Conversation, Message, StreamEvent, Task } from "./types/chat";

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
  // v0.3 任务模式
  const [taskMode, setTaskMode] = useState(false);
  const [liveTask, setLiveTask] = useState<Task | null>(null);
  const [liveText, setLiveText] = useState("");
  // 会话侧边栏：更多菜单 / 多选
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  // 应用内确认弹窗
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  const confirmResolve = useRef<((v: boolean) => void) | null>(null);
  const activeIdRef = useRef<number | null>(null);
  activeIdRef.current = activeId;
  const visibleIdsRef = useRef<number[]>([]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("theme", theme); } catch { /* 忽略存储失败 */ }
  }, [theme]);

  const refresh = useCallback(async () => {
    const items = await chatApi.listConversations();
    setConversations(items);
    return items;
  }, []);

  /** 应用内确认弹窗（替代 window.confirm）。 */
  const askConfirm = useCallback(
    (title: string, message: string, danger = true, labels?: { confirm?: string; cancel?: string }) => (
      new Promise<boolean>(resolve => {
        confirmResolve.current = resolve;
        setConfirmState({ title, message, danger, confirmLabel: labels?.confirm, cancelLabel: labels?.cancel });
      })
    ), []);

  const closeConfirm = useCallback((v: boolean) => {
    confirmResolve.current?.(v);
    confirmResolve.current = null;
    setConfirmState(null);
  }, []);

  const load = useCallback(async (id: number) => {
    setActiveId(id);
    setVersionSel({});
    setLiveTask(null);
    setLiveText("");
    const [msgs, ts] = await Promise.all([
      chatApi.listMessages(id),
      tasksApi.listByConversation(id).catch(() => [] as Task[]),
    ]);
    setMessages(msgs);
    // 恢复该会话未收尾的任务卡片（待审阅 / 失败可重试）
    const open = ts.find(t => t.status === "awaiting_approval") ?? ts.find(t => t.status === "failed") ?? null;
    setLiveTask(open);
  }, []);

  // 初始界面 = 主界面：只拉列表，不选中任何会话
  useEffect(() => {
    void refresh().catch((e: unknown) => setError(e instanceof Error ? e.message : "连接后端失败"));
  }, [refresh]);

  /** “新建会话”不立即落库：切回主界面，首次发送时才真正创建会话。 */
  function openHome() {
    setActiveId(null);
    setMessages([]);
    setLiveTask(null);
    setLiveText("");
    setVersionSel({});
    setError("");
    setMenuFor(null);
    setSelectMode(false);
    setSelectedIds(new Set());
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
    const ok = await askConfirm("删除会话", `删除会话「${c.title}」？此操作不可恢复。`);
    if (!ok) return;
    try {
      setError("");
      await chatApi.deleteConversation(c.id);
      setSelectedIds(cur => {
        const n = new Set(cur);
        n.delete(c.id);
        return n;
      });
      if (activeId === c.id) openHome();
      else await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除会话失败");
    }
  }

  function toggleSelect(id: number) {
    setSelectedIds(cur => {
      const n = new Set(cur);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  function toggleSelectMode() {
    setSelectMode(v => !v);
    setSelectedIds(new Set());
    setMenuFor(null);
  }

  function toggleAllSelected() {
    setSelectedIds(cur => (cur.size ? new Set() : new Set(visibleIdsRef.current)));
  }

  async function bulkDelete() {
    const ids = [...selectedIds];
    if (!ids.length) return;
    const ok = await askConfirm("删除会话", `确认删除选中的 ${ids.length} 个会话？此操作不可恢复。`);
    if (!ok) return;
    setError("");
    let failed = 0;
    for (const id of ids) {
      try { await chatApi.deleteConversation(id); } catch { failed += 1; }
    }
    if (failed) setError(`${failed} 个会话删除失败`);
    const wasActive = activeId !== null && selectedIds.has(activeId);
    setSelectedIds(new Set());
    setSelectMode(false);
    if (wasActive) openHome();
    else await refresh();
  }

  async function bulkPin(pinned: boolean) {
    for (const id of selectedIds) {
      try { await chatApi.updateConversation(id, { pinned }); } catch { /* 单个失败不阻断批量 */ }
    }
    setSelectedIds(new Set());
    setSelectMode(false);
    await refresh();
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
    if (taskMode) {
      // 任务模式：只创建任务（规划出计划），审阅后在卡片上点“执行计划”
      setBusy(true);
      try {
        const task = await tasksApi.create(content, activeId);
        setLiveTask(task);
        setLiveText("");
        setInput("");
        setAttachments([]);
      } catch (e) {
        setError(e instanceof Error ? e.message : "任务创建失败");
      } finally {
        setBusy(false);
      }
      return;
    }
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

  /** v0.3：任务执行事件 → 卡片状态。 */
  function handleTaskEvent(ev: StreamEvent) {
    switch (ev.type) {
      case "plan_created":
        setLiveText("");
        setLiveTask(t => (t ? { ...t, status: "running", steps: ev.steps ?? t.steps } : t));
        break;
      case "step_started":
        setLiveText("");
        setLiveTask(t => (t ? { ...t, status: "running", steps: t.steps.map(s => (s.idx === ev.index ? { ...s, status: "running" as const } : s)) } : t));
        break;
      case "text_delta":
        setLiveText(prev => prev + (ev.content ?? ""));
        break;
      case "artifact_ready":
        setLiveTask(t => (t ? { ...t, steps: t.steps.map(s => (s.status === "running"
          ? { ...s, artifacts: [...(s.artifacts ?? []), { filename: ev.filename ?? "", url: ev.url ?? "", format: ev.format ?? "" }] }
          : s)) } : t));
        break;
      case "step_completed":
        setLiveText("");
        setLiveTask(t => (t ? { ...t, steps: t.steps.map(s => (s.idx === ev.index
          ? { ...s, status: "done" as const, summary: ev.summary ?? "", artifacts: ev.artifacts ?? s.artifacts }
          : s)) } : t));
        break;
      case "step_failed":
        setLiveTask(t => (t ? { ...t, status: "failed", steps: t.steps.map(s => (s.idx === ev.index ? { ...s, status: "failed" as const, error: ev.error ?? "" } : s)) } : t));
        break;
      case "task_completed": {
        const st = ev.status ?? "completed";
        if (st === "cancelled") {
          setLiveTask(null);
          setLiveText("");
        } else {
          setLiveTask(t => (t ? { ...t, status: st } : t));
        }
        break;
      }
    }
  }

  async function executeTask(taskId: number) {
    if (busy) return;
    setBusy(true);
    setToolLog([]);
    setError("");
    try {
      // streamHandlers(-1)：占位消息 id 不存在 → onDelta 无副作用，只借工具读数与事件旁路
      await tasksApi.execute(taskId, { ...streamHandlers(-1), onEvent: handleTaskEvent });
    } catch (e) {
      setError(e instanceof Error ? e.message : "任务执行失败");
    } finally {
      setBusy(false);
    }
    try {
      const latest = await tasksApi.get(taskId);
      if (latest.status === "completed") {
        setLiveTask(null);
        setLiveText("");
        const cid = latest.conversation_id;
        if (cid !== null && (activeIdRef.current === null || activeIdRef.current === cid)) await load(cid);
        await refresh();
      } else {
        setLiveTask(latest);
      }
    } catch { /* 同步失败保留现场 */ }
  }

  async function reviseLiveTask(steps: { title: string; detail: string }[]) {
    if (!liveTask) return;
    setLiveTask(await tasksApi.revise(liveTask.id, steps));
  }

  async function cancelLiveTask() {
    if (!liveTask) return;
    const ok = await askConfirm("取消任务", "取消后该任务不再执行；已产生的步骤结果仍会保留。", false,
      { confirm: "取消任务", cancel: "继续" });
    if (!ok) return;
    try {
      const t = await tasksApi.cancel(liveTask.id);
      if (t.status === "cancelled") {
        setLiveTask(null);
        setLiveText("");
      } else {
        setLiveTask(t);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "取消任务失败");
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
  visibleIdsRef.current = visible.map(c => c.id);

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><b className="mark">◉</b><div className="brand-word"><strong>Agent</strong><span>工作台</span></div></div>
      <button className="new" onClick={openHome}>新建会话</button>
      <div className="section-label conv-head">
        <span>会话</span>
        <button type="button" className={`conv-select-toggle ${selectMode ? "on" : ""}`} onClick={toggleSelectMode}>
          {selectMode ? "退出多选" : "多选"}
        </button>
      </div>
      <input className="conv-search" placeholder="搜索会话…" value={search}
        onChange={e => setSearch(e.target.value)} />
      {selectMode && (
        <div className="conv-bulk-bar">
          <button type="button"
            onClick={toggleAllSelected}>{selectedIds.size > 0 && selectedIds.size === visibleIdsRef.current.length ? "取消全选" : "全选"}</button>
          <em>已选 {selectedIds.size}</em>
          <button type="button" disabled={!selectedIds.size} onClick={() => void bulkPin(true)}>置顶</button>
          <button type="button" disabled={!selectedIds.size} onClick={() => void bulkPin(false)}>取消置顶</button>
          <button type="button" className="danger" disabled={!selectedIds.size} onClick={() => void bulkDelete()}>删除</button>
        </div>
      )}
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
          <div key={c.id} className={`conv-item ${activeId === c.id ? "selected" : ""} ${selectMode && selectedIds.has(c.id) ? "checked" : ""}`}>
            {selectMode && (
              <input type="checkbox" className="conv-check" checked={selectedIds.has(c.id)}
                onChange={() => toggleSelect(c.id)} aria-label={`选择会话 ${c.title}`} />
            )}
            <button className="conv-title" title={c.title}
              onClick={() => (selectMode ? toggleSelect(c.id) : void load(c.id))}
              onDoubleClick={() => startEdit(c)}>
              {c.pinned && <span className="conv-pin-flag" title="已置顶">📌</span>}
              {c.title}
            </button>
            {!selectMode && (
              <button className="conv-more" type="button" title="更多操作" aria-label="更多操作"
                onClick={() => setMenuFor(menuFor === c.id ? null : c.id)}>⋯</button>
            )}
            {menuFor === c.id && (
              <>
                <div className="menu-scrim" onClick={() => setMenuFor(null)} />
                <div className="conv-menu">
                  <button type="button" onClick={() => { setMenuFor(null); startEdit(c); }}>重命名</button>
                  <button type="button" onClick={() => { setMenuFor(null); void pin(c); }}>{c.pinned ? "取消置顶" : "置顶"}</button>
                  <button type="button" className="danger" onClick={() => { setMenuFor(null); void removeConv(c); }}>删除</button>
                </div>
              </>
            )}
          </div>
        )
      )}</nav>
      <div className="side-foot"><span className="led" />本地运行</div>
    </aside>

    <main className="main">
      <header className="topbar">
        <div className="topbar-title">{activeConv?.title ?? "主界面"}</div>
        <div className="topbar-meta">
          <span className="meta-item">模型 <b>DeepSeek</b></span>
          <span className="meta-item">v0.3.0</span>
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
        {turns.length === 0 && !liveTask
          ? <div className="welcome">
              <div className="welcome-mark">◉</div>
              <h2>从一个想法开始</h2>
              <p>输入一句话，Agent 会<b>联网搜索</b>最新信息、<b>生成文档</b>（Word / PDF / Markdown），
              或打开<b>任务模式</b>把目标拆解为多步计划执行。</p>
              <div className="panel">
                <div className="panel-cell"><span>模型</span><b>DeepSeek</b></div>
                <div className="panel-cell"><span>工具</span><b>搜索 · 文档 · 任务</b></div>
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
            })}
            {liveTask && (
              <TaskCard task={liveTask} liveText={liveText} busy={busy}
                onExecute={() => void executeTask(liveTask.id)}
                onCancel={() => void cancelLiveTask()}
                onRevise={reviseLiveTask} />
            )}
            </div>}
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
              <button type="button" className={`mode-pill ${taskMode ? "on" : ""}`}
                title="任务模式：把目标拆解为多步计划，审阅后执行"
                onClick={() => setTaskMode(v => !v)}>任务模式</button>
              <span className="hint">{taskMode ? "描述一个目标，Agent 先给出执行计划" : "支持联网搜索与文档生成"}</span>
            </div>
            <button className="send-btn" disabled={busy || !input.trim()} onClick={() => void send()}>
              {busy ? (liveTask?.status === "running" ? "执行中…" : taskMode ? "规划中…" : "生成中…") : taskMode ? "规划任务" : "发送　↑"}
            </button>
          </div>
        </div>
        <p className="disclaimer">Agent 可能生成不准确的信息。重要内容请自行核实。</p>
      </div>
    </main>

    {settingsOpen && (
      <SettingsModal theme={theme} onThemeChange={setTheme} onClose={() => setSettingsOpen(false)} />
    )}
    {confirmState && <ConfirmDialog state={confirmState} onClose={closeConfirm} />}
  </div>;
}
