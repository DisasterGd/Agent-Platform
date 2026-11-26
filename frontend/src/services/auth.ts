/** v0.7 认证：邮箱验证码登录/注册合一 + 当前身份。 */
import { request } from "./api";

/** /auth/me 返回：mode=local 时前端直接进入应用（永远看不到登录页）。 */
export interface MeInfo {
  id: number;
  mode: "local" | "cloud";
  email: string | null;
  display_name: string;
  is_admin: boolean;
}

export const authApi = {
  me: () => request<MeInfo>("/api/auth/me"),
  /** 发送登录/注册验证码（统一 204，不区分邮箱是否存在）。 */
  requestCode: (email: string) =>
    request<void>("/api/auth/request-code", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  /** 验证并登录；邮箱未注册过即注册（可带邀请码）。 */
  verify: (email: string, code: string, invite_code?: string) =>
    request<MeInfo>("/api/auth/verify", {
      method: "POST",
      body: JSON.stringify({ email, code, invite_code: invite_code ?? "" }),
    }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
};
