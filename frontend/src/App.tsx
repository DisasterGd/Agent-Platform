import { useCallback, useEffect, useRef, useState } from "react";
import { chatApi, type StreamHandlers } from "./services/chat";
import { tasksApi } from "./services/tasks";
import { projectsApi } from "./services/projects";
import { groupsApi } from "./services/groups";
import { settingsApi } from "./services/settings";
import { authApi, type MeInfo } from "./services/auth";
import { onUnauthorized } from "./services/api";
import Markdown from "./components/Markdown";
import SettingsModal from "./components/SettingsModal";
import LoginView from "./components/LoginView";
import ConfirmDialog, { type ConfirmState } from "./components/ConfirmDialog";
import ThinkingTicker, { useThinkingTracker } from "./components/ThinkingTicker";
import GlobalTip from "./components/GlobalTip";
import Sidebar, { type ListFilter } from "./components/Sidebar";
import SearchModal from "./components/SearchModal";
import ProjectsModal from "./components/ProjectsModal";
import LibraryModal from "./components/LibraryModal";
import TaskWorkspace from "./components/TaskWorkspace";
import type { Artifact, Attachment, Conversation, Message, Project, StreamEvent, Task, ConvGroup, TaskHit } from "./types/chat";

type ViewMode = "chat" | "task";

const TOOL_LABELS: Record<string, string> = {
  web_search: "联网搜索",
  fetch_url: "抓取网页",
  generate_file: "生成文档",
  write_file: "写入文件",
  create_zip: "打包压缩包",
};

/** 与后端 provisional_title 保持一致：生成阶段先用截取标题，完成后模型精炼。 */
function truncTitle(content: string): string {
  const text = content.replace(/\s+/g, " ").trim();
  return text.slice(0, 20) + (text.length > 20 ? "…" : "");
}

/** 版本链分组结果：同一 group 的多个消息变体合并为一个气泡，可左右翻页。 */
type Turn = { key: number; role: "user" | "assistant"; items: Message[] };

function buildTurns(msgs: Message[]): Turn[] {
  const order: Turn[] = [];
  const byKey = new Map<number, Turn>();
  for (const m of msgs) {
    const key = m.group_id ?? m.id;
    let turn = byKey.get(key);
    if (!turn) {
      turn = { key, role: m.role, items: [] };
      byKey.set(key, turn);
      order.push(turn);
    }
    turn.items.push(m);
  }
  for (const t of order) {
    t.items.sort((a, b) => (a.variant_index ?? 0) - (b.variant_index ?? 0) || a.id - b.id);
  }
  return order;
}

