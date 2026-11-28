import { useEffect, useRef, useState } from "react";
import { localProjectsApi } from "../services/localProjects";
import type { Conversation, LocalProject, Project } from "../types/chat";

interface Props {
  projects: Project[];
  conversations: Conversation[];
  /** v0.7.4 本地项目（仅 local 模式非空）：注册/开关/注销在弹窗内完成。 */
  localProjects?: LocalProject[];
  onLocalCreated?: (p: LocalProject) => void;
  onLocalToggle?: (p: LocalProject) => void;
  onLocalDelete?: (p: LocalProject) => void;
  /** v0.7.5 点开本地项目 → 伪编辑器。 */
  onOpenLocal?: (p: LocalProject) => void;
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
  const { projects, conversations, localProjects, onLocalCreated, onLocalToggle, onLocalDelete, onOpenLocal,
    onClose, onCreate, onRename, onPin, onDelete, onPick } = props;
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState("");
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftName, setDraftName] = useState("");
  // v0.8.2 本地项目：原生目录选择对话框（后端 tkinter askdirectory）+ 命名确认；行内菜单
  const [picking, setPicking] = useState(false);
  const [pickError, setPickError] = useState("");
  const [pickedPath, setPickedPath] = useState<string | null>(null);
  const [pickTitle, setPickTitle] = useState("");
  const [pickBusy, setPickBusy] = useState(false);
  const [lpMenuFor, setLpMenuFor] = useState<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { if (menuFor != null) setMenuFor(null); else onClose(); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuFor, onClose]);

  /** 弹 Windows 原生目录选择对话框：选中后进入命名确认，取消则静默返回。 */
  async function startPick() {
    setPicking(true);
    setPickError("");
    try {
      const { path } = await localProjectsApi.pick();
      if (path) {
        setPickedPath(path);
        setPickTitle(path.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "");
      }
    } catch (e) {
      setPickError(e instanceof Error ? e.message : "无法打开目录选择窗口");
    } finally {
      setPicking(false);
    }
  }

  async function createPicked() {
    if (!pickedPath) return;
    setPickBusy(true);
    setPickError("");
    try {
      const project = await localProjectsApi.create(pickedPath, pickTitle.trim());
      onLocalCreated?.(project);
      setPickedPath(null);
      setPickTitle("");
    } catch (e) {
      setPickError(e instanceof Error ? e.message : "注册失败");
    } finally {
      setPickBusy(false);
    }
  }

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
              <button type="button" className="proj-new-btn" disabled={picking}
                onClick={() => void startPick()}>
                {picking ? "请在弹出窗口中选择…" : "＋ 添加本地项目"}
              </button>
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

        {pickError && !pickedPath && <p className="login-error pick-error" role="alert">{pickError}</p>}

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
                  <button type="button" className="lp-open" data-tip="打开伪编辑器（只读预览）"
                    onClick={() => { onOpenLocal?.(lp); onClose(); }}>
                    <span className="lp-title">{lp.title}</span>
                    <span className="lp-path">{lp.root_path}</span>
                  </button>
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

      {pickedPath && (
        <div className="modal-overlay" onMouseDown={e => { if (e.target === e.currentTarget && !pickBusy) setPickedPath(null); }}>
          <div className="modal fixed" onClick={e => e.stopPropagation()}>
            <div className="modal-head">
              <span className="modal-title">确认本地项目</span>
              <button className="modal-close" data-tip="关闭" disabled={pickBusy} onClick={() => setPickedPath(null)}>×</button>
            </div>
            <div className="modal-body">
              {pickError && <p className="login-error">{pickError}</p>}
              <p className="set-note">项目目录</p>
              <p className="fp-path">{pickedPath}</p>
              <label className="login-label" htmlFor="lp-title">显示名</label>
              <input
                id="lp-title" className="login-input" type="text" autoFocus
                value={pickTitle} onChange={e => setPickTitle(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") void createPicked(); }}
              />
              <p className="set-note">注册只记录路径，不会移动或改动任何文件。</p>
              <div className="fp-naming-actions">
                <button type="button" className="login-link" disabled={pickBusy} onClick={() => setPickedPath(null)}>取消</button>
                <button type="button" className="login-btn" disabled={pickBusy} onClick={() => void createPicked()}>
                  {pickBusy ? "注册中…" : "注册本地项目"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
