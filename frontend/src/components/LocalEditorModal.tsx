/** v0.7.5 伪编辑器：目录树懒加载 + 文件查看；v0.7.6 右栏接入本地项目对话（Agent 直接读写真实目录）。
 *
 * - 树：按目录路径缓存各层，点开才请求（大仓库不卡）；噪音目录后端已过滤；
 * - 查看器：md 走 Markdown 渲染、其它文本等宽、图片 data URI、二进制/超大只给元信息；
 * - 对话区：Agent 工具完成（local_*）→ 刷新已展开的树层（磁盘是事实来源，所见即最新）；
 * - 只读边界：用户改文件请用自己顺手的本机工具直接改真实目录，树刷新即见。
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import LocalEditorChat from "./LocalEditorChat";
import Markdown from "./Markdown";
import { localProjectsApi, type FileContent, type TreeEntry } from "../services/localProjects";
import type { LocalProject } from "../types/chat";

interface Props {
  project: LocalProject;
  onClose: () => void;
  /** 项目「允许写入」开关变更（对话区内切换），父组件同步列表与编辑器状态。 */
  onProjectChange: (next: LocalProject) => void;
}

/** 大小展示（小工具，避免为它引整份 filetypes 前端词典）。 */
function humanSize(size: number | null): string {
  if (size == null) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export default function LocalEditorModal({ project, onClose, onProjectChange }: Props) {
  // 树：layers[path] = 该目录条目；expanded = 已展开目录集合
  const [layers, setLayers] = useState<Record<string, TreeEntry[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loadingDir, setLoadingDir] = useState<string | null>(null);
  const [treeError, setTreeError] = useState("");
  // 查看器
  const [selRel, setSelRel] = useState("");
  const [selName, setSelName] = useState("");
  const [content, setContent] = useState<FileContent | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [fileError, setFileError] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const loadLayer = useCallback(async (rel: string) => {
    setLoadingDir(rel);
    setTreeError("");
    try {
      const result = await localProjectsApi.tree(project.id, rel || ".");
      setLayers(cur => ({ ...cur, [rel]: result.entries }));
    } catch (e) {
      setTreeError(e instanceof Error ? e.message : "目录读取失败");
    } finally {
      setLoadingDir(null);
    }
  }, [project.id]);

  useEffect(() => { void loadLayer("."); }, [loadLayer]);

  /** Agent 对项目执行过工具（写文件等）→ 重载根层与全部已展开层。 */
  const refreshTree = useCallback(async () => {
    const targets = [".", ...expanded];
    const results = await Promise.allSettled(
      targets.map(rel => localProjectsApi.tree(project.id, rel || ".")),
    );
    setLayers(cur => {
      const next = { ...cur };
      results.forEach((r, i) => {
        if (r.status === "fulfilled") next[targets[i]] = r.value.entries;
      });
      return next;
    });
  }, [expanded, project.id]);

  async function toggleDir(rel: string) {
    const next = new Set(expanded);
    if (next.has(rel)) { next.delete(rel); setExpanded(next); return; }
    next.add(rel);
    setExpanded(next);
    if (!layers[rel]) await loadLayer(rel);
  }

  async function openFile(rel: string, name: string) {
    setSelRel(rel); setSelName(name);
    setFileLoading(true); setFileError(""); setContent(null);
    try {
      setContent(await localProjectsApi.readFile(project.id, rel));
    } catch (e) {
      setFileError(e instanceof Error ? e.message : "文件读取失败");
    } finally {
      setFileLoading(false);
    }
  }

  /** 递归渲染：目录可展开（懒加载），文件点击查看。 */
  function renderEntries(rel: string, depth: number): ReactNode[] {
    const entries = layers[rel];
    if (!entries) return loadingDir === rel ? [<p key={`${rel}-loading`} className="editor-hint">正在读取…</p>] : [];
    const base = rel === "." ? "" : rel; // 根层不带前导斜杠（否则后端 safe_resolve 判越界）
    return entries.flatMap(entry => {
      const childRel = base ? `${base}/${entry.name}` : entry.name;
      if (entry.type === "dir") {
        const isOpen = expanded.has(childRel);
        return [
          <button key={`d${childRel}`} type="button"
            className={`editor-tree-item ${isOpen ? "open" : ""}`}
            style={{ paddingLeft: 10 + depth * 14 }}
            onClick={() => void toggleDir(childRel)}>
            <span className="editor-tree-icon">{isOpen ? "▾" : "▸"}</span>{entry.name}
          </button>,
          ...(isOpen ? renderEntries(childRel, depth + 1) : []),
        ];
      }
      return [
        <button key={`f${childRel}`} type="button"
          className={`editor-tree-item file ${selRel === childRel ? "active" : ""}`}
          style={{ paddingLeft: 10 + depth * 14 + 14 }}
          onClick={() => void openFile(childRel, entry.name)}>
          <span className="editor-tree-icon">·</span>{entry.name}
          <em className="editor-tree-size">{humanSize(entry.size)}</em>
        </button>,
      ];
    });
  }

  function renderViewer() {
    if (fileLoading) return <p className="editor-hint">正在读取文件…</p>;
    if (fileError) return <p className="login-error">{fileError}</p>;
    if (!selRel) return (
      <div className="editor-empty">
        <p className="editor-hint">左侧选择一个文件查看内容。</p>
        <p className="editor-hint">这是只读预览——想自己改文件，直接用你顺手的本机工具改真实目录，然后点开文件即见最新内容；让 Agent 改，在右侧对话区说一声即可。</p>
      </div>
    );
    if (!content) return null;
    if (content.kind === "text" && content.truncated) {
      return <p className="editor-note">文件过大（{humanSize(content.size)}），超出预览上限，请用本机编辑器打开。</p>;
    }
    if (content.kind === "image") {
      return <img className="editor-img" src={content.content ?? ""} alt={selName} />;
    }
    if (content.kind === "binary") {
      return <p className="editor-note">二进制文件（{content.mime}，{humanSize(content.size)}）不支持预览。</p>;
    }
    // 文本：md 渲染，其余等宽
    const isMarkdown = content.mime === "text/markdown";
    return isMarkdown
      ? <Markdown content={content.content ?? ""} />
      : <pre className="editor-code">{content.content}</pre>;
  }

  return (
    <div className="modal-overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="editor-shell" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{project.title}<em className="editor-root" title={project.root_path}>{project.root_path}</em></span>
          <span className="editor-badge">本地项目</span>
          <button className="modal-close" data-tip="关闭" onClick={onClose}>×</button>
        </div>
        <div className="editor-body">
          <aside className="editor-tree">
            {treeError && <p className="login-error">{treeError}</p>}
            {renderEntries(".", 0)}
          </aside>
          <section className="editor-view">
            {selName && <p className="editor-file-head">{selRel}</p>}
            {renderViewer()}
          </section>
          <aside className="editor-chat">
            <LocalEditorChat
              project={project}
              onFilesChanged={() => void refreshTree()}
              onAllowWriteChange={onProjectChange}
            />
          </aside>
        </div>
      </div>
    </div>
  );
}
