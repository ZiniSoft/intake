import { CircleHelp } from 'lucide-react'
import { useId } from 'react'

// A "?" that explains a rule of the screen. One sentence, or several points shown as a list: never a long paragraph.
export function HelpTip({ label, content }: { label: string; content: string | string[] }) {
  const id = useId()
  return (
    <span className="ui-help">
      <button type="button" aria-label={label} aria-describedby={id}><CircleHelp size={16} /></button>
      <span className="ui-help-tip" id={id} role="tooltip">
        {Array.isArray(content) ? content.map((point) => <span className="ui-help-point" key={point}>{point}</span>) : content}
      </span>
    </span>
  )
}
