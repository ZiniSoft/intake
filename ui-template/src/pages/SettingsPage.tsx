import { Plus, Users } from 'lucide-react'
import { FormEvent, useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { Member, useStore } from '../app/store'
import { useI18n } from '../i18n'
import { PageHeader, RightPanel } from '../shell'
import { Button, ConfirmDialog, EmptyState, Field, Input, LinkButton, Notice, Panel, Select, Status, Steps, Table, Tabs } from '../ui'
import { AccountSections } from './AccountPage'

type Tab = 'projects' | 'members' | 'account'
const tabsInOrder: Tab[] = ['projects', 'members', 'account']

// Pattern: things that are set up rarely live together under Settings, one tab each. The tab is part of the address.
export function SettingsPage() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const { tab } = useParams()
  const current = tabsInOrder.find((value) => value === tab)
  if (!current) return <Navigate to="/settings/projects" replace />
  return (
    <div className="page-stack">
      <PageHeader title={t('settings.title')} />
      <Tabs label={t('settings.title')} value={current} onChange={(value) => navigate(`/settings/${value}`)}
        items={[{ value: 'projects', label: t('settings.projects') }, { value: 'members', label: t('settings.members') }, { value: 'account', label: t('settings.account') }]} />
      {current === 'projects' && <ProjectsTab />}
      {current === 'members' && <MembersTab />}
      {current === 'account' && <AccountSections />}
    </div>
  )
}

function ProjectsTab() {
  const { t } = useI18n()
  const { projects } = useStore()
  return (
    <Panel title={t('settings.projects')} action={<LinkButton variant="primary" to="/settings/projects/new" icon={<Plus size={16} />}>{t('projects.create')}</LinkButton>} flush>
      <Table label={t('settings.projects')} columns={[t('projects.name'), t('projects.code'), t('projects.kind'), t('projects.lead')]}
        rows={projects.map((project) => ({ key: project.id, cells: [project.name, <code>{project.code}</code>, t(project.kind === 'software' ? 'projects.kindSoftware' : 'projects.kindContent'), project.lead] }))} />
    </Panel>
  )
}

// Pattern: a managed list. Add and edit open in the right panel; removing asks first; the result is said where it happened.
function MembersTab() {
  const { t } = useI18n()
  const { members, saveMember, removeMember } = useStore()
  const [editing, setEditing] = useState<Member | 'new' | null>(null)
  const [removing, setRemoving] = useState<Member | null>(null)
  const [saved, setSaved] = useState('')
  return (
    <>
      {saved && <Notice tone="good" title={t('members.saved', { name: saved })} />}
      <Panel title={t('settings.members')} action={<Button variant="primary" icon={<Plus size={16} />} onClick={() => setEditing('new')}>{t('members.add')}</Button>} flush>
        {members.length === 0 ? <EmptyState icon={<Users size={20} />} title={t('members.empty')} text={t('members.emptyText')} /> : (
          <Table label={t('settings.members')} columns={[t('members.name'), t('members.email'), t('members.role'), t('members.state'), '']}
            rows={members.map((member) => ({ key: member.id, cells: [
              member.name, member.email, t(member.role === 'lead' ? 'members.roleLead' : 'members.roleMember'),
              <Status tone={member.active ? 'good' : 'neutral'}>{t(member.active ? 'members.active' : 'members.paused')}</Status>,
              <span className="table-actions"><Button size="sm" onClick={() => setEditing(member)}>{t('common.edit')}</Button><Button size="sm" variant="danger" onClick={() => setRemoving(member)}>{t('common.delete')}</Button></span>,
            ] }))} />
        )}
      </Panel>
      {editing && (
        <RightPanel title={editing === 'new' ? t('members.add') : t('members.editTitle', { name: editing.name })} onClose={() => setEditing(null)}>
          <MemberForm key={editing === 'new' ? 'new' : editing.id} member={editing === 'new' ? undefined : editing} onSaved={(member) => { saveMember(member); setSaved(member.name); setEditing(null) }} />
        </RightPanel>
      )}
      <ConfirmDialog open={Boolean(removing)} danger title={t('members.removeTitle', { name: removing?.name || '' })} text={t('members.removeText')} confirmLabel={t('members.remove')} cancelLabel={t('common.cancel')}
        onConfirm={() => { if (removing) removeMember(removing.id); setRemoving(null) }} onCancel={() => setRemoving(null)} />
    </>
  )
}

