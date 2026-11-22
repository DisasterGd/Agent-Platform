import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { searchApi, type SearchScope } from "../services/search";
import type { Conversation, ConvGroup, Project, SearchResults, TaskHit } from "../types/chat";

interface Props {
  projects: Project[];
  groups: ConvGroup[];
  conversations: Conversation[];
  onClose: () => void;
  onOpenConversation: (id: number) => void;
  onOpenTask: (task: TaskHit) => void;
  onOpenProject: (id: number) => void;
  onOpenGroup: (id: number) => void;
}

const TABS: { key: SearchScope; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "conversations", label: "对话" },
  { key: "tasks", label: "任务" },
  { key: "projects", label: "项目" },
  { key: "groups", label: "分组" },
];

const TASK_STATUS_LABEL: Record<TaskHit["status"], string> = {
  awaiting_approval: "待审阅",
  running: "执行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

/** 命中片段高亮：按关键词切分（不区分大小写）。 */
function Highlight({ text, q }: { text: string; q: string }) {
  const kw = q.trim().toLowerCase();
  if (!kw) return <>{text}</>;
  const parts: ReactNode[] = [];
  const lower = text.toLowerCase();
  let pos = 0;
  let n = 0;
  for (;;) {
    const hit = lower.indexOf(kw, pos);
    if (hit < 0) break;
    if (hit > pos) parts.push(text.slice(pos, hit));
    parts.push(<mark key={`m${n++}`}>{text.slice(hit, hit + kw.length)}</mark>);
    pos = hit + kw.length;
  }
  parts.push(text.slice(pos));
  return <>{parts}</>;
}

function relTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Date.now() - t;
  const min = Math.floor(diff / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} 天前`;
  return new Date(t).toLocaleDateString();
}

export default function SearchModal(props: Props) {
  const { projects, groups, conversations, onClose, onOpenConversation, onOpenTask, onOpenProject, onOpenGroup } = props;
  const [q, setQ] = useState("");
  const [scope, setScope] = useState<SearchScope>("all");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const timer = useRef<number | undefined>(undefined);
  const seq = useRef(0);

  const run = useCallback((keyword: string, s: SearchScope) => {
    window.clearTimeout(timer.current);
    if (!keyword.trim()) { setResults(null); setError(""); setLoading(false); return; }
    setLoading(true);
    const my = ++seq.current;
    timer.current = window.setTimeout(async () => {
      try {
        const r = await searchApi.query(keyword, s);
        if (seq.current === my) { setResults(r); setError(""); }
      } catch (e) {
        if (seq.current === my) setError(e instanceof Error ? e.message : "搜索失败");
      } finally {
        if (seq.current === my) setLoading(false);
      }
    }, 250);
  }, []);

  useEffect(() => { run(q, scope); }, [q, scope, run]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const convTitle = (id: number | null) =>
    id == null ? null : conversations.find(c => c.id === id)?.title ?? null;
  const projectName = (id?: number | null) =>
    id == null ? null : projects.find(p => p.id === id)?.name ?? null;
  const groupName = (id?: number | null) =>
    id == null ? null : groups.find(g => g.id === id)?.name ?? null;
  const convCountInProject = (id: number) => conversations.filter(c => c.project_id === id).length;
  const convCountInGroup = (id: number) => conversations.filter(c => c.group_id === id).length;

  const convRows = (items: SearchResults["conversations"]) => items.map(c => (
    <button type="button" className="s-item" key={`c${c.id}`}
      onClick={() => { onOpenConversation(c.id); onClose(); }}>
      <div className="s-item-top">
        <span className="s-item-title">
          {c.pinned && "📌 "}{c.kind === "task" && "[任务] "}<Highlight text={c.title} q={q} />
        </span>
        <span className="s-item-meta">
          {projectName(c.project_id) && <em>项目·{projectName(c.project_id)}</em>}
          {groupName(c.group_id) && <em>分组·{groupName(c.group_id)}</em>}
          <em>{relTime(c.updated_at)}</em>
        </span>
      </div>
      {c.snippet && <div className="s-item-snippet"><Highlight text={c.snippet} q={q} /></div>}
    </button>
  ));

  const taskRows = (items: TaskHit[]) => items.map(t => (
    <button type="button" className="s-item" key={`t${t.id}`}
      onClick={() => { onOpenTask(t); onClose(); }}>
      <div className="s-item-top">
        <span className="s-item-title"><Highlight text={t.goal} q={q} /></span>
        <span className="s-item-meta">
          <em className={`task-status s-${t.status}`}>{TASK_STATUS_LABEL[t.status]}</em>
          {t.steps_total > 0 && <em>{t.steps_done}/{t.steps_total}</em>}
          <em>{relTime(t.updated_at)}</em>
        </span>
      </div>
      {convTitle(t.conversation_id) && (
        <div className="s-item-snippet">会话：{convTitle(t.conversation_id)}</div>
      )}
    </button>
  ));

  const projectRows = (items: Project[]) => items.map(p => (
    <button type="button" className="s-item" key={`p${p.id}`}
      onClick={() => { onOpenProject(p.id); onClose(); }}>
      <div className="s-item-top">
        <span className="s-item-title">{p.pinned && "📌 "}<Highlight text={p.name} q={q} /></span>
        <span className="s-item-meta"><em>{relTime(p.updated_at)}</em></span>
      </div>
      <div className="s-item-snippet">
        {convCountInProject(p.id)} 个会话{p.description ? ` · ${p.description}` : ""}
      </div>
    </button>
  ));

  const groupRows = (items: ConvGroup[]) => items.map(g => (
    <button type="button" className="s-item" key={`g${g.id}`}
      onClick={() => { onOpenGroup(g.id); onClose(); }}>
      <div className="s-item-top">
        <span className="s-item-title"><Highlight text={g.name} q={q} /></span>
        <span className="s-item-meta"><em>{relTime(g.updated_at)}</em></span>
      </div>
      <div className="s-item-snippet">{convCountInGroup(g.id)} 个会话</div>
    </button>
  ));

  const emptyIn = (label: string) => <div className="s-empty">「{label}」中无结果</div>;

  const total = results
    ? results.conversations.length + results.tasks.length + results.projects.length + results.groups.length
    : 0;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal wide" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">搜索</span>
          <button className="modal-close" title="关闭" onClick={onClose}>×</button>
        </div>
        <div className="search-input-row">
          <input className="search-input" autoFocus placeholder="搜索对话、任务、项目、分组…"
            value={q} onChange={e => setQ(e.target.value)} />
        </div>
        <div className="s-tabs" role="tablist">
          {TABS.map(t => (
            <button key={t.key} type="button" role="tab" aria-selected={scope === t.key}
              className={`s-tab ${scope === t.key ? "on" : ""}`} onClick={() => setScope(t.key)}>
              {t.label}
            </button>
          ))}
        </div>

        <div className="modal-body search-body">
          {error && <div className="error">{error}</div>}
          {!q.trim() && (
            <div className="s-empty">输入关键词开始搜索。支持按标题、消息内容、任务目标与名称检索。</div>
          )}
          {q.trim() && loading && !results && <div className="s-empty">正在搜索…</div>}
          {q.trim() && results && total === 0 && !loading && (
            scope === "all"
              ? <div className="s-empty">没有找到与「{q.trim()}」相关的内容</div>
              : emptyIn(TABS.find(t => t.key === scope)!.label)
          )}
          {q.trim() && results && total > 0 && (
            scope === "all" ? (
              <>
                {results.conversations.length > 0 && (
                  <><div className="s-group-label">对话 · {results.conversations.length}</div>{convRows(results.conversations)}</>
                )}
                {results.tasks.length > 0 && (
                  <><div className="s-group-label">任务 · {results.tasks.length}</div>{taskRows(results.tasks)}</>
                )}
                {results.projects.length > 0 && (
                  <><div className="s-group-label">项目 · {results.projects.length}</div>{projectRows(results.projects)}</>
                )}
                {results.groups.length > 0 && (
                  <><div className="s-group-label">分组 · {results.groups.length}</div>{groupRows(results.groups)}</>
                )}
              </>
            ) : (
              <>
                {scope === "conversations" && emptyIf(results.conversations.length, "对话")}
                {scope === "tasks" && emptyIf(results.tasks.length, "任务")}
                {scope === "projects" && emptyIf(results.projects.length, "项目")}
                {scope === "groups" && emptyIf(results.groups.length, "分组")}
                {scope === "conversations" && convRows(results.conversations)}
                {scope === "tasks" && taskRows(results.tasks)}
                {scope === "projects" && projectRows(results.projects)}
                {scope === "groups" && groupRows(results.groups)}
              </>
            )
          )}
        </div>
      </div>
    </div>
  );

  function emptyIf(count: number, label: string) {
    return count === 0 ? emptyIn(label) : null;
  }
}
