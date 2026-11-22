import { useEffect, useMemo, useRef, useState } from "react";
import type { Task, TaskStepStatus } from "../types/chat";
import Markdown from "./Markdown";

interface StepDraft { title: string; detail: string }

interface Props {
  task: Task;
  /** 当前 running 步骤的流式文本（仅执行中且本卡片活跃时有值）。 */
  liveText: string;
  /** SSE 是否正在本任务上运行。 */
  busy: boolean;
  onExecute: () => void;
  onCancel: () => void;
  onRevise: (steps: StepDraft[]) => Promise<void>;
}

const STATUS_LABEL: Record<Task["status"], string> = {
  awaiting_approval: "待审阅",
  running: "执行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const STEP_LABEL: Record<TaskStepStatus, string> = {
  pending: "待执行",
  running: "执行中",
  done: "完成",
  failed: "失败",
};

function clip(text: string, max = 160): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export default function TaskCard({ task, liveText, busy, onExecute, onCancel, onRevise }: Props) {
  const editable = task.status === "awaiting_approval" && !busy;
  const [drafts, setDrafts] = useState<StepDraft[]>([]);
  const [saving, setSaving] = useState(false);
  // 步骤摘要展开态（替代此前浏览器原生 title 悬停预览）
  const [openSummary, setOpenSummary] = useState<Set<number>>(new Set());
  const liveRef = useRef<HTMLDivElement>(null);

  // 执行中的实时输出：新内容到达即跟随到底部（滚动节奏跟执行速度一致）
  useEffect(() => {
    const el = liveRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [liveText]);

  useEffect(() => {
    setDrafts(task.steps.map(s => ({ title: s.title, detail: s.detail })));
  }, [task.id, task.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = useMemo(
    () => editable && JSON.stringify(drafts) !== JSON.stringify(task.steps.map(s => ({ title: s.title, detail: s.detail }))),
    [drafts, editable, task.steps],
  );

  async function run() {
    if (saving) return;
    setSaving(true);
    try {
      if (dirty) {
        const cleaned = drafts
          .map(d => ({ title: d.title.trim(), detail: d.detail.trim() }))
          .filter(d => d.title || d.detail);
        if (!cleaned.length) return;
        await onRevise(cleaned);
      }
      onExecute();
    } finally {
      setSaving(false);
    }
  }

  function setDraft(idx: number, patch: Partial<StepDraft>) {
    setDrafts(cur => cur.map((d, i) => (i === idx ? { ...d, ...patch } : d)));
  }

  function removeDraft(idx: number) {
    setDrafts(cur => cur.filter((_, i) => i !== idx));
  }

  function addDraft() {
    setDrafts(cur => [...cur, { title: "", detail: "" }]);
  }

  return (
    <article className={`task-card ${task.status} ${busy ? "streaming" : ""}`}>
      <div className="task-head">
        <span className="task-kicker">任务</span>
        <span className={`task-status s-${task.status}`}>{STATUS_LABEL[task.status]}</span>
      </div>
      <p className="task-goal">{task.goal}</p>

      <ol className="task-steps">
        {task.steps.map((s, i) => (
          <li key={s.idx} className={`task-step ${s.status}`}>
            <span className="task-step-dot" aria-hidden />
            <div className="task-step-body">
              {editable ? (
                <div className="task-step-edit">
                  <input
                    className="task-step-title"
                    value={drafts[i]?.title ?? ""}
                    placeholder="步骤名称"
                    onChange={e => setDraft(i, { title: e.target.value })}
                  />
                  <textarea
                    className="task-step-detail"
                    rows={2}
                    value={drafts[i]?.detail ?? ""}
                    placeholder="这一步要做什么"
                    onChange={e => setDraft(i, { detail: e.target.value })}
                  />
                  <button className="task-step-remove" type="button" data-tip="删除该步骤"
                    onClick={() => removeDraft(i)} disabled={drafts.length <= 1}>×</button>
                </div>
              ) : (
                <>
                  <div className="task-step-line">
                    <b>{s.title}</b>
                    <em className={s.status === "running" ? "shimmer" : undefined}>{STEP_LABEL[s.status]}</em>
                  </div>
                  {s.status === "running" && (
                    <div className="task-step-live" ref={liveRef}>
                      {liveText
                        ? <><Markdown content={liveText} /><span className="live-caret" aria-hidden /></>
                        : <span className="live-waiting">正在思考…</span>}
                    </div>
                  )}
                  {s.status === "done" && s.summary && (
                    <div className={`task-step-summary ${openSummary.has(s.idx) ? "open" : ""}`}>
                      {openSummary.has(s.idx)
                        ? <Markdown content={s.summary} />
                        : <span className="sum-line">{clip(s.summary)}</span>}
                      <button type="button" className="sum-toggle" aria-expanded={openSummary.has(s.idx)}
                        onClick={() => setOpenSummary(cur => {
                          const n = new Set(cur);
                          if (n.has(s.idx)) n.delete(s.idx);
                          else n.add(s.idx);
                          return n;
                        })}>
                        {openSummary.has(s.idx) ? "收起" : "展开全文"}
                      </button>
                    </div>
                  )}
                  {s.status === "failed" && s.error && (
                    <div className="task-step-error">{s.error}</div>
                  )}
                  {s.artifacts && s.artifacts.length > 0 && (
                    <div className="artifacts">
                      {s.artifacts.map((a, j) => (
                        <a key={j} className="artifact" href={a.url} download={a.filename} target="_blank" rel="noreferrer">
                          <span className="artifact-icon">📄</span>
                          <span className="artifact-name">{a.filename}</span>
                          <span className="artifact-dl">下载</span>
                        </a>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          </li>
        ))}
      </ol>

      {editable && (
        <button className="task-add-step" type="button" onClick={addDraft}>＋ 添加步骤</button>
      )}

      {task.status === "running" && !busy && (
        <div className="task-note">该任务正在后台执行；刷新本页不会继续接收进度，完成后可在对话中看到结果。</div>
      )}

      <div className="task-actions">
        {task.status === "awaiting_approval" && (
          <>
            <button className="task-cancel-btn" type="button" onClick={onCancel}>删除任务</button>
            <button className="task-run-btn" type="button" disabled={saving} onClick={() => void run()}>
              {dirty ? "保存计划并执行" : "执行计划"}
            </button>
          </>
        )}
        {task.status === "running" && (
          <button className="task-cancel-btn" type="button" onClick={onCancel}>取消任务</button>
        )}
        {task.status === "failed" && (
          <>
            <button className="task-cancel-btn" type="button" onClick={onCancel}>删除任务</button>
            <button className="task-run-btn" type="button" onClick={onExecute}>重新执行</button>
          </>
        )}
      </div>
    </article>
  );
}
