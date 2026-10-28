import { ArrowRight, Inbox, Plus } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { useStore } from '../app/store'
import { MessageKey, useI18n } from '../i18n'
import { PageHeader } from '../shell'
import { Bars, Button, EmptyState, List, ListRow, Panel, StatCard, Status } from '../ui'

// Pattern: the first screen after sign-in. A greeting as the title, the numbers that need a decision,
// the work waiting for this person, and one simple comparison over time. Nothing here is decoration.
export function DashboardPage() {
  const { t } = useI18n()
  const { session, requests } = useStore()
  const navigate = useNavigate()
  const hour = new Date().getHours()
  const greeting: MessageKey = hour < 12 ? 'dashboard.morning' : hour < 18 ? 'dashboard.afternoon' : 'dashboard.evening'
  const count = (status: string) => requests.filter((request) => request.status === status).length
  const waiting = requests.filter((request) => request.status === 'waiting')
  const weeks = [
    { label: t('dashboard.thisWeek'), reviewed: 5, direct: 2 },
    { label: t('dashboard.week', { date: '28/09' }), reviewed: 7, direct: 1 },
    { label: t('dashboard.week', { date: '21/09' }), reviewed: 4, direct: 0 },
  ]
  return (
    <div className="page-stack">
      <PageHeader title={t(greeting, { name: session?.name.split(' ')[0] || '' })} action={<Button variant="primary" icon={<Plus size={16} />} onClick={() => navigate('/requests')}>{t('dashboard.newRequest')}</Button>} />
      <div className="stat-grid">
        <StatCard tone="warn" label={t('dashboard.statWaiting')} value={count('waiting')} hint={t('dashboard.statWaitingHint')} onClick={() => navigate('/requests?status=waiting')} />
        <StatCard tone="info" label={t('dashboard.statNew')} value={count('new')} hint={t('dashboard.statNewHint')} onClick={() => navigate('/requests?status=new')} />
        <StatCard tone="good" label={t('dashboard.statApproved')} value={count('approved')} hint={t('dashboard.statApprovedHint')} onClick={() => navigate('/requests?status=approved')} />
        <StatCard label={t('dashboard.statRejected')} value={count('rejected')} hint={t('dashboard.statRejectedHint')} onClick={() => navigate('/requests?status=rejected')} />
      </div>
      <Panel title={t('dashboard.waitingTitle')} action={<Link className="page-link" to="/requests?status=waiting">{t('dashboard.viewAll')} <ArrowRight size={14} /></Link>} flush>
        {waiting.length === 0 ? <EmptyState icon={<Inbox size={20} />} title={t('dashboard.waitingEmpty')} text={t('dashboard.waitingEmptyText')} /> : (
          <List label={t('dashboard.waitingTitle')}>
            {waiting.map((request) => (
              <ListRow key={request.id} tag={<Status tone="warn">{request.code}</Status>} title={request.title} meta={request.project}
                action={<Button size="sm" onClick={() => navigate(`/requests/${request.id}`)}>{t('dashboard.open')}</Button>} />
            ))}
          </List>
        )}
      </Panel>
      <Panel title={t('dashboard.chartTitle')}>
        <Bars legend={[{ tone: 'ink', label: t('dashboard.chartReviewed') }, { tone: 'accent', label: t('dashboard.chartDirect') }]}
          rows={weeks.map((week) => ({ label: week.label, parts: [{ value: week.reviewed, tone: 'ink' as const }, { value: week.direct, tone: 'accent' as const }], note: t('dashboard.chartNote', { total: week.reviewed + week.direct, direct: week.direct }) }))} />
      </Panel>
    </div>
  )
}