/** 该气泡当前选看的版本；默认（未翻页）为最新一版。 */
function selectedVersion(selMap: Record<number, number>, turn: Turn): number {
  const stored = selMap[turn.key];
  const last = turn.items.length - 1;
  if (stored === undefined || stored < 0) return last;
  return Math.min(stored, last);
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function App() {
  // v0.7 认证门：先取身份，登录后才挂载工作台（Workbench）——
  // 避免未登录时业务请求打出 401、在界面上残留错误并与登录流程竞争。
  // me: undefined=检查中 / null=未登录 / MeInfo=已登录；任意请求 401 时全局切回登录页。
  const [me, setMe] = useState<MeInfo | null | undefined>(undefined);
  useEffect(() => {
    let alive = true;
    authApi.me()
      .then(info => { if (alive) setMe(info); })
      .catch(() => { if (alive) setMe(null); });
    const off = onUnauthorized(() => setMe(null));
    return () => { alive = false; off(); };
  }, []);

  async function logout() {
    try { await authApi.logout(); } catch { /* 会话可能已过期：照常回登录页 */ }
    setMe(null);
  }

  if (me === undefined) {
    return (
      <div className="login-page">
        <div className="login-card"><p className="login-note">正在检查登录状态…</p></div>
      </div>
    );
  }
  if (me === null) {
    return <LoginView onSuccess={setMe} />;
  }
  return <Workbench me={me} onLogout={() => void logout()} />;
}

function Workbench({ me, onLogout }: { me: MeInfo; onLogout: () => void }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [busy, setBusy] = useState(false);
  // 思考过程动态展示（仅内存态，不落库；完成后虚化再移除）
  const thinking = useThinkingTracker();
  // 正在生成的会话 id：侧边栏该行显示转圈动画
  const [generatingConvId, setGeneratingConvId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [editingMsgId, setEditingMsgId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [versionSel, setVersionSel] = useState<Record<number, number>>({});
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    try { return (localStorage.getItem("theme") as "light" | "dark") || "light"; }
    catch { return "light"; }
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  // v0.6.0 模型指示（顶栏 + 欢迎卡）：读真实生效配置（永不含 Key），保存设置后刷新
  // v0.6.0 起以“主模型角色”为准——它才决定实际对话用的是哪家哪个模型
  const [modelNote, setModelNote] = useState("加载中…");
  const refreshModelNote = useCallback(() => {
    settingsApi.get()
      .then(r => {
        const reasoning = r.roles?.reasoning ?? null;
        const pid = reasoning?.provider || r.config.provider || "deepseek";
        const preset = r.presets[pid];
        const label = preset?.label || pid || "自定义";
        const model = reasoning?.model || r.config.model || preset?.model || "默认模型";
        const usable = reasoning ? reasoning.usable : r.config.has_api_key;
        setModelNote(usable ? `${label} · ${model}` : "本地演示（主模型未就绪）");
      })
      .catch(() => setModelNote("未知"));
  }, []);
  useEffect(() => { refreshModelNote(); }, [refreshModelNote]);
  // v0.4.1 双界面：聊天 / 任务。切换只换主区，左侧信息栏不变。
  const [mode, setMode] = useState<ViewMode>(() => {
    try { return localStorage.getItem("app.mode") === "task" ? "task" : "chat"; }
    catch { return "chat"; }
  });
  const [liveText, setLiveText] = useState("");
  const [planning, setPlanning] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [groups, setGroups] = useState<ConvGroup[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [listFilter, setListFilter] = useState<ListFilter>(null);
  // v0.4.3：侧边栏收起态（极致压缩图标条，保留 新聊天/搜索/最近/项目）
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try { return localStorage.getItem("sidebar.collapsed") === "1"; } catch { return false; }
  });
  useEffect(() => {
    try { localStorage.setItem("sidebar.collapsed", sidebarCollapsed ? "1" : "0"); } catch { /* 忽略存储失败 */ }
  }, [sidebarCollapsed]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [projectsOpen, setProjectsOpen] = useState(false);
  // v0.5 资料库：上传与生成的文件统一查看、重命名、删除、下载
  const [libraryOpen, setLibraryOpen] = useState(false);
  // 应用内确认弹窗
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  const confirmResolve = useRef<((v: boolean) => void) | null>(null);
  const activeIdRef = useRef<number | null>(null);
  activeIdRef.current = activeId;

  // “回到底部”：聊天区滚动至非底部时出现
  const chatRef = useRef<HTMLElement | null>(null);
  const [showJumpBottom, setShowJumpBottom] = useState(false);
  const updateJumpBottom = useCallback(() => {
    const el = chatRef.current;
    if (!el) { setShowJumpBottom(false); return; }
    setShowJumpBottom(el.scrollHeight - el.scrollTop - el.clientHeight > 120);
  }, []);
  function jumpToBottom() {
    const el = chatRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("theme", theme); } catch { /* 忽略存储失败 */ }
  }, [theme]);

  useEffect(() => {
    try { localStorage.setItem("app.mode", mode); } catch { /* 忽略存储失败 */ }
  }, [mode]);

  const refresh = useCallback(async () => {
    const [items, projs, grps, tks] = await Promise.all([
      chatApi.listConversations(),
      projectsApi.list().catch(() => [] as Project[]),
      groupsApi.list().catch(() => [] as ConvGroup[]),
      tasksApi.list().catch(() => [] as Task[]),
    ]);
    setConversations(items);
    setProjects(projs);
    setGroups(grps);
    setTasks(tks);
    return items;
  }, []);

  /** 应用内确认弹窗（替代 window.confirm）。 */
  const askConfirm = useCallback(
    (title: string, message: string, danger = true, labels?: { confirm?: string; cancel?: string }) => (
      new Promise<boolean>(resolve => {
        confirmResolve.current = resolve;
        setConfirmState({ title, message, danger, confirmLabel: labels?.confirm, cancelLabel: labels?.cancel });
      })
    ), []);

  const closeConfirm = useCallback((v: boolean) => {
    confirmResolve.current?.(v);
    confirmResolve.current = null;
    setConfirmState(null);
  }, []);

  const load = useCallback(async (id: number) => {
    setActiveId(id);
    setVersionSel({});
    setLiveText("");
    const msgs = await chatApi.listMessages(id);
    setMessages(msgs);
  }, []);

  /** 打开会话：任务模式相关会话进任务界面并选中其最新任务，普通会话进聊天界面。 */
  const openConversation = useCallback(async (c: Conversation) => {
    setActiveId(c.id);
    setVersionSel({});
    setLiveText("");
    const [msgs, ts] = await Promise.all([
      chatApi.listMessages(c.id),
      tasksApi.listByConversation(c.id).catch(() => [] as Task[]),
    ]);
    setMessages(msgs);
    if (ts.length > 0) {
      setTasks(cur => [...ts, ...cur.filter(t => !ts.some(x => x.id === t.id))]);
      setSelectedTaskId(ts[0].id);
      setMode("task");
    } else {
      setSelectedTaskId(null);
      setMode("chat");
    }
  }, []);

  // 初始界面 = 主界面：只拉列表，不选中任何会话
  useEffect(() => {
    void refresh().catch((e: unknown) => setError(e instanceof Error ? e.message : "连接后端失败"));
  }, [refresh]);

  /** “新聊天”不立即落库：切回聊天主界面，首次发送时才真正创建会话。 */
  function openHome() {
    setActiveId(null);
    setMessages([]);
    setLiveText("");
    setVersionSel({});
    setError("");
    setMode("chat");
  }

  // ---------- v0.4.1 项目管理（弹窗调用） ----------

  async function createProject(name: string) {
    try {
      setError("");
      const p = await projectsApi.create(name);
      setProjects(cur => [p, ...cur]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "项目创建失败");
    }
  }

  async function renameProject(id: number, name: string) {
    try {
      setError("");
      const p = await projectsApi.update(id, { name });
      setProjects(cur => cur.map(x => (x.id === id ? p : x)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "重命名失败");
    }
  }

  async function pinProject(p: Project) {
    try {
      setError("");
      await projectsApi.update(p.id, { pinned: !p.pinned });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "置顶失败");
    }
  }

  async function removeProject(p: Project) {
    const ok = await askConfirm(
      "删除项目",
      `删除项目「${p.name}」？其中的会话会退回默认分组（不删除），项目记忆将被清除。`,
    );
    if (!ok) return;
    try {
      setError("");
      await projectsApi.remove(p.id);
      if (listFilter?.kind === "project" && listFilter.id === p.id) setListFilter(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除项目失败");
    }
  }

  // ---------- v0.4.1 自定义分组 ----------

  async function createGroup(name: string) {
    try {
      setError("");
      const g = await groupsApi.create(name);
      setGroups(cur => [...cur, g]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "分组创建失败");
    }
  }

  async function renameGroup(id: number, name: string) {
    try {
      setError("");
      const g = await groupsApi.rename(id, name);
      setGroups(cur => cur.map(x => (x.id === id ? g : x)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "分组重命名失败");
    }
  }

  async function removeGroup(g: ConvGroup) {
    const ok = await askConfirm(
      "删除分组",
      `删除分组「${g.name}」？其中的会话将退回默认分组（项目 / 任务 / 未分组），不会删除会话。`,
      false,
      { confirm: "删除分组" },
    );
    if (!ok) return;
    try {
      setError("");
      await groupsApi.remove(g.id);
      if (listFilter?.kind === "group" && listFilter.id === g.id) setListFilter(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除分组失败");
    }
  }

  // ---------- 会话操作 ----------

  async function rename(id: number, title: string) {
    try {
      setError("");
      await chatApi.updateConversation(id, { title });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "重命名失败");
    }
  }

  async function pin(c: Conversation) {
    try {
      setError("");
      await chatApi.updateConversation(c.id, { pinned: !c.pinned });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "置顶失败");
    }
  }

  async function removeConv(c: Conversation) {
    const ok = await askConfirm("删除会话", `删除会话「${c.title}」？此操作不可恢复。`);
    if (!ok) return;
    try {
      setError("");
      await chatApi.deleteConversation(c.id);
      if (activeId === c.id) openHome();
      else await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除会话失败");
    }
  }

  /** 会话编辑基础操作：PATCH 显式字段，改完刷新列表重算归类。 */
  async function moveConv(id: number, patch: { project_id?: number | null; group_id?: number | null }) {
    try {
      setError("");
      const updated = await chatApi.updateConversation(id, patch);
      setConversations(cur => cur.map(c => (c.id === id ? { ...c, ...updated } : c)));
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "移动失败");
    }
  }

  /** 移入项目时同时离开自定义分组（归类的呈现互斥：先落到哪边，就离开另一边）。 */
  function moveToProject(c: Conversation, projectId: number | null) {
    const patch: { project_id: number | null; group_id?: null } = { project_id: projectId };
    if (projectId != null && c.group_id != null) patch.group_id = null;
    void moveConv(c.id, patch);
  }

  /** 移入分组时同时离开项目；任务会话只应被移入任务子分组（菜单侧已限制）。 */
  function moveToGroup(c: Conversation, groupId: number | null) {
    const patch: { group_id: number | null; project_id?: null } = { group_id: groupId };
    if (groupId != null && c.project_id != null) patch.project_id = null;
    void moveConv(c.id, patch);
  }

  /** 任务会话直接回到“任务”本体归类：清分组并清项目。 */
  function moveToTaskSection(c: Conversation) {
    void moveConv(c.id, { group_id: null, project_id: null });
  }

  /** 右键批量移动：同一规则逐个应用（移入一边即离开另一边），只刷新一次列表。 */
  async function bulkMove(convs: Conversation[], kind: "project" | "group" | "out-project" | "out-group" | "task", id?: number | null) {
    if (!convs.length) return;
    setError("");
    let failed = 0;
    for (const c of convs) {
      let patch: { project_id?: number | null; group_id?: number | null } | null = null;
      if (kind === "project") patch = { project_id: id ?? null, ...(c.group_id != null ? { group_id: null } : {}) };
      else if (kind === "group") patch = { group_id: id ?? null, ...(c.project_id != null ? { project_id: null } : {}) };
      else if (kind === "out-project") patch = c.project_id != null ? { project_id: null } : null;
      else if (kind === "out-group") patch = c.group_id != null ? { group_id: null } : null;
      else if (kind === "task") patch = c.project_id != null || c.group_id != null ? { project_id: null, group_id: null } : null;
      if (patch === null) continue;
      try { await chatApi.updateConversation(c.id, patch); } catch { failed += 1; }
    }
    if (failed) setError(`${failed} 个会话移动失败`);
    await refresh();
  }

  /** 右键批量新建分组并移入：按首个会话的类型决定 task 子分组 / 根级分组（同组条件已由菜单保证）。 */
  async function createGroupForMany(convs: Conversation[], name: string) {
    if (!convs.length) return;
    const isTask = (convs[0].kind ?? "chat") === "task";
    try {
      setError("");
      const g = await groupsApi.create(name, isTask ? "task" : "group");
      setGroups(cur => [...cur, g]);
      await bulkMove(convs, "group", g.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "分组创建失败");
    }
  }

  /** 在“移至分组”菜单内新建分组并立刻移入：任务会话建 task 子分组，普通会话建根级分组。 */
  async function createGroupFor(c: Conversation, name: string) {
    try {
      setError("");
      const g = await groupsApi.create(name, c.kind === "task" ? "task" : "group");
      setGroups(cur => [...cur, g]);
      moveToGroup(c, g.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "分组创建失败");
    }
  }

  async function bulkDelete(ids: number[]) {
    if (!ids.length) return;
    const ok = await askConfirm("删除会话", `确认删除选中的 ${ids.length} 个会话？此操作不可恢复。`);
    if (!ok) return;
    setError("");
    let failed = 0;
    for (const id of ids) {
      try { await chatApi.deleteConversation(id); } catch { failed += 1; }
    }
    if (failed) setError(`${failed} 个会话删除失败`);
    if (activeId !== null && ids.includes(activeId)) openHome();
    else await refresh();
  }

  async function bulkPin(ids: number[], pinned: boolean) {
    for (const id of ids) {
      try { await chatApi.updateConversation(id, { pinned }); } catch { /* 单个失败不阻断批量 */ }
    }
    await refresh();
  }

  async function attachFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setError("");
    try {
      for (const file of Array.from(files)) {
        const att = await chatApi.uploadFile(file);
        setAttachments(cur => [...cur, att]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "上传失败");
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function removeAttachment(index: number) {
    setAttachments(cur => cur.filter((_, i) => i !== index));
  }

  function streamHandlers(assistantId: number): StreamHandlers {
    return {
      onDelta: delta => {
        setMessages(current => current.map(m =>
          m.id === assistantId ? { ...m, content: m.content + delta } : m
        ));
        thinking.appendText(delta);
      },
      onToolStart: name => thinking.pushLabel(`正在${TOOL_LABELS[name] || name}…`),
      onToolEnd: () => thinking.pushLabel("继续生成回复…"),
      onArtifact: (artifact: Artifact) => {
        setMessages(current => current.map(m =>
          m.id === assistantId ? { ...m, artifacts: [...(m.artifacts || []), artifact] } : m
        ));
        thinking.pushLabel(`已生成文件 ${artifact.filename}`);
      },
      onEvent: ev => {
        if (ev.type === "context_compressed") {
          thinking.pushLabel(`前文过长：已把 ${ev.count ?? 0} 条早期消息自动压缩为摘要`);
        } else if (ev.type === "memory_saved" && ev.items && ev.items.length > 0) {
          const names = ev.items.map(i => i.title).filter(Boolean).slice(0, 2).join("、");
          thinking.pushLabel(`已写入 ${ev.items.length} 条记忆${names ? `：${names}` : ""}`);
        }
      },
    };
  }

  async function send() {
    const content = input.trim();
    if (!content || busy) return;
    setError("");
    setBusy(true);
    thinking.begin("正在生成回复…");
    let id = activeId;
    try {
      if (id === null) {
        // 生成阶段就创建会话：内容、失败与中断都有处可归；归入当前筛选的项目/分组
        const projectId = listFilter?.kind === "project" ? listFilter.id : null;
        const groupId = listFilter?.kind === "group" ? listFilter.id : null;
        let item = await chatApi.createConversation(truncTitle(content), projectId);
        if (groupId != null) {
          try { item = await chatApi.updateConversation(item.id, { group_id: groupId }); }
          catch { /* 归属失败不阻断聊天 */ }
        }
        id = item.id;
        setActiveId(id);
        setConversations(cur => [item, ...cur]);
      }
      const sentAttachments = [...attachments];
      const userMessage: Message = {
        id: Date.now(), conversation_id: id, role: "user",
        content, created_at: new Date().toISOString(),
        attachments: sentAttachments.length ? sentAttachments : undefined,
      };
      const assistantId = Date.now() + 1;
      const assistantMessage: Message = {
        id: assistantId, conversation_id: id, role: "assistant",
        content: "", created_at: new Date().toISOString(), artifacts: [],
      };
      setMessages(current => [...current, userMessage, assistantMessage]);
      setInput("");
      setAttachments([]);
      setGeneratingConvId(id);
      await chatApi.streamMessage(id, content, sentAttachments, streamHandlers(assistantId));
      // 用户已切走时不再强行跳回；服务端已落库（含部分产出），切回来即可看到
      if (activeIdRef.current === null || activeIdRef.current === id) await load(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "发送消息失败");
      if (id !== null) {
        if (activeIdRef.current === null || activeIdRef.current === id) {
          try { await load(id); } catch { /* keep original error */ }
        } else {
          try { await refresh(); } catch { /* 列表刷新失败保留原错误 */ }
        }
      }
    } finally {
      setGeneratingConvId(null);
      thinking.end();
      setBusy(false);
    }
  }

  async function regenerate(userMessageId: number, newContent?: string) {
    if (busy || activeId === null) return;
    const raw = messages.find(m => m.id === userMessageId);
    if (!raw) return;
    const convId = activeId;
    const trimmed = newContent?.trim();
    const edited = trimmed !== undefined && trimmed !== "" && trimmed !== raw.content;
    setError("");
    setBusy(true);
    thinking.begin("正在重新生成…");
    setGeneratingConvId(convId);
    setEditingMsgId(null);
    setEditDraft("");

    // 乐观追加新版本行（同链 group_id），旧版本保留在链内可翻页；流结束后用服务端数据回填
    const turnsNow = buildTurns(messages);
    const lastTurn = turnsNow[turnsNow.length - 1];
    const asstTurn = lastTurn && lastTurn.role === "assistant" ? lastTurn : null;
    const maxIdx = (items: Message[]) => items.reduce((acc, m) => Math.max(acc, m.variant_index ?? 0), 0);
    const userGroup = raw.group_id ?? raw.id;
    const stamp = Date.now();
    const userVariant: Message | null = edited
      ? {
          id: stamp, conversation_id: convId, role: "user", content: trimmed!,
          created_at: new Date().toISOString(), attachments: raw.attachments,
          group_id: userGroup, variant_index: maxIdx(turnsNow.find(t => t.key === userGroup)?.items ?? []) + 1,
        }
      : null;
    const assistantId = stamp + 1;
    const assistantMessage: Message = {
      id: assistantId, conversation_id: convId, role: "assistant",
      content: "", created_at: new Date().toISOString(), artifacts: [],
      group_id: asstTurn?.key, variant_index: asstTurn ? maxIdx(asstTurn.items) + 1 : 0,
    };
    try {
      setMessages(current => [...current, ...(userVariant ? [userVariant] : []), assistantMessage]);
      setVersionSel({});
      await chatApi.regenerate(convId, userMessageId, newContent, streamHandlers(assistantId));
      await load(convId);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "重新生成失败");
      try { await load(convId); } catch { /* keep original error */ }
    } finally {
      setGeneratingConvId(null);
      thinking.end();
      setBusy(false);
    }
  }

  // ---------- v0.4.1 任务界面 ----------

  function patchTask(id: number, fn: (t: Task) => Task) {
    setTasks(cur => cur.map(t => (t.id === id ? fn(t) : t)));
  }

  async function createTask(goal: string) {
    if (planning || busy) return;
    setPlanning(true);
    thinking.begin("正在拆解任务、生成计划…");
    setError("");
    try {
      const projectId = listFilter?.kind === "project" ? listFilter.id : null;
      const task = await tasksApi.create(goal, null, projectId);
      setTasks(cur => [task, ...cur.filter(t => t.id !== task.id)]);
      setSelectedTaskId(task.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "任务创建失败");
    } finally {
      thinking.end();
      setPlanning(false);
    }
  }

  /** v0.3：任务执行事件 → 任务列表状态 + 思考过程展示。 */
  function handleTaskEvent(ev: StreamEvent, taskId: number) {
    switch (ev.type) {
      case "plan_created": {
        setLiveText("");
        patchTask(taskId, t => ({ ...t, status: "running", steps: ev.steps ?? t.steps }));
        const cid = ev.conversation_id ?? null;
        if (cid !== null) {
          // 执行开始即绑定/新建会话：侧边栏立刻可见，失败也有记录可回看
          setGeneratingConvId(cid);
          void refresh().catch(() => undefined);
        }
        thinking.pushLabel("计划已确认，开始执行");
        break;
      }
      case "step_started":
        setLiveText("");
        thinking.pushLabel(`执行步骤 ${(ev.index ?? 0) + 1}：${ev.title ?? ""}`);
        patchTask(taskId, t => ({ ...t, status: "running", steps: t.steps.map(s => (s.idx === ev.index ? { ...s, status: "running" as const } : s)) }));
        break;
      case "text_delta":
        setLiveText(prev => prev + (ev.content ?? ""));
        break;
      case "artifact_ready":
        patchTask(taskId, t => ({ ...t, steps: t.steps.map(s => (s.status === "running"
          ? { ...s, artifacts: [...(s.artifacts ?? []), { filename: ev.filename ?? "", url: ev.url ?? "", format: ev.format ?? "" }] }
          : s)) }));
        break;
      case "step_completed":
        setLiveText("");
        thinking.pushLabel(`步骤 ${(ev.index ?? 0) + 1} 完成`);
        patchTask(taskId, t => ({ ...t, steps: t.steps.map(s => (s.idx === ev.index
          ? { ...s, status: "done" as const, summary: ev.summary ?? "", artifacts: ev.artifacts ?? s.artifacts }
          : s)) }));
        break;
      case "step_failed":
        thinking.pushLabel(`⚠ 步骤 ${(ev.index ?? 0) + 1} 失败：${ev.error ?? ""}`);
        patchTask(taskId, t => ({ ...t, status: "failed", steps: t.steps.map(s => (s.idx === ev.index ? { ...s, status: "failed" as const, error: ev.error ?? "" } : s)) }));
        break;
      case "task_completed": {
        const st = ev.status ?? "completed";
        patchTask(taskId, t => ({ ...t, status: st }));
        setLiveText("");
        break;
      }
    }
  }

  async function executeTask(taskId: number) {
    if (busy) return;
    setBusy(true);
    thinking.begin("准备执行计划…");
    setError("");
    // streamHandlers(-1)：占位消息 id 不存在 → onDelta 无副作用，只借工具读数与事件旁路
    try {
      await tasksApi.execute(taskId, { ...streamHandlers(-1), onEvent: ev => handleTaskEvent(ev, taskId) });
    } catch (e) {
      setError(e instanceof Error ? e.message : "任务执行失败");
    } finally {
      setGeneratingConvId(null);
      thinking.end();
      setBusy(false);
    }
    // 完成/失败都已绑定会话：以服务端为准回填任务与会话列表
    try {
      const latest = await tasksApi.get(taskId);
      patchTask(taskId, () => latest);
      if (activeIdRef.current !== null && latest.conversation_id === activeIdRef.current) {
        await load(latest.conversation_id);
      }
      await refresh();
    } catch { /* 同步失败保留现场 */ }
  }

  async function reviseTask(taskId: number, steps: { title: string; detail: string }[]) {
    try {
      setError("");
      const updated = await tasksApi.revise(taskId, steps);
      patchTask(taskId, () => updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "计划更新失败");
    }
  }

  /** TaskCard 的取消按钮：执行中 → 取消；待审阅/失败 → 删除任务记录。 */
  async function cancelOrDeleteTask(taskId: number) {
    const t = tasks.find(x => x.id === taskId);
    if (!t) return;
    if (t.status === "running") {
      const ok = await askConfirm("取消任务", "取消后该任务不再执行；已产生的步骤结果仍会保留。", false,
        { confirm: "取消任务", cancel: "继续" });
      if (!ok) return;
      try {
        const updated = await tasksApi.cancel(taskId);
        patchTask(taskId, () => updated);
      } catch (e) {
        setError(e instanceof Error ? e.message : "取消任务失败");
      }
      return;
    }
    const ok = await askConfirm("删除任务", `删除任务「${t.goal.slice(0, 20)}…」？该任务记录会被移除，已产生的会话不受影响。`, false,
      { confirm: "删除任务" });
    if (!ok) return;
    try {
      setError("");
      await tasksApi.remove(taskId);
      const remaining = tasks.filter(x => x.id !== taskId);
      setTasks(remaining);
      if (selectedTaskId === taskId) setSelectedTaskId(remaining[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除任务失败");
    }
  }

  /** 搜索结果点击任务：进任务界面并选中（不在列表里则拉取补齐）。 */
  function openTaskHit(hit: TaskHit) {
    setMode("task");
    setSelectedTaskId(hit.id);
    void (async () => {
      try {
        const latest = await tasksApi.get(hit.id);
        setTasks(cur => (cur.some(t => t.id === hit.id) ? cur.map(t => (t.id === hit.id ? latest : t)) : [latest, ...cur]));
      } catch { /* 保留占位选中，列表由下次刷新补齐 */ }
    })();
  }

  function startEditMessage(turn: Turn, row: Message) {
    setEditingMsgId(turn.key);
    setEditDraft(row.content);
  }

  function cancelEditMessage() {
    setEditingMsgId(null);
    setEditDraft("");
  }

  async function copyMessage(m: Message) {
    try {
      await navigator.clipboard.writeText(m.content);
      setCopiedId(m.id);
      window.setTimeout(() => setCopiedId(cur => (cur === m.id ? null : cur)), 1500);
    } catch {
      setError("复制失败，请手动选择文本");
    }
  }

  function jumpTo(id: number) {
    document.getElementById(`msg-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  const turns = buildTurns(messages);
  // 消息增减/切换会话后重算“回到底部”显隐（流式增长时若已离底应保持显示）
  useEffect(() => { updateJumpBottom(); }, [turns.length, activeId, mode, updateJumpBottom]);
  const questions = turns.filter(t => t.role === "user" && t.items[t.items.length - 1].content.trim());
  const activeConv = conversations.find(c => c.id === activeId);
  const lastUserTurn = [...turns].reverse().find(t => t.role === "user");
  const activeProjectName = listFilter?.kind === "project"
    ? projects.find(p => p.id === listFilter.id)?.name ?? null
    : null;

  return <div className={generatingConvId ? "shell busy" : "shell"}>
    <Sidebar
      conversations={conversations} projects={projects} groups={groups}
      activeId={activeId} generatingConvId={generatingConvId} listFilter={listFilter}
      collapsed={sidebarCollapsed} onToggleCollapsed={setSidebarCollapsed}
      onNewChat={openHome}
      onOpenSearch={() => setSearchOpen(true)}
      onOpenProjects={() => setProjectsOpen(true)}
      onOpenLibrary={() => setLibraryOpen(true)}
      onOpenConversation={c => void openConversation(c)}
      onRename={(id, title) => void rename(id, title)}
      onPin={c => void pin(c)}
      onDelete={c => void removeConv(c)}
      onMoveProject={moveToProject}
      onMoveGroup={moveToGroup}
      onMoveToTaskSection={moveToTaskSection}
      onCreateGroupFor={(c, name) => void createGroupFor(c, name)}
      onBulkMove={(convs, kind, id) => void bulkMove(convs, kind, id)}
      onCreateGroupForMany={(convs, name) => void createGroupForMany(convs, name)}
      onBulkDelete={ids => void bulkDelete(ids)}
      onBulkPin={(ids, pinned) => void bulkPin(ids, pinned)}
      onSetFilter={setListFilter}
      onCreateGroup={name => void createGroup(name)}
      onRenameGroup={(id, name) => void renameGroup(id, name)}
      onDeleteGroup={g => void removeGroup(g)}
    />

    <main className="main">
      <header className="topbar">
        <div className="topbar-left">
          <div className="mode-switch" role="tablist" aria-label="界面切换">
            <button type="button" role="tab" aria-selected={mode === "chat"}
              className={mode === "chat" ? "on" : ""} onClick={() => setMode("chat")}>聊天</button>
            <button type="button" role="tab" aria-selected={mode === "task"}
              className={mode === "task" ? "on" : ""} onClick={() => setMode("task")}>任务</button>
          </div>
          <div className="topbar-title">{mode === "task" ? "任务中心" : activeConv?.title ?? "主界面"}</div>
        </div>
        <div className="topbar-meta">
          <span className="meta-item" data-tip="当前生效的模型配置（设置页可改）">模型 <b>{modelNote}</b></span>
          <span className="meta-item">v0.7.0</span>
          <span className="meta-item"><span className="led" />就绪</span>
          <button className="settings-btn" onClick={() => setSettingsOpen(true)}>设置</button>
        </div>
      </header>

      {mode === "chat" ? (<>
        {questions.length > 0 && (
          <aside className="index">
            <div className="index-head"><span>问题索引</span><em>{questions.length}</em></div>
            <div className="index-list">
              {questions.map((q, i) => {
                const latest = q.items[q.items.length - 1];
                return (
                <button key={q.key} className="index-item" data-tip={latest.content} onClick={() => jumpTo(q.key)}>
                  <span className="index-num">{i + 1}</span>
                  <span className="index-label">{latest.content.replace(/\s+/g, " ").trim().slice(0, 18) || "…"}</span>
                </button>
                );
              })}
            </div>
          </aside>
        )}

        <section className="chat-area" ref={chatRef} onScroll={updateJumpBottom}>
          {turns.length === 0
            ? <div className="welcome">
                <div className="welcome-mark">◉</div>
                <h2>从一个想法开始</h2>
                <p>输入一句话，Agent 会<b>联网搜索</b>最新信息、<b>生成文件</b>：文档（Word / PDF / Markdown）、
                代码与配置（按文件名与后缀原样写出）、以及把整套文件<b>打包成 zip</b> 下载。<br />
                需要多步骤的工作时，点顶栏的<b>任务</b>切到任务界面，把目标拆成计划、审阅后逐步执行。
                它还会随着交流逐渐<b>记住你的偏好</b>——在“设置 → 记忆”中随时查看与管理。</p>
                <div className="panel">
                  <div className="panel-cell"><span>模型</span><b>{modelNote}</b></div>
                  <div className="panel-cell"><span>工具</span><b>搜索 · 文档 · 代码 · 压缩包 · 记忆</b></div>
                  <div className="panel-cell"><span>资料</span><b>侧边栏「资料库」统一查看</b></div>
                </div>
              </div>
            : <div className="messages">{turns.map((t, ti) => {
                const isLastTurn = ti === turns.length - 1;
                const sel = selectedVersion(versionSel, t);
                const row = t.items[sel];
                const hasVariants = t.items.length > 1;
                const isEditing = editingMsgId === t.key;
                // 版本翻页器：同一逻辑消息有多个版本（重新生成/编辑产生）时显示“‹ n/N ›”
                const pager = hasVariants && (
                  <span className="msg-versions" data-tip="该消息有多个版本，可左右翻页查看">
                    <button type="button" aria-label="上一版本" disabled={sel <= 0}
                      onClick={() => setVersionSel(v => ({ ...v, [t.key]: Math.max(0, selectedVersion(v, t) - 1) }))}>‹</button>
                    <em>{sel + 1}/{t.items.length}</em>
                    <button type="button" aria-label="下一版本" disabled={sel >= t.items.length - 1}
                      onClick={() => setVersionSel(v => ({ ...v, [t.key]: Math.min(t.items.length - 1, selectedVersion(v, t) + 1) }))}>›</button>
                  </span>
                );
                return (
                <article id={`msg-${t.key}`} className={`message ${t.role}`} key={t.key}>
                  <div className="msg-meta">
                    <span className="msg-who">{t.role === "user" ? "你" : "AGENT"}</span>
                    <span className="msg-time">{fmtTime(row.created_at)}</span>
                    {row.content && (
                      <button className="msg-copy" type="button" onClick={() => void copyMessage(row)}>
                        {copiedId === row.id ? "已复制" : "复制"}
                      </button>
                    )}
                  </div>
                  <div className="body">
                    {t.role === "user"
                      ? isEditing
                        ? (<div className="edit-box">
                            <textarea autoFocus value={editDraft}
                              onChange={e => setEditDraft(e.target.value)}
                              onKeyDown={e => { if (e.key === "Escape") cancelEditMessage(); }} />
                            <div className="edit-actions">
                              <button type="button" onClick={cancelEditMessage}>取消</button>
                              <button type="button" className="primary" disabled={busy || !editDraft.trim()}
                                onClick={() => void regenerate(row.id, editDraft.trim())}>保存并重新生成</button>
                            </div>
                          </div>)
                        : (<>
                            {row.content && <p className="user-text">{row.content}</p>}
                            {row.attachments && row.attachments.length > 0 && (
                              <div className="attachments">
                                {row.attachments.map((a, i) => a.content_type.startsWith("image/")
                                  ? <a key={i} className="attachment-image" href={a.url} target="_blank" rel="noreferrer"><img src={a.url} alt={a.name} /></a>
                                  : <a key={i} className="attachment-file" href={a.url} target="_blank" rel="noreferrer">📄 {a.name}</a>
                                )}
                              </div>
                            )}
                            {(hasVariants || (isLastTurn && !busy)) && (
                              <div className="msg-actions">
                                {pager}
                                {isLastTurn && !busy && (
                                  <button className="msg-action" type="button" onClick={() => startEditMessage(t, row)}>编辑</button>
                                )}
                              </div>
                            )}
                          </>)
                      : (<>
                          {row.content ? <Markdown content={row.content} />
                            : <span className="thinking">{busy ? "正在思考…" : ""}</span>}
                          {row.artifacts && row.artifacts.length > 0 && (
                            <div className="artifacts">
                              {row.artifacts.map((a, i) => (
                                <a key={i} className="artifact" href={a.url} download={a.filename} target="_blank" rel="noreferrer">
                                  <span className="artifact-icon">📄</span>
                                  <span className="artifact-name">{a.filename}</span>
                                  <span className="artifact-dl">下载</span>
                                </a>
                              ))}
                            </div>
                          )}
                          {(hasVariants || (isLastTurn && !busy && row.content && lastUserTurn)) && (
                            <div className="msg-actions">
                              {pager}
                              {isLastTurn && !busy && row.content && lastUserTurn && (
                                <button className="msg-action" type="button"
                                  onClick={() => void regenerate(lastUserTurn.items[selectedVersion(versionSel, lastUserTurn)].id)}>重新生成</button>
                              )}
                            </div>
                          )}
                        </>)}
                  </div>
                </article>
                );
              })}</div>}
        </section>

        {showJumpBottom && turns.length > 0 && (
          <button type="button" className="jump-bottom" aria-label="回到底部" data-tip="回到底部" onClick={jumpToBottom}>
            <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M8 2.6v9.2M4 8.6l4 4 4-4" />
            </svg>
          </button>
        )}

        <div className="composer-wrap">
          <ThinkingTicker tracker={thinking} />
          {error && <div className="error">{error}</div>}
          <div className="composer">
            {attachments.length > 0 && (
              <div className="attachment-chips">
                {attachments.map((a, i) => (
                  <span className="chip" key={i}>
                    {a.content_type.startsWith("image/")
                      ? <img src={a.url} alt={a.name} />
                      : <span className="chip-file">📄 {a.name}</span>}
                    <button type="button" data-tip="移除" onClick={() => removeAttachment(i)}>×</button>
                  </span>
                ))}
              </div>
            )}
            <textarea className="composer-input" rows={2} value={input} disabled={busy}
              placeholder="向 Agent 发送消息…（Enter 发送，Shift + Enter 换行）"
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} />
            <div className="composer-bottom">
              <div className="composer-tools">
                <input ref={fileInputRef} type="file" multiple hidden
                  onChange={e => void attachFiles(e.target.files)} />
                <button className="attach-btn" type="button" data-tip="上传文件或图片（文本与代码可直接被读取）"
                  onClick={() => fileInputRef.current?.click()}>＋</button>
                <span className="hint">可上传任意文件（代码/配置/文本会直接读取正文）；多步工作请切换到顶栏「任务」界面</span>
              </div>
              <button className="send-btn" disabled={busy || !input.trim()} onClick={() => void send()}>
                {busy ? "生成中…" : "发送　↑"}
              </button>
            </div>
          </div>
          <p className="disclaimer">Agent 可能生成不准确的信息。重要内容请自行核实。</p>
        </div>
      </>) : (
        <TaskWorkspace
          tasks={tasks} selectedId={selectedTaskId} busy={busy} planning={planning} liveText={liveText}
          thinking={thinking} error={error} projectName={activeProjectName} conversations={conversations}
          onSelect={setSelectedTaskId}
          onCreate={goal => void createTask(goal)}
          onExecute={id => void executeTask(id)}
          onCancel={id => void cancelOrDeleteTask(id)}
          onRevise={reviseTask}
          onOpenConversation={id => {
            const c = conversations.find(x => x.id === id);
            if (c) void openConversation(c);
            else void (async () => { try { await refresh(); } catch { /* 会话可能已删除 */ } })();
          }}
        />
      )}
    </main>

    {searchOpen && (
      <SearchModal
        projects={projects} groups={groups} conversations={conversations}
        onClose={() => setSearchOpen(false)}
        onOpenConversation={id => {
          const c = conversations.find(x => x.id === id);
          if (c) void openConversation(c);
        }}
        onOpenTask={openTaskHit}
        onOpenProject={id => setListFilter({ kind: "project", id })}
        onOpenGroup={id => setListFilter({ kind: "group", id })}
      />
    )}
    {projectsOpen && (
      <ProjectsModal
        projects={projects} conversations={conversations}
        onClose={() => setProjectsOpen(false)}
        onCreate={name => void createProject(name)}
        onRename={(id, name) => void renameProject(id, name)}
        onPin={p => void pinProject(p)}
        onDelete={p => void removeProject(p)}
        onPick={id => setListFilter({ kind: "project", id })}
      />
    )}
    {libraryOpen && (
      <LibraryModal
        projects={projects}
        onClose={() => setLibraryOpen(false)}
        confirm={askConfirm}
        onOpenConversation={id => {
          const c = conversations.find(x => x.id === id);
          if (c) void openConversation(c);
        }}
      />
    )}
    {settingsOpen && (
      <SettingsModal theme={theme} onThemeChange={setTheme} me={me} onLogout={onLogout}
        onClose={() => { setSettingsOpen(false); refreshModelNote(); }}
      />
    )}
    {confirmState && <ConfirmDialog state={confirmState} onClose={closeConfirm} />}
    <GlobalTip />
  </div>;
}
