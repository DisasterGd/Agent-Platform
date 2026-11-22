import { useEffect, useRef, useState } from "react";
import type { Conversation, Project } from "../types/chat";

interface Props {
  projects: Project[];
  conversations: Conversation[];
  onClose: () => void;
  onCreate: (name: string) => void;
  onRename: (id: number, name: string) => void;
  onPin: (p: Project) => void;
  onDelete: (p: Project) => void;
  onPick: (id: number) => void;
}

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

export default function ProjectsModal(props: Props) {
  const { projects, conversations, onClose, onCreate, onRename, onPin, onDelete, onPick } = props;
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState("");
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftName, setDraftName] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { if (menuFor != null) setMenuFor(null); else onClose(); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuFor, onClose]);

  function commitCreate() {
    const name = draft.trim();
    setCreating(false);
    setDraft("");
    if (name) onCreate(name);
  }

  function commitRename(id: number) {
    setEditingId(null);
    const next = draftName.trim();
    if (next && next !== projects.find(p => p.id === id)?.name) onRename(id, next);
  }

  const convsIn = (id: number) => conversations.filter(c => c.project_id === id);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal xwide" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">项目</span>
          <button className="modal-close" title="关闭" onClick={onClose}>×</button>
        </div>

        <div className="proj-toolbar">
          <span className="proj-toolbar-hint">把相关会话收进同一个项目，项目记忆只在项目内生效。</span>
          {!creating && <button type="button" className="proj-new-btn" onClick={() => { setCreating(true); inputRef.current?.focus(); }}>＋ 新建项目</button>}
          {creating && (
            <input ref={inputRef} className="proj-new-input" autoFocus placeholder="项目名，Enter 创建"
              value={draft} onChange={e => setDraft(e.target.value)}
              onBlur={commitCreate}
              onKeyDown={e => {
                if (e.key === "Enter") { e.preventDefault(); commitCreate(); }
                if (e.key === "Escape") { setCreating(false); setDraft(""); }
              }} />
          )}
        </div>

        <div className="modal-body proj-body">
          {projects.length === 0 && !creating && (
            <div className="s-empty">还没有项目。新建一个项目，把相关会话收进来；卡片上的“⋯”可以重命名、置顶或删除。</div>
          )}
          <div className="proj-grid">
            {projects.map(p => {
              const convs = convsIn(p.id);
              const taskCount = convs.filter(c => c.kind === "task").length;
              return (
                <div key={p.id} className={`proj-card ${editingId === p.id ? "editing" : ""}`}>
                  {editingId === p.id ? (
                    <input className="proj-card-name-input" autoFocus value={draftName}
                      onChange={e => setDraftName(e.target.value)}
                      onBlur={() => commitRename(p.id)}
                      onKeyDown={e => {
                        if (e.key === "Enter") { e.preventDefault(); (e.currentTarget as HTMLInputElement).blur(); }
                        if (e.key === "Escape") setEditingId(null);
                      }} />
                  ) : (
                    <button type="button" className="proj-card-open" title="筛选该项目的会话"
                      onClick={() => { onPick(p.id); onClose(); }}>
                      <span className="proj-card-name">{p.pinned && "📌 "}{p.name}</span>
                      <span className="proj-card-desc">{p.description || "暂无描述"}</span>
                      <span className="proj-card-stats">
                        <em>{convs.length} 会话</em>
                        {taskCount > 0 && <em>{taskCount} 任务</em>}
                        <em>{relTime(p.updated_at)}</em>
                      </span>
                    </button>
                  )}
                  <button className="proj-card-more" type="button" aria-label="项目操作"
                    onClick={() => setMenuFor(menuFor === p.id ? null : p.id)}>⋯</button>
                  {menuFor === p.id && (
                    <>
                      <div className="menu-scrim" onClick={() => setMenuFor(null)} />
                      <div className="conv-menu card-menu">
                        <button type="button" onClick={() => {
                          setMenuFor(null);
                          setEditingId(p.id);
                          setDraftName(p.name);
                        }}>重命名</button>
                        <button type="button" onClick={() => { setMenuFor(null); onPin(p); }}>{p.pinned ? "取消置顶" : "置顶"}</button>
                        <button type="button" className="danger" onClick={() => { setMenuFor(null); onDelete(p); }}>删除</button>
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
