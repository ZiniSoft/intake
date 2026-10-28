import { useState } from 'react'
import { useStore } from '../app/store'
import { useI18n } from '../i18n'
import { Button, Notice, Panel, Section, Status } from '../ui'
import { PasswordForm } from './LoginPage'

// Pattern: a settings page as one column of sections. Each section says what it is in a sentence, has one action,
// and opens its form only when asked. A disabled action says why it is disabled.
export function AccountSections() {
  const { t } = useI18n()
  const { session } = useStore()
  const [changing, setChanging] = useState(false)
  const [changed, setChanged] = useState(false)
  const [twoStep, setTwoStep] = useState(false)
  if (!session) return null
  const initials = session.name.split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('')
  return (
    <div className="account">
      <Panel className="account-identity" flush>
        <span className="account-avatar" aria-hidden="true">{initials}</span>
        <div><strong>{session.name}</strong><small>{session.email}</small></div>
        <Status tone={twoStep ? 'good' : 'warn'}>{twoStep ? t('account.twoStepOn') : t('account.twoStepOff')}</Status>
      </Panel>

      <Section title={t('account.password')} text={t('account.passwordText')} action={!changing && <Button onClick={() => { setChanging(true); setChanged(false) }}>{t('account.changePassword')}</Button>}>
        {changed && !changing ? <Notice tone="good" title={t('account.passwordChanged')} /> : null}
        {changing && <><PasswordForm onChanged={() => { setChanging(false); setChanged(true) }} /><Button variant="quiet" onClick={() => setChanging(false)}>{t('common.cancel')}</Button></>}
      </Section>

      <Section title={t('account.twoStep')} text={t('account.twoStepText')} action={<Button variant={twoStep ? 'secondary' : 'primary'} onClick={() => setTwoStep(!twoStep)}>{twoStep ? t('account.twoStepDisable') : t('account.twoStepEnable')}</Button>} />

      <Section title={t('account.recovery')} text={twoStep ? t('account.recoveryText') : t('account.recoveryLocked')} action={<Button disabled={!twoStep}>{t('account.recoveryCreate')}</Button>} />
    </div>
  )
}
