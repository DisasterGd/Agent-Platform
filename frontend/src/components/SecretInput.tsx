import { useEffect, useState } from "react";

interface Props {
  /** true=该供应商档案里已有 Key：显示固定长度掩码（长度与真实 Key 无关） */
  hasSaved: boolean;
  /** null=保留服务端现有；字符串=用户即将保存的值（""=清除） */
  value: string | null;
  onChange: (v: string | null) => void;
}

/**
 * v0.5.2 防窥/防复制的 API Key 输入框。
 *
 * - 真实 Key 从不进前端（服务端只回 has_api_key），这里天然无可复制之物；
 * - 已存有 Key 时显示**固定 16 个点**的掩码——不随长度变化，全选复制只会拿到占位文本；
 * - “替换/清除”进入编辑态：粘贴新 Key；留空保存=清除；“取消”=维持保留。
 */
export default function SecretInput({ hasSaved, value, onChange }: Props) {
  const [editing, setEditing] = useState(false);

  // 保存成功后父组件把 value 复位为 null → 退出编辑态，回到掩码视图
  useEffect(() => {
    if (value === null) setEditing(false);
  }, [value]);

  if (hasSaved && value === null && !editing) {
    return (
      <div className="secret-keep">
        <span
          className="secret-mask"
          onCopy={e => { e.preventDefault(); e.clipboardData.setData("text/plain", "（API Key 已隐藏）"); }}
        >••••••••••••••••</span>
        <button type="button" className="secret-act" onClick={() => setEditing(true)}>替换 / 清除</button>
      </div>
    );
  }

  return (
    <div className="secret-edit">
      <input
        type="password"
        autoFocus={editing}
        value={value ?? ""}
        placeholder={hasSaved ? "输入新 Key 即替换；留空保存则清除" : "sk-…"}
        autoComplete="off"
        spellCheck={false}
        onChange={e => onChange(e.target.value)}
      />
      {hasSaved && (
        <button type="button" className="secret-act"
          onClick={() => { setEditing(false); onChange(null); }}>取消</button>
      )}
    </div>
  );
}
