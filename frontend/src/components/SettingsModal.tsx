import { useEffect, useMemo, useState } from "react";
import { guessBaseUrl, settingsApi, type ModelConfig, type Preset } from "../services/settings";
import MemoryPanel from "./MemoryPanel";

interface Props {
  theme: "light" | "dark";
  onThemeChange: (t: "light" | "dark") => void;
  onClose: () => void;
}

type ModelField = "base_url" | "api_key" | "model" | "vision_model";

const FIELDS: { key: ModelField; label: string; secret?: boolean; list?: string; hint?: string }[] = [
  { key: "base_url", label: "Base URL" },
  { key: "api_key", label: "API Key", secret: true },
  { key: "model", label: "模型", list: "set-model-options", hint: "下拉选择或直接输入" },
  { key: "vision_model", label: "视觉模型（识图）", list: "set-vision-options", hint: "留空则不启用识图" },
];

export default function SettingsModal({ theme, onThemeChange, onClose }: Props) {
  const [tab, setTab] = useState<"model" | "memory">("model");
  const [config, setConfig] = useState<ModelConfig>({
    provider: "deepseek", base_url: "", api_key: "", model: "", vision_model: "",
  });
  const [presets, setPresets] = useState<Record<string, Preset>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  // v0.5.1 “获取可用模型”：实时列表并入下拉候选；note 兼作猜测/获取的提示（bad=红字）
  const [discovered, setDiscovered] = useState<string[]>([]);
  const [discovering, setDiscovering] = useState(false);
  const [discoverNote, setDiscoverNote] = useState("");
  const [discoverBad, setDiscoverBad] = useState(false);

  useEffect(() => {
    settingsApi.get()
      .then(r => { setConfig(r.config); setPresets(r.presets); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "加载设置失败"));
  }, []);

  function applyPreset(id: string) {
    const p = presets[id];
    if (!p) return;
    setConfig(c => ({ ...c, provider: id, base_url: p.base_url, model: p.model, vision_model: p.vision_model }));
    setDiscovered([]); // 旧端点的实时列表不适用于新厂商
    setDiscoverNote("");
  }

  /** 自定义供应商：填 Key 后若 Base URL 还空着，按 Key 形态猜一个（只猜有唯一指纹的厂商） */
  function onKeyBlur() {
    if (config.provider !== "custom" || config.base_url.trim()) return;
    const guess = guessBaseUrl(config.api_key);
    if (!guess) return;
    setConfig(c => ({ ...c, base_url: guess }));
    setDiscoverBad(false);
    setDiscoverNote(`按 API Key 格式填入 Base URL：${guess}（仅为推测，不对可手改）`);
  }

  async function discover() {
    const base = config.base_url.trim();
    const key = config.api_key.trim();
    if (!base || !key) {
      setDiscoverBad(true);
      setDiscoverNote("请先填写 Base URL 与 API Key（无需先保存）");
      return;
    }
    setDiscovering(true);
    setDiscoverNote("");
    try {
      const r = await settingsApi.discoverModels({ base_url: base, api_key: key });
      setDiscovered(r.models);
      setDiscoverBad(false);
      setDiscoverNote(`已获取 ${r.models.length} 个可用模型，已并入下拉候选`);
    } catch (e) {
      setDiscovered([]);
      setDiscoverBad(true);
      setDiscoverNote(e instanceof Error ? e.message : "获取失败");
    } finally {
      setDiscovering(false);
    }
  }

  async function save() {
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      await settingsApi.save(config);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  const activePreset = presets[config.provider];
  const modelOptions = useMemo(
    () => [...new Set([...(activePreset?.models ?? []), ...discovered])],
    [activePreset, discovered],
  );
  const visionOptions = useMemo(
    () => [...new Set([...(activePreset?.vision_models ?? []), ...discovered])],
    [activePreset, discovered],
  );

  return (
    <div className="modal-overlay" onClick={onClose}>
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
                <button key={id} className={`preset ${config.provider === id ? "on" : ""}`} onClick={() => applyPreset(id)}>
                  {p.label}
                </button>
              ))}
            </div>

            {FIELDS.map(f => (
              <label key={f.key} className="field">
                <span>{f.label}{f.hint && <em className="field-hint">（{f.hint}）</em>}</span>
                <input
                  type={f.secret ? "password" : "text"}
                  list={f.list}
                  value={config[f.key]}
                  placeholder={f.secret ? "sk-…" : ""}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={e => setConfig(c => ({ ...c, [f.key]: e.target.value }))}
                  onBlur={f.secret ? onKeyBlur : undefined}
                />
              </label>
            ))}
            <datalist id="set-model-options">
              {modelOptions.map(m => <option key={m} value={m} />)}
            </datalist>
            <datalist id="set-vision-options">
              {visionOptions.map(m => <option key={m} value={m} />)}
            </datalist>

            <p className="set-note">
              模型名会原样发给厂商接口，必须与官方 id 完全一致（含大小写与 -）；
              可从下拉中选，也可用“获取可用模型”拉取你 Key 下的实时列表。
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
              {saving ? "保存中…" : saved ? "已保存" : "保存"}
            </button>
          </section>
          </>)}
        </div>
      </div>
    </div>
  );
}
