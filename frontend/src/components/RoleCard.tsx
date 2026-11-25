import ModelSelect from "./ModelSelect";
import type { Preset, ProfileView, RoleDraft } from "../services/settings";

interface Props {
  title: string;
  desc: string;
  /** null=该角色未启用（仅 allowNone 的角色可为 null） */
  value: RoleDraft | null;
  optionKey: "models" | "vision_models" | "image_models" | "embedding_models";
  presets: Record<string, Preset>;
  profiles: Record<string, ProfileView>;
  discoveredBy: Record<string, string[]>;
  /** 首次启用该角色时默认引用的供应商（=凭据区正在编辑的那家） */
  defaultProvider: string;
  allowNone: boolean;
  onChange: (v: RoleDraft | null) => void;
}

/**
 * v0.6 角色卡片：一个“谁干哪类活”的配置单元。
 *
 * 角色只记 {供应商, 模型名}；凭据（Base URL/Key）来自供应商档案——
 * 因此推理、识图、生图可以分属三家厂商，各用各的 Key。
 * 模型名留空时按“该供应商默认名”解析（reasoning 还会经 .env 兜底）。
 */
export default function RoleCard({
  title, desc, value, optionKey, presets, profiles, discoveredBy, defaultProvider, allowNone, onChange,
}: Props) {
  const pid = value?.provider ?? "";
  const preset = presets[pid];
  const curated = preset?.[optionKey] ?? [];
  const live = discoveredBy[pid] ?? [];
  // vision/image_gen 的实时列表混着大量非目标模态资源：仅在“自定义”（没有精选清单）时才并入
  const options = [...new Set([...curated, ...(optionKey === "models" || pid === "custom" ? live : [])])];
  const hasKey = pid ? (profiles[pid]?.has_api_key ?? false) : false;

  return (
    <div className="role-card">
      <div className="role-head">
        <b>{title}</b>
        {!value ? <span className="role-badge off">未配置</span>
          : hasKey ? <span className="role-badge ok">就绪</span>
            : <span className="role-badge warn">缺 Key</span>}
      </div>
      {/* 说明不再单行截断：整段换行呈现，全文直达（v0.6.2，悬停提示对长文无效） */}
      <p className="role-desc">{desc}</p>

      {!value ? (
        <button type="button" className="role-enable"
          onClick={() => onChange({ provider: defaultProvider || "deepseek", model: "" })}>
          ＋ 配置该角色
        </button>
      ) : (
        <>
          <div className="role-row">
            <span className="role-label">供应商</span>
            <div className="role-providers">
              {Object.entries(presets).map(([id, p]) => (
                <button key={id} type="button"
                  className={`role-chip${pid === id ? " on" : ""}`}
                  data-tip={profiles[id]?.has_api_key ? `${p.label}：已配置 Key` : `${p.label}：尚未配置 Key`}
                  onClick={() => onChange({ provider: id, model: "" })}>
                  {p.label}
                  {profiles[id]?.has_api_key && <i className="role-dot" />}
                </button>
              ))}
            </div>
          </div>
          <div className="role-row">
            <span className="role-label">模型</span>
            <ModelSelect
              value={value.model} options={options} discovered={new Set(live)}
              placeholder="下拉选择或输入模型名"
              onChange={v => onChange({ ...value, model: v })}
            />
          </div>
          {/* 长占位符既难看又易被当成已填值（v0.6.2）：改短，留空语义挪到行下提示，且只在留空时出现 */}
          {!value.model && <p className="role-hint">模型名留空 · 将使用该供应商的默认模型</p>}
          {allowNone && (
            <button type="button" className="role-disable" onClick={() => onChange(null)}>不使用该角色</button>
          )}
        </>
      )}
    </div>
  );
}
