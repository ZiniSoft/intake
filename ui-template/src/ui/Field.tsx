import { Search } from 'lucide-react'
import { createContext, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes, useContext, useId } from 'react'

// The control inside a Field gets its id, its description and its error state from here.
const FieldContext = createContext<{ id?: string; describedBy?: string; invalid?: boolean }>({})

// A label above its control, with an optional hint below and an error that replaces the hint.
// The label is the control's name; the hint or error is its description, so screen readers read them separately.
export function Field({ label, help, error, children }: { label: string; help?: string; error?: string; children: ReactNode }) {
  const id = useId()
  const messageId = `${id}-message`
  const message = error || help
  return (
    <div className={error ? 'ui-field ui-field-error' : 'ui-field'}>
      <label className="ui-field-label" htmlFor={id}>{label}</label>
      <FieldContext.Provider value={{ id, describedBy: message ? messageId : undefined, invalid: Boolean(error) }}>{children}</FieldContext.Provider>
      {message && <small className="ui-field-message" id={messageId} role={error ? 'alert' : undefined}>{message}</small>}
    </div>
  )
}

function useFieldProps(className: string | undefined, base: string) {
  const field = useContext(FieldContext)
  return { id: field.id, 'aria-describedby': field.describedBy, 'aria-invalid': field.invalid || undefined, className: [base, className || ''].filter(Boolean).join(' ') }
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...useFieldProps(props.className, 'ui-input')} {...withoutClass(props)} />
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...useFieldProps(props.className, 'ui-input')} {...withoutClass(props)} />
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea rows={3} {...useFieldProps(props.className, 'ui-input ui-textarea')} {...withoutClass(props)} />
}

function withoutClass<Props extends { className?: string }>(props: Props) {
  const { className: _className, ...rest } = props
  return rest
}

// A search box: an Input with a magnifier. `label` names it for screen readers and is shown as the placeholder.
export function SearchInput({ label, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <span className="ui-search">
      <Search size={15} aria-hidden="true" />
      <input type="search" aria-label={label} placeholder={label} {...props} className="ui-input" />
    </span>
  )
}

// The row above a list that narrows it: a search box and selectors on the left, the number of results on the right.
export function FilterBar({ count, children }: { count: string; children?: ReactNode }) {
  return <div className="ui-panel ui-filter-bar">{children}<span className="ui-filter-count">{count}</span></div>
}
