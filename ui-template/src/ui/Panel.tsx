import { ReactNode } from 'react'

// A bordered block of related content. With a title it gets a heading row; `action` sits at the right of that row.
// flush: the content brings its own padding (a list or a table that runs edge to edge).
export function Panel({ title, action, flush, className, children }: { title?: string; action?: ReactNode; flush?: boolean; className?: string; children: ReactNode }) {
  return (
    <section className={['ui-panel', className || ''].filter(Boolean).join(' ')}>
      {title && <header className="ui-panel-head"><h2>{title}</h2>{action}</header>}
      {flush ? children : <div className="ui-panel-body">{children}</div>}
    </section>
  )
}
