import { useEffect, useRef, useState } from "react";

interface Props {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  /** 其中哪些来自“获取可用模型”的实时列表（面板里加“实时”角标） */
  discovered?: Set<string>;
  placeholder?: string;
}

/**
 * v0.5.2 模型下拉：替代原生 datalist。
 *
 * datalist 会按输入框现值过滤候选（值填 deepseek-v4-pro 时就只剩它一条）——正是“下拉只有一个”的根因。
 * 这里展开面板永远先列**全部**候选；打开后再输入才做子串收窄（大小写不敏感）；
 * 输入框保持自由文本，手输/自建服务的名字不受任何限制。
 */
export default function ModelSelect({ value, options, onChange, discovered, placeholder }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const shown = query.trim()
    ? options.filter(o => o.toLowerCase().includes(query.trim().toLowerCase()))
    : options;

  return (
    <div className="model-select" ref={box}>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        onChange={e => {
          onChange(e.target.value);
          if (open) setQuery(e.target.value);
        }}
      />
      <button type="button" className="ms-caret" aria-label="展开模型候选" aria-expanded={open}
        onClick={() => {
          if (!open) setQuery(""); // 展开时展示全部，而不是“和现值相同的那一条”
          setOpen(v => !v);
        }}>▾</button>
      {open && (
        <div className="ms-panel" role="listbox">
          {shown.length === 0 && (
            <div className="ms-empty">
              {options.length === 0
                ? "该供应商没有预设候选：可手输，或点“获取可用模型”拉实时列表"
                : "没有匹配项，输入值仍会原样使用"}
            </div>
          )}
          {shown.map(o => (
            <button type="button" key={o} role="option" aria-selected={o === value}
              className={`ms-opt${o === value ? " cur" : ""}`}
              onMouseDown={e => e.preventDefault()}
              onClick={() => { onChange(o); setOpen(false); }}>
              <span>{o}</span>
              {discovered?.has(o) && <em>实时</em>}
              {o === value && <span className="ms-cur">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
