import { useEffect, useRef } from 'react'
import { Button } from './Button'

// Asked before anything that removes, rejects or cannot be undone. The text says what will happen, in one or two sentences;
// the confirm button repeats the action ("Xóa dự án"), never just "OK".
export function ConfirmDialog({ open, title, text, confirmLabel, cancelLabel, danger, onConfirm, onCancel }: {
  open: boolean; title: string; text: string; confirmLabel: string; cancelLabel: string; danger?: boolean; onConfirm: () => void; onCancel: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current
    if (!element) return
    if (open && !element.open) element.showModal()
    if (!open && element.open) element.close()
  }, [open])
  return (
    <dialog ref={dialog} className="ui-dialog" onCancel={(event) => { event.preventDefault(); onCancel() }} onClick={(event) => { if (event.target === dialog.current) onCancel() }}>
      <h2>{title}</h2>
      <p>{text}</p>
      <div className="ui-dialog-actions">
        <Button onClick={onCancel} autoFocus>{cancelLabel}</Button>
        <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm}>{confirmLabel}</Button>
      </div>
    </dialog>
  )
}
