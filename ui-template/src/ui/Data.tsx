import { Children, ReactNode } from 'react'
import { Check } from 'lucide-react'

// A number that answers one question, with a few words under it. As a button it filters the list below it.
export function StatCard({ label, value, hint, tone = 'neutral', active, onClick }: { label: string; value: ReactNode; hint?: string; tone?: 'neutral' | 'good' | 'warn' | 'bad' | 'info'; active?: boolean; onClick?: () => void }) {
  const content = <><span>{label}</span><strong>{value}</strong>{hint && <small>{hint}</small>}</>
  const classes = `ui-stat ui-stat-${tone}${active ? ' active' : ''}`
  return onClick ? <button type="button" className={classes} aria-pressed={active} onClick={onClick}>{content}</button> : <div className={classes}>{content}</div>
}

export type Step = { label: string; state: 'done' | 'now' | 'todo' | 'skip'; text?: ReactNode }

// Where something stands on a fixed path. Each step says what happened, not only its name.
export function Steps({ steps, label }: { steps: Step[]; label: string }) {
  return (
    <ol className="ui-steps" aria-label={label}>
      {steps.map((step) => (
        <li key={step.label} className={`ui-step-${step.state}`} aria-current={step.state === 'now' ? 'step' : undefined}>
          <span className="ui-step-dot" aria-hidden="true">{step.state === 'done' ? <Check size={12} /> : null}</span>
          <strong>{step.label}</strong>
          {step.text && <small>{step.text}</small>}
        </li>
      ))}
    </ol>
  )
}

// A plain table for records that are compared column by column. The last column may hold one small action per row.
export function Table({ columns, rows, label }: { columns: string[]; rows: { key: string; cells: ReactNode[] }[]; label: string }) {
  return (
    <div className="ui-table-wrap">
      <table className="ui-table" aria-label={label}>
        <thead><tr>{columns.map((column) => <th key={column} scope="col">{column}</th>)}</tr></thead>
        <tbody>{rows.map((row) => <tr key={row.key}>{row.cells.map((cell, index) => <td key={index}>{cell}</td>)}</tr>)}</tbody>
      </table>
    </div>
  )
}

// Counts compared across a few periods or groups. Every bar is drawn on the scale of the largest one.
export function Bars({ rows, legend }: { rows: { label: string; parts: { value: number; tone: 'ink' | 'accent' }[]; note: string }[]; legend: { tone: 'ink' | 'accent'; label: string }[] }) {
  const most = Math.max(...rows.map((row) => row.parts.reduce((sum, part) => sum + part.value, 0)), 1)
  return (
    <div className="ui-bars">
      <div className="ui-bars-legend">{legend.map((item) => <span key={item.label}><i className={`ui-bars-${item.tone}`} />{item.label}</span>)}</div>
      <ul>
        {rows.map((row) => (
          <li key={row.label}>
            <span>{row.label}</span>
            <div className="ui-bars-track" role="img" aria-label={row.note}>{row.parts.filter((part) => part.value > 0).map((part) => <i key={part.tone} className={`ui-bars-${part.tone}`} style={{ width: `${(part.value / most) * 100}%` }} />)}</div>
            <small>{row.note}</small>
          </li>
        ))}
      </ul>
    </div>
  )
}

// One block of a settings-like page: what it is, one action at the right, and content that appears when needed.
export function Section({ title, text, action, children }: { title: string; text?: string; action?: ReactNode; children?: ReactNode }) {
  return (
    <section className="ui-panel ui-section">
      <header><div><h3>{title}</h3>{text && <p>{text}</p>}</div>{action}</header>
      {Children.toArray(children).length > 0 && <div className="ui-section-body">{children}</div>}
    </section>
  )
}
