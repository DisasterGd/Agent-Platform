/** 统一 API 请求封装：处理 JSON 序列化与错误。 */

/** v0.7：带状态码的错误——401（登录过期）可被上层识别并引导重新登录。 */
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** v0.7：任意请求收到 401 时通知（App 借此把界面切回登录页）。 */
type UnauthorizedListener = () => void;
const unauthorizedListeners: UnauthorizedListener[] = [];
export function onUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.push(listener);
  return () => {
    const i = unauthorizedListeners.indexOf(listener);
    if (i >= 0) unauthorizedListeners.splice(i, 1);
  };
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const raw = await response.text();
    let message = raw || `HTTP ${response.status}`;
    // FastAPI 的 HTTPException 以 {"detail": "…"} 返回：取 detail 作为可读消息
    try {
      const parsed = JSON.parse(raw) as { detail?: unknown };
      if (typeof parsed.detail === "string" && parsed.detail) message = parsed.detail;
    } catch { /* 非 JSON 错误体保留原文 */ }
    if (response.status === 401) {
      // 会话过期/未登录：通知顶层切回登录页（cloud 模式），local 模式不会出现 401
      for (const listener of unauthorizedListeners) {
        try { listener(); } catch { /* 监听器异常不影响请求方 */ }
      }
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T; // 无响应体（如发码/登出）
  return response.json() as Promise<T>;
}
