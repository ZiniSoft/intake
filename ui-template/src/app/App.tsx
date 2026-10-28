import { CalendarOff, House, Inbox, LayoutGrid, Settings } from 'lucide-react'
import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { GalleryPage } from '../gallery/GalleryPage'
import { useI18n } from '../i18n'
import { DashboardPage } from '../pages/DashboardPage'
import { ForcedPasswordPage, LoginPage } from '../pages/LoginPage'
import { RequestDetailPage, RequestsPage } from '../pages/RequestsPage'
import { ProjectWizardPage, SettingsPage } from '../pages/SettingsPage'
import { TimeOffPage } from '../pages/TimeOffPage'
import { AppShell, NavGroup, NavItem, ShellAlert } from '../shell'
import { useStore } from './store'

// What the sidebar shows. A new screen is added here and as a <Route> below.
const groups: NavGroup[] = [
  { items: [
    { to: '/', label: 'nav.overview', icon: <House size={17} /> },
    { to: '/requests', label: 'nav.requests', icon: <Inbox size={17} /> },
    { to: '/time-off', label: 'nav.timeOff', icon: <CalendarOff size={17} /> },
  ] },
  { label: 'nav.groupStandard', items: [{ to: '/gallery', label: 'nav.gallery', icon: <LayoutGrid size={17} /> }] },
]
const foot: NavItem[] = [{ to: '/settings', label: 'nav.settings', icon: <Settings size={17} /> }]

// Everything after sign-in sits inside the frame. Without a session the only screen is sign-in.
function Frame() {
  const { t } = useI18n()
  const { session, signOut, requests } = useStore()
  if (!session) return <Navigate to="/login" replace />
  if (session.mustChangePassword) return <ForcedPasswordPage />
  const waiting = requests.filter((request) => request.status === 'waiting').length
  // The bell lists what waits for this person. Each entry leads to the place where it is dealt with.
  const alerts: ShellAlert[] = [
    ...(waiting > 0 ? [{ id: 'approvals', title: t('dashboard.alertWaiting', { count: waiting }), text: t('dashboard.statWaitingHint'), to: '/requests?status=waiting' }] : []),
    { id: 'two-step', urgent: true, title: t('account.twoStepOff'), text: t('account.twoStepText'), to: '/settings/account' },
  ]
  return (
    <AppShell groups={groups} foot={foot} user={{ name: session.name, role: session.email }} alerts={alerts} onSignOut={signOut}>
      <Outlet />
    </AppShell>
  )
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<Frame />}>
        <Route index element={<DashboardPage />} />
        <Route path="requests" element={<RequestsPage />} />
        <Route path="requests/:id" element={<RequestDetailPage />} />
        <Route path="time-off" element={<TimeOffPage />} />
        <Route path="settings/projects/new" element={<ProjectWizardPage />} />
        <Route path="settings/:tab?" element={<SettingsPage />} />
        <Route path="gallery" element={<GalleryPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
