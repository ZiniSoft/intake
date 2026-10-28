// How much of something is used. Meters shown together share one `scale`, so a smaller total looks smaller:
// the part beyond `total` is hatched, the used part is the accent colour, and going over turns it red.
export function Meter({ used, total, scale, label }: { used: number; total: number; scale?: number; label: string }) {
  const full = Math.max(scale ?? total, total, used, 1)
  return (
    <div className="ui-meter" role="img" aria-label={label} title={label}>
      {total > 0 && <span className="ui-meter-total" style={{ width: `${(total / full) * 100}%` }} />}
      {used > 0 && <span className={used > total ? 'ui-meter-used ui-meter-over' : 'ui-meter-used'} style={{ width: `${(Math.min(used, full) / full) * 100}%` }} />}
    </div>
  )
}
