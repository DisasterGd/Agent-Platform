import { useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import type { Conversation, ConvGroup, Project } from "../types/chat";

/** 列表过滤：项目弹窗/搜索结果选定后把侧边栏会话列表收拢到某个项目或分组。 */
export type ListFilter = { kind: "project" | "group"; id: number } | null;

interface Props {
  conversations: Conversation[];
  projects: Project[];
  groups: ConvGroup[];
  activeId: number | null;
  generatingConvId: number | null;
  listFilter: ListFilter;
  collapsed: boolean;
  onToggleCollapsed: (v: boolean) => void;
  onNewChat: () => void;
  onOpenSearch: () => void;
  onOpenProjects: () => void;
  /** v0.5 资料库：上传与生成的文件统一查看/管理 */
  onOpenLibrary: () => void;
  onOpenConversation: (c: Conversation) => void;
  onRename: (id: number, title: string) => void;
  onPin: (c: Conversation) => void;
  onDelete: (c: Conversation) => void;
  /** 添加至/更换项目：移入项目时同时离开自定义分组（归类互斥，项目优先呈现）。 */
  onMoveProject: (c: Conversation, projectId: number | null) => void;
  /** 移至/更换分组：移入分组时同时离开项目；任务会话只应进入任务子分组。 */
  onMoveGroup: (c: Conversation, groupId: number | null) => void;
  /** 任务会话直接归入“任务”：清分组并清项目。 */
  onMoveToTaskSection: (c: Conversation) => void;
  /** 在“移至分组”菜单内新建分组并立刻把会话移入（kind 按会话类型自动取 task/group）。 */
  onCreateGroupFor: (c: Conversation, name: string) => void;
  /** 右键批量移动：对所有目标会话按同一规则改归属（kind 决定子分组类型）。 */
  onBulkMove: (convs: Conversation[], kind: "project" | "group" | "out-project" | "out-group" | "task", id?: number | null) => void;
  /** 右键批量：在当前（子）分组内新建分组并把所有目标移入。 */
  onCreateGroupForMany: (convs: Conversation[], name: string) => void;
  onBulkDelete: (ids: number[]) => void;
  onBulkPin: (ids: number[], pinned: boolean) => void;
  onSetFilter: (f: ListFilter) => void;
  onCreateGroup: (name: string) => void;
  onRenameGroup: (id: number, name: string) => void;
  onDeleteGroup: (g: ConvGroup) => void;
}

const collapsedStore = "sidebar.collapsedSections";
// v0.5.2：默认宽度 ≈15% 视口；**不再记忆拖宽**（sidebar.width.* 旧存储作废），每次启动回到默认位置
const DEFAULT_RATIO = 0.15;
/** 拉伸下限：按“分区头与操作行不碎裂”定 192px（15% 视口在 1366 宽屏上也才 ≈205px，旧 246px 下限会顶穿默认值）。 */
const MIN_WIDTH = 192;
/** 拉伸上限：视口 32%（v0.4.4 的 40% 过宽：超过 1/3 后主区被挤得不成比例）。 */
const MAX_RATIO = 0.32;
/** 拖拽越界收起缓冲：宽度到下限后再向左超过该像素数，视为“继续收缩”→ 收起侧边栏。 */
const COLLAPSE_SLACK = 32;
/** 收起态图标条宽度（与 styles.css .sidebar.rail 一致）与“向右拖回”的触发阈值（参考 ChatGPT）。 */
const RAIL_WIDTH = 64;
const RAIL_EXPAND_PX = RAIL_WIDTH + 40;

function loadCollapsed(): Set<string> {
  try {
    const raw = localStorage.getItem(collapsedStore);
    return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
  } catch {
    return new Set();
  }
}

function clampWidth(w: number): number {
  const max = Math.round(window.innerWidth * MAX_RATIO);
  return Math.min(Math.max(w, MIN_WIDTH), Math.max(max, MIN_WIDTH));
}

function defaultWidth(): number {
  return clampWidth(Math.round(window.innerWidth * DEFAULT_RATIO));
}

function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => window.matchMedia("(max-width: 760px)").matches);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 760px)");
    const on = () => setNarrow(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return narrow;
}

function byName(a: { name: string }, b: { name: string }) {
  return a.name.localeCompare(b.name, "zh");
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <circle cx="6.8" cy="6.8" r="4.6" />
      <line x1="10.6" y1="10.6" x2="14" y2="14" />
    </svg>
  );
}

function FolderIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <path d="M1.6 4.2c0-.6.5-1.2 1.2-1.2h3l1.4 1.6h6c.6 0 1.2.5 1.2 1.2v6.4c0 .6-.5 1.2-1.2 1.2H2.8c-.6 0-1.2-.5-1.2-1.2z" />
    </svg>
  );
}

/** v0.5 资料库：叠层图标（一堆资料）。 */
function LibraryIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M8 2.2 14 5 8 7.8 2 5z" />
      <path d="M2 8.4 8 11.2 14 8.4" />
      <path d="M2 11.6 8 14.4 14 11.6" />
    </svg>
  );
}

