import { ChevronDown } from 'lucide-react'
import { ReactNode, useState } from 'react'

export function List({ children, label }: { children: ReactNode; label?: string }) {
  return <ul className="ui-list" aria-label={label}>{children}</ul>
}

// One line per entry: a short tag, the title, a few words of context, and at most one action that is always visible.
// Anything longer (detail, edit, delete) goes in `children` and opens when the row is clicked; such a row shows a small
// arrow so the person can tell it opens.
export function ListRow({ tag, title, meta, action, children }: { tag?: ReactNode; title: string; meta?: string; action?: ReactNode; children?: ReactNode }) {
  const [open, setOpen] = useState(false)
  const line = <>{tag}<span className="ui-row-title">{title}{meta && <small> · {meta}</small>}</span></>
  return (
    <li className={open ? 'ui-row ui-row-open' : 'ui-row'}>
      <div className="ui-row-line">
        {children ? <button type="button" className="ui-row-main" aria-expanded={open} onClick={() => setOpen(!open)}>{line}<ChevronDown className="ui-row-arrow" size={14} aria-hidden="true" /></button> : <div className="ui-row-main">{line}</div>}
        {action}
      </div>
      {open && <div className="ui-row-more">{children}</div>}
    </li>
  )
}
