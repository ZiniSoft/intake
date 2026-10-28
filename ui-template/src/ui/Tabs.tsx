// Views of the same subject, switched in place. For moving between different subjects use the sidebar.
export function Tabs<Value extends string>({ items, value, onChange, label }: { items: { value: Value; label: string }[]; value: Value; onChange: (value: Value) => void; label: string }) {
  return (
    <div className="ui-tabs" role="tablist" aria-label={label}>
      {items.map((item) => (
        <button key={item.value} type="button" role="tab" aria-selected={item.value === value} className={item.value === value ? 'active' : undefined} onClick={() => onChange(item.value)}>{item.label}</button>
      ))}
    </div>
  )
}