function PenIcon() {
  return (
    <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M11.2 2.4 13.6 4.8 5.2 13.2l-3 .8.8-3z" />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden>
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4.6V8l2.4 1.6" />
    </svg>
  );
}

function CollapseIcon({ flip }: { flip?: boolean }) {
  return (
    <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden
      style={flip ? { transform: "scaleX(-1)" } : undefined}>
      <rect x="1.6" y="2.6" width="12.8" height="10.8" rx="1.6" />
      <line x1="6.2" y1="2.6" x2="6.2" y2="13.4" />
    </svg>
  );
}

/** 分区头部的“全选”复选框（多选模式下出现；部分选中时显示为半选）。 */
function SelBox({ ids, selected, onToggle, label }: {
  ids: number[]; selected: Set<number>; onToggle: () => void; label: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const all = ids.length > 0 && ids.every(i => selected.has(i));
  const some = ids.some(i => selected.has(i));
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = some && !all;
  }, [some, all]);
  return (
    <input ref={ref} type="checkbox" className="sec-check" checked={all}
      onChange={onToggle} onClick={e => e.stopPropagation()} aria-label={`全选${label}`} />
  );
}

export default function Sidebar(props: Props) {
  const {
    conversations, projects, groups, activeId, generatingConvId, listFilter,
    collapsed, onToggleCollapsed,
    onNewChat, onOpenSearch, onOpenProjects, onOpenLibrary, onOpenConversation, onRename, onPin, onDelete,
    onMoveProject, onMoveGroup, onMoveToTaskSection, onCreateGroupFor,
    onBulkMove, onCreateGroupForMany, onBulkDelete, onBulkPin, onSetFilter,
    onCreateGroup, onRenameGroup, onDeleteGroup,
  } = props;

  const narrow = useNarrow();

  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const cancelRename = useRef(false);

  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(loadCollapsed);
  const toggleSection = (key: string) => {
    setCollapsedSections(cur => {
      const next = new Set(cur);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      try { localStorage.setItem(collapsedStore, JSON.stringify([...next])); } catch { /* 忽略 */ }
      return next;
    });
  };

  const [creatingGroup, setCreatingGroup] = useState(false);
  const [draftGroup, setDraftGroup] = useState("");
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null);
  const [draftGroupName, setDraftGroupName] = useState("");
  const [groupMenuKey, setGroupMenuKey] = useState<string | null>(null);

  // 拖宽：默认 ≈ 视口 15%（v0.5.2 起不记忆，每次启动回默认），下限 192px、上限 32%；越过下限继续左拖则收起
  const [width, setWidth] = useState<number>(defaultWidth);
  useEffect(() => {
    const on = () => setWidth(w => clampWidth(w));
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  /**
   * v0.6.2 统一拖拽把手：一次按住可从 图标条 → 最小宽 → 最大宽 全程连续，状态切换不再中断拖拽。
   * - 收起态向右过阈值 → 展开并**继续跟鼠标**改宽（不再松手重来、也不再弹回默认宽）；
   * - 展开态拖到最小宽后再向左越过缓冲 → 收起，监听不撤，向右可再次拖出；
   * - 拖拽中途收起后的再展开阈值 = MIN_WIDTH（> 收起阈值 MIN-32），留出死区防边缘抖动。
   */
  function startDrag(e: ReactMouseEvent) {
    e.preventDefault();
    const ac = new AbortController();
    document.body.classList.add("side-resizing");
    const stop = () => { ac.abort(); document.body.classList.remove("side-resizing"); };
    let isCollapsed = collapsed;
    let expandAt = isCollapsed ? RAIL_EXPAND_PX : MIN_WIDTH;
    window.addEventListener("mousemove", ev => {
      const x = ev.clientX;
      if (isCollapsed) {
        if (x > expandAt) {
          isCollapsed = false;
          onToggleCollapsed(false);
          setWidth(clampWidth(x)); // 展开瞬间起宽跟手：x<MIN 时钳在 192，到 MIN 即自然衔接
        }
        return;
      }
      if (x < MIN_WIDTH - COLLAPSE_SLACK) {
        isCollapsed = true;
        expandAt = MIN_WIDTH;
        onToggleCollapsed(true);
        return;
      }
      setWidth(clampWidth(x));
    }, { signal: ac.signal });
    window.addEventListener("mouseup", stop, { signal: ac.signal });
  }

  // “⋯”菜单与子菜单用 fixed 定位（按按钮 rect），不再被侧边栏 overflow 裁掉
  const [menu, setMenu] = useState<{ c: Conversation; top: number; right: number } | null>(null);
  const [sub, setSub] = useState<{ type: "project" | "group"; top: number; left: number } | null>(null);
  const [subCreating, setSubCreating] = useState(false);
  const [subDraft, setSubDraft] = useState("");

  // 右键自定义菜单（行或组别头部）：targets 为操作对象，ctxSub 为二级菜单
  const [ctx, setCtx] = useState<{ targets: Conversation[]; top: number; left: number } | null>(null);
  const [ctxSub, setCtxSub] = useState<{ type: "project" | "group"; top: number; left: number } | null>(null);
  const [ctxCreating, setCtxCreating] = useState(false);
  const [ctxDraft, setCtxDraft] = useState("");

  // 收起态“最近”浮出面板（≤10 个最近更新会话）
  const [recentOpen, setRecentOpen] = useState(false);
  const [recentPos, setRecentPos] = useState({ top: 0, left: 0 });

  const rootGroups = useMemo(() => groups.filter(g => g.kind !== "task").slice().sort(byName), [groups]);
  const taskGroups = useMemo(() => groups.filter(g => g.kind === "task").slice().sort(byName), [groups]);
  const groupsMap = useMemo(() => new Map(groups.map(g => [g.id, g])), [groups]);
  const projectMap = useMemo(() => new Map(projects.map(p => [p.id, p])), [projects]);

  /** 归类（优先级）：任务子分组 → 根级分组 → 项目 → 任务 → 未分组；任务与普通会话互不混入。 */
  const bucketKeyOf = useMemo(() => {
    return (c: Conversation): string => {
      const g = c.group_id != null ? groupsMap.get(c.group_id) : undefined;
      if (g?.kind === "task") return `t:${g.id}`;
      if (g) return `g:${g.id}`;
      if (c.project_id) return `p:${c.project_id}`;
      if (c.kind === "task") return "__taskbare";
      return "none";
    };
  }, [groupsMap]);

  const buckets = useMemo(() => {
    const map = new Map<string, Conversation[]>();
    for (const c of conversations) {
      const k = bucketKeyOf(c);
      const arr = map.get(k);
      if (arr) arr.push(c);
      else map.set(k, [c]);
    }
    return map;
  }, [conversations, bucketKeyOf]);
  const B = (k: string) => buckets.get(k) ?? [];

  const recentConvs = useMemo(
    () => [...conversations].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 10),
    [conversations],
  );

  const closeMenu = () => { setMenu(null); setSub(null); setSubCreating(false); setSubDraft(""); };
  const closeCtx = () => { setCtx(null); setCtxSub(null); setCtxCreating(false); setCtxDraft(""); };
  const closeAll = () => { closeMenu(); closeCtx(); setRecentOpen(false); setGroupMenuKey(null); };

  // 菜单/浮层打开期间滚动或缩放视口先关闭，避免 fixed 元素错位
  useEffect(() => {
    if (!menu && !ctx && !recentOpen) return;
    const close = () => closeAll();
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [menu, ctx, recentOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  function openMenu(c: Conversation, el: HTMLElement) {
    const rect = el.getBoundingClientRect();
    setMenu({ c, top: rect.bottom + 4, right: Math.max(8, window.innerWidth - rect.right) });
    setSub(null);
    setSubCreating(false);
  }

  function openSub(type: "project" | "group", el: HTMLElement) {
    const rect = el.getBoundingClientRect();
    setSub({ type, top: rect.top - 4, left: Math.min(rect.right + 6, window.innerWidth - 236) });
    setSubCreating(false);
    setSubDraft("");
  }

  function showCtxAt(targets: Conversation[], x: number, y: number) {
    if (targets.length === 0) return;
    const left = Math.min(x, window.innerWidth - 196);
    const top = Math.min(y, window.innerHeight - 240);
    setCtx({ targets, top, left });
    setCtxSub(null);
    setCtxCreating(false);
    setCtxDraft("");
  }

  /** 右键行：多选且命中已选 → 全部选中；否则仅该行。阻止浏览器原生菜单。 */
  function openCtx(c: Conversation, e: ReactMouseEvent) {
    let targets: Conversation[];
    if (selectMode && selectedIds.has(c.id)) targets = conversations.filter(x => selectedIds.has(x.id));
    else {
      targets = [c];
      if (selectMode) setSelectedIds(new Set([c.id]));
    }
    if (targets.length === 0) return;
    e.preventDefault();
    e.stopPropagation();
    showCtxAt(targets, e.clientX, e.clientY);
  }

  /** 右键组别头部：对该组别（子组别）全部会话操作；多选模式下同步选中它们。 */
  function openCtxSection(memberIds: number[], e: ReactMouseEvent) {
    const set = new Set(memberIds);
    const targets = conversations.filter(c => set.has(c.id));
    if (targets.length === 0) return;
    e.preventDefault();
    e.stopPropagation();
    if (selectMode) setSelectedIds(new Set(memberIds));
    showCtxAt(targets, e.clientX, e.clientY);
  }

  function openCtxSub(type: "project" | "group", el: HTMLElement) {
    const rect = el.getBoundingClientRect();
    setCtxSub({ type, top: rect.top - 4, left: Math.min(rect.right + 6, window.innerWidth - 236) });
  }

  function openRecent(el: HTMLElement) {
    const rect = el.getBoundingClientRect();
    setRecentPos({
      top: Math.max(8, Math.min(rect.top, window.innerHeight - 460)),
      left: Math.min(rect.right + 6, window.innerWidth - 280),
    });
    setRecentOpen(true);
  }

  function startEdit(c: Conversation) {
    cancelRename.current = false;
    setEditingId(c.id);
    setDraftTitle(c.title);
  }

  function commitRename(id: number, title: string) {
    setEditingId(null);
    if (cancelRename.current) { cancelRename.current = false; return; }
    const next = title.trim();
    if (!next || next === conversations.find(c => c.id === id)?.title) return;
    onRename(id, next);
  }

  function toggleSelect(id: number) {
    setSelectedIds(cur => {
      const n = new Set(cur);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  function toggleIds(ids: number[]) {
    setSelectedIds(cur => {
      const n = new Set(cur);
      const allSelected = ids.length > 0 && ids.every(i => n.has(i));
      if (allSelected) ids.forEach(i => n.delete(i));
      else ids.forEach(i => n.add(i));
      return n;
    });
  }

  function toggleSelectMode() {
    setSelectMode(v => !v);
    setSelectedIds(new Set());
    closeAll();
  }

  const filterName = listFilter?.kind === "project"
    ? projectMap.get(listFilter.id)?.name
    : listFilter?.kind === "group"
      ? groupsMap.get(listFilter.id)?.name
      : null;

  const flatList = listFilter
    ? conversations.filter(c => (listFilter.kind === "project" ? c.project_id === listFilter.id : c.group_id === listFilter.id))
    : null;

  // ---------- 行 ----------

  function renderRow(c: Conversation, sectionKey: string) {
    const projectName = c.project_id != null ? projectMap.get(c.project_id)?.name : null;
    const showProjTag = !sectionKey.startsWith("p:") && listFilter?.kind !== "project" && projectName;
    const showTaskTag = !sectionKey.startsWith("t:") && sectionKey !== "__taskbare" && c.kind === "task";
    return editingId === c.id ? (
      <input key={c.id} className="rename-input" autoFocus value={draftTitle}
        onChange={e => setDraftTitle(e.target.value)}
        onBlur={() => commitRename(c.id, draftTitle)}
        onKeyDown={e => {
          if (e.key === "Enter") { e.preventDefault(); (e.currentTarget as HTMLInputElement).blur(); }
          if (e.key === "Escape") { cancelRename.current = true; setEditingId(null); }
        }} />
    ) : (
      <div key={c.id} className={`conv-item ${activeId === c.id ? "selected" : ""} ${selectMode && selectedIds.has(c.id) ? "checked" : ""}`}
        onContextMenu={e => openCtx(c, e)}>
        {selectMode && (
          <input type="checkbox" className="conv-check" checked={selectedIds.has(c.id)}
            onChange={() => toggleSelect(c.id)} aria-label={`选择会话 ${c.title}`} />
        )}
        {showProjTag && <span className="conv-tag" data-tip={projectName ?? ""}>{projectName}</span>}
        {!showProjTag && showTaskTag && <span className="conv-tag" data-tip="任务模式相关会话">任务</span>}
        <button className="conv-title" data-tip={c.title}
          onClick={() => (selectMode ? toggleSelect(c.id) : onOpenConversation(c))}
          onDoubleClick={() => startEdit(c)}>
          <span className="conv-dot" aria-hidden />
          {generatingConvId === c.id && (
            <span className="conv-spinner" role="status" aria-label="正在生成" data-tip="正在生成" />
          )}
          {c.pinned && <span className="conv-pin-flag" data-tip="已置顶">📌</span>}
          {c.title}
        </button>
        {!selectMode && (
          <button className="conv-more" type="button" data-tip="更多操作" aria-label="更多操作"
            onClick={e => {
              if (menu?.c.id === c.id) closeMenu();
              else openMenu(c, e.currentTarget);
            }}>⋯</button>
        )}
      </div>
    );
  }

  // ---------- 分区头部 ----------

  function renderGroupMenu(g: ConvGroup) {
    return (
      <>
        <button type="button" onClick={() => {
          setGroupMenuKey(null);
          setEditingGroupId(g.id);
          setDraftGroupName(g.name);
        }}>重命名</button>
        <button type="button" className="danger" onClick={() => { setGroupMenuKey(null); onDeleteGroup(g); }}>删除</button>
      </>
    );
  }

  function renderSecHead(opts: {
    sKey: string; label: string; memberIds: number[];
    group?: ConvGroup; nested?: boolean;
  }) {
    const { sKey, label, memberIds, group, nested } = opts;
    const isCollapsed = collapsedSections.has(sKey);
    return (
      <div className={`sec-head ${nested ? "nested" : ""}`} role="button" tabIndex={0} aria-expanded={!isCollapsed}
        onClick={() => toggleSection(sKey)}
        onContextMenu={e => openCtxSection(memberIds, e)}
        onKeyDown={e => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleSection(sKey); }
        }}>
        <span className="sec-caret">{isCollapsed ? "▸" : "▾"}</span>
        {selectMode && (
          <SelBox ids={memberIds} selected={selectedIds} onToggle={() => toggleIds(memberIds)} label={label} />
        )}
        {editingGroupId != null && group?.id === editingGroupId ? (
          <input className="sec-edit" autoFocus value={draftGroupName}
            onClick={e => e.stopPropagation()}
            onChange={e => setDraftGroupName(e.target.value)}
            onBlur={() => {
              setEditingGroupId(null);
              const next = draftGroupName.trim();
              if (next && next !== group?.name) onRenameGroup(group!.id, next);
            }}
            onKeyDown={e => {
              if (e.key === "Enter") { e.preventDefault(); (e.currentTarget as HTMLInputElement).blur(); }
              if (e.key === "Escape") setEditingGroupId(null);
            }} />
        ) : (
          <span className="sec-name">{label}</span>
        )}
        <span className="sec-count">{memberIds.length}</span>
        {group && (
          <>
            <button type="button" className="sec-more" aria-label="分组操作"
              onClick={e => { e.stopPropagation(); setGroupMenuKey(groupMenuKey === `g${group.id}` ? null : `g${group.id}`); }}>⋯</button>
            {groupMenuKey === `g${group.id}` && (
              <>
                <div className="menu-scrim" onClick={() => setGroupMenuKey(null)} onContextMenu={e => { e.preventDefault(); setGroupMenuKey(null); }} />
                <div className="conv-menu sec-menu">
                  {renderGroupMenu(group)}
                </div>
              </>
            )}
          </>
        )}
      </div>
    );
  }

  /** 普通分区：头部 + 行列表（自定义根分组 / 未分组）。 */
  function renderPlainSection(sKey: string, label: string, convs: Conversation[], group?: ConvGroup) {
    return (
      <div key={sKey} className="conv-section">
        {renderSecHead({ sKey, label, memberIds: convs.map(c => c.id), group })}
        {!collapsedSections.has(sKey) && <div className="sec-body">{convs.map(c => renderRow(c, sKey))}</div>}
      </div>
    );
  }

  /** 父分区：项目（下挂各项目子组别）、任务（下挂任务子组别）。children 已含各自折叠逻辑。 */
  function renderParentSection(sKey: string, label: string, allConvs: Conversation[], children: ReactNode) {
    return (
      <div key={sKey} className="conv-section">
        {renderSecHead({ sKey, label, memberIds: allConvs.map(c => c.id) })}
        {!collapsedSections.has(sKey) && (
          <div className="sec-body">
            {children}
          </div>
        )}
      </div>
    );
  }

  /** 项目子组别（每个项目可独立展开/收起）。 */
  function renderProjectSubgroup(pid: number) {
    const convs = B(`p:${pid}`);
    const p = projectMap.get(pid);
    if (!p || convs.length === 0) return null;
    const sKey = `p:${pid}`;
    return (
      <div key={sKey} className="conv-subsection">
        {renderSecHead({ sKey, label: p.name, memberIds: convs.map(c => c.id), nested: true })}
        {!collapsedSections.has(sKey) && <div className="sec-body sub">{convs.map(c => renderRow(c, sKey))}</div>}
      </div>
    );
  }

  /** 任务子分组（kind=task 的自定义分组，仅任务会话可归入）。 */
  function renderTaskSubgroup(g: ConvGroup) {
    const convs = B(`t:${g.id}`);
    const sKey = `t:${g.id}`;
    return (
      <div key={sKey} className="conv-subsection">
        {renderSecHead({ sKey, label: g.name, memberIds: convs.map(c => c.id), group: g, nested: true })}
        {!collapsedSections.has(sKey) && <div className="sec-body sub">{convs.map(c => renderRow(c, sKey))}</div>}
      </div>
    );
  }

  const projectConvs = [...buckets.keys()].filter(k => k.startsWith("p:")).flatMap(k => B(k));
  const taskBare = B("__taskbare");
  const taskConvsAll = [...taskBare, ...taskGroups.flatMap(g => B(`t:${g.id}`))];
  const sortedProjectIds = projects.filter(p => B(`p:${p.id}`).length > 0).map(p => p.id);

  // ---------- 移动目标计算（⋯菜单 与 右键菜单 共用规则：任务/普通不混用） ----------

  const menuConv = menu?.c ?? null;
  const menuIsTask = menuConv?.kind === "task";
  const groupTargets = menuIsTask ? taskGroups : rootGroups;
  const projectLabel = menuConv?.project_id != null ? "更换项目" : "添加至项目";
  const groupLabel = menuConv?.group_id != null ? "更换分组" : "移至分组";

  const ctxTargets = ctx?.targets ?? [];
  const ctxIds = ctxTargets.map(t => t.id);
  const ctxCanMove = ctxTargets.length > 0
    && ctxTargets.every(t => bucketKeyOf(t) === bucketKeyOf(ctxTargets[0]))
    && ctxTargets.every(t => (t.kind ?? "chat") === (ctxTargets[0].kind ?? "chat"));
  const ctxIsTask = (ctxTargets[0]?.kind ?? "chat") === "task";
  const ctxGroupTargets = ctxIsTask ? taskGroups : rootGroups;
  const ctxSameProject = ctxCanMove ? ctxTargets[0].project_id ?? null : null;
  const ctxSameGroup = ctxCanMove ? ctxTargets[0].group_id ?? null : null;

  // ---------- 收起态：极致压缩的图标条 ----------

  if (collapsed && !narrow) {
    return <aside className="sidebar rail">
      <button type="button" className="rail-mark" data-tip="展开侧边栏" aria-label="展开侧边栏" onClick={() => onToggleCollapsed(false)}>
        <b className="mark">◉</b>
      </button>
      <div className="rail-list">
        <button type="button" className="rail-btn" data-tip="新聊天" aria-label="新聊天" onClick={onNewChat}><PenIcon /></button>
        <button type="button" className="rail-btn" data-tip="搜索" aria-label="搜索" onClick={onOpenSearch}><SearchIcon /></button>
        <button type="button" className={`rail-btn ${recentOpen ? "on" : ""}`} data-tip="最近" aria-label="最近会话"
          onClick={e => (recentOpen ? setRecentOpen(false) : openRecent(e.currentTarget))}><ClockIcon /></button>
        <button type="button" className="rail-btn" data-tip="项目" aria-label="项目" onClick={onOpenProjects}><FolderIcon /></button>
        <button type="button" className="rail-btn" data-tip="资料库" aria-label="资料库" onClick={onOpenLibrary}><LibraryIcon /></button>
      </div>
      <div className="rail-foot">
        <button type="button" className="rail-btn" data-tip="展开侧边栏" aria-label="展开侧边栏" onClick={() => onToggleCollapsed(false)}>
          <CollapseIcon flip />
        </button>
      </div>

      {/* 收起态也能拖边拉回：右缘把手，向右拖出阈值即展开并继续跟手变宽（一次拖拽不中断） */}
      {!narrow && (
        <div className="side-resizer" role="separator" aria-orientation="vertical"
          data-tip="向右拖动展开侧边栏" onMouseDown={startDrag} />
      )}

      {recentOpen && (
        <>
          <div className="menu-scrim" onClick={() => setRecentOpen(false)} onContextMenu={e => { e.preventDefault(); setRecentOpen(false); }} />
          <div className="recent-panel fixed" style={{ top: recentPos.top, left: recentPos.left }}>
            <div className="recent-head">最近</div>
            {recentConvs.length === 0 && <div className="sub-empty">最近还没有会话</div>}
            {recentConvs.map(c => (
              <button key={c.id} type="button" className="recent-item" data-tip={c.title}
                onClick={() => { setRecentOpen(false); onOpenConversation(c); }}>
                {c.pinned && "📌 "}{c.title}
              </button>
            ))}
          </div>
        </>
      )}
    </aside>;
  }

  // ---------- 展开态 ----------

  return <aside className="sidebar" style={narrow ? undefined : { width, flexBasis: width }}>
    <div className="brand">
      <b className="mark">◉</b>
      <div className="brand-word"><strong>Agent</strong><span>工作台</span></div>
      <button type="button" className="side-collapse" data-tip="收起侧边栏" aria-label="收起侧边栏" onClick={() => onToggleCollapsed(true)}>
        <CollapseIcon />
      </button>
    </div>
    <button className="new" onClick={() => { closeAll(); onNewChat(); }}>新聊天</button>
    <div className="side-actions">
      <button type="button" className="side-action" onClick={() => { closeAll(); onOpenSearch(); }}>
        <SearchIcon /><span>搜索</span>
      </button>
      <button type="button" className="side-action" onClick={() => { closeAll(); onOpenProjects(); }}>
        <FolderIcon /><span>项目</span>
        {projects.length > 0 && <em className="side-action-count">{projects.length}</em>}
      </button>
      <button type="button" className="side-action" onClick={() => { closeAll(); onOpenLibrary(); }}>
        <LibraryIcon /><span>资料库</span>
      </button>
    </div>

    <div className="section-label conv-head">
      <span>分组</span>
      <div className="groups-tools">
        <button type="button" className="proj-add" data-tip="新建自定义分组" aria-label="新建自定义分组"
          onClick={() => setCreatingGroup(true)}>＋</button>
        <button type="button" className={`conv-select-toggle ${selectMode ? "on" : ""}`} onClick={toggleSelectMode}>
          {selectMode ? "退出多选" : "多选"}
        </button>
      </div>
    </div>
    {selectMode && (
      <div className="conv-bulk-bar slim">
        <em>已选 {selectedIds.size}</em>
        <button type="button" disabled={!selectedIds.size} onClick={() => setSelectedIds(new Set())}>清空</button>
        <span className="bulk-hint">右键会话或组别可批量操作</span>
      </div>
    )}

    <nav className="conv-list">
      {creatingGroup && (
        <input className="group-new" autoFocus placeholder="分组名，Enter 创建"
          value={draftGroup} onChange={e => setDraftGroup(e.target.value)}
          onBlur={() => {
            const name = draftGroup.trim();
            setCreatingGroup(false);
            setDraftGroup("");
            if (name) onCreateGroup(name);
          }}
          onKeyDown={e => {
            if (e.key === "Enter") { e.preventDefault(); (e.currentTarget as HTMLInputElement).blur(); }
            if (e.key === "Escape") { setCreatingGroup(false); setDraftGroup(""); }
          }} />
      )}
      {listFilter ? (
        <>
          <div className="list-filter">
            <span>{listFilter.kind === "project" ? "项目" : "分组"}：{filterName ?? "已失效"}</span>
            <button type="button" aria-label="退出筛选" onClick={() => onSetFilter(null)}>✕</button>
          </div>
          {(flatList ?? []).map(c => renderRow(c, ""))}
        </>
      ) : (
        <>
          {/* 默认区固定顺序：项目 → 任务 → …自定义分组(A~Z)… → 未分组（自定义分组插在任务与未分组之间） */}
          {projectConvs.length > 0 && renderParentSection(
            "__project", "项目", projectConvs,
            sortedProjectIds.map(pid => renderProjectSubgroup(pid)),
          )}
          {(taskConvsAll.length > 0 || taskGroups.length > 0) && renderParentSection(
            "__task", "任务", taskConvsAll,
            <>
              {taskBare.map(c => renderRow(c, "__taskbare"))}
              {taskGroups.map(g => renderTaskSubgroup(g))}
            </>,
          )}
          {rootGroups.map(g => renderPlainSection(`g:${g.id}`, g.name, B(`g:${g.id}`), g))}
          {renderPlainSection("none", "未分组", B("none"))}
        </>
      )}
    </nav>

    <div className="side-foot"><span className="led" />本地运行</div>

    {/* 拖宽把手（窄屏禁用） */}
    {!narrow && (
      <div className="side-resizer" role="separator" aria-orientation="vertical" data-tip="拖动调整侧边栏宽度；拖到最窄后继续向左可收起，无需松手再向右拖即可拖回" onMouseDown={startDrag} />
    )}

    {/* 会话“⋯”菜单：fixed 定位，可越出侧边栏，不再被裁切 */}
    {menu && menuConv && (
      <>
        <div className="menu-scrim" onClick={closeMenu} onContextMenu={e => { e.preventDefault(); closeMenu(); }} />
        <div className="conv-menu fixed" style={{ top: menu.top, right: menu.right }}>
          <button type="button" onClick={() => { closeMenu(); startEdit(menuConv); }}>重命名</button>
          <button type="button" onClick={() => { closeMenu(); onPin(menuConv); }}>{menuConv.pinned ? "取消置顶" : "置顶"}</button>
          <button type="button" className={sub?.type === "project" ? "open" : ""}
            onMouseEnter={e => openSub("project", e.currentTarget)}
            onClick={e => openSub("project", e.currentTarget)}>{projectLabel}</button>
          <button type="button" className={sub?.type === "group" ? "open" : ""}
            onMouseEnter={e => openSub("group", e.currentTarget)}
            onClick={e => openSub("group", e.currentTarget)}>{groupLabel}</button>
          <button type="button" className="danger" onClick={() => { closeMenu(); onDelete(menuConv); }}>删除</button>
        </div>
        {sub?.type === "project" && (
          <div className="conv-submenu fixed" style={{ top: sub.top, left: sub.left }}>
            {projects.length === 0 && <span className="sub-empty">暂无项目</span>}
            {projects.map(p => (
              <button key={p.id} type="button" className={menuConv.project_id === p.id ? "cur" : ""}
                onClick={() => { closeMenu(); if (menuConv.project_id !== p.id) onMoveProject(menuConv, p.id); }}>
                {p.pinned && "📌"}{p.name}{menuConv.project_id === p.id && " ✓"}
              </button>
            ))}
            {menuConv.project_id != null && (
              <button type="button" onClick={() => { closeMenu(); onMoveProject(menuConv, null); }}>从项目中移除</button>
            )}
          </div>
        )}
        {sub?.type === "group" && (
          <div className="conv-submenu fixed" style={{ top: sub.top, left: sub.left }}>
            {groupTargets.length === 0 && (
              <span className="sub-empty">{menuIsTask ? "暂无任务子分组，可在下方新建" : "暂无自定义分组，可在下方新建"}</span>
            )}
            {groupTargets.map(g => (
              <button key={g.id} type="button" className={menuConv.group_id === g.id ? "cur" : ""}
                onClick={() => { closeMenu(); if (menuConv.group_id !== g.id) onMoveGroup(menuConv, g.id); }}>
                {g.name}{menuConv.group_id === g.id && " ✓"}
              </button>
            ))}
            {menuIsTask && (menuConv.group_id != null || menuConv.project_id != null) && (
              <button type="button" onClick={() => { closeMenu(); onMoveToTaskSection(menuConv); }}>任务（直接归类）</button>
            )}
            {menuConv.group_id != null && (
              <button type="button" onClick={() => { closeMenu(); onMoveGroup(menuConv, null); }}>移出分组</button>
            )}
            <div className="sub-sep" />
            {subCreating ? (
              <input className="sub-input" autoFocus placeholder={menuIsTask ? "子分组名，Enter 创建并移入" : "分组名，Enter 创建并移入"}
                value={subDraft} onChange={e => setSubDraft(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    const name = subDraft.trim();
                    closeMenu();
                    if (name) onCreateGroupFor(menuConv, name);
                  }
                  if (e.key === "Escape") setSubCreating(false);
                }} />
            ) : (
              <button type="button" className="sub-new" onClick={() => setSubCreating(true)}>＋ 新建分组</button>
            )}
          </div>
        )}
      </>
    )}

    {/* 右键批量菜单（行 / 组别头部；自定义，屏蔽浏览器原生菜单） */}
    {ctx && ctxTargets.length > 0 && (
      <>
        <div className="menu-scrim" onClick={closeCtx} onContextMenu={e => { e.preventDefault(); closeCtx(); }} />
        <div className="conv-menu fixed" style={{ top: ctx.top, left: ctx.left, right: "auto" }}>
          <div className="ctx-title">{ctxIds.length > 1 ? `已选 ${ctxIds.length} 项` : ctxTargets[0].title}</div>
          <button type="button" onClick={() => { closeCtx(); setSelectedIds(new Set()); onBulkPin(ctxIds, true); }}>置顶</button>
          <button type="button" onClick={() => { closeCtx(); setSelectedIds(new Set()); onBulkPin(ctxIds, false); }}>取消置顶</button>
          {ctxCanMove && (
            <button type="button" className={ctxSub?.type === "project" ? "open" : ""}
              onMouseEnter={e => openCtxSub("project", e.currentTarget)}
              onClick={e => openCtxSub("project", e.currentTarget)}>
              {ctxSameProject != null ? "更换项目" : "添加至项目"}
            </button>
          )}
          {ctxCanMove && (
            <button type="button" className={ctxSub?.type === "group" ? "open" : ""}
              onMouseEnter={e => openCtxSub("group", e.currentTarget)}
              onClick={e => openCtxSub("group", e.currentTarget)}>
              {ctxSameGroup != null ? "更换分组" : "移至分组"}
            </button>
          )}
          <button type="button" className="danger" onClick={() => { closeCtx(); setSelectedIds(new Set()); onBulkDelete(ctxIds); }}>删除</button>
          {ctxIds.length > 1 && !ctxCanMove && (
            <div className="ctx-note">仅当所选在同一分组时可批量移动</div>
          )}
        </div>
        {ctxSub?.type === "project" && (
          <div className="conv-submenu fixed" style={{ top: ctxSub.top, left: ctxSub.left }}>
            {projects.length === 0 && <span className="sub-empty">暂无项目</span>}
            {projects.map(p => (
              <button key={p.id} type="button" className={ctxSameProject === p.id ? "cur" : ""}
                onClick={() => { closeCtx(); setSelectedIds(new Set()); if (ctxSameProject !== p.id) onBulkMove(ctxTargets, "project", p.id); }}>
                {p.pinned && "📌"}{p.name}{ctxSameProject === p.id && " ✓"}
              </button>
            ))}
            {ctxSameProject != null && (
              <button type="button" onClick={() => { closeCtx(); setSelectedIds(new Set()); onBulkMove(ctxTargets, "out-project"); }}>从项目中移除</button>
            )}
          </div>
        )}
        {ctxSub?.type === "group" && (
          <div className="conv-submenu fixed" style={{ top: ctxSub.top, left: ctxSub.left }}>
            {ctxGroupTargets.length === 0 && (
              <span className="sub-empty">{ctxIsTask ? "暂无任务子分组，可在下方新建" : "暂无自定义分组，可在下方新建"}</span>
            )}
            {ctxGroupTargets.map(g => (
              <button key={g.id} type="button" className={ctxSameGroup === g.id ? "cur" : ""}
                onClick={() => { closeCtx(); setSelectedIds(new Set()); if (ctxSameGroup !== g.id) onBulkMove(ctxTargets, "group", g.id); }}>
                {g.name}{ctxSameGroup === g.id && " ✓"}
              </button>
            ))}
            {ctxIsTask && ctxCanMove && (ctxSameGroup != null || ctxSameProject != null) && (
              <button type="button" onClick={() => { closeCtx(); setSelectedIds(new Set()); onBulkMove(ctxTargets, "task"); }}>任务（直接归类）</button>
            )}
            {ctxSameGroup != null && (
              <button type="button" onClick={() => { closeCtx(); setSelectedIds(new Set()); onBulkMove(ctxTargets, "out-group"); }}>移出分组</button>
            )}
            <div className="sub-sep" />
            {ctxCreating ? (
              <input className="sub-input" autoFocus placeholder={ctxIsTask ? "子分组名，Enter 创建并移入" : "分组名，Enter 创建并移入"}
                value={ctxDraft} onChange={e => setCtxDraft(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    const name = ctxDraft.trim();
                    closeCtx();
                    setSelectedIds(new Set());
                    if (name) onCreateGroupForMany(ctxTargets, name);
                  }
                  if (e.key === "Escape") setCtxCreating(false);
                }} />
            ) : (
              <button type="button" className="sub-new" onClick={() => setCtxCreating(true)}>＋ 新建分组</button>
            )}
          </div>
        )}
      </>
    )}
  </aside>;
}