function MemberForm({ member, onSaved }: { member?: Member; onSaved: (member: Omit<Member, 'id'> & { id?: string }) => void }) {
  const { t } = useI18n()
  const [name, setName] = useState(member?.name || '')
  const [email, setEmail] = useState(member?.email || '')
  const [role, setRole] = useState<Member['role']>(member?.role || 'member')
  const [active, setActive] = useState(member?.active ?? true)
  const [tried, setTried] = useState(false)
  const emailWrong = !/^\S+@\S+\.\S+$/.test(email)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setTried(true)
    if (name.trim() && !emailWrong) onSaved({ id: member?.id, name: name.trim(), email: email.trim(), role, active })
  }
  // Errors appear under their field, and only after the first attempt to save.
  return (
    <form className="panel-form" onSubmit={submit} noValidate>
      <Field label={t('members.name')} error={tried && !name.trim() ? t('members.nameMissing') : undefined}><Input value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
      <Field label={t('members.email')} help={t('members.emailHelp')} error={tried && emailWrong ? t('members.emailWrong') : undefined}><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
      <Field label={t('members.role')}><Select value={role} onChange={(e) => setRole(e.target.value as Member['role'])}><option value="member">{t('members.roleMember')}</option><option value="lead">{t('members.roleLead')}</option></Select></Field>
      <Field label={t('members.state')}><Select value={active ? 'active' : 'paused'} onChange={(e) => setActive(e.target.value === 'active')}><option value="active">{t('members.active')}</option><option value="paused">{t('members.paused')}</option></Select></Field>
      <Button variant="primary" type="submit">{member ? t('common.save') : t('members.addSubmit')}</Button>
    </form>
  )
}

// Pattern: a task with several decisions is split into steps. The person always sees where they are,
// can go back without losing anything, and reviews everything before the step that cannot be undone.
export function ProjectWizardPage() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const { members, addProject } = useStore()
  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [kind, setKind] = useState<'software' | 'content'>('software')
  const [lead, setLead] = useState('')
  const leads = members.filter((member) => member.active)
  const codeWrong = code.length > 0 && !/^[A-Z]{3}$/.test(code)
  const ready = [Boolean(name.trim()) && /^[A-Z]{3}$/.test(code), Boolean(lead), true][step]
  const state = (index: number) => (index < step ? 'done' as const : index === step ? 'now' as const : 'todo' as const)
  return (
    <div className="page-stack wizard">
      <PageHeader title={t('projects.create')} />
      <Panel>
        <Steps label={t('projects.create')} steps={[
          { label: t('wizard.stepBasics'), state: state(0), text: name || undefined },
          { label: t('wizard.stepLead'), state: state(1), text: lead || undefined },
          { label: t('wizard.stepReview'), state: state(2) },
        ]} />
      </Panel>
      <Panel>
        <div className="panel-form">
          {step === 0 && <>
            <Field label={t('projects.name')}><Input value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
            <Field label={t('projects.code')} help={t('wizard.codeHelp')} error={codeWrong ? t('wizard.codeWrong') : undefined}><Input value={code} onChange={(e) => setCode(e.target.value.toUpperCase().slice(0, 3))} /></Field>
            <Field label={t('projects.kind')}><Select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}><option value="software">{t('projects.kindSoftware')}</option><option value="content">{t('projects.kindContent')}</option></Select></Field>
          </>}
          {step === 1 && <Field label={t('projects.lead')} help={t('wizard.leadHelp')}><Select value={lead} onChange={(e) => setLead(e.target.value)}><option value="">{t('wizard.leadChoose')}</option>{leads.map((member) => <option key={member.id} value={member.name}>{member.name}</option>)}</Select></Field>}
          {step === 2 && <dl className="wizard-review">
            <dt>{t('projects.name')}</dt><dd>{name}</dd>
            <dt>{t('projects.code')}</dt><dd><code>{code}</code></dd>
            <dt>{t('projects.kind')}</dt><dd>{t(kind === 'software' ? 'projects.kindSoftware' : 'projects.kindContent')}</dd>
            <dt>{t('projects.lead')}</dt><dd>{lead}</dd>
          </dl>}
          <div className="wizard-actions">
            {step === 0 ? <Button onClick={() => navigate('/settings/projects')}>{t('common.cancel')}</Button> : <Button onClick={() => setStep(step - 1)}>{t('wizard.back')}</Button>}
            {step < 2 ? <Button variant="primary" disabled={!ready} onClick={() => setStep(step + 1)}>{t('wizard.next')}</Button>
              : <Button variant="primary" onClick={() => { addProject({ name: name.trim(), code, kind, lead }); navigate('/settings/projects') }}>{t('projects.create')}</Button>}
          </div>
        </div>
      </Panel>
    </div>
  )
}
