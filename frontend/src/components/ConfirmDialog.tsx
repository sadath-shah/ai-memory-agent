import { useEffect, useRef } from "react";

interface Props {
  open: boolean; title: string; body: string; confirmLabel: string; busy?: boolean;
  onConfirm: () => void; onCancel: () => void;
}

/** Native <dialog>: focus trap, Esc and backdrop handled by the browser. */
export function ConfirmDialog({ open, title, body, confirmLabel, busy, onConfirm, onCancel }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className="dialog" aria-labelledby="dlg-title" onCancel={(e) => { e.preventDefault(); onCancel(); }}
      onClick={(e) => { if (e.target === ref.current) onCancel(); }}>
      <h3 id="dlg-title">{title}</h3>
      <p className="muted">This permanently removes only this memory.</p>
      <blockquote>{body}</blockquote>
      <div className="row end">
        <button type="button" className="btn" onClick={onCancel} autoFocus>Cancel</button>
        <button type="button" className="btn btn--danger-solid" onClick={onConfirm} disabled={busy}>{confirmLabel}</button>
      </div>
    </dialog>
  );
}
