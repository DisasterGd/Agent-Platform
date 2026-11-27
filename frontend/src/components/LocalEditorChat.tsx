/** v0.7.6 本地项目对话区：伪编辑器右栏的 Agent 会话（本地项目专属）。
 *
 * 复用服务层 streamSSE（与主界面同一套收发逻辑）与消息 CSS；渲染是刻意精简的版本：
 * 无版本翻页/编辑重生成/附件（这些属于主界面工作流），工具调用以轻量 chips 展示。
 * local_* 工具完成即回调 onFilesChanged → 左侧树刷新（磁盘是事实来源）。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Markdown from "./Markdown";
import { chatApi } from "../services/chat";
import { localProjectsApi } from "../services/localProjects";
import type { Conversation, LocalProject, Message } from "../types/chat";

interface Props {
  project: LocalProject;
  /** Agent 对本地项目执行过工具（写文件等）→ 父组件刷新树。 */
  onFilesChanged: () => void;
  /** 项目「允许写入」开关变更（已持久化，父组件同步状态）。 */
  onAllowWriteChange: (next: LocalProject) => void;
}

interface ToolChip {
  name: string;
  running: boolean;
}

export default function LocalEditorChat({ project, onFilesChanged, onAllowWriteChange }: Props) {
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [liveText, setLiveText] = useState("");
  const [chips, setChips] = useState<ToolChip[]>([]);
  const [error, setError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  const loadConvs = useCallback(async () => {
    const all = await chatApi.listConversations().catch(() => [] as Conversation[]);
    const mine = all.filter(c => c.local_project_id === project.id);
    setConvs(mine);
    return mine;
  }, [project.id]);

  const openConv = useCallback(async (id: number) => {
    setActiveId(id);
    const rows = await chatApi.listMessages(id).catch(() => [] as Message[]);
    setMessages(rows);
  }, []);

  // 打开项目：取该本地项目最近的会话（无则等待首条消息再惰性创建）
  useEffect(() => {
    setMessages([]); setActiveId(null); setLiveText(""); setChips([]); setError("");
    void (async () => {
      const mine = await loadConvs();
      if (mine.length > 0) await openConv(mine[0].id);
    })();
  }, [loadConvs, openConv]);

  useEffect(scrollToBottom, [messages, liveText, chips, scrollToBottom]);

  async function send() {
    const content = input.trim();
    if (!content || busy) return;
    setBusy(true); setError(""); setLiveText(""); setChips([]);
    setInput("");
    try {
      let convId = activeId;
      if (convId == null) {
        const created = await chatApi.createConversation("新会话", null, project.id);
        convId = created.id;
        setActiveId(convId);
      }
      // 本地乐观插入用户消息（服务端权威列表在流结束后覆盖）
      setMessages(cur => [...cur, {
        id: -Date.now(), conversation_id: convId!, role: "user", content,
        created_at: new Date().toISOString(),
      }]);
      await chatApi.streamMessage(convId, content, [], {
        onDelta: t => setLiveText(cur => cur + t),
        onToolStart: name => setChips(cur => [...cur, { name, running: true }]),
        onToolEnd: name => {
          setChips(cur => cur.map(c => (c.name === name ? { ...c, running: false } : c)));
          if (name.startsWith("local_")) onFilesChanged();
        },
      });
      setLiveText(""); setChips([]);
      await openConv(convId);
      await loadConvs();
    } catch (e) {
      setError(e instanceof Error ? e.message : "发送失败");
      setLiveText(""); setChips([]);
    } finally {
      setBusy(false);
    }
  }

  async function toggleWrite() {
    try {
      const next = await localProjectsApi.update(project.id, { allow_write: !project.allow_write });
      onAllowWriteChange(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "切换写入开关失败");
    }
  }

  return (
    <div className="lec-root">
      <div className="lec-head">
        <span className="lec-title">对话</span>
        <label className="lp-switch" data-tip={project.allow_write ? "允许 Agent 写入" : "只读：Agent 不能改文件"}>
          <input type="checkbox" checked={project.allow_write} onChange={() => void toggleWrite()} />
          <span>{project.allow_write ? "可写入" : "只读"}</span>
        </label>
        <button type="button" className="lec-new" data-tip="另开一个该项目的会话"
          onClick={() => { setActiveId(null); setMessages([]); setLiveText(""); setChips([]); }}>
          ＋ 新对话
        </button>
      </div>

      <div className="lec-history">
        {convs.length > 1 && convs.slice(0, 5).map(c => (
          <button key={c.id} type="button"
            className={`lec-conv ${c.id === activeId ? "active" : ""}`}
            onClick={() => void openConv(c.id)}>
            {c.title}
          </button>
        ))}
      </div>

      <div className="lec-messages" ref={scrollRef}>
        {messages.length === 0 && !busy && (
          <p className="editor-hint">让 Agent 直接操作这个项目：读代码、写文件、改配置……全部落盘到真实目录。</p>
        )}
        <div className="messages">
          {messages.map(m => (
            <article key={m.id} className={`message ${m.role}`}>
              <div className="msg-meta">
                <span className="msg-who">{m.role === "user" ? "你" : "AGENT"}</span>
              </div>
              <div className="body">
                {m.role === "user"
                  ? <p className="user-text">{m.content}</p>
                  : m.content ? <Markdown content={m.content} /> : null}
              </div>
            </article>
          ))}
        </div>
        {(liveText || chips.length > 0) && (
          <article className="message assistant">
            <div className="msg-meta"><span className="msg-who">AGENT</span></div>
            <div className="body">
              {chips.length > 0 && (
                <div className="lec-chips">
                  {chips.map((c, i) => (
                    <span key={`${c.name}-${i}`} className={`lec-chip ${c.running ? "running" : ""}`}>
                      {c.running ? "⏳" : "✓"} {c.name}
                    </span>
                  ))}
                </div>
              )}
              {liveText ? <Markdown content={liveText} /> : chips.length === 0 && <span className="thinking">正在思考…</span>}
            </div>
          </article>
        )}
      </div>

      {error && <p className="login-error">{error}</p>}
      <div className="lec-input">
        <textarea
          placeholder={project.allow_write
            ? "让 Agent 操作这个项目（Enter 发送）"
            : "只读模式：可以提问与分析，Agent 不能改文件（Enter 发送）"}
          value={input} disabled={busy}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); }
          }}
        />
        <button type="button" className="lec-send" disabled={busy || !input.trim()} onClick={() => void send()}>
          {busy ? "…" : "发送"}
        </button>
      </div>
    </div>
  );
}
