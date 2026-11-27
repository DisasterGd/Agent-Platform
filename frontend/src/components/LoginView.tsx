/** v0.7 登录表单：邮箱 → 验证码两步卡片（登录注册合一）。
 *
 * - LoginView：cloud 模式未登录时的全屏登录页；
 * - LoginForm：可复用表单本体，设置弹窗「账号管理」页签也用它（v0.7.2 起 local 模式可随时登录）。
 *
 * 防枚举由服务端保证（响应不含邮箱存在性），本页只如实转述服务端错误（频控/验证码错等）；
 * 发码响应带 channel（console/smtp），据此提示验证码去向——console 通道即"码在后端控制台"。
 */
import { useEffect, useRef, useState } from "react";
import { authApi, type MeInfo } from "../services/auth";

const RESEND_SECONDS = 60;

export function LoginForm({
  onSuccess,
  bindNote,
}: {
  onSuccess: (me: MeInfo) => void;
  /** 本地模式的绑定提示：默认账号还没有邮箱时显示"首次登录将绑定当前账号"。 */
  bindNote?: string;
}) {
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [cooldown, setCooldown] = useState(0);
  const emailRef = useRef<HTMLInputElement>(null);

  useEffect(() => { emailRef.current?.focus(); }, [step]);
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown(s => s - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  async function requestCode() {
    const value = email.trim();
    if (!value) { setError("请输入邮箱"); return; }
    setBusy(true); setError(""); setNote("");
    try {
      const { channel } = await authApi.requestCode(value);
      setStep("code");
      setCooldown(RESEND_SECONDS);
      setNote(channel === "console"
        ? "当前邮件通道为 console（未配置真实发信）：验证码已打印到后端控制台/日志，请在那里查看；配置 MAIL_PROVIDER=smtp 后验证码才会发送到邮箱。"
        : "验证码已发送，请查收邮箱（10 分钟内有效）");
      window.setTimeout(() => document.getElementById("login-code")?.focus(), 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "验证码发送失败");
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    if (!code.trim()) { setError("请输入验证码"); return; }
    setBusy(true); setError("");
    try {
      const me = await authApi.verify(email.trim(), code.trim());
      onSuccess(me);
    } catch (e) {
      setError(e instanceof Error ? e.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-form">
      {step === "email" ? (
        <>
          <label className="login-label" htmlFor="login-email">邮箱</label>
          <input
            id="login-email" ref={emailRef} className="login-input" type="email"
            placeholder="you@example.com" autoComplete="email" value={email}
            disabled={busy}
            onChange={e => setEmail(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") void requestCode(); }}
          />
          <button className="login-btn" disabled={busy || !email.trim() || cooldown > 0}
            onClick={() => void requestCode()}>
            {busy ? "发送中…" : cooldown > 0 ? `重新发送（${cooldown}s）` : "获取验证码"}
          </button>
        </>
      ) : (
        <>
          <label className="login-label" htmlFor="login-code">验证码</label>
          <input
            id="login-code" className="login-input login-code" type="text" inputMode="numeric"
            placeholder="6 位数字" maxLength={6} value={code} disabled={busy}
            onChange={e => setCode(e.target.value.replace(/\D/g, ""))}
            onKeyDown={e => { if (e.key === "Enter") void verify(); }}
          />
          <button className="login-btn" disabled={busy || !code.trim()}
            onClick={() => void verify()}>
            {busy ? "验证中…" : "登录 / 注册"}
          </button>
          <div className="login-sub">
            <button type="button" className="login-link" onClick={() => { setStep("email"); setCode(""); setError(""); setNote(""); }}>
              ← 换一个邮箱
            </button>
            <button type="button" className="login-link" disabled={busy || cooldown > 0}
              onClick={() => void requestCode()}>
              {cooldown > 0 ? `重新发送（${cooldown}s）` : "重新发送验证码"}
            </button>
          </div>
        </>
      )}

      {bindNote && step === "email" && !error && <p className="login-note">{bindNote}</p>}
      {note && !error && <p className="login-note">{note}</p>}
      {error && <p className="login-error">{error}</p>}
    </div>
  );
}

export default function LoginView({ onSuccess }: { onSuccess: (me: MeInfo) => void }) {
  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <span className="mark">A</span>
          <div className="brand-word">
            <strong>Agent Platform</strong>
            <span>登录后开始使用</span>
          </div>
        </div>
        <LoginForm onSuccess={onSuccess} />
        <p className="login-hint">首次使用：验证通过即自动创建账号，无需密码。</p>
      </div>
    </div>
  );
}
