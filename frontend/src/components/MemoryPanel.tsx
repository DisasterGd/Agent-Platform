import { useCallback, useEffect, useMemo, useState } from "react";
import { memoriesApi } from "../services/memories";
import { projectsApi } from "../services/projects";
import { settingsApi, type ModelConfig } from "../services/settings";
import type { Memory, Project } from "../types/chat";

/**
 * v0.4 记忆管理面板（设置 → 记忆）。
 *
 * 这里是"真·系统级记忆"的管理入口：内容存数据库 memories 表，
 * 由后端在每次构建上下文时按作用域检索注入，并非写进某个静态文档。
 * 类别由模型归类，界面按类别分组展示；可编辑 / 启用停用 / 删除 / 手动添加。
 */

type ScopeSel = "global" | number;

const SOURCE_LABEL: Record<string, string> = {
  explicit: "用户要求记住",
  auto: "对话自动提炼",
};

export default function MemoryPanel() {
  const [scope, setScope] = useState<ScopeSel>("global");
  const [projects, setProjects] = useState<Project[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [memoryEnabled, setMemoryEnabled] = useState(true);
  const [fullConfig, setFullConfig] = useState<ModelConfig | null>(null);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftContent, setDraftContent] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState<number | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");

  const reload = useCallback(async () => {
    setError("");
    try {
      setMemories(scope === "global" ? await memoriesApi.list("global") : await memoriesApi.list("project", scope));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载记忆失败");
    }
  }, [scope]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    projectsApi.list().then(setProjects).catch(() => undefined);
    settingsApi.get()
      .then(r => { setFullConfig(r.config); setMemoryEnabled(r.config.memory_enabled !== false); })
      .catch(() => undefined);
  }, []);

  async function toggleAuto(v: boolean) {
    setMemoryEnabled(v);
    if (!fullConfig) return;
    try {
      // v0.5.2：只回传 provider+开关即可——api_key 字段缺省=服务器保留现有档案与 Key
      await settingsApi.save({ provider: fullConfig.provider, memory_enabled: v });
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存开关失败");
    }
  }

  async function toggleEnabled(m: Memory) {
    try {
      const updated = await memoriesApi.update(m.id, { enabled: !m.enabled });
      setMemories(cur => cur.map(x => (x.id === m.id ? updated : x)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    }
  }

  async function saveEdit(id: number) {
    const content = draftContent.trim();
    if (!content) return;
    try {
      const updated = await memoriesApi.update(id, { content });
      setMemories(cur => cur.map(x => (x.id === id ? updated : x)));
      setEditingId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    }
  }

  async function remove(m: Memory) {
    if (confirmingDelete !== m.id) {
      setConfirmingDelete(m.id);
      setEditingId(null);
      return;
    }
    try {
      await memoriesApi.remove(m.id);
      setMemories(cur => cur.filter(x => x.id !== m.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setConfirmingDelete(null);
    }
  }

  async function addMemory() {
    const content = newContent.trim();
    if (!content) return;
    try {
      setError("");
      await memoriesApi.create({
        content,
        title: newTitle.trim(),
        scope: scope === "global" ? "global" : "project",
        project_id: scope === "global" ? undefined : scope,
      });
      setNewTitle("");
      setNewContent("");
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "添加失败");
    }
  }

  const groups = useMemo(() => {
    const map = new Map<string, Memory[]>();
    for (const m of memories) {
      const key = m.category || "其他";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(m);
    }
    return [...map.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [memories]);

  return (
    <div className="mem-panel">
      <label className="mem-switch">
        <input type="checkbox" checked={memoryEnabled} onChange={e => void toggleAuto(e.target.checked)} />
        <span>自动记忆：从对话中提炼并注入上下文（关闭后仍可手动添加）</span>
      </label>

      <div className="mem-chips">
        <button type="button" className={`mem-chip ${scope === "global" ? "on" : ""}`} onClick={() => setScope("global")}>
          全局记忆
        </button>
        {projects.map(p => (
          <button key={p.id} type="button" className={`mem-chip ${scope === p.id ? "on" : ""}`} onClick={() => setScope(p.id)}>
            {p.name}
          </button>
        ))}
      </div>

      {error && <div className="error">{error}</div>}

      <div className="mem-add">
        <input placeholder="标签（可留空，由内容自动截取）" value={newTitle}
          onChange={e => setNewTitle(e.target.value)} />
        <textarea rows={2} placeholder="手动添加一条记忆…（视同用户明确要求记住）" value={newContent}
          onChange={e => setNewContent(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void addMemory(); }} />
        <button type="button" className="mem-add-btn" disabled={!newContent.trim()} onClick={() => void addMemory()}>
          添加记忆
        </button>
      </div>

      {groups.map(([category, rows]) => (
        <section className="mem-group" key={category}>
          <h4>{category}<em>{rows.length}</em></h4>
          {rows.map(m => (
            <article className={`mem-item ${m.enabled ? "" : "off"}`} key={m.id}>
              <div className="mem-item-head">
                <b data-tip={m.title}>{m.title || "记忆"}</b>
                <span className={`mem-src s-${m.source}`}>{SOURCE_LABEL[m.source] ?? m.source}</span>
                <span className="mem-act">
                  <button type="button" onClick={() => void toggleEnabled(m)}>{m.enabled ? "停用" : "启用"}</button>
                  <button type="button" onClick={() => { setEditingId(m.id); setDraftContent(m.content); setConfirmingDelete(null); }}>编辑</button>
                  <button type="button" className="danger" onClick={() => void remove(m)}>
                    {confirmingDelete === m.id ? "确认删除？" : "删除"}
                  </button>
                </span>
              </div>
              {editingId === m.id ? (
                <div className="mem-edit">
                  <textarea rows={3} value={draftContent} onChange={e => setDraftContent(e.target.value)} />
                  <div className="mem-edit-actions">
                    <button type="button" onClick={() => setEditingId(null)}>取消</button>
                    <button type="button" className="primary" onClick={() => void saveEdit(m.id)}>保存</button>
                  </div>
                </div>
              ) : (
                <p className="mem-item-content">{m.content}</p>
              )}
            </article>
          ))}
        </section>
      ))}

      {memories.length === 0 && (
        <p className="mem-empty">
          {scope === "global"
            ? "还没有全局记忆。Agent 会在对话中逐渐积累（说“请记住…”最稳妥），也可以手动添加。"
            : "该项目还没有记忆。"}
        </p>
      )}
    </div>
  );
}
