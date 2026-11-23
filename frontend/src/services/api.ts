/** 统一 API 请求封装：处理 JSON 序列化与错误。 */
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
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
