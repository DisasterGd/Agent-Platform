import { useMemo, useState } from "react";
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
  onMoveProject: (id: number, projectId: number | null) => void;
  onMoveGroup: (id: number, groupId: number | null) => void;
  onBulkDelete: (ids: number[]) => void;
  onBulkPin: (ids: number[], pinned: boolean) => void;
  onSetFilter: (f: ListFilter) => void;
  onCreateGroup: (name: string) => void;
  onRenameGroup: (id: number, name: string) => void;
  onDeleteGroup: (g: ConvGroup) => void;
}

const DEFAULT_SECTIONS = [
  { key: "__project", label: "项目" },
  { key: "__task", label: "任务" },
  { key: "__none", label: "未分组" },
] as const;

/** 默认分组归类（优先级）：自定义分组 > 项目 > 任务（任务模式会话）> 未分组。 */
function bucketKey(c: Conversation, groupIds: Set<number>): string {
  if (c.group_id != null && groupIds.has(c.group_id)) return `g:${c.group_id}`;
  if (c.project_id) return "__project";
  if (c.kind === "task") return "__task";
  return "__none";
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

export default function Sidebar(props: Props) {
  const {
    conversations, projects, groups, activeId, generatingConvId, listFilter,
    onNewChat, onOpenSearch, onOpenProjects, onOpenConversation, onRename, onPin, onDelete,
    onMoveProject, onMoveGroup, onBulkDelete, onBulkPin, onSetFilter,
    onCreateGroup, onRenameGroup, onDeleteGroup,
  } = props;

  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [subMenu, setSubMenu] = useState<"project" | "group" | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const cancelRename = { current: false };

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
  const [groupMenuFor, setGroupMenuFor] = useState<number | null>(null);

  const groupIds = useMemo(() => new Set(groups.map(g => g.id)), [groups]);

  const closeMenu = () => { setMenuFor(null); setSubMenu(null); };

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

  function toggleSelectMode() {
    setSelectMode(v => !v);
    setSelectedIds(new Set());
    closeMenu();
  }

  // —— 分区计算 ——
  const buckets = useMemo(() => {
    const map = new Map<string, Conversation[]>();
    for (const c of conversations) {
      const k = bucketKey(c, groupIds);
      const arr = map.get(k);
      if (arr) arr.push(c);
      else map.set(k, [c]);
    }
    return map;
  }, [conversations, groupIds]);

  const filterName = listFilter?.kind === "project"
    ? projects.find(p => p.id === listFilter.id)?.name
    : listFilter?.kind === "group"
      ? groups.find(g => g.id === listFilter.id)?.name
      : null;

  const flatList = listFilter
    ? conversations.filter(c => (listFilter.kind === "project" ? c.project_id === listFilter.id : c.group_id === listFilter.id))
    : null;

  const sections = listFilter
    ? []
    : [
        ...groups.map(g => ({ key: `g:${g.id}`, label: g.name, group: g, locked: false as const })),
        ...DEFAULT_SECTIONS.map(s => ({ key: s.key, label: s.label, group: null, locked: true as const })),
      ];

  const visibleIds = flatList ? flatList.map(c => c.id) : sections.flatMap(s => buckets.get(s.key) ?? []).map(c => c.id);

  function renderRow(c: Conversation, sectionKey: string) {
    const projectName = c.project_id ? projects.find(p => p.id === c.project_id)?.name : null;
    const taskTag = c.kind === "task" && sectionKey !== "__task";
    const projTag = sectionKey === "__project" && projectName;
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
        {projTag && <span className="conv-tag" title={projectName ?? ""}>{projectName}</span>}
        {!projTag && taskTag && <span className="conv-tag" title="任务模式相关会话">任务</span>}
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
            onClick={() => { if (menuFor === c.id) closeMenu(); else { setMenuFor(c.id); setSubMenu(null); } }}>⋯</button>
        )}
        {menuFor === c.id && (
          <>
            <div className="menu-scrim" onClick={closeMenu} />
            <div className="conv-menu">
              <button type="button" onClick={() => { closeMenu(); startEdit(c); }}>重命名</button>
              <button type="button" onClick={() => { closeMenu(); onPin(c); }}>{c.pinned ? "取消置顶" : "置顶"}</button>
              <button type="button" className={subMenu === "project" ? "open" : ""}
                onClick={() => setSubMenu(subMenu === "project" ? null : "project")}>添加至项目</button>
              <button type="button" className={subMenu === "group" ? "open" : ""}
                onClick={() => setSubMenu(subMenu === "group" ? null : "group")}>添加至分组</button>
              <button type="button" className="danger" onClick={() => { closeMenu(); onDelete(c); }}>删除</button>
              {subMenu === "project" && (
                <div className="conv-submenu">
                  {projects.length === 0 && <span className="sub-empty">暂无项目</span>}
                  {projects.map(p => (
                    <button key={p.id} type="button" className={c.project_id === p.id ? "cur" : ""}
                      onClick={() => { closeMenu(); if (c.project_id !== p.id) onMoveProject(c.id, p.id); }}>
                      {p.pinned && "📌"}{p.name}{c.project_id === p.id && " ✓"}
                    </button>
                  ))}
                  {c.project_id != null && (
                    <button type="button" onClick={() => { closeMenu(); onMoveProject(c.id, null); }}>移出项目</button>
                  )}
                </div>
              )}
              {subMenu === "group" && (
                <div className="conv-submenu">
                  {/* 分组子菜单只列自定义分组，默认分组（项目/任务/未分组）由代码归类 */}
                  {groups.length === 0 && <span className="sub-empty">暂无自定义分组</span>}
                  {groups.map(g => (
                    <button key={g.id} type="button" className={c.group_id === g.id ? "cur" : ""}
                      onClick={() => { closeMenu(); if (c.group_id !== g.id) onMoveGroup(c.id, g.id); }}>
                      {g.name}{c.group_id === g.id && " ✓"}
                    </button>
                  ))}
                  {c.group_id != null && (
                    <button type="button" onClick={() => { closeMenu(); onMoveGroup(c.id, null); }}>移出分组</button>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    );
  }

  function renderSection(section: (typeof sections)[number]) {
    const items = buckets.get(section.key) ?? [];
    // 默认分区“项目/任务”空了不占位；自定义分组与“未分组”始终可见
    if (section.locked && section.key !== "__none" && items.length === 0) return null;
    const isCollapsed = collapsed.has(section.key);
    return (
      <div key={section.key} className="conv-section">
        <div className="sec-head" role="button" tabIndex={0} aria-expanded={!isCollapsed}
          onClick={() => toggleCollapsed(section.key)}
          onKeyDown={e => {
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleCollapsed(section.key); }
          }}>
          <span className="sec-caret">{isCollapsed ? "▸" : "▾"}</span>
          {editingGroupId != null && section.group?.id === editingGroupId ? (
            <input className="sec-edit" autoFocus value={draftGroupName}
              onClick={e => e.stopPropagation()}
              onChange={e => setDraftGroupName(e.target.value)}
              onBlur={() => {
                setEditingGroupId(null);
                const next = draftGroupName.trim();
                if (next && next !== section.group?.name) onRenameGroup(section.group!.id, next);
              }}
              onKeyDown={e => {
                if (e.key === "Enter") { e.preventDefault(); (e.currentTarget as HTMLInputElement).blur(); }
                if (e.key === "Escape") setEditingGroupId(null);
              }} />
          ) : (
            <span className="sec-name">{section.label}</span>
          )}
          <span className="sec-count">{items.length}</span>
          {section.group && (
            <>
              <button type="button" className="sec-more" aria-label="分组操作"
                onClick={e => { e.stopPropagation(); setGroupMenuFor(groupMenuFor === section.group!.id ? null : section.group!.id); }}>⋯</button>
              {groupMenuFor === section.group.id && (
                <>
                  <div className="menu-scrim" onClick={() => setGroupMenuFor(null)} />
                  <div className="conv-menu sec-menu">
                    <button type="button" onClick={() => {
                      setGroupMenuFor(null);
                      setEditingGroupId(section.group!.id);
                      setDraftGroupName(section.group!.name);
                    }}>重命名</button>
                    <button type="button" className="danger" onClick={() => { setGroupMenuFor(null); onDeleteGroup(section.group!); }}>删除</button>
                  </div>
                </>
              )}
            </>
          )}
        </div>
        {!isCollapsed && <div className="sec-body">{items.map(c => renderRow(c, section.key))}</div>}
      </div>
    );
  }

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
        <button type="button" className="proj-add" title="新建分组" aria-label="新建分组"
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
        sections.map(renderSection)
      )}
    </nav>
    <div className="side-foot"><span className="led" />本地运行</div>
  </aside>;
}
