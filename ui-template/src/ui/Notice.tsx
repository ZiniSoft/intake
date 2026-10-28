import { ReactNode } from 'react'

// A message placed next to the thing it is about. title: what happened; children: what it means or what to do.
// Several notices of the same kind are merged into one, listing what they apply to.
export function Notice({ tone = 'info', title, action, children }: { tone?: 'info' | 'good' | 'warn' | 'bad'; title?: string; action?: ReactNode; children?: ReactNode }) {
  return (
    <div className={`ui-notice ui-tone-${tone}`} role={tone === 'bad' ? 'alert' : 'status'}>
      <div>{title && <strong>{title}</strong>}{children && <span>{children}</span>}</div>
      {action}
    </div>
  )
}
