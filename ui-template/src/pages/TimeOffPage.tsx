import { CalendarOff, Plus } from 'lucide-react'
import { FormEvent, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { TimeOff, TimeOffStatus, useStore } from '../app/store'
import { MessageKey, useFormat, useI18n } from '../i18n'
import { PageHeader, RightPanel } from '../shell'
import { Button, ConfirmDialog, EmptyState, Field, FilterBar, Input, LinkButton, List, ListRow, Notice, Panel, Select, StatCard, Status, Textarea, Tone } from '../ui'

const statuses: TimeOffStatus[] = ['waiting', 'approved', 'declined']
const statusTone: Record<TimeOffStatus, Tone> = { waiting: 'warn', approved: 'good', declined: 'neutral' }
const statTone: Record<TimeOffStatus, 'warn' | 'good' | 'neutral'> = { waiting: 'warn', approved: 'good', declined: 'neutral' }
const statusLabel: Record<TimeOffStatus, MessageKey> = { waiting: 'timeOff.statusWaiting', approved: 'timeOff.statusApproved', declined: 'timeOff.statusDeclined' }
const doneMessage = { added: 'timeOff.added', approved: 'timeOff.approved', declined: 'timeOff.declined', removed: 'timeOff.removed' } as const

const today = () => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

// Pattern: a list of things to act on, managed in place. Numbers on top that filter, the count, one line per entry
// with its most common action on the line and the others inside the opened row. Adding opens in the right panel;
// declining and deleting ask first; the result is said above the list.
export function TimeOffPage() {
  const { t } = useI18n()
  const format = useFormat()
  const { timeOff, addTimeOff, decideTimeOff, removeTimeOff } = useStore()
  const [params, setParams] = useSearchParams()
  const [adding, setAdding] = useState(false)
  const [asking, setAsking] = useState<{ entry: TimeOff; action: 'decline' | 'remove' } | null>(null)
  const [done, setDone] = useState<{ what: keyof typeof doneMessage; name: string } | null>(null)
  const status = statuses.find((value) => value === params.get('status'))
  const setStatus = (value: string) => setParams(value ? { status: value } : {}, { replace: true })
  const shown = timeOff.filter((entry) => !status || entry.status === status)
  const date = (entry: TimeOff) => format.date(entry.startDate)
  const confirm = () => {
    if (!asking) return
    if (asking.action === 'decline') decideTimeOff(asking.entry.id, 'declined'); else removeTimeOff(asking.entry.id)
    setDone({ what: asking.action === 'decline' ? 'declined' : 'removed', name: asking.entry.member })
    setAsking(null)
  }
  return (
    <div className="page-stack">
      <PageHeader title={t('timeOff.title')} help={[t('timeOff.help.one'), t('timeOff.help.two'), t('timeOff.help.three')]}
        action={<Button variant="primary" icon={<Plus size={16} />} onClick={() => setAdding(true)}>{t('timeOff.add')}</Button>} />
      <div className="stat-grid">
        {statuses.map((value) => (
          <StatCard key={value} tone={statTone[value]} label={t(statusLabel[value])} value={timeOff.filter((entry) => entry.status === value).length}
            active={status === value} onClick={() => setStatus(status === value ? '' : value)} />
        ))}
      </div>
      <FilterBar count={t('timeOff.count', { count: shown.length })} />
      {done && <Notice tone={done.what === 'added' || done.what === 'approved' ? 'good' : 'info'} title={t(doneMessage[done.what], { name: done.name })}>{done.what === 'added' ? t('timeOff.addedText') : undefined}</Notice>}
      <Panel flush>
        {timeOff.length === 0 ? (
          <EmptyState icon={<CalendarOff size={20} />} title={t('timeOff.empty')} text={t('timeOff.emptyText')} action={<Button onClick={() => setAdding(true)}>{t('timeOff.add')}</Button>} />
        ) : shown.length === 0 ? (
          <EmptyState icon={<CalendarOff size={20} />} title={t('timeOff.emptyFilter')} text={t('timeOff.emptyFilterText')} action={<Button onClick={() => setStatus('')}>{t('timeOff.clearFilter')}</Button>} />
        ) : (
          <List label={t('timeOff.title')}>
            {shown.map((entry) => (
              <ListRow key={entry.id} tag={<Status tone={statusTone[entry.status]}>{t(statusLabel[entry.status])}</Status>} title={entry.member}
                meta={t('timeOff.meta', { date: date(entry), count: entry.days })}
                action={entry.status === 'waiting' ? <Button size="sm" onClick={() => { decideTimeOff(entry.id, 'approved'); setDone({ what: 'approved', name: entry.member }) }}>{t('timeOff.approve')}</Button> : undefined}>
                <p>{t('timeOff.reasonLine', { reason: entry.reason })}</p>
                <div className="row-actions">
                  {entry.status === 'waiting' && <Button size="sm" variant="danger" onClick={() => setAsking({ entry, action: 'decline' })}>{t('timeOff.decline')}</Button>}
                  <Button variant="quiet" onClick={() => setAsking({ entry, action: 'remove' })}>{t('common.delete')}</Button>
                </div>
              </ListRow>
            ))}
          </List>
        )}
      </Panel>
      {adding && (
        <RightPanel title={t('timeOff.add')} onClose={() => setAdding(false)}>
          <TimeOffForm onAdded={(entry) => {
            addTimeOff(entry)
            // The new entry waits for approval; a filter on another status would hide it.
            if (status && status !== 'waiting') setStatus('')
            setDone({ what: 'added', name: entry.member })
            setAdding(false)
          }} />
        </RightPanel>
      )}
      <ConfirmDialog open={Boolean(asking)} danger
        title={asking ? t(asking.action === 'decline' ? 'timeOff.declineTitle' : 'timeOff.removeTitle', { name: asking.entry.member, date: date(asking.entry) }) : ''}
        text={t(asking?.action === 'decline' ? 'timeOff.declineText' : 'timeOff.removeText')}
        confirmLabel={t(asking?.action === 'decline' ? 'timeOff.decline' : 'timeOff.remove')} cancelLabel={t('common.cancel')}
        onConfirm={confirm} onCancel={() => setAsking(null)} />
    </div>
  )
}

function TimeOffForm({ onAdded }: { onAdded: (entry: Omit<TimeOff, 'id' | 'status'>) => void }) {
  const { t } = useI18n()
  const { members } = useStore()
  const [member, setMember] = useState('')
  const [startDate, setStartDate] = useState(today)
  const [days, setDays] = useState('1')
  const [reason, setReason] = useState('')
  const [tried, setTried] = useState(false)
  const daysWrong = !/^[1-9]\d*$/.test(days.trim())
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setTried(true)
    if (member && startDate && !daysWrong && reason.trim()) onAdded({ member, startDate, days: Number(days), reason: reason.trim() })
  }
  if (members.length === 0) return <Notice tone="warn" title={t('timeOff.noMembers')} action={<LinkButton size="sm" to="/settings/members">{t('timeOff.openMembers')}</LinkButton>}>{t('timeOff.noMembersText')}</Notice>
  // Errors appear under their field, and only after the first attempt to add.
  return (
    <form className="panel-form" onSubmit={submit} noValidate>
      <Field label={t('timeOff.member')} error={tried && !member ? t('timeOff.memberMissing') : undefined}>
        <Select value={member} onChange={(e) => setMember(e.target.value)} autoFocus>
          <option value="">{t('timeOff.memberChoose')}</option>
          {members.map((entry) => <option key={entry.id} value={entry.name}>{entry.name}</option>)}
        </Select>
      </Field>
      <Field label={t('timeOff.start')} error={tried && !startDate ? t('timeOff.startMissing') : undefined}><Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} /></Field>
      <Field label={t('timeOff.days')} help={t('timeOff.daysHelp')} error={tried && daysWrong ? t('timeOff.daysWrong') : undefined}><Input type="number" min={1} step={1} inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)} /></Field>
      <Field label={t('timeOff.reason')} error={tried && !reason.trim() ? t('timeOff.reasonMissing') : undefined}><Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      <Button variant="primary" type="submit">{t('timeOff.add')}</Button>
    </form>
  )
}
