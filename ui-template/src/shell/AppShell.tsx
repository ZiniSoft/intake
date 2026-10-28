import { Bell, LogOut, Menu, PanelLeft, X } from 'lucide-react'
import { createContext, ReactNode, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useLocation } from 'react-router-dom'
import { brand } from '../brand'
import { MessageKey, useI18n } from '../i18n'
import { HelpTip, IconButton } from '../ui'

export type NavItem = { to: string; label: MessageKey; icon: ReactNode; active?: (pathname: string) => boolean }
export type NavGroup = { label?: MessageKey; items: NavItem[] }
// Something that waits for the signed-in person. urgent: a risk to data or security, shown first and in red.
export type ShellAlert = { id: string; urgent?: boolean; title: string; text: string; to: string }

const COLLAPSED_KEY = 'ui.nav.collapsed'
const Slots = createContext<{ title: HTMLElement | null; action: HTMLElement | null; panel: HTMLElement | null }>({ title: null, action: null, panel: null })

// The frame of every signed-in screen: sidebar on the left, a top bar that stays in view, the page, and a right panel
// that pushes the page aside when a page opens one.
export function AppShell({ groups, foot, user, alerts, onSignOut, children }: {
  groups: NavGroup[]; foot: NavItem[]; user: { name: string; role: string }; alerts: ShellAlert[]; onSignOut: () => void; children: ReactNode
}) {
  const { t, language, setLanguage } = useI18n()
  const { pathname } = useLocation()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSED_KEY) === '1')
  const [menuOpen, setMenuOpen] = useState(false)
  const [title, setTitle] = useState<HTMLElement | null>(null)
  const [action, setAction] = useState<HTMLElement | null>(null)
  const [panel, setPanel] = useState<HTMLElement | null>(null)
  const slots = useMemo(() => ({ title, action, panel }), [title, action, panel])
  useEffect(() => { setMenuOpen(false) }, [pathname])

  const toggleCollapsed = () => {
    localStorage.setItem(COLLAPSED_KEY, collapsed ? '0' : '1')
    setCollapsed(!collapsed)
  }
  const isActive = (item: NavItem) => (item.active ? item.active(pathname) : item.to === '/' ? pathname === '/' : pathname.startsWith(item.to))
  const link = (item: NavItem) => (
    <Link key={item.to} to={item.to} className={isActive(item) ? 'active' : undefined} aria-current={isActive(item) ? 'page' : undefined} title={collapsed ? t(item.label) : undefined}>
      <span className="shell-nav-icon" aria-hidden="true">{item.icon}</span><span className="shell-nav-text">{t(item.label)}</span>
    </Link>
  )
  const initials = user.name.split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('')

  return (
    <div className={collapsed ? 'shell shell-collapsed' : 'shell'}>
      <aside className={menuOpen ? 'shell-sidebar shell-sidebar-open' : 'shell-sidebar'}>
        <div className="shell-brand"><img src={brand.logo} alt="" /><strong className="shell-nav-text">{brand.name}</strong></div>
        <nav aria-label={t('shell.nav')}>
          {groups.map((group, index) => (
            <div className="shell-nav-group" key={group.label ?? index}>
              {group.label && <div className="shell-nav-label shell-nav-text">{t(group.label)}</div>}
              {group.items.map(link)}
            </div>
          ))}
        </nav>
        <div className="shell-foot">
          {foot.map(link)}
          <div className="shell-language shell-nav-text" role="group" aria-label={t('shell.language')}>
            <button type="button" aria-pressed={language === 'vi'} onClick={() => setLanguage('vi')}>Tiếng Việt</button>
            <button type="button" aria-pressed={language === 'en'} onClick={() => setLanguage('en')}>English</button>
          </div>
          <div className="shell-user"><span className="shell-avatar" aria-hidden="true">{initials}</span><span className="shell-nav-text"><strong>{user.name}</strong><small>{user.role}</small></span></div>
          <button type="button" className="shell-sign-out" onClick={onSignOut} title={collapsed ? t('shell.signOut') : undefined}><LogOut size={15} /><span className="shell-nav-text">{t('shell.signOut')}</span></button>
        </div>
      </aside>
      {menuOpen && <button type="button" className="shell-backdrop" onClick={() => setMenuOpen(false)} aria-label={t('shell.closeMenu')} />}
      <div className="shell-content">
        <header className="shell-topbar">
          <IconButton className="shell-menu-button" label={menuOpen ? t('shell.closeMenu') : t('shell.openMenu')} onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? <X size={20} /> : <Menu size={20} />}</IconButton>
          <IconButton className="shell-collapse-button" label={collapsed ? t('shell.expand') : t('shell.collapse')} aria-pressed={collapsed} onClick={toggleCollapsed}><PanelLeft size={17} /></IconButton>
          <div className="shell-title" ref={setTitle} />
          <strong className="shell-title-fallback">{brand.name}</strong>
          <div className="shell-action" ref={setAction} />
          <AlertBell alerts={alerts} />
        </header>
        <div className="shell-body">
          <main className="shell-page"><Slots.Provider value={slots}>{children}</Slots.Provider></main>
          <div className="shell-panel-slot" ref={setPanel} />
        </div>
      </div>
    </div>
  )
}

