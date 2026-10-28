import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../app/store'
import { brand } from '../brand'
import { useI18n } from '../i18n'
import { Button, Field, Input, Notice } from '../ui'

// Pattern: a screen before sign-in. One centred column, the brand, one task, one primary button.
export function LoginPage() {
  const { t } = useI18n()
  const { signIn } = useStore()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [wrong, setWrong] = useState(false)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setWrong(false)
    // The delay stands in for the request, so the loading state can be seen.
    window.setTimeout(() => {
      setBusy(false)
      if (signIn(email, password) === 'wrong') setWrong(true)
      else navigate('/')
    }, 500)
  }
  return (
    <main className="auth">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-brand"><img src={brand.logo} alt="" /><strong>{brand.name}</strong></div>
        <h1>{t('login.title')}</h1>
        {wrong && <Notice tone="bad" title={t('login.wrong')}>{t('login.wrongText')}</Notice>}
        <Field label={t('login.email')}><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" autoFocus required /></Field>
        <Field label={t('login.password')}><Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></Field>
        <Button variant="primary" type="submit" disabled={busy}>{busy ? t('login.submitting') : t('login.submit')}</Button>
        <p className="auth-hint">{t('login.sampleHint')}</p>
      </form>
    </main>
  )
}

// Shown instead of the app while the person still uses a password someone else gave them.
export function ForcedPasswordPage() {
  const { t } = useI18n()
  const { setOwnPassword, signOut } = useStore()
  return (
    <main className="auth">
      <div className="auth-card">
        <div className="auth-brand"><img src={brand.logo} alt="" /><strong>{brand.name}</strong></div>
        <h1>{t('password.forcedTitle')}</h1>
        <p>{t('password.forcedText')}</p>
        <PasswordForm onChanged={setOwnPassword} />
        <Button variant="quiet" onClick={signOut}>{t('shell.signOut')}</Button>
      </div>
    </main>
  )
}

export function PasswordForm({ onChanged }: { onChanged: () => void }) {
  const { t } = useI18n()
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const short = next.length > 0 && next.length < 12
  const mismatch = repeat.length > 0 && next !== repeat
  return (
    <form className="auth-fields" onSubmit={(event) => { event.preventDefault(); onChanged() }}>
      <Field label={t('password.new')} help={short ? undefined : t('password.rule')} error={short ? t('password.tooShort') : undefined}><Input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required /></Field>
      <Field label={t('password.repeat')} error={mismatch ? t('password.mismatch') : undefined}><Input type="password" value={repeat} onChange={(e) => setRepeat(e.target.value)} autoComplete="new-password" required /></Field>
      <Button variant="primary" type="submit" disabled={next.length < 12 || next !== repeat}>{t('password.submit')}</Button>
    </form>
  )
}
