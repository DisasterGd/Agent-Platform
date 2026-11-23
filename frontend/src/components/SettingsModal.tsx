import { useEffect, useMemo, useState } from "react";
import { guessBaseUrl, settingsApi, type ModelConfig, type Preset, type ProfileView } from "../services/settings";
import MemoryPanel from "./MemoryPanel";
import ModelSelect from "./ModelSelect";
import SecretInput from "./SecretInput";

interface Props {
  theme: "light" | "dark";
  onThemeChange: (t: "light" | "dark") => void;
  onClose: () => void;
}

/** 表单态：正在编辑哪个供应商的档案。apiKey=null 表示“保留服务器上的”。 */
interface Draft {
  provider: string;
  base_url: string;
  model: string;
  vision_model: string;
  api_key: string | null;
}

/**
 * 组装编辑草稿：档案已存值 > 生效视图（active 时含 .env/预设兜底）> 预设默认。
 * “档案是否已有 Key”同样对 active 供应商合并 config.has_api_key（.env 的 Key 也算已配置）。
 */
function draftFrom(provider: string, profiles: Record<string, ProfileView>, presets: Record<string, Preset>, config: ModelConfig | null): Draft {
  const profile = profiles[provider];
  const preset = presets[provider];
  const active = config?.provider === provider ? config : null;
  return {
    provider,
    base_url: profile?.base_url || active?.base_url || preset?.base_url || "",
    model: profile?.model || active?.model || preset?.model || "",
    vision_model: profile?.vision_model || active?.vision_model || preset?.vision_model || "",
    api_key: null,
  };
}

function profileHasKey(provider: string, profiles: Record<string, ProfileView>, config: ModelConfig | null): boolean {
  if (config?.provider === provider) return config.has_api_key || (profiles[provider]?.has_api_key ?? false);
  return profiles[provider]?.has_api_key ?? false;
}

export default function SettingsModal({ theme, onThemeChange, onClose }: Props) {
  const [tab, setTab] = useState<"model" | "memory">("model");
  const [presets, setPresets] = useState<Record<string, Preset>>({});
  const [profiles, setProfiles] = useState<Record<string, ProfileView>>({});
  const [config, setConfig] = useState<ModelConfig | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  // “获取可用模型”：实时列表并入下拉候选；note 兼作提示（bad=红字）
  const [discovered, setDiscovered] = useState<string[]>([]);
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
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "加载设置失败"));
  }, []);

  /** 切供应商 = 切档案：只换编辑对象，绝不覆写别的供应商；空档案才用预设打底。 */
  function switchProvider(id: string) {
    if (!id || id === draft?.provider) return;
    setDraft(draftFrom(id, profiles, presets, config));
    setDiscovered([]);
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
        model: draft.model,
        vision_model: draft.vision_model,
      });
      setPresets(r.presets);
      setProfiles(r.profiles);
      setConfig(r.config);
      setDraft(draftFrom(draft.provider, r.profiles, r.presets, r.config));
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
        api_key: draft?.api_key ?? "", // 未填则服务端用已存 Key
      });
      setDiscovered(r.models);
      setDiscoverNote(`已获取 ${r.models.length} 个模型（实时），下拉候选已并入`);
    } catch (e) {
      setDiscovered([]);
      setDiscoverBad(true);
      setDiscoverNote(e instanceof Error ? e.message : "获取失败");
    } finally {
      setDiscovering(false);
    }
  }

  const activePreset = draft ? presets[draft.provider] : undefined;
  const discoveredSet = useMemo(() => new Set(discovered), [discovered]);
  const modelOptions = useMemo(
    () => [...new Set([...(activePreset?.models ?? []), ...discovered])],
    [activePreset, discovered],
  );
  const visionOptions = useMemo(
    () => [...new Set([...(activePreset?.vision_models ?? []), ...(draft?.provider === "custom" ? discovered : [])])],
    [activePreset, discovered, draft],
  );
  const draftHasSavedKey = draft ? profileHasKey(draft.provider, profiles, config) : false;

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
          <section className="set-section">
            <h3>主题</h3>
            <div className="theme-toggle">
              <button className={theme === "light" ? "on" : ""} onClick={() => onThemeChange("light")}>浅色</button>
              <button className={theme === "dark" ? "on" : ""} onClick={() => onThemeChange("dark")}>深色</button>
            </div>
          </section>

          <section className="set-section">
            <h3>模型配置</h3>
            <div className="preset-row">
              {Object.entries(presets).map(([id, p]) => (
                <button key={id} type="button" className={`preset ${draft?.provider === id ? "on" : ""}`}
                  data-tip={`切换到 ${p.label} 的档案（各供应商配置互相独立、互不覆写）`}
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
                <SecretInput hasSaved={draftHasSavedKey} value={draft.api_key} onChange={onKeyChange} />
              </label>

              <label className="field">
                <span>模型<em className="field-hint">（下拉选，或直接输入）</em></span>
                <ModelSelect value={draft.model} options={modelOptions} discovered={discoveredSet}
                  placeholder="选择或输入模型名" onChange={v => update({ model: v })} />
              </label>

              <label className="field">
                <span>视觉模型（识图）<em className="field-hint">（留空则不启用识图）</em></span>
                <ModelSelect value={draft.vision_model} options={visionOptions}
                  placeholder="选择或输入视觉模型名" onChange={v => update({ vision_model: v })} />
              </label>

              <p className="set-note">
                模型名会原样发给厂商接口，必须与其官方 id 一致（大小写、- 与 . 都参与匹配，填错会明确报错而不是悄悄换模型）；
                拿不准就选下拉，或点“获取可用模型”拉你 Key 下的实时列表。切换供应商按钮只是切换编辑的档案，不会改动其他供应商的配置。
              </p>

              {activePreset?.api_url && (
                <a className="api-link" href={activePreset.api_url} target="_blank" rel="noreferrer">
                  获取 {activePreset.label} API Key ↗
                </a>
              )}

              <div className="discover-row">
                <button type="button" className="discover-btn" onClick={() => void discover()} disabled={discovering}>
                  {discovering ? "获取中…" : "获取可用模型"}
                </button>
                {discoverNote && <span className={`discover-msg${discoverBad ? " err" : ""}`}>{discoverNote}</span>}
              </div>

              {error && <div className="error">{error}</div>}
              <button className="save-btn" onClick={() => void save()} disabled={saving}>
                {saving ? "保存中…" : saved ? "已保存" : "保存到当前档案"}
              </button>
            </>)}
          </section>
          </>)}
        </div>
      </div>
    </div>
  );
}