// Every page starts with one PageHeader. The title, its help and the page's single main action are shown in the top bar.
export function PageHeader({ title, help, action }: { title: string; help?: string | string[]; action?: ReactNode }) {
  const slots = useContext(Slots)
  const { t } = useI18n()
  return (
    <>
      {slots.title && createPortal(<><h1>{title}</h1>{help && <HelpTip label={t('shell.help')} content={help} />}</>, slots.title)}
      {action && slots.action && createPortal(action, slots.action)}
    </>
  )
}

// A form or a detail that belongs to the page but should not cover it. On a wide screen it pushes the page aside;
// on a phone it is a sheet from the bottom. Render it while it should be open.
export function RightPanel({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const slots = useContext(Slots)
  const { t } = useI18n()
  useEffect(() => {
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    document.addEventListener('keydown', escape)
    return () => document.removeEventListener('keydown', escape)
  }, [onClose])
  if (!slots.panel) return null
  return createPortal(
    <aside className="shell-panel" aria-label={title}>
      <header><h2>{title}</h2><IconButton label={t('shell.closePanel')} onClick={onClose}><X size={17} /></IconButton></header>
      <div className="shell-panel-body">{children}</div>
    </aside>,
    slots.panel,
  )
}

function AlertBell({ alerts }: { alerts: ShellAlert[] }) {
  const { t } = useI18n()
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { setOpen(false) }, [pathname])
  useEffect(() => {
    if (!open) return
    const away = (event: MouseEvent) => { if (!box.current?.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', escape) }
  }, [open])
  const ordered = [...alerts].sort((a, b) => Number(Boolean(b.urgent)) - Number(Boolean(a.urgent)))
  const urgent = alerts.some((alert) => alert.urgent)
  return (
    <div className="shell-bell" ref={box}>
      <IconButton label={alerts.length > 0 ? t('shell.alertsCount', { count: alerts.length }) : t('shell.alertsNone')} aria-expanded={open} onClick={() => setOpen(!open)}>
        <Bell size={17} />
        {alerts.length > 0 && <span className={urgent ? 'shell-bell-count urgent' : 'shell-bell-count'}>{alerts.length}</span>}
      </IconButton>
      {open && (
        <div className="shell-bell-menu" role="menu">
          <strong>{t('shell.alerts')}</strong>
          {ordered.length === 0 ? <p>{t('shell.alertsNone')}</p> : ordered.map((alert) => (
            <Link key={alert.id} to={alert.to} role="menuitem" className={alert.urgent ? 'urgent' : undefined}><span>{alert.title}</span><small>{alert.text}</small></Link>
          ))}
        </div>
      )}
    </div>
  )
}
