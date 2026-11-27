import { useEffect, useRef, useState } from "react";
import FolderPickerModal from "./FolderPickerModal";
import type { Conversation, LocalProject, Project } from "../types/chat";

interface Props {
  projects: Project[];
  conversations: Conversation[];
  /** v0.7.4 本地项目（仅 local 模式非空）：注册/开关/注销在弹窗内完成。 */
  localProjects?: LocalProject[];
  onLocalCreated?: (p: LocalProject) => void;
  onLocalToggle?: (p: LocalProject) => void;
  onLocalDelete?: (p: LocalProject) => void;
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
  const { projects, conversations, localProjects, onLocalCreated, onLocalToggle, onLocalDelete,
    onClose, onCreate, onRename, onPin, onDelete, onPick } = props;
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState("");
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftName, setDraftName] = useState("");
  // v0.7.4 本地项目：添加弹窗与行内菜单
  const [pickerOpen, setPickerOpen] = useState(false);
  const [lpMenuFor, setLpMenuFor] = useState<number | null>(null);
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
    <div className="modal-overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal xwide fixed" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">项目</span>
          <button className="modal-close" data-tip="关闭" onClick={onClose}>×</button>
        </div>

        <div className="proj-toolbar">
          <span className="proj-toolbar-hint">把相关会话收进同一个项目，项目记忆只在项目内生效。</span>
          <div className="proj-toolbar-actions">
            {localProjects && onLocalCreated && (
              <button type="button" className="proj-new-btn" onClick={() => setPickerOpen(true)}>＋ 添加本地项目</button>
            )}
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
                    <button type="button" className="proj-card-open" data-tip="筛选该项目的会话"
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

        {localProjects && localProjects.length > 0 && (
          <div className="proj-local">
            <div className="proj-local-head">
              <span className="proj-local-title">本地项目</span>
              <span className="proj-local-hint">机器上的真实目录：Agent 直接读写其中的文件，平台数据只保留注册记录。</span>
            </div>
            <ul className="proj-local-list">
              {localProjects.map(lp => (
                <li key={lp.id} className="lp-row">
                  <div className="lp-info">
                    <span className="lp-title">{lp.title}</span>
                    <span className="lp-path" title={lp.root_path}>{lp.root_path}</span>
                  </div>
                  <label className="lp-switch" data-tip={lp.allow_write ? "允许 Agent 写入" : "只读：Agent 不能改文件"}>
                    <input type="checkbox" checked={lp.allow_write}
                      onChange={() => onLocalToggle?.(lp)} />
                    <span>{lp.allow_write ? "可写入" : "只读"}</span>
                  </label>
                  <button className="proj-card-more" type="button" aria-label="本地项目操作"
                    onClick={() => setLpMenuFor(lpMenuFor === lp.id ? null : lp.id)}>⋯</button>
                  {lpMenuFor === lp.id && (
                    <>
                      <div className="menu-scrim" onClick={() => setLpMenuFor(null)} />
                      <div className="conv-menu card-menu">
                        <button type="button" className="danger" onClick={() => {
                          setLpMenuFor(null);
                          onLocalDelete?.(lp);
                        }}>移除注册</button>
                      </div>
                    </>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {pickerOpen && onLocalCreated && (
        <FolderPickerModal
          onClose={() => setPickerOpen(false)}
          onCreated={onLocalCreated}
        />
      )}
    </div>
  );
}
