import { request } from "./api";

export interface ModelConfig {
  provider: string;
  base_url: string;
  api_key: string;
  model: string;
  vision_model: string;
  /** v0.4 自动记忆开关（后端会一并返回/保存） */
  memory_enabled?: boolean;
}

export interface Preset {
  label: string;
  base_url: string;
  model: string;
  vision_model: string;
  api_url: string;
  /** v0.5.1 “模型/视觉模型”输入框的下拉候选（仍可手输任意名称） */
  models?: string[];
  vision_models?: string[];
}

export interface SettingsResponse {
  config: ModelConfig;
  presets: Record<string, Preset>;
}

export const settingsApi = {
  get: () => request<SettingsResponse>("/api/settings"),
  save: (config: ModelConfig) =>
    request<SettingsResponse>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(config),
    }),
  /** 获取可用模型：向后端填入的 Base URL 发 GET /models（OpenAI 兼容），返回模型 id 列表 */
  discoverModels: (body: { base_url: string; api_key: string }) =>
    request<{ models: string[] }>("/api/settings/discover-models", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

/**
 * 自定义供应商下由 API Key 形态猜 Base URL（问题 5 的保守实现）。
 * 只收录“格式有唯一指纹”的厂商：DeepSeek/阿里等 Key 同为 sk-+32位十六进制，
 * 彼此无法区分，猜不出也不乱猜——这类场景用“获取可用模型”按钮实测即可。
 */
export function guessBaseUrl(apiKey: string): string | null {
  const key = apiKey.trim();
  if (!key) return null;
  if (key.startsWith("sk-or-")) return "https://openrouter.ai/api/v1";
  if (key.startsWith("sk-proj-")) return "https://api.openai.com/v1";
  if (key.startsWith("sk-ant-")) return "https://api.anthropic.com/v1";
  if (/^[A-Za-z0-9-]{8,32}\.[A-Za-z0-9]{16,128}$/.test(key)) return "https://open.bigmodel.cn/api/paas/v4";
  return null;
}
