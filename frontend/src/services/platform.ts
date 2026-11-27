/** v0.8.0 平台配置接口：部署级邮件通道与搜索源（仅部署者可见，local=本机用户/cloud=admin）。
 *
 * 敏感字段永不回显：服务端只回 has_password / has_api_key；保存语义与模型 Key 一致——
 * 缺省（null）=保留 / 空串=清除 / 非空=替换。
 */
import { request } from "./api";

export interface MailConfigView {
  provider: "console" | "smtp";
  host: string;
  port: number;
  user: string;
  from_addr: string;
  has_password: boolean;
  /** host/user/password 三者齐全（可发真实邮件） */
  smtp_complete: boolean;
}

export interface SearchConfigView {
  provider: string;
  has_api_key: boolean;
}

export const platformApi = {
  getMail: () => request<MailConfigView>("/api/admin/settings/mail"),

  updateMail: (patch: {
    provider?: string;
    host?: string;
    port?: number;
    user?: string;
    /** null=保留现有；""=清除；字符串=替换 */
    password?: string | null;
    from_addr?: string;
  }) =>
    request<MailConfigView>("/api/admin/settings/mail", {
      method: "PUT",
      body: JSON.stringify({ ...patch, password: patch.password ?? undefined }),
    }),

  testMail: (to: string) =>
    request<{ ok: boolean; message: string }>("/api/admin/settings/mail/test", {
      method: "POST",
      body: JSON.stringify({ to }),
    }),

  getSearch: () => request<SearchConfigView>("/api/admin/settings/search"),

  updateSearch: (patch: { provider?: string; api_key?: string | null }) =>
    request<SearchConfigView>("/api/admin/settings/search", {
      method: "PUT",
      body: JSON.stringify({ ...patch, api_key: patch.api_key ?? undefined }),
    }),
};
