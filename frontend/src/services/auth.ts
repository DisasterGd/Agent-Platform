/** v0.7 认证：邮箱验证码登录/注册合一 + 当前身份。 */
import { request } from "./api";

/** /auth/request-code 返回：channel=console 时验证码只打印在后端控制台（未配置真实发信）。 */
export interface RequestCodeResult {
  channel: "console" | "smtp";
}

/** /auth/me 返回：mode=local 时前端直接进入应用（永远看不到登录页）。 */
export interface MeInfo {
  id: number;
  mode: "local" | "cloud";
  email: string | null;
  display_name: string;
  is_admin: boolean;
  /** v0.7.2：当前身份是否来自已登录会话（local 模式 false=本地默认身份未登录）。 */
  via_session: boolean;
}

export const authApi = {
  me: () => request<MeInfo>("/api/auth/me"),
  /** 发送登录/注册验证码；返回邮件通道类型（不区分邮箱是否存在——防枚举）。 */
  requestCode: (email: string) =>
    request<RequestCodeResult>("/api/auth/request-code", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  /** 验证并登录；邮箱未注册过即注册（验证码即唯一凭证，无需密码）。 */
  verify: (email: string, code: string) =>
    request<MeInfo>("/api/auth/verify", {
      method: "POST",
      body: JSON.stringify({ email, code }),
    }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
};
