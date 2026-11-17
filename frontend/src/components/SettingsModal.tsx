import { useEffect, useState } from "react";
import { settingsApi, type ModelConfig, type Preset } from "../services/settings";

interface Props {
  theme: "light" | "dark";
  onThemeChange: (t: "light" | "dark") => void;
  onClose: () => void;
}

const FIELDS: { key: keyof ModelConfig; label: string; secret?: boolean }[] = [
  { key: "base_url", label: "Base URL" },
  { key: "api_key", label: "API Key", secret: true },
  { key: "model", label: "模型" },
  { key: "vision_model", label: "视觉模型（识图）" },
];

export default function SettingsModal({ theme, onThemeChange, onClose }: Props) {
  const [config, setConfig] = useState<ModelConfig>({
    provider: "deepseek", base_url: "", api_key: "", model: "", vision_model: "",
  });
  const [presets, setPresets] = useState<Record<string, Preset>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    settingsApi.get()
      .then(r => { setConfig(r.config); setPresets(r.presets); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "加载设置失败"));
  }, []);

  function applyPreset(id: string) {
    const p = presets[id];
    if (!p) return;
    setConfig(c => ({ ...c, provider: id, base_url: p.base_url, model: p.model, vision_model: p.vision_model }));
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

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">设置</span>
          <button className="modal-close" title="关闭" onClick={onClose}>×</button>
        </div>

        <div className="modal-body">
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
                <span>{f.label}</span>
                <input
                  type={f.secret ? "password" : "text"}
                  value={config[f.key]}
                  placeholder={f.secret ? "sk-…" : ""}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={e => setConfig(c => ({ ...c, [f.key]: e.target.value }))}
                />
              </label>
            ))}

            {activePreset?.api_url && (
              <a className="api-link" href={activePreset.api_url} target="_blank" rel="noreferrer">
                获取 {activePreset.label} API Key ↗
              </a>
            )}

            {error && <div className="error">{error}</div>}
            <button className="save-btn" onClick={() => void save()} disabled={saving}>
              {saving ? "保存中…" : saved ? "已保存" : "保存"}
            </button>
          </section>
        </div>
      </div>
    </div>
  );
}
