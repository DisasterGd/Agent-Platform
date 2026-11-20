import { useEffect } from "react";

/** 通用确认弹窗状态（resolve 由父组件通过 ref 持有）。 */
export interface ConfirmState {
  title: string;
  message: string;
  danger?: boolean;
  confirmLabel?: string;
  cancelLabel?: string;
}

interface Props {
  state: ConfirmState;
  onClose: (v: boolean) => void;
}

/** 替代 window.confirm 的应用内弹窗：Esc/点遮罩 = 取消。 */
export default function ConfirmDialog({ state, onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-overlay" onClick={() => onClose(false)}>
      <div className="modal confirm-modal" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="modal-head">
          <span className="modal-title">{state.title}</span>
          <button className="modal-close" title="关闭" onClick={() => onClose(false)}>×</button>
        </div>
        <div className="modal-body">
          <p className="confirm-message">{state.message}</p>
          <div className="confirm-actions">
            <button type="button" onClick={() => onClose(false)}>{state.cancelLabel ?? "取消"}</button>
            <button
              type="button"
              autoFocus
              className={state.danger ? "danger" : "primary"}
              onClick={() => onClose(true)}
            >
              {state.confirmLabel ?? (state.danger ? "删除" : "确定")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
