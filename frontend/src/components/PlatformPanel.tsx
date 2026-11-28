/** v0.8.0 平台页签：部署级配置——邮件通道（验证码发信）+ 搜索源。
 *
 * 可见性：local 模式=本机用户（部署者本人）；cloud=仅 admin（父组件控制页签显隐）。
 * 敏感字段走 SecretInput（永不回显）；保存立即生效（服务端每次实时解析，无需重启）。
 */
import { useEffect, useState } from "react";
import SecretInput from "./SecretInput";
import { platformApi, type MailConfigView, type SearchConfigView } from "../services/platform";

const MAIL_PROVIDERS = [
  { value: "console", label: "console（验证码打印到后端控制台，本地调试）" },
  { value: "smtp", label: "smtp（真实发信：QQ/163 授权码即可）" },
];
const SEARCH_PROVIDERS = [
  { value: "auto", label: "auto（DuckDuckGo → Bing 网页兜底，零配置）" },
  { value: "duckduckgo", label: "duckduckgo" },
  { value: "bing_scrape", label: "bing_scrape（Bing 网页解析，无 Key）" },
  { value: "bing", label: "bing（官方 API，需 Key）" },
  { value: "tavily", label: "tavily（需 Key）" },
];

export default function PlatformPanel() {
  const [mail, setMail] = useState<MailConfigView | null>(null);
  const [search, setSearch] = useState<SearchConfigView | null>(null);
  const [mProvider, setMProvider] = useState("smtp");
  const [mHost, setMHost] = useState("");
  const [mPort, setMPort] = useState(465);
  const [mUser, setMUser] = useState("");
  const [mFrom, setMFrom] = useState("");
  const [mPwd, setMPwd] = useState<string | null>(null);
  const [sProvider, setSProvider] = useState("auto");
  const [sKey, setSKey] = useState<string | null>(null);
  const [testTo, setTestTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        const m = await platformApi.getMail();
        setMail(m);
        setMProvider(m.provider);
        setMHost(m.host);
        setMPort(m.port);
        setMUser(m.user);
        setMFrom(m.from_addr);
        const s = await platformApi.getSearch();
        setSearch(s);
        setSProvider(s.provider);
      } catch (e) {
        setError(e instanceof Error ? e.message : "加载平台配置失败");
      }
    })();
  }, []);

  async function saveMail() {
    setBusy(true); setError(""); setNote("");
    try {
      const next = await platformApi.updateMail({
        provider: mProvider, host: mHost.trim(), port: mPort,
        user: mUser.trim(), password: mPwd, from_addr: mFrom.trim(),
      });
      setMail(next); setMPwd(null);
      setNote("邮件配置已保存，立即生效（无需重启）。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function sendTest() {
    setBusy(true); setError(""); setNote("");
    try {
      const r = await platformApi.testMail(testTo.trim());
      setNote(r.message);
    } catch (e) {
      setError(e instanceof Error ? e.message : "发送失败");
    } finally {
      setBusy(false);
    }
  }

  async function saveSearch() {
    setBusy(true); setError(""); setNote("");
    try {
      const next = await platformApi.updateSearch({ provider: sProvider, api_key: sKey });
      setSearch(next); setSKey(null);
      setNote("搜索源配置已保存，立即生效（无需重启）。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="set-section">
        <h3>邮件通道（登录验证码发信）</h3>
        <p className="set-note">
          cloud 上线必须切到 smtp，否则用户收不到验证码。QQ 邮箱三步：网页版设置 → 账号 → 开启「IMAP/SMTP 服务」
          → 手机短信生成<b>授权码</b>（不是登录密码）。配置立即生效；上线前请先「发送测试邮件」。
        </p>
        {mail && !mail.smtp_complete && mail.provider === "smtp" && (
          <p className="set-note"><b>SMTP 尚未配齐（host / 账号 / 密码），真实发信会失败。</b></p>
        )}
        <label className="login-label" htmlFor="pf-mail-provider">通道</label>
        <select id="pf-mail-provider" className="set-input" value={mProvider}
          onChange={e => setMProvider(e.target.value)}>
          {MAIL_PROVIDERS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
        {mProvider === "smtp" && (
          <>
            <label className="login-label" htmlFor="pf-smtp-host">SMTP 服务器</label>
            <input id="pf-smtp-host" className="set-input" type="text" placeholder="smtp.qq.com"
              value={mHost} onChange={e => setMHost(e.target.value)} />
            <label className="login-label" htmlFor="pf-smtp-port">端口（SSL 直连，QQ/163 都是 465）</label>
            <input id="pf-smtp-port" className="set-input" type="number" value={mPort}
              onChange={e => setMPort(Number(e.target.value) || 465)} />
            <label className="login-label" htmlFor="pf-smtp-user">发信账号（完整邮箱地址）</label>
            <input id="pf-smtp-user" className="set-input" type="text" placeholder="you@qq.com"
              value={mUser} onChange={e => setMUser(e.target.value)} />
            <label className="login-label" htmlFor="pf-smtp-pwd">授权码</label>
            <SecretInput hasSaved={mail?.has_password ?? false} value={mPwd} onChange={setMPwd} />
            <label className="login-label" htmlFor="pf-mail-from">发件人地址（QQ/163/126 必须与发信账号一致；留空则同发信账号）</label>
            <input id="pf-mail-from" className="set-input" type="text" placeholder="you@qq.com"
              value={mFrom} onChange={e => setMFrom(e.target.value)} />
          </>
        )}
        <div className="pf-actions">
          <button type="button" className="login-btn" disabled={busy} onClick={() => void saveMail()}>
            保存邮件配置
          </button>
        </div>
        {mProvider === "smtp" && (
          <div className="pf-test">
            <label className="login-label" htmlFor="pf-test-to">发送测试邮件到</label>
            <div className="pf-test-row">
              <input id="pf-test-to" className="set-input" type="email" placeholder="you@example.com"
                value={testTo} onChange={e => setTestTo(e.target.value)} />
              <button type="button" className="login-btn" disabled={busy || !testTo.trim()}
                onClick={() => void sendTest()}>发送测试</button>
            </div>
          </div>
        )}
      </section>

      <section className="set-section">
        <h3>联网搜索源</h3>
        <p className="set-note">
          Agent 的 web_search 工具从这里取搜索源。auto 默认零配置；bing / tavily 需要对应服务的 API Key
          （保存语义与模型 Key 相同：留空保存=清除）。
        </p>
        <label className="login-label" htmlFor="pf-search-provider">搜索源</label>
        <select id="pf-search-provider" className="set-input" value={sProvider}
          onChange={e => setSProvider(e.target.value)}>
          {SEARCH_PROVIDERS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
        {(sProvider === "bing" || sProvider === "tavily") && (
          <>
            <label className="login-label" htmlFor="pf-search-key">搜索 API Key</label>
            <SecretInput hasSaved={search?.has_api_key ?? false} value={sKey} onChange={setSKey} />
          </>
        )}
        <div className="pf-actions">
          <button type="button" className="login-btn" disabled={busy} onClick={() => void saveSearch()}>
            保存搜索配置
          </button>
        </div>
      </section>

      {note && !error && <p className="set-note">{note}</p>}
      {error && <p className="login-error">{error}</p>}
    </>
  );
}
