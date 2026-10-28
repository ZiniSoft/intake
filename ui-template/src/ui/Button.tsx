import { ButtonHTMLAttributes, ReactNode } from 'react'
import { Link } from 'react-router-dom'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  // primary: the one main action of a screen or form. secondary: everything else.
  // danger: removes or rejects something. quiet: a low-key text action inside a row.
  variant?: 'primary' | 'secondary' | 'danger' | 'quiet'
  size?: 'md' | 'sm'
  icon?: ReactNode
}

export function Button({ variant = 'secondary', size = 'md', icon, className, children, type = 'button', ...rest }: ButtonProps) {
  const classes = ['ui-button', `ui-button-${variant}`, size === 'sm' ? 'ui-button-sm' : '', className || ''].filter(Boolean).join(' ')
  return <button type={type} className={classes} {...rest}>{icon}{children}</button>
}

// An icon on its own says nothing to a screen reader, so the label is required.
export function IconButton({ label, children, className, type = 'button', ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return <button type={type} className={['ui-icon-button', className || ''].filter(Boolean).join(' ')} aria-label={label} title={label} {...rest}>{children}</button>
}

// The same look for an action that goes to another page. Use it instead of a button that only navigates.
export function LinkButton({ to, variant = 'secondary', size = 'md', icon, children }: { to: string; variant?: 'primary' | 'secondary'; size?: 'md' | 'sm'; icon?: ReactNode; children: ReactNode }) {
  return <Link to={to} className={['ui-button', `ui-button-${variant}`, size === 'sm' ? 'ui-button-sm' : ''].filter(Boolean).join(' ')}>{icon}{children}</Link>
}
