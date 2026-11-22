import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Conversation, ConvGroup, Project } from "../types/chat";

/** 列表过滤：项目弹窗/搜索结果选定后把侧栏会话列表收拢到某个项目或分组。 */
export type ListFilter = { kind: "project" | "group"; id: number } | null;

interface Props {
  conversations: Conversation[];
  projects: Project[];
  groups: ConvGroup[];
  activeId: number | null;
  generatingConvId: number | null;
  listFilter: ListFilter;
  onNewChat: () => void;
  onOpenSearch: () => void;
  onOpenProjects: () => void;
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
  onBulkDelete: (ids: number[]) => void;
  onBulkPin: (ids: number[], pinned: boolean) => void;
  onSetFilter: (f: ListFilter) => void;
  onCreateGroup: (name: string) => void;
  onRenameGroup: (id: number, name: string) => void;
  onDeleteGroup: (g: ConvGroup) => void;
}

const collapsedStore = "sidebar.collapsedSections";

function loadCollapsed(): Set<string> {
  try {
    const raw = localStorage.getItem(collapsedStore);
    return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
  } catch {
    return new Set();
  }
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
    onNewChat, onOpenSearch, onOpenProjects, onOpenConversation, onRename, onPin, onDelete,
    onMoveProject, onMoveGroup, onMoveToTaskSection, onCreateGroupFor,
    onBulkDelete, onBulkPin, onSetFilter,
    onCreateGroup, onRenameGroup, onDeleteGroup,
  } = props;

  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const cancelRename = useRef(false);

  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  const [collapsed, setCollapsed] = useState<Set<string>>(loadCollapsed);
  const toggleCollapsed = (key: string) => {
    setCollapsed(cur => {
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

  // “⋯”菜单与子菜单用 fixed 定位（按按钮 rect），不再被侧栏 overflow 裁掉
  const [menu, setMenu] = useState<{ c: Conversation; top: number; right: number } | null>(null);
  const [sub, setSub] = useState<{ type: "project" | "group"; top: number; left: number } | null>(null);
  const [subCreating, setSubCreating] = useState(false);
  const [subDraft, setSubDraft] = useState("");

  const rootGroups = useMemo(() => groups.filter(g => g.kind !== "task"), [groups]);
  const taskGroups = useMemo(() => groups.filter(g => g.kind === "task"), [groups]);
  const groupsMap = useMemo(() => new Map(groups.map(g => [g.id, g])), [groups]);
  const projectMap = useMemo(() => new Map(projects.map(p => [p.id, p])), [projects]);

  /** 归类（优先级）：任务子分组 → 根级分组 → 项目 → 任务 → 未分组；任务与普通会话互不混入。 */
  const buckets = useMemo(() => {
    const map = new Map<string, Conversation[]>();
    const push = (k: string, c: Conversation) => {
      const arr = map.get(k);
      if (arr) arr.push(c);
      else map.set(k, [c]);
    };
    for (const c of conversations) {
      const g = c.group_id != null ? groupsMap.get(c.group_id) : undefined;
      if (g?.kind === "task") push(`t:${g.id}`, c);
      else if (g) push(`g:${g.id}`, c);
      else if (c.project_id) push(`p:${c.project_id}`, c);
      else if (c.kind === "task") push("__taskbare", c);
      else push("none", c);
    }
    return map;
  }, [conversations, groupsMap]);
  const B = (k: string) => buckets.get(k) ?? [];

  const closeMenu = () => { setMenu(null); setSub(null); setSubCreating(false); setSubDraft(""); };

  // 菜单打开期间滚动/缩放视口先关闭，避免 fixed 菜单与行错位
  useEffect(() => {
    if (!menu) return;
    const close = () => closeMenu();
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [menu]); // eslint-disable-line react-hooks/exhaustive-deps

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
    closeMenu();
  }

  const filterName = listFilter?.kind === "project"
    ? projectMap.get(listFilter.id)?.name
    : listFilter?.kind === "group"
      ? groupsMap.get(listFilter.id)?.name
      : null;

  const flatList = listFilter
    ? conversations.filter(c => (listFilter.kind === "project" ? c.project_id === listFilter.id : c.group_id === listFilter.id))
    : null;

  const visibleIds = flatList ? flatList.map(c => c.id) : conversations.map(c => c.id);

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
      <div key={c.id} className={`conv-item ${activeId === c.id ? "selected" : ""} ${selectMode && selectedIds.has(c.id) ? "checked" : ""}`}>
        {selectMode && (
          <input type="checkbox" className="conv-check" checked={selectedIds.has(c.id)}
            onChange={() => toggleSelect(c.id)} aria-label={`选择会话 ${c.title}`} />
        )}
        {showProjTag && <span className="conv-tag" title={projectName ?? ""}>{projectName}</span>}
        {!showProjTag && showTaskTag && <span className="conv-tag" title="任务模式相关会话">任务</span>}
        <button className="conv-title" title={c.title}
          onClick={() => (selectMode ? toggleSelect(c.id) : onOpenConversation(c))}
          onDoubleClick={() => startEdit(c)}>
          {generatingConvId === c.id && (
            <span className="conv-spinner" role="status" aria-label="正在生成" title="正在生成" />
          )}
          {c.pinned && <span className="conv-pin-flag" title="已置顶">📌</span>}
          {c.title}
        </button>
        {!selectMode && (
          <button className="conv-more" type="button" title="更多操作" aria-label="更多操作"
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
    const isCollapsed = collapsed.has(sKey);
    return (
      <div className={`sec-head ${nested ? "nested" : ""}`} role="button" tabIndex={0} aria-expanded={!isCollapsed}
        onClick={() => toggleCollapsed(sKey)}
        onKeyDown={e => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleCollapsed(sKey); }
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
                <div className="menu-scrim" onClick={() => setGroupMenuKey(null)} />
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
        {!collapsed.has(sKey) && <div className="sec-body">{convs.map(c => renderRow(c, sKey))}</div>}
      </div>
    );
  }

  /** 父分区：项目（下挂各项目子组别）、任务（下挂任务子组别）。children 已含各自折叠逻辑。 */
  function renderParentSection(sKey: string, label: string, allConvs: Conversation[], children: ReactNode) {
    return (
      <div key={sKey} className="conv-section">
        {renderSecHead({ sKey, label, memberIds: allConvs.map(c => c.id) })}
        {!collapsed.has(sKey) && (
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
        {!collapsed.has(sKey) && <div className="sec-body sub">{convs.map(c => renderRow(c, sKey))}</div>}
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
        {!collapsed.has(sKey) && <div className="sec-body sub">{convs.map(c => renderRow(c, sKey))}</div>}
      </div>
    );
  }

  const projectConvs = [...buckets.keys()].filter(k => k.startsWith("p:")).flatMap(k => B(k));
  const taskBare = B("__taskbare");
  const taskConvsAll = [...taskBare, ...taskGroups.flatMap(g => B(`t:${g.id}`))];

  // ---------- “移至分组”子菜单的可选目标（任务/普通不混用） ----------

  const menuConv = menu?.c ?? null;
  const menuIsTask = menuConv?.kind === "task";
  const groupTargets = menuIsTask ? taskGroups : rootGroups;
  const projectLabel = menuConv?.project_id != null ? "更换项目" : "添加至项目";
  const groupLabel = menuConv?.group_id != null ? "更换分组" : "移至分组";

  return <aside className="sidebar">
    <div className="brand"><b className="mark">◉</b><div className="brand-word"><strong>Agent</strong><span>工作台</span></div></div>
    <button className="new" onClick={() => { closeMenu(); onNewChat(); }}>新聊天</button>
    <div className="side-actions">
      <button type="button" className="side-action" onClick={() => { closeMenu(); onOpenSearch(); }}>
        <SearchIcon /><span>搜索</span>
      </button>
      <button type="button" className="side-action" onClick={() => { closeMenu(); onOpenProjects(); }}>
        <FolderIcon /><span>项目</span>
        {projects.length > 0 && <em className="side-action-count">{projects.length}</em>}
      </button>
    </div>

    <div className="section-label conv-head">
      <span>分组</span>
      <div className="groups-tools">
        <button type="button" className="proj-add" title="新建自定义分组" aria-label="新建自定义分组"
          onClick={() => setCreatingGroup(true)}>＋</button>
        <button type="button" className={`conv-select-toggle ${selectMode ? "on" : ""}`} onClick={toggleSelectMode}>
          {selectMode ? "退出多选" : "多选"}
        </button>
      </div>
    </div>
    {selectMode && (
      <div className="conv-bulk-bar">
        <button type="button"
          onClick={() => setSelectedIds(cur => (cur.size ? new Set() : new Set(visibleIds)))}>
          {selectedIds.size > 0 && selectedIds.size === visibleIds.length ? "取消全选" : "全选"}
        </button>
        <em>已选 {selectedIds.size}</em>
        <button type="button" disabled={!selectedIds.size} onClick={() => { onBulkPin([...selectedIds], true); setSelectedIds(new Set()); }}>置顶</button>
        <button type="button" disabled={!selectedIds.size} onClick={() => { onBulkPin([...selectedIds], false); setSelectedIds(new Set()); }}>取消置顶</button>
        <button type="button" className="danger" disabled={!selectedIds.size} onClick={() => { onBulkDelete([...selectedIds]); setSelectedIds(new Set()); }}>删除</button>
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
          {rootGroups.map(g => renderPlainSection(`g:${g.id}`, g.name, B(`g:${g.id}`), g))}
          {projectConvs.length > 0 && renderParentSection(
            "__project", "项目", projectConvs,
            [...new Set(projectConvs.map(c => c.project_id))].map(pid => renderProjectSubgroup(pid!)),
          )}
          {(taskConvsAll.length > 0 || taskGroups.length > 0) && renderParentSection(
            "__task", "任务", taskConvsAll,
            <>
              {taskBare.map(c => renderRow(c, "__taskbare"))}
              {taskGroups.map(g => renderTaskSubgroup(g))}
            </>,
          )}
          {renderPlainSection("none", "未分组", B("none"))}
        </>
      )}
    </nav>

    {/* 会话“⋯”菜单：fixed 定位，可越出侧栏，不再被裁切 */}
    {menu && menuConv && (
      <>
        <div className="menu-scrim" onClick={closeMenu} />
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
            {/* 任务会话可从“项目/子分组”直接回到“任务”本体归类；普通会话无此选项 */}
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

    <div className="side-foot"><span className="led" />本地运行</div>
  </aside>;
}
