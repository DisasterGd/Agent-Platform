import { request } from "./api";

export interface ModelConfig {
  provider: string;
  base_url: string;
  api_key: string;
  model: string;
  vision_model: string;
}

export interface Preset {
  label: string;
  base_url: string;
  model: string;
  vision_model: string;
  api_url: string;
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
};
