import { useEffect, useMemo, useState } from "react";
import {
  guessBaseUrl, settingsApi,
  type ModelConfig, type Preset, type ProfileView, type RoleDraft, type RoleKey,
} from "../services/settings";
import type { MeInfo } from "../services/auth";
import MemoryPanel from "./MemoryPanel";
import RoleCard from "./RoleCard";
import SecretInput from "./SecretInput";

interface Props {
  theme: "light" | "dark";
  onThemeChange: (t: "light" | "dark") => void;
  onClose: () => void;
  /** v0.7 账号区（仅 cloud 模式渲染）：当前身份 + 退出登录。 */
  me?: MeInfo | null;
  onLogout?: () => void;
}

/** 凭据草稿：正在编辑哪个供应商的 Base URL / Key。apiKey=null 表示“保留服务器上的”。 */
interface Draft {
  provider: string;
  base_url: string;
  api_key: string | null;
}

const ROLE_META: { key: RoleKey; title: string; desc: string; optionKey: "models" | "vision_models" | "image_models" | "embedding_models"; allowNone: boolean }[] = [
  { key: "reasoning", title: "主模型（推理）", desc: "对话、任务规划与执行、工具循环、记忆提炼——纯文本任务只用它", optionKey: "models", allowNone: false },
  { key: "vision", title: "识图（视觉）", desc: "把附件图片描述成文字供主模型理解；不配置时，原生支持图像的主模型会直接收图", optionKey: "vision_models", allowNone: true },
  { key: "image_gen", title: "图像生成", desc: "generate_image 工具所用：插画/海报/头像等，产物自动进资料库", optionKey: "image_models", allowNone: true },
  { key: "embedding", title: "向量检索（嵌入）", desc: "给知识库加语义检索：换个说法也能命中；不配置时检索退为纯关键词，索引与召回不受影响", optionKey: "embedding_models", allowNone: true },
];

function draftFrom(provider: string, profiles: Record<string, ProfileView>, presets: Record<string, Preset>, config: ModelConfig | null): Draft {
  const profile = profiles[provider];
  const preset = presets[provider];
  const active = config?.provider === provider ? config : null;
  return {
    provider,
    base_url: profile?.base_url || active?.base_url || preset?.base_url || "",
    api_key: null,
  };
}

function roleDrafts(roles: Partial<Record<RoleKey, { provider: string; model: string } | null>> | undefined, config: ModelConfig | null): Record<RoleKey, RoleDraft | null> {
  const fallbackProvider = config?.provider || "deepseek";
  return {
    // reasoning 永远有草稿：未配置时以“当前凭据供应商 + 默认模型名”起步
    reasoning: roles?.reasoning ?? { provider: fallbackProvider, model: "" },
    vision: roles?.vision ?? null,
    image_gen: roles?.image_gen ?? null,
    embedding: roles?.embedding ?? null,
  };
}

function profileHasKey(provider: string, profiles: Record<string, ProfileView>, config: ModelConfig | null): boolean {
  if (config?.provider === provider) return config.has_api_key || (profiles[provider]?.has_api_key ?? false);
  return profiles[provider]?.has_api_key ?? false;
}

