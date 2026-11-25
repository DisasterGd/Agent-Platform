import { request } from "./api";

/** 设置页视图：服务端永不回显 API Key（v0.5.2 起只有 has_api_key 布尔）。 */
export interface ModelConfig {
  provider: string;
  base_url: string;
  model: string;
  vision_model: string;
  has_api_key: boolean;
  /** v0.4 自动记忆开关（后端会一并返回/保存） */
  memory_enabled?: boolean;
}

/** 单个供应商的档案（同样不含 Key）。 */
export interface ProfileView {
  base_url: string;
  model: string;
  vision_model: string;
  has_api_key: boolean;
}

export interface Preset {
  label: string;
  base_url: string;
  model: string;
  vision_model: string;
  api_url: string;
  /** 四个角色的下拉候选（输入框仍可手输任意名称） */
  models?: string[];
  vision_models?: string[];
  image_models?: string[];
  embedding_models?: string[];
}

/** v0.6 角色：谁干哪类活（引用某供应商档案的凭据）。model 可空，解析时用预设默认兜底。 */
export type RoleKey = "reasoning" | "vision" | "image_gen" | "embedding";

export interface RoleDraft {
  provider: string;
  model: string;
}

/** 服务端角色视图：usable=所引供应商是否已有 Key。 */
export interface RoleConfig extends RoleDraft {
  usable: boolean;
}

export interface SettingsResponse {
  config: ModelConfig;
  profiles: Record<string, ProfileView>;
  roles: Record<RoleKey, RoleConfig | null>;
  presets: Record<string, Preset>;
}

/** PUT 载荷：api_key 缺省/null=保留现有，""=清除，非空=替换；roles 出现的键整体替换对应角色。 */
export interface SettingsPayload {
  provider: string;
  base_url?: string | null;
  api_key?: string | null;
  memory_enabled?: boolean | null;
  roles?: Record<RoleKey, RoleDraft | null> | null;
}

export const settingsApi = {
  get: () => request<SettingsResponse>("/api/settings"),
  save: (payload: SettingsPayload) =>
    request<SettingsResponse>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  /** 获取可用模型：字段留空由服务端回退到已存配置（DeepSeek/百炼/智谱等均支持 OpenAI 兼容 /models） */
  discoverModels: (body: { base_url?: string; api_key?: string }) =>
    request<{ models: string[] }>("/api/settings/discover-models", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

/**
 * 自定义供应商下由 API Key 形态猜 Base URL（只收录“格式有唯一指纹”的厂商）。
 * 2026-11 实测：百炼新一代 Key 形如 sk-ws-×.×××（约 115 字符），可与 DeepSeek 的 sk-+32位十六进制区分；
 * 猜不出来就不猜——这类场景用“获取可用模型”按钮实测即可。
 */
export function guessBaseUrl(apiKey: string): string | null {
  const key = apiKey.trim();
  if (!key) return null;
  if (key.startsWith("sk-ws-")) return "https://dashscope.aliyuncs.com/compatible-mode/v1";
  if (key.startsWith("sk-or-")) return "https://openrouter.ai/api/v1";
  if (key.startsWith("sk-proj-")) return "https://api.openai.com/v1";
  if (key.startsWith("sk-ant-")) return "https://api.anthropic.com/v1";
  if (/^[A-Za-z0-9-]{8,32}\.[A-Za-z0-9]{16,128}$/.test(key)) return "https://open.bigmodel.cn/api/paas/v4";
  return null;
}
