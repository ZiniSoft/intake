import { ArrowLeft, Inbox } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Request, RequestStatus, useStore } from '../app/store'
import { MessageKey, useFormat, useI18n } from '../i18n'
import { PageHeader } from '../shell'
import { Button, ConfirmDialog, EmptyState, FilterBar, LinkButton, List, ListRow, Notice, Panel, SearchInput, Select, StatCard, Status, Step, Steps, Tone } from '../ui'

const statusTone: Record<RequestStatus, Tone> = { new: 'info', waiting: 'warn', approved: 'good', rejected: 'neutral' }
const statusLabel: Record<RequestStatus, MessageKey> = { new: 'requests.statusNew', waiting: 'requests.statusWaiting', approved: 'requests.statusApproved', rejected: 'requests.statusRejected' }
const statTone: Record<RequestStatus, 'info' | 'warn' | 'good' | 'neutral'> = { new: 'info', waiting: 'warn', approved: 'good', rejected: 'neutral' }
const statuses: RequestStatus[] = ['waiting', 'new', 'approved', 'rejected']

// Pattern: a list. Numbers on top that also filter, one filter bar, then one line per record.
// The filter lives in the address, so a filtered list can be bookmarked and shared.
export function RequestsPage() {
  const { t } = useI18n()
  const format = useFormat()
  const { requests } = useStore()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const status = statuses.find((value) => value === params.get('status'))
  const search = params.get('q') || ''
  const change = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value); else next.delete(key)
    setParams(next, { replace: true })
  }
  const shown = requests.filter((request) => (!status || request.status === status) && `${request.code} ${request.title}`.toLowerCase().includes(search.trim().toLowerCase()))
  return (
    <div className="page-stack">
      <PageHeader title={t('requests.title')} help={t('requests.help')} />
      <div className="stat-grid">
        {statuses.map((value) => (
          <StatCard key={value} tone={statTone[value]} label={t(statusLabel[value])} value={requests.filter((request) => request.status === value).length}
            active={status === value} onClick={() => change('status', status === value ? '' : value)} />
        ))}
      </div>
      <FilterBar count={t('requests.count', { count: shown.length })}>
        <SearchInput label={t('requests.search')} value={search} onChange={(e) => change('q', e.target.value)} />
        <Select aria-label={t('requests.filterStatus')} value={status || ''} onChange={(e) => change('status', e.target.value)}>
          <option value="">{t('requests.allStatuses')}</option>
          {statuses.map((value) => <option key={value} value={value}>{t(statusLabel[value])}</option>)}
        </Select>
      </FilterBar>
      <Panel flush>
        {shown.length === 0 ? (
          <EmptyState icon={<Inbox size={20} />} title={t('requests.empty')} text={t('requests.emptyText')} action={<Button onClick={() => setParams({}, { replace: true })}>{t('requests.clearFilters')}</Button>} />
        ) : (
          <List label={t('requests.title')}>
            {shown.map((request) => (
              <ListRow key={request.id} tag={<Status tone={statusTone[request.status]}>{t(statusLabel[request.status])}</Status>} title={request.title}
                meta={`${request.code} · ${request.project} · ${format.dateTime(request.receivedAt)}`}
                action={<Button size="sm" onClick={() => navigate(`/requests/${request.id}`)}>{t('requests.open')}</Button>} />
            ))}
          </List>
        )}
      </Panel>
    </div>
  )
}

// Pattern: a detail page. Where the record stands, the source next to what was made of it, and the decision at the end.
export function RequestDetailPage() {
  const { t } = useI18n()
  const format = useFormat()
  const { id } = useParams()
  const { requests, decide } = useStore()
  const [rejecting, setRejecting] = useState(false)
  const request = requests.find((entry) => entry.id === id)
  if (!request) return <EmptyState icon={<Inbox size={20} />} title={t('requests.notFound')} text={t('requests.notFoundText')} action={<LinkButton to="/requests">{t('requests.back')}</LinkButton>} />
  return (
    <div className="page-stack">
      <PageHeader title={request.code} action={request.status === 'waiting' ? (
        <><Button variant="danger" onClick={() => setRejecting(true)}>{t('requests.reject')}</Button><Button variant="primary" onClick={() => decide(request.id, 'approved')}>{t('requests.approve')}</Button></>
      ) : undefined} />
      <Link className="page-link" to="/requests"><ArrowLeft size={14} /> {t('requests.back')}</Link>
      <header className="detail-head"><h2>{request.title}</h2><Status tone={statusTone[request.status]}>{t(statusLabel[request.status])}</Status></header>
      {request.status === 'approved' && <Notice tone="good" title={t('requests.approvedNotice')}>{t('requests.approvedNoticeText')}</Notice>}
      <Panel><Steps label={t('requests.stepsLabel')} steps={stepsOf(request, t, format.dateTime)} /></Panel>
      <div className="detail-compare">
        <Panel title={t('requests.original')} action={<Status>{request.from}</Status>}><p className="detail-text">{request.original}</p></Panel>
        <Panel title={t('requests.summary')}>{request.summary ? <p className="detail-text">{request.summary}</p> : <p className="detail-muted">{t('requests.summaryMissing')}</p>}</Panel>
      </div>
      <ConfirmDialog open={rejecting} danger title={t('requests.rejectTitle', { code: request.code })} text={t('requests.rejectText')} confirmLabel={t('requests.reject')} cancelLabel={t('common.cancel')}
        onConfirm={() => { decide(request.id, 'rejected'); setRejecting(false) }} onCancel={() => setRejecting(false)} />
    </div>
  )
}

function stepsOf(request: Request, t: (key: MessageKey, values?: Record<string, string | number>) => string, when: (value: string) => string): Step[] {
  const decided = request.status === 'approved' || request.status === 'rejected'
  return [
    { label: t('requests.stepReceived'), state: 'done', text: `${request.from} · ${when(request.receivedAt)}` },
    { label: t('requests.stepSummarised'), state: request.summary ? 'done' : 'now', text: request.summary ? t('requests.stepSummarisedDone') : t('requests.stepSummarisedWaiting') },
    { label: t('requests.stepDecision'), state: decided ? (request.status === 'approved' ? 'done' : 'skip') : request.summary ? 'now' : 'todo', text: decided ? t(statusLabel[request.status]) : t('requests.stepDecisionWaiting') },
    { label: t('requests.stepAssigned'), state: request.status === 'rejected' ? 'skip' : request.owner && request.status === 'approved' ? 'done' : 'todo', text: request.status === 'rejected' ? t('requests.stepNotApplicable') : request.owner && request.status === 'approved' ? request.owner : t('requests.stepAssignedWaiting') },
  ]
}
