import { useEffect, useRef, useState, type MutableRefObject } from "react";

/**
 * 执行/生成过程中的“思考过程”动态展示（对标主流平台）。
 *
 * - 每开始一步（工具调用、步骤切换）追加一行标签，流式文本汇入当前行；
 * - 行列表循环上下滚动，滚动速度与实际生成速度（chars/s 的 EMA）相关联；
 * - 生成结束后进入“虚化”状态（模糊 + 半透明）短暂停留，随后整体卸载；
 * - 内容只存内存、不落库，不占用本地磁盘。
 */

export interface ThinkLine {
  id: number;
  label: string;
  text: string;
}

export type ThinkPhase = "idle" | "live" | "faded";

export interface ThinkingTracker {
  lines: ThinkLine[];
  phase: ThinkPhase;
  /** 最近生成速度（字符/秒），由 rAF 滚动循环直接读取，避免高频 setState。 */
  speedRef: MutableRefObject<number>;
  begin: (label: string) => void;
  pushLabel: (label: string) => void;
  appendText: (text: string) => void;
  end: () => void;
}

const MAX_LINES = 10;
const LINE_TEXT_LIMIT = 160;
const FLUSH_MS = 200;
const FADE_MS = 2800;

export function useThinkingTracker(): ThinkingTracker {
  const [lines, setLines] = useState<ThinkLine[]>([]);
  const [phase, setPhase] = useState<ThinkPhase>("idle");
  // begin/end 与事件回调可能发生在同一次 flush 内，用 ref 做同步门控（state 只用于渲染）
  const phaseRef = useRef<ThinkPhase>("idle");
  const speedRef = useRef(0);
  const idRef = useRef(0);
  const fadeTimer = useRef<number | null>(null);
  // 当前行的滚动文本尾与速率统计窗口
  const bufRef = useRef({ text: "", chars: 0, windowStart: 0, lastFlush: 0 });

  const setBothPhases = (p: ThinkPhase) => {
    phaseRef.current = p;
    setPhase(p);
  };

  const resetBuf = () => {
    bufRef.current = { text: "", chars: 0, windowStart: 0, lastFlush: 0 };
  };

  const clearFade = () => {
    if (fadeTimer.current !== null) {
      window.clearTimeout(fadeTimer.current);
      fadeTimer.current = null;
    }
  };

  useEffect(() => () => clearFade(), []);

  const begin = (label: string) => {
    clearFade();
    resetBuf();
    speedRef.current = 0;
    idRef.current += 1;
    setLines([{ id: idRef.current, label, text: "" }]);
    setBothPhases("live");
  };

  const pushLabel = (label: string) => {
    bufRef.current.text = "";
    idRef.current += 1;
    const line: ThinkLine = { id: idRef.current, label, text: "" };
    setLines(cur => {
      const next = [...cur, line];
      return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
    });
  };

  const appendText = (text: string) => {
    if (!text || phaseRef.current !== "live") return;
    const b = bufRef.current;
    const now = performance.now();
    if (b.windowStart === 0) b.windowStart = now;
    if (now - b.windowStart >= 1000) {
      const rate = (b.chars * 1000) / (now - b.windowStart);
      speedRef.current = speedRef.current * 0.6 + rate * 0.4;
      b.chars = 0;
      b.windowStart = now;
    }
    b.chars += text.length;
    b.text = (b.text + text).replace(/\s+/g, " ").slice(-LINE_TEXT_LIMIT);
    if (now - b.lastFlush < FLUSH_MS) return;
    b.lastFlush = now;
    const shown = b.text;
    setLines(cur => (cur.length ? [...cur.slice(0, -1), { ...cur[cur.length - 1], text: shown }] : cur));
  };

  const end = () => {
    clearFade();
    if (phaseRef.current !== "live") return;
    // 把尚未 flush 的尾巴写进当前行，虚化前看到最后一句
    const tail = bufRef.current.text;
    if (tail) setLines(cur => (cur.length ? [...cur.slice(0, -1), { ...cur[cur.length - 1], text: tail }] : cur));
    setBothPhases("faded");
    fadeTimer.current = window.setTimeout(() => {
      fadeTimer.current = null;
      setLines([]);
      setBothPhases("idle");
      speedRef.current = 0;
    }, FADE_MS);
  };

  return { lines, phase, speedRef, begin, pushLabel, appendText, end };
}

interface Props {
  tracker: ThinkingTracker;
}

export default function ThinkingTicker({ tracker }: Props) {
  const { lines, phase, speedRef } = tracker;
  const trackRef = useRef<HTMLDivElement>(null);
  const offsetRef = useRef(0);

  // 行高固定（单行省略），复制一份列表实现无缝循环；rAF 按生成速度推进位移。
  useEffect(() => {
    if (phase !== "live" || lines.length <= 1) return;
    offsetRef.current = 0;
    let raf = 0;
    let last = performance.now();
    const step = (t: number) => {
      const dt = Math.min(0.1, (t - last) / 1000);
      last = t;
      const el = trackRef.current;
      if (el) {
        const half = el.scrollHeight / 2;
        // 滚动速度与执行速度相关联：生成快 → 滚得快（并夹在 14～100 px/s 之间）
        const pxPerSec = 14 + Math.min(86, speedRef.current * 0.35);
        offsetRef.current += pxPerSec * dt;
        if (half > 0 && offsetRef.current >= half) offsetRef.current -= half;
        el.style.transform = `translateY(${-offsetRef.current}px)`;
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [phase, lines.length, speedRef]);

  if (phase === "idle" || lines.length === 0) return null;
  const current = lines[lines.length - 1];
  const looping = lines.length > 1;
  const renderLines = looping ? [...lines, ...lines] : lines;

  return (
    <div className={`thinking-ticker ${phase}`} aria-hidden={phase === "faded"}>
      <div className="tt-head">
        <span className={`tt-spin ${phase === "live" ? "on" : ""}`} aria-hidden />
        <b className="tt-label">{current.label}</b>
        {current.text && <span className="tt-preview">…{current.text.slice(-46)}</span>}
      </div>
      <div className="tt-window">
        <div className="tt-track" ref={trackRef}>
          {renderLines.map((l, i) => (
            <div className="tt-line" key={`${l.id}-${i}`}>
              <em>{l.label}</em>
              {l.text && <span className="tt-line-text">{l.text}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