export default function SettingsModal({ theme, onThemeChange, onClose, me, onLogout }: Props) {
  const [tab, setTab] = useState<"model" | "memory">("model");
  const [presets, setPresets] = useState<Record<string, Preset>>({});
  const [profiles, setProfiles] = useState<Record<string, ProfileView>>({});
  const [config, setConfig] = useState<ModelConfig | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [roles, setRoles] = useState<Record<RoleKey, RoleDraft | null>>(roleDrafts(undefined, null));
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  // “获取可用模型”：按供应商分别缓存实时列表，并入对应角色的下拉候选
  const [discoveredBy, setDiscoveredBy] = useState<Record<string, string[]>>({});
  const [discovering, setDiscovering] = useState(false);
  const [discoverNote, setDiscoverNote] = useState("");
  const [discoverBad, setDiscoverBad] = useState(false);

  useEffect(() => {
    settingsApi.get()
      .then(r => {
        setPresets(r.presets);
        setProfiles(r.profiles);
        setConfig(r.config);
        setDraft(draftFrom(r.config.provider, r.profiles, r.presets, r.config));
        setRoles(roleDrafts(r.roles, r.config));
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "加载设置失败"));
  }, []);

  /** 切供应商 = 切凭据编辑对象：只换表单，绝不覆写别的供应商，也不动角色。 */
  function switchProvider(id: string) {
    if (!id || id === draft?.provider) return;
    setDraft(draftFrom(id, profiles, presets, config));
    setDiscoverNote("");
    setError("");
  }

  function update(patch: Partial<Draft>) {
    setDraft(d => (d ? { ...d, ...patch } : d));
  }

  /** 自定义供应商：粘 Key 且 Base URL 还是空 → 按 Key 形态猜一个（只猜有唯一指纹的厂商） */
  function onKeyChange(v: string | null) {
    if (!draft) return;
    const next: Draft = { ...draft, api_key: v };
    if (v && draft.provider === "custom" && !draft.base_url.trim()) {
      const guess = guessBaseUrl(v);
      if (guess) {
        next.base_url = guess;
        setDiscoverBad(false);
        setDiscoverNote(`按 API Key 格式填入 Base URL：${guess}（仅为推测，不对可手改）`);
      }
    }
    setDraft(next);
  }

  async function save() {
    if (!draft) return;
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const r = await settingsApi.save({
        provider: draft.provider,
        base_url: draft.base_url,
        api_key: draft.api_key, // null=保留现有 / ""=清除 / 非空=替换
        roles,                 // 三个角色全量提交（出现的键整体替换）
      });
      setPresets(r.presets);
      setProfiles(r.profiles);
      setConfig(r.config);
      setDraft(draftFrom(draft.provider, r.profiles, r.presets, r.config));
      setRoles(roleDrafts(r.roles, r.config));
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function discover() {
    setDiscovering(true);
    setDiscoverNote("");
    setDiscoverBad(false);
    try {
      const r = await settingsApi.discoverModels({
        base_url: draft?.base_url.trim() || "",
        api_key: draft?.api_key ?? "", // 未填则服务端回退到该供应商已存 Key
      });
      const pid = draft?.provider ?? "custom";
      setDiscoveredBy(cur => ({ ...cur, [pid]: r.models }));
      setDiscoverNote(`已为 ${presets[pid]?.label ?? pid} 获取 ${r.models.length} 个模型（实时），已并入下拉候选`);
    } catch (e) {
      setDiscoverBad(true);
      setDiscoverNote(e instanceof Error ? e.message : "获取失败");
    } finally {
      setDiscovering(false);
    }
  }

  const activePreset = draft ? presets[draft.provider] : undefined;
  const draftHasSavedKey = useMemo(
    () => (draft ? profileHasKey(draft.provider, profiles, config) : false),
    [draft, profiles, config],
  );
  const reasoningUnusable = !!roles.reasoning && !profileHasKey(roles.reasoning.provider, profiles, config);

  return (
    <div className="modal-overlay"
      onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">设置</span>
          <button className="modal-close" data-tip="关闭" onClick={onClose}>×</button>
        </div>

        <div className="modal-tabs">
          <button type="button" className={tab === "model" ? "on" : ""} onClick={() => setTab("model")}>模型</button>
          <button type="button" className={tab === "memory" ? "on" : ""} onClick={() => setTab("memory")}>记忆</button>
        </div>

        <div className="modal-body">
          {tab === "memory" ? <MemoryPanel /> : (<>
          {me?.mode === "cloud" && (
            <section className="set-section">
              <h3>账号</h3>
              <div className="account-row">
                <span className="account-email" title={me.email ?? undefined}>{me.email || `用户 ${me.id}`}</span>
                {me.is_admin && <span className="account-badge" data-tip="由 .env 的 ADMIN_EMAIL 指定">管理员</span>}
                {onLogout && (
                  <button type="button" className="logout-btn" onClick={onLogout}>退出登录</button>
                )}
              </div>
            </section>
          )}
          <section className="set-section">
            <h3>主题</h3>
            <div className="theme-toggle">
              <button className={theme === "light" ? "on" : ""} onClick={() => onThemeChange("light")}>浅色</button>
              <button className={theme === "dark" ? "on" : ""} onClick={() => onThemeChange("dark")}>深色</button>
            </div>
          </section>

          <section className="set-section">
            <h3>模型角色</h3>
            <p className="set-note">
              分工预配置：主模型负责推理与写码，识图/生图交给真正的多模态厂商——四个角色可以引用<b>不同供应商</b>的凭据，
              组合出性价比方案（如推理 DeepSeek + 识图百炼 + 嵌入百炼）。纯文本任务只走主模型，不会动用其他角色。
            </p>
            {ROLE_META.map(meta => (
              <RoleCard
                key={meta.key}
                title={meta.title} desc={meta.desc} optionKey={meta.optionKey} allowNone={meta.allowNone}
                value={roles[meta.key]}
                presets={presets} profiles={profiles} discoveredBy={discoveredBy}
                defaultProvider={draft?.provider ?? "deepseek"}
                onChange={v => setRoles(cur => ({ ...cur, [meta.key]: v }))}
              />
            ))}
            {reasoningUnusable && (
              <div className="role-warn">主模型引用的供应商还没有 API Key：到下方“供应商凭据”里选好该家并填入 Key 后保存。</div>
            )}
          </section>

          <section className="set-section">
            <h3>供应商凭据</h3>
            <p className="set-note">这里只编辑**一个供应商**的 Base URL 与 API Key（各供应商互相独立、互不覆写）；上方的角色决定谁干活。</p>
            <div className="preset-row">
              {Object.entries(presets).map(([id, p]) => (
                <button key={id} type="button" className={`preset ${draft?.provider === id ? "on" : ""}`}
                  data-tip={`编辑 ${p.label} 的凭据`}
                  onClick={() => switchProvider(id)}>
                  {p.label}
                  {profiles[id]?.has_api_key && <span className="preset-dot" aria-label="已配置 Key" />}
                </button>
              ))}
            </div>

            {!draft ? (
              <div className="sub-empty">正在读取配置…</div>
            ) : (<>
              <label className="field">
                <span>Base URL</span>
                <input type="text" value={draft.base_url} placeholder="https://api.example.com/v1"
                  autoComplete="off" spellCheck={false}
                  onChange={e => update({ base_url: e.target.value })} />
              </label>

              <label className="field">
                <span>API Key{draftHasSavedKey && <em className="field-hint">（已加密保存，不会回显）</em>}</span>
                <SecretInput key={draft.provider} hasSaved={draftHasSavedKey} value={draft.api_key} onChange={onKeyChange} />
              </label>

              {activePreset?.api_url && (
                <a className="api-link" href={activePreset.api_url} target="_blank" rel="noreferrer">
                  获取 {activePreset.label} API Key ↗
                </a>
              )}

              <div className="discover-row">
                <button type="button" className="discover-btn" onClick={() => void discover()} disabled={discovering}
                  data-tip="向该 Base URL 发 GET /models（OpenAI 兼容），实时列出这个 Key 能调用的全部模型">
                  {discovering ? "获取中…" : "获取可用模型"}
                </button>
                {discoverNote && <span className={`discover-msg${discoverBad ? " err" : ""}`}>{discoverNote}</span>}
              </div>

              <p className="set-note">
                模型名会原样发给厂商接口，必须与其官方 id 一致（大小写、. 与 - 都参与匹配，填错会明确报错而不是悄悄换模型）；
                拿不准就选下拉或先“获取可用模型”。模型名留空时，自动使用该供应商的默认模型名。
              </p>

              {error && <div className="error">{error}</div>}
              <button className="save-btn" onClick={() => void save()} disabled={saving}>
                {saving ? "保存中…" : saved ? "已保存" : "保存（角色 + 当前凭据）"}
              </button>
            </>)}
          </section>
          </>)}
        </div>
      </div>
    </div>
  );
}
