import { useEffect, useMemo, useRef, useState } from "react";
import TaskCard from "./TaskCard";
import ThinkingTicker, { type ThinkingTracker } from "./ThinkingTicker";
import Markdown from "./Markdown";
import type { Conversation, Task, TaskStatus } from "../types/chat";

interface Props {
  tasks: Task[];
  selectedId: number | null;
  busy: boolean;
  planning: boolean;
  liveText: string;
  thinking: ThinkingTracker;
  error: string;
  projectName: string | null;
  conversations: Conversation[];
  onSelect: (id: number) => void;
  onCreate: (goal: string) => void;
  onExecute: (id: number) => void;
  onCancel: (id: number) => void;
  onRevise: (id: number, steps: { title: string; detail: string }[]) => Promise<void>;
  onOpenConversation: (id: number) => void;
}

const FILTERS: { key: "all" | TaskStatus; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "awaiting_approval", label: "待审阅" },
  { key: "running", label: "执行中" },
  { key: "completed", label: "已完成" },
  { key: "failed", label: "失败" },
];

const STATUS_LABEL: Record<TaskStatus, string> = {
  awaiting_approval: "待审阅",
  running: "执行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

function relTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const min = Math.floor((Date.now() - t) / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.floor(hr / 24);
  return day < 30 ? `${day} 天前` : new Date(t).toLocaleDateString();
}

export default function TaskWorkspace(props: Props) {
  const {
    tasks, selectedId, busy, planning, liveText, thinking, error,
    projectName, conversations, onSelect, onCreate, onExecute, onCancel, onRevise, onOpenConversation,
  } = props;

  const [filter, setFilter] = useState<"all" | TaskStatus>("all");
  const [goal, setGoal] = useState("");
  const goalRef = useRef<HTMLTextAreaElement>(null);

  const visible = useMemo(
    () => (filter === "all" ? tasks : tasks.filter(t => t.status === filter)),
    [tasks, filter],
  );
  const selected = tasks.find(t => t.id === selectedId) ?? null;
  const attentionCount = tasks.filter(t => t.status === "awaiting_approval" || t.status === "failed").length;

  // 切换选中任务时把滚动位置带回详情顶部
  useEffect(() => {
    document.getElementById("task-detail-scroll")?.scrollTo({ top: 0 });
  }, [selectedId]);

  function submit() {
    const text = goal.trim();
    if (!text || busy || planning) return;
    setGoal("");
    onCreate(text);
  }

  return <section className="task-view">
    <div className="task-rail">
      <div className="task-rail-head">
        <span>任务</span>
        <em>{visible.length}{attentionCount > 0 && ` · ${attentionCount} 待处理`}</em>
      </div>
      <div className="task-filters">
        {FILTERS.map(f => (
          <button key={f.key} type="button" className={`task-filter ${filter === f.key ? "on" : ""}`}
            onClick={() => setFilter(f.key)}>
            {f.label}
          </button>
        ))}
      </div>
      <div className="task-rail-list">
        {visible.length === 0 && (
          <div className="task-rail-empty">
            {tasks.length === 0 ? "还没有任务。在下方描述一个目标，Agent 会先给出执行计划。" : "该状态下暂无任务"}
          </div>
        )}
        {visible.map(t => {
          const done = t.steps.filter(s => s.status === "done").length;
          return (
            <button key={t.id} type="button" className={`task-row ${t.id === selectedId ? "on" : ""}`}
              onClick={() => onSelect(t.id)}>
              <div className="task-row-top">
                <span className={`task-status s-${t.status}`}>{STATUS_LABEL[t.status]}</span>
                <span className="task-row-meta">{t.steps.length > 0 ? `${done}/${t.steps.length}` : ""}</span>
              </div>
              <span className="task-row-goal">{t.goal}</span>
              <span className="task-row-meta">{relTime(t.updated_at)}</span>
            </button>
          );
        })}
      </div>
    </div>

    <div className="task-work">
      <div className="task-detail-scroll" id="task-detail-scroll">
      {error && <div className="error task-error">{error}</div>}
      {selected ? (
        <div className="task-detail">
          <TaskCard task={selected} liveText={selected.status === "running" ? liveText : ""} busy={busy}
            onExecute={() => onExecute(selected.id)}
            onCancel={() => onCancel(selected.id)}
            onRevise={steps => onRevise(selected.id, steps)} />
          {selected.status === "completed" && selected.summary && (
            <div className="task-result">
              <div className="task-result-head">最终总结</div>
              <Markdown content={selected.summary} />
            </div>
          )}
          {selected.status === "failed" && selected.error && (
            <div className="task-step-error">{selected.error}</div>
          )}
          <div className="task-detail-actions">
            {selected.conversation_id != null && (
              <button type="button" className="msg-action"
                onClick={() => onOpenConversation(selected.conversation_id!)}>
                在对话中查看
                {conversations.find(c => c.id === selected.conversation_id)?.title
                  ? ` · ${conversations.find(c => c.id === selected.conversation_id)!.title}` : ""}
              </button>
            )}
            {planning && <span className="hint">正在生成计划…</span>}
          </div>
        </div>
      ) : (
        <div className="task-welcome">
          <div className="welcome-mark">◉</div>
          <h2>把目标交给 Agent</h2>
          <p>描述一个多步骤目标，它会先拆解出<b>执行计划</b>；你可以审阅、调整步骤，<b>确认后执行</b>。
          执行结果会写入一个会话，方便后续继续追问。</p>
        </div>
      )}
    </div>

    <div className="task-composer-wrap">
      <ThinkingTicker tracker={thinking} />
      <div className="composer">
        <textarea ref={goalRef} className="composer-input" rows={2} value={goal} disabled={busy || planning}
          placeholder="描述一个目标，例如：调研三款向量数据库并输出一份对比报告…（Enter 规划任务，Shift + Enter 换行）"
          onChange={e => setGoal(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }} />
        <div className="composer-bottom">
          <div className="composer-tools">
            <span className="hint">
              {projectName ? `新任务将归入项目「${projectName}」` : "先在左侧选中项目，可让任务归入该项目"}
            </span>
          </div>
          <button className="send-btn" disabled={busy || planning || !goal.trim()} onClick={submit}>
            {planning ? "规划中…" : "规划任务"}
          </button>
        </div>
      </div>
      <p className="disclaimer">任务执行会逐步落库；中断与失败都会在对应会话中留下记录。</p>
      </div>
    </div>
  </section>;
}
