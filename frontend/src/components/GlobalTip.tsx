import { useEffect, useRef, useState } from "react";

/**
 * v0.4.6 应用内统一悬浮提示：替代浏览器原生 title tooltip。
 * 任何元素加 data-tip="文案" 即生效——悬停 320ms 后在元素下方弹出气泡，
 * 移出/滚动/切换目标即消失；靠近视口底缘自动翻到上方。不依赖浏览器 UI，
 * 便于日后从 Web 迁移到独立客户端时保持观感一致。
 */
export default function GlobalTip() {
  const [tip, setTip] = useState<{ text: string; left: number; top: number } | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    const hide = () => {
      window.clearTimeout(timer.current);
      setTip(null);
    };
    const place = (el: Element) => {
      const text = el.getAttribute("data-tip");
      if (!text) return;
      const r = el.getBoundingClientRect();
      const estW = Math.min(340, window.innerWidth - 16);
      const left = Math.max(8, Math.min(r.left, window.innerWidth - estW - 8));
      const below = r.bottom + 8;
      // 预估高度 90px：放不下就翻到元素上方
      const top = below + 90 > window.innerHeight ? Math.max(8, r.top - 94) : below;
      setTip({ text, left, top });
    };
    const onOver = (e: MouseEvent) => {
      const el = (e.target as Element | null)?.closest?.("[data-tip]");
      if (!el) { hide(); return; }
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => place(el), 320);
    };
    const onOut = (e: MouseEvent) => {
      if ((e.target as Element | null)?.closest?.("[data-tip]")) hide();
    };
    document.addEventListener("mouseover", onOver);
    document.addEventListener("mouseout", onOut);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    return () => {
      document.removeEventListener("mouseover", onOver);
      document.removeEventListener("mouseout", onOut);
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
      window.clearTimeout(timer.current);
    };
  }, []);

  if (!tip) return null;
  return <div className="g-tip" role="tooltip" style={{ left: tip.left, top: tip.top }}>{tip.text}</div>;
}
