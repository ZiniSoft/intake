import { ReactNode } from 'react'

// Shown where a list or a result would be. It says why it is empty and what the person can do next.
export function EmptyState({ icon, title, text, action }: { icon: ReactNode; title: string; text: string; action?: ReactNode }) {
  return (
    <div className="ui-empty">
      <span aria-hidden="true">{icon}</span>
      <strong>{title}</strong>
      <p>{text}</p>
      {action}
    </div>
  )
}
