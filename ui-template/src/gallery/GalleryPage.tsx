import { Plus, RefreshCw, Users } from 'lucide-react'
import { ReactNode, useState } from 'react'
import { useI18n } from '../i18n'
import { PageHeader, RightPanel } from '../shell'
import { Bars, Button, ConfirmDialog, EmptyState, Field, FilterBar, IconButton, Input, List, ListRow, Meter, Notice, Panel, SearchInput, Section, Select, StatCard, Status, Steps, Table, Tabs, Textarea, Tone } from '../ui'

// Every component in every state. It is the reference for people and for the visual check: a change that makes this
// page look different is a change to the standard.
export function GalleryPage() {
  const { t } = useI18n()
  const [tab, setTab] = useState<'overview' | 'members' | 'history'>('overview')
  const [confirming, setConfirming] = useState(false)
  const [choice, setChoice] = useState<'yes' | 'no'>()
  const [adding, setAdding] = useState(false)
  const [stat, setStat] = useState<'waiting' | 'new'>('waiting')
  const tones: Tone[] = ['neutral', 'info', 'warn', 'good', 'bad', 'accent']
  const tabs = [
    { value: 'overview' as const, label: t('gallery.tabs.overview') },
    { value: 'members' as const, label: t('gallery.tabs.members') },
    { value: 'history' as const, label: t('gallery.tabs.history') },
  ]
  // Three people on one 8-hour scale: a full day, a short day, and a day planned over its hours.
  const days = [{ name: 'An', total: 8, used: 3 }, { name: 'Bình', total: 4, used: 4 }, { name: 'Chi', total: 6, used: 8 }]

  return (
    <div className="gallery">
      <PageHeader title={t('gallery.title')} help={[t('gallery.help.one'), t('gallery.help.two'), t('gallery.help.three')]} action={<Button variant="primary" icon={<Plus size={16} />}>{t('gallery.action')}</Button>} />

      <Block title={t('gallery.tokens')}>
        <div className="gallery-swatches">
          <Swatches label={t('gallery.tokens.surface')} names={['paper', 'fill', 'hover', 'line', 'copy', 'ink']} />
          <Swatches label={t('gallery.tokens.meaning')} names={['good', 'good-soft', 'warn', 'warn-soft', 'bad', 'bad-soft', 'info', 'info-soft']} />
          <Swatches label={t('gallery.tokens.accent')} names={['accent', 'accent-soft', 'accent-ink']} />
        </div>
        <div className="gallery-type" aria-label={t('gallery.tokens.type')}>
          {['xl', 'lg', 'md', 'sm', 'xs'].map((size) => <p key={size} style={{ fontSize: `var(--text-${size})` }}><code>--text-{size}</code>{t('gallery.tokens.typeSample')}</p>)}
        </div>
      </Block>

      <Block title={t('gallery.buttons')} rule={t('gallery.buttons.rule')}>
        <div className="gallery-row">
          <Button variant="primary">{t('gallery.buttons.primary')}</Button>
          <Button>{t('gallery.buttons.secondary')}</Button>
          <Button variant="danger">{t('gallery.buttons.danger')}</Button>
          <Button icon={<Plus size={16} />}>{t('gallery.buttons.withIcon')}</Button>
          <Button variant="primary" disabled>{t('gallery.buttons.disabled')}</Button>
          <Button size="sm">{t('gallery.buttons.small')}</Button>
          <Button variant="quiet">{t('gallery.buttons.quiet')}</Button>
          <IconButton label={t('gallery.buttons.iconOnly')}><RefreshCw size={17} /></IconButton>
        </div>
      </Block>

      <Block title={t('gallery.fields')}>
        <div className="gallery-fields">
          <Field label={t('gallery.fields.name')} help={t('gallery.fields.nameHelp')}><Input placeholder={t('gallery.fields.namePlaceholder')} /></Field>
          <Field label={t('gallery.fields.email')} error={t('gallery.fields.emailError')}><Input defaultValue="an@congty" /></Field>
          <Field label={t('gallery.fields.kind')}><Select defaultValue="software"><option value="software">{t('gallery.fields.kindSoftware')}</option><option value="content">{t('gallery.fields.kindContent')}</option></Select></Field>
          <Field label={t('gallery.fields.locked')} help={t('gallery.fields.lockedHelp')}><Input defaultValue="PORTAL" disabled /></Field>
          <Field label={t('gallery.fields.note')}><Textarea placeholder={t('gallery.fields.notePlaceholder')} /></Field>
        </div>
      </Block>

      <Block title={t('gallery.status')}>
        <div className="gallery-row">{tones.map((tone) => <Status key={tone} tone={tone}>{t(`gallery.status.${tone}`)}</Status>)}</div>
      </Block>

      <Block title={t('gallery.notices')}>
        <div className="gallery-stack">
          <Notice tone="info" title={t('gallery.notices.infoTitle')}>{t('gallery.notices.infoText')}</Notice>
          <Notice tone="good" title={t('gallery.notices.goodTitle')} />
          <Notice tone="warn" title={t('gallery.notices.warnTitle')} action={<Button size="sm">{t('gallery.notices.warnAction')}</Button>}>{t('gallery.notices.warnText')}</Notice>
          <Notice tone="bad" title={t('gallery.notices.badTitle')} action={<Button size="sm">{t('common.retry')}</Button>}>{t('gallery.notices.badText')}</Notice>
        </div>
      </Block>

      <Block title={t('gallery.list')}>
        <Panel title={t('gallery.list.panelTitle')} action={<Status>{t('gallery.list.count', { count: 3 })}</Status>} flush>
          <List label={t('gallery.list.panelTitle')}>
            <ListRow tag={<Status tone="warn">{t('gallery.list.tagTask')}</Status>} title={t('gallery.list.one')} meta={t('gallery.list.oneMeta')} action={<Button size="sm" icon={<Plus size={13} />}>{t('gallery.list.create')}</Button>}>
              <p>{t('gallery.list.oneDetail')}</p>
              <div className="gallery-row"><Button variant="quiet">{t('common.edit')}</Button><Button variant="quiet">{t('common.delete')}</Button></div>
            </ListRow>
            <ListRow tag={<Status tone="good">{t('gallery.list.tagDecision')}</Status>} title={t('gallery.list.two')}><p>{t('gallery.list.twoDetail')}</p></ListRow>
            <ListRow tag={<Status tone="info">{t('gallery.list.tagQuestion')}</Status>} title={t('gallery.list.three')} />
          </List>
        </Panel>
      </Block>

      <Block title={t('gallery.tabs')}>
        <Tabs label={t('gallery.tabs.label')} items={tabs} value={tab} onChange={setTab} />
        <p className="gallery-note">{t('gallery.tabs.showing', { tab: tabs.find((item) => item.value === tab)?.label || '' })}</p>
      </Block>

      <Block title={t('gallery.empty')}>
        <Panel flush><EmptyState icon={<Users size={20} />} title={t('gallery.empty.title')} text={t('gallery.empty.text')} action={<Button variant="primary" icon={<Plus size={16} />}>{t('gallery.buttons.withIcon')}</Button>} /></Panel>
      </Block>

      <Block title={t('gallery.confirm')}>
        <div className="gallery-row">
          <Button variant="danger" onClick={() => setConfirming(true)}>{t('gallery.confirm.open')}</Button>
          {choice && <span className="gallery-note">{t('gallery.confirm.result', { choice: t(choice === 'yes' ? 'gallery.confirm.chosenYes' : 'gallery.confirm.chosenNo') })}</span>}
        </div>
        <ConfirmDialog open={confirming} danger title={t('gallery.confirm.title')} text={t('gallery.confirm.text')} confirmLabel={t('gallery.confirm.yes')} cancelLabel={t('common.cancel')}
          onConfirm={() => { setChoice('yes'); setConfirming(false) }} onCancel={() => { setChoice('no'); setConfirming(false) }} />
      </Block>

      <Block title={t('gallery.stats')} rule={t('gallery.stats.rule')}>
        <div className="gallery-stats">
          <StatCard tone="warn" label={t('dashboard.statWaiting')} value={2} hint={t('dashboard.statWaitingHint')} active={stat === 'waiting'} onClick={() => setStat('waiting')} />
          <StatCard tone="info" label={t('dashboard.statNew')} value={1} hint={t('dashboard.statNewHint')} active={stat === 'new'} onClick={() => setStat('new')} />
          <StatCard tone="good" label={t('dashboard.statApproved')} value={14} hint={t('dashboard.statApprovedHint')} />
        </div>
      </Block>

      <Block title={t('gallery.filter')} rule={t('gallery.filter.rule')}>
        <div className="gallery-stack">
          <FilterBar count={t('requests.count', { count: 5 })}>
            <SearchInput label={t('requests.search')} />
            <Select aria-label={t('requests.filterStatus')} defaultValue=""><option value="">{t('requests.allStatuses')}</option><option value="waiting">{t('requests.statusWaiting')}</option></Select>
          </FilterBar>
          <FilterBar count={t('requests.count', { count: 1 })} />
        </div>
      </Block>

      <Block title={t('gallery.steps')} rule={t('gallery.steps.rule')}>
        <Panel>
          <Steps label={t('requests.stepsLabel')} steps={[
            { label: t('requests.stepReceived'), state: 'done', text: 'Email · 06/10' },
            { label: t('requests.stepDecision'), state: 'now', text: t('requests.stepDecisionWaiting') },
            { label: t('gallery.steps.skipped'), state: 'skip', text: t('gallery.steps.skippedText') },
            { label: t('requests.stepAssigned'), state: 'todo', text: t('requests.stepAssignedWaiting') },
          ]} />
        </Panel>
      </Block>

      <Block title={t('gallery.table')} rule={t('gallery.table.rule')}>
        <Panel flush>
          <Table label={t('settings.members')} columns={[t('members.name'), t('members.role'), t('members.state'), '']} rows={[
            { key: 'an', cells: ['An Nguyễn', t('members.roleLead'), <Status tone="good">{t('members.active')}</Status>, <Button size="sm">{t('common.edit')}</Button>] },
            { key: 'dung', cells: ['Dũng Phạm', t('members.roleMember'), <Status>{t('members.paused')}</Status>, <Button size="sm">{t('common.edit')}</Button>] },
          ]} />
        </Panel>
      </Block>

      <Block title={t('gallery.bars')} rule={t('gallery.bars.rule')}>
        <Panel>
          <Bars legend={[{ tone: 'ink', label: t('dashboard.chartReviewed') }, { tone: 'accent', label: t('dashboard.chartDirect') }]} rows={[
            { label: t('dashboard.thisWeek'), parts: [{ value: 5, tone: 'ink' }, { value: 2, tone: 'accent' }], note: t('dashboard.chartNote', { total: 7, direct: 2 }) },
            { label: t('dashboard.week', { date: '28/09' }), parts: [{ value: 3, tone: 'ink' }, { value: 0, tone: 'accent' }], note: t('dashboard.chartNote', { total: 3, direct: 0 }) },
          ]} />
        </Panel>
      </Block>

      <Block title={t('gallery.section')} rule={t('gallery.section.rule')}>
        <div className="gallery-stack">
          <Section title={t('account.password')} text={t('account.passwordText')} action={<Button>{t('account.changePassword')}</Button>} />
          <Section title={t('account.recovery')} text={t('account.recoveryLocked')} action={<Button disabled>{t('account.recoveryCreate')}</Button>} />
        </div>
      </Block>

      <Block title={t('gallery.meter')} rule={t('gallery.meter.rule')}>
        <ul className="gallery-meters">
          {days.map((day) => (
            <li key={day.name}>
              <strong>{day.name}</strong>
              <Meter used={day.used} total={day.total} scale={8} label={t('gallery.meter.label', { total: day.total, used: day.used })} />
              <span>{day.used > day.total ? t('gallery.meter.over', { over: day.used - day.total, total: day.total }) : t('gallery.meter.left', { left: day.total - day.used, total: day.total })}</span>
            </li>
          ))}
        </ul>
      </Block>

      <Block title={t('gallery.panel')} rule={t('gallery.panel.rule')}>
        <Button icon={<Plus size={16} />} onClick={() => setAdding(true)}>{t('gallery.panel.open')}</Button>
        {adding && (
          <RightPanel title={t('gallery.panel.title')} onClose={() => setAdding(false)}>
            <Field label={t('gallery.panel.name')}><Input autoFocus /></Field>
            <Field label={t('gallery.panel.role')}><Select defaultValue="member"><option value="member">{t('gallery.panel.roleMember')}</option><option value="owner">{t('gallery.panel.roleOwner')}</option></Select></Field>
            <Button variant="primary" onClick={() => setAdding(false)}>{t('gallery.panel.submit')}</Button>
          </RightPanel>
        )}
      </Block>
    </div>
  )
}

function Block({ title, rule, children }: { title: string; rule?: string; children: ReactNode }) {
  return (
    <section className="gallery-block">
      <header><h2>{title}</h2>{rule && <p>{rule}</p>}</header>
      {children}
    </section>
  )
}

function Swatches({ label, names }: { label: string; names: string[] }) {
  return (
    <div className="gallery-swatch-group">
      <strong>{label}</strong>
      <ul>{names.map((name) => <li key={name}><span style={{ background: `var(--${name})` }} /><code>--{name}</code></li>)}</ul>
    </div>
  )
}
