/** v0.7.4 添加本地项目：盘符 → 逐层点选子目录 → 命名注册，全程不手输路径。
 *
 * 目录列表来自后端 /local-projects/browse（忽略 node_modules/.git 等噪音，仅列子目录）；
 * 只在 local 模式有此功能（cloud 下端点 404，入口按钮也不渲染）。
 */
import { useEffect, useRef, useState } from "react";
import { localProjectsApi } from "../services/localProjects";
import type { LocalProject } from "../types/chat";

interface Props {
  onClose: () => void;
  /** 注册成功后回调（App 负责并入状态）。 */
  onCreated: (project: LocalProject) => void;
}

export default function FolderPickerModal({ onClose, onCreated }: Props) {
  const [drives, setDrives] = useState<string[]>([]);
  const [path, setPath] = useState("");
  const [parent, setParent] = useState("");
  const [dirs, setDirs] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // 第二步：确认目录 + 命名
  const [naming, setNaming] = useState(false);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const titleRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void (async () => {
      try {
        const { drives: list } = await localProjectsApi.drives();
        setDrives(list);
        if (list.length === 1) await navigate(list[0]);
        else setLoading(false);
      } catch (e) {
        setError(e instanceof Error ? e.message : "无法读取磁盘列表");
        setLoading(false);
      }
    })();
  }, []);

  async function navigate(target: string) {
    setLoading(true); setError("");
    try {
      const result = await localProjectsApi.browse(target);
      setPath(result.path); setParent(result.parent); setDirs(result.dirs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "目录不可读");
    } finally {
      setLoading(false);
    }
  }

  function confirmPick() {
    if (!path) return;
    const name = path.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "";
    setTitle(name);
    setNaming(true);
    window.setTimeout(() => titleRef.current?.focus(), 0);
  }

  async function create() {
    if (!path) return;
    setBusy(true); setError("");
    try {
      const project = await localProjectsApi.create(path, title.trim());
      onCreated(project);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "注册失败");
      setBusy(false);
    }
  }

  const baseName = path ? path.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "" : "";

  return (
    <div className="modal-overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal fixed" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">添加本地项目</span>
          <button className="modal-close" data-tip="关闭" onClick={onClose}>×</button>
        </div>

        <div className="proj-toolbar">
          <span className="proj-toolbar-hint">
            {naming ? "确认目录并起个显示名；注册只记录路径，不会移动或改动任何文件。" : "逐层点选进入目录，选中后注册为本地项目。"}
          </span>
          {!naming && path && (
            <button type="button" className="proj-new-btn" onClick={confirmPick}>选择此目录</button>
          )}
        </div>

        <div className="modal-body fp-body">
          {error && <p className="login-error">{error}</p>}

          {naming ? (
            <div className="fp-naming">
              <p className="set-note">项目目录</p>
              <p className="fp-path">{path}</p>
              <label className="login-label" htmlFor="fp-title">显示名</label>
              <input
                id="fp-title" ref={titleRef} className="login-input" type="text"
                placeholder={baseName} value={title}
                onChange={e => setTitle(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") void create(); }}
              />
              <div className="fp-naming-actions">
                <button type="button" className="login-link" onClick={() => setNaming(false)}>← 重新选择</button>
                <button type="button" className="login-btn" disabled={busy} onClick={() => void create()}>
                  {busy ? "注册中…" : "注册本地项目"}
                </button>
              </div>
            </div>
          ) : (
            <>
              {drives.length > 1 && (
                <div className="fp-row">
                  {drives.map(d => (
                    <button key={d} type="button" className={`fp-crumb ${path === d ? "active" : ""}`}
                      onClick={() => void navigate(d)}>{d}</button>
                  ))}
                </div>
              )}
              {path && (
                <div className="fp-row">
                  <span className="fp-path" title={path}>{path}</span>
                  {parent && parent !== path && (
                    <button type="button" className="fp-crumb" onClick={() => void navigate(parent)}>← 上一级</button>
                  )}
                </div>
              )}
              {loading ? (
                <div className="s-empty">正在读取目录…</div>
              ) : !path ? (
                <div className="s-empty">选择一个磁盘开始浏览。</div>
              ) : dirs.length === 0 ? (
                <div className="s-empty">此目录下没有子目录（或只有被忽略的目录）。</div>
              ) : (
                <ul className="fp-list">
                  {dirs.map(d => {
                    // 统一用 "/" 拼接：Windows 的 Path 同样接受正斜杠，跨平台安全
                    const child = `${path.replace(/[\\/]+$/, "")}/${d}`;
                    return (
                      <li key={d}>
                        <button type="button" className="fp-item" onClick={() => void navigate(child)}>
                          <span className="fp-item-icon">▸</span>{d}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
