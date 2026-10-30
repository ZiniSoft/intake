import {
  createContext,
  DragEvent,
  FormEvent,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { createPortal } from 'react-dom'
import {
  Link,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useOutletContext,
  useParams,
  useSearchParams,
} from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  ArrowUpRight,
  Bell,
  CalendarClock,
  BadgeCheck,
  CalendarDays,
  CalendarRange,
  Check,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  CircleCheck,
  CircleHelp,
  Info,
  ListChecks,
  Terminal,
  ClipboardCheck,
  Columns3,
  Copy,
  Download,
  Eye,
  FileText,
  House,
  Inbox,
  Lightbulb,
  Link2,
  List,
  Lock,
  LogOut,
  Menu,
  MessagesSquare,
  MessageSquarePlus,
  Mic,
  Moon,
  PanelLeft,
  Paperclip,
  Pencil,
  Plus,
  RotateCcw,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Star,
  Sun,
  Trash2,
  TriangleAlert,
  Settings,
  UserRound,
  Rocket,
  Timer,
  History,
  GripVertical,
  X,
} from 'lucide-react'
import { api, ApiError, AUTH_EXPIRED_EVENT, formatError } from './api'
import { clearCursorPagination, readCursorPagination, writeCursorPagination } from './list-url'
import { ALL_HINTS, ALL_INTROS, HINT_PAGES, type HintKey, type PageIntroKey } from './hints'
import { POST_HINT_PAGES } from './hints_posts'
import { useLocale } from './i18n'
import { movePlanningProject, orderPlanningProjects, type PlanningProjectOrder } from './planning-order'
import { addDays, CHANNEL_NAMES, CHANNEL_ORDER, CHANNEL_SHORT, CHANNEL_VERSION_LABELS, dayOfStamp, FORMAT_LABELS, POST_COLUMNS, POST_STATUS_LABELS, POST_WORDS, postColumnOf, stampOf, timeOfStamp, type UiMode } from './words'
import { dismissPendingSync, leaveRecording, resetRecording, resumePendingRecordings, rewriteRecording, startRecording, stopRecording, uploadRecording, usePendingSync, useRecording, type RecordingState } from './recording'
import type { RecordingSource } from './recording'
import type {
  ApprovalDecision,
  ApprovalDecisionPage,
  Channel,
  ConnectorDelivery,
  ConnectorMapping,
  ConnectorSummary,
  ConnectorTry,
  Pillar,
  WatchConnector,
  WatchPlatform,
  WatchSettings,
  WatchTopics,
  Intake,
  IntakePage,
  IntakeSyncSummary,
  IntakeLifecycleStage,
  IntakeStatus,
  OperationsStatus,
  AiProvider,
  AiProviderTest,
  AiRoute,
  PipelineStatus,
  DailyCapacity,
  DayPlans,
  DayPlanProject,
  IntakeAttachment,
  IntakeRaw,
  FeedbackItem,
  EvidenceLink,
  ProjectContext,
  ProjectContextSuggestion,
  MyDay,
  WorkStatus,
  WorkStatusResult,
  DailyReport,
  DailyReportDetail,
  DailyReportItem,
  DailyReportSource,
  GlossaryTerm,
  Meeting,
  MeetingDetail,
  MeetingNoteBulkIntakeOut,
  MeetingNoteWorkOut,
  MeetingPart,
  MeetingNoteItem,
  PlanningAssignment,
  IssueVerification,
  PlanningCandidate,
  AcceptanceItem,
  AcceptanceQueue,
  AcceptanceWorkLog,
  Changelog,
  ChangelogEntry,
  NoIssueReason,
  WeekProject,
  WeekSummary,
  PlanningDay,
  CtoTime,
  PeopleDay,
  PeopleDayPerson,
  PersonalMatrix,
  PersonalTask,
  PersonalWeekBlock,
  TelegramMessageRow,
  TelegramStatus,
  TrackerUsers,
  PlanningOverview,
  PlanningOverviewProject,
  PostDraft,
  PrivateIdea,
  PrivateSpace,
  PrivateVoice,
  PromptPreview,
  DraftChannel,
  DraftTrack,
  DraftContext,
  DraftCommercial,
  PlanSlot,
  PlanTrack,
  PlanWeek,
  PillarKeywords,
  RhythmSlot,
  TrackNote,
  VoiceReference,
  ApiToken,
  VoiceTrial,
  WatchDemand,
  WatchHealth,
  WatchSignal,
  WatchSource,
  VoiceChannel,
  IntakeDetails,
  PlanningRun,
  PlanningWarning,
  PlanningRunSyncStatus,
  PlanningSlot,
  Priority,
  Project,
  Account,
  AgentCommand,
  AgentCommandSheet,
  ProjectMemberAdded,
  ProjectMemberCandidate,
  ProjectMemberRemoved,
  ProjectTeam,
  ApprovalSourceWeek,
  BackupDetail,
  IntakeJourney,
  IntakeWorkLog,
  AgentReadiness,
  MailboxStatus,
  PlanningWorkItem,
  PlanningAddWorkResult,
  ProjectKind,
  SetupState,
  IntegrationProbe,
  GitLabUser,
  RemoteProject,
  RouteTarget,
  SyncStatus,
  User,
  WorkforceMember,
  ChannelRule,
  WorkDetail,
  WorkHistory,
  WorkItem,
  WorkItemStatus,
} from './types'

type AuthContextValue = {
  user: User | null
  loading: boolean
  login: (subject: string, password: string, otp?: string, recoveryCode?: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('Auth context is unavailable')
  return value
}

function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = async () => {
    try {
      setUser(await api<User>('/auth/me'))
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error
      setUser(null)
    }
  }

  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    const expire = () => setUser(null)
    window.addEventListener(AUTH_EXPIRED_EVENT, expire)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, expire)
  }, [])

  const login = async (subject: string, password: string, otp?: string, recoveryCode?: string) => {
    await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({
        subject,
        password,
        otp: otp || null,
        recovery_code: recoveryCode || null,
      }),
    })
    await refresh()
  }

  const logout = async () => {
    await api('/auth/logout', { method: 'POST' })
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  )
}

const statusLabels: Record<IntakeStatus, string> = {
  NEW: 'Mới',
  PROCESSING: 'Đang xử lý',
  PENDING_APPROVAL: 'Chờ duyệt',
  NEEDS_INFORMATION: 'Cần làm rõ',
  PROCESSING_FAILED: 'Xử lý lỗi',
  DEFERRED: 'Đã hoãn',
  APPROVED: 'Đã duyệt',
  REJECTED: 'Từ chối',
  SYNC_PENDING: 'Chờ đồng bộ',
  SYNCED: 'Đã đồng bộ',
  CLOSED: 'Đã đóng',
}

const lifecycleLabels: Record<IntakeLifecycleStage, string> = {
  RECEIVED: 'Tiếp nhận',
  NEEDS_INFORMATION: 'Cần làm rõ',
  PENDING_APPROVAL: 'Chờ duyệt',
  WAITING_PLANNING: 'Chờ xếp việc',
  IN_PROGRESS: 'Đang thực hiện',
  PENDING_ACCEPTANCE: 'Chờ nghiệm thu',
  ACCEPTED: 'Đã nghiệm thu',
  STOPPED: 'Đã dừng',
}

const legacyStatusStages: Partial<Record<IntakeStatus, IntakeLifecycleStage>> = {
  NEW: 'RECEIVED', PROCESSING: 'RECEIVED', PROCESSING_FAILED: 'RECEIVED',
  NEEDS_INFORMATION: 'NEEDS_INFORMATION', PENDING_APPROVAL: 'PENDING_APPROVAL',
  APPROVED: 'WAITING_PLANNING', SYNC_PENDING: 'WAITING_PLANNING', SYNCED: 'WAITING_PLANNING',
  REJECTED: 'STOPPED', DEFERRED: 'STOPPED', CLOSED: 'STOPPED',
}

// Order is the order in the channel chip: typed-in first, since that is how most requests arrive at the composer.
const channelLabels: Record<Channel, string> = {
  MANUAL: 'Nhập tay',
  ZALO: 'Zalo',
  AGENT: 'Agent',
  TELEGRAM: 'Telegram',
  FEEDBACK: 'Góp ý',
  WHATSAPP: 'WhatsApp',
  EMAIL: 'Email',
  MEETING: 'Meeting',
}

const channelLabelsEn: Record<Channel, string> = {
  MANUAL: 'Manual',
  ZALO: 'Zalo',
  AGENT: 'Agent',
  TELEGRAM: 'Telegram',
  FEEDBACK: 'Feedback',
  WHATSAPP: 'WhatsApp',
  EMAIL: 'Email',
  MEETING: 'Meeting',
}

const routeLabels: Record<RouteTarget, string> = {
  RESPONSE: 'Phản hồi',
  WORK: 'Việc nội bộ',
  PLANE: 'Plane · lịch sử',
  GITLAB: 'GitLab',
  GITHUB: 'GitHub',
  NEEDS_INFO: 'Cần thêm thông tin',
}

const routeLabelsEn: Record<RouteTarget, string> = {
  RESPONSE: 'Response',
  WORK: 'Internal work',
  PLANE: 'Plane · legacy',
  GITLAB: 'GitLab',
  GITHUB: 'GitHub',
  NEEDS_INFO: 'Needs information',
}

// A plan date (YYYY-MM-DD) as dd/mm, without shifting it through a time zone.
function formatDay(value: string) {
  const [, month, day] = value.slice(0, 10).split('-')
  return `${day}/${month}`
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('vi-VN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function greeting(user: User) {
  const hour = Number(new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Ho_Chi_Minh', hour: '2-digit', hourCycle: 'h23' }).format(new Date()))
  const period = hour < 12 ? 'sáng' : hour < 18 ? 'chiều' : 'tối'
  const displayName = user.display_name?.trim()
  // Seeded accounts carry the email local part as display name; address those by role instead.
  const name = displayName && displayName !== user.email.split('@')[0] ? displayName : user.role
  return `Chào buổi ${period}, ${name}`
}

function todayInPlanningTimezone() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Ho_Chi_Minh',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date())
}

function StatusBadge({ status }: { status: IntakeStatus }) {
  return <span className={`status status-${status.toLowerCase()}`}>{statusLabels[status]}</span>
}

function LifecycleBadge({ stage }: { stage: IntakeLifecycleStage }) {
  return <span className={`status lifecycle lifecycle-${stage.toLowerCase()}`}>{lifecycleLabels[stage]}</span>
}

function PriorityBadge({ priority }: { priority: Priority | null }) {
  return priority ? <span className={`priority priority-${priority.toLowerCase()}`}>{priority}</span> : <span className="muted">—</span>
}

// Where a page puts its title and main action: the two slots of the top bar.
const TopBarSlots = createContext<{ title: HTMLElement | null; action: HTMLElement | null }>({ title: null, action: null })

// The page title, its helper and the page's main action are shown in the top bar, which stays in view while scrolling.
// helper: one sentence, or several points shown as a bulleted list in the tooltip.
function PageHeader({ title, description, helper, action }: { title: string; description?: string; helper?: string | string[]; action?: ReactNode }) {
  const slots = useContext(TopBarSlots)
  return (
    <>
      {slots.title && createPortal(
        <>
          <h1>{title}</h1>
          {helper && (
            <span className="page-helper">
              <button type="button" aria-label="Quy tắc nguồn dữ liệu và phê duyệt" aria-describedby="page-header-helper"><CircleHelp size={16} /></button>
              <span className="page-helper-tooltip" id="page-header-helper" role="tooltip">{Array.isArray(helper) ? helper.map((point) => <span className="page-helper-point" key={point}>{point}</span>) : helper}</span>
            </span>
          )}
        </>,
        slots.title,
      )}
      {action && slots.action && createPortal(action, slots.action)}
      {description && <p className="page-description">{description}</p>}
    </>
  )
}

// Everything that waits for the signed-in person, in one place that is visible on every page.
// Why no scanned post came in, from what the owner can fix here to what the scanner outside must.
const watchReasons: Record<NonNullable<WatchHealth['tracks'][number]['reason']>, string> = {
  ROUTES_CLOSED: 'Chưa đặt khóa trên máy chủ nên công cụ quét không gọi được Intake.',
  NO_SOURCES: 'Mạch này chưa có nguồn nào đang bật.',
  NO_KEYWORDS: 'Chưa trụ nào của mạch có từ khóa để tìm.',
  FLOW_SILENT: 'Công cụ quét không gọi Intake lần nào: có thể nó đã dừng.',
  NOTHING_SENT: 'Công cụ quét vẫn gọi Intake nhưng không gửi bài nào.',
}

function AlertBell() {
  const { user } = useAuth()
  const { pathname } = useLocation()
  const isCto = user?.role === 'CTO'
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const intakes = useQuery({ queryKey: ['alert-intakes'], queryFn: () => api<IntakePage>('/intakes?limit=1'), refetchInterval: 60000 })
  const reports = useQuery({ queryKey: ['daily-reports'], queryFn: () => api<DailyReport[]>('/reports/daily'), refetchInterval: 120000 })
  const operations = useQuery({ queryKey: ['operations'], queryFn: () => api<OperationsStatus>('/operations/status'), enabled: isCto, refetchInterval: 300000 })
  const watch = useQuery({ queryKey: ['watch-health'], queryFn: () => api<WatchHealth>('/private-space/watch/health'), enabled: isCto, refetchInterval: 300000 })
  // The same board the home page shows; one fetch serves both.
  const boardDay = todayInPlanningTimezone()
  const board = useQuery({ queryKey: ['planning-overview', boardDay], queryFn: () => api<PlanningOverview>(`/planning/overview/${boardDay}`), staleTime: 60_000, refetchInterval: 120000 })
  useEffect(() => { setOpen(false) }, [pathname])
  useEffect(() => {
    if (!open) return
    const away = (event: MouseEvent) => { if (!box.current?.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', escape) }
  }, [open])

  // A count that cannot be read is no reason to break the whole screen.
  const pending = intakes.data?.summary?.pending_approval || 0
  const approvedList = useQuery({ queryKey: ['intakes', 'today-approved'], queryFn: () => api<IntakePage>('/intakes?limit=100&status=APPROVED'), refetchInterval: 120000 })
  const unsynced = (approvedList.data?.items || []).filter((item) => SYNCABLE_ROUTES.includes(item.approved_route || '') && !item.sync_targets.some((target) => target.status === 'SUCCEEDED' && !target.superseded)).length
  const unread = reportsToConfirm(reports.data)
  const backup = operations.data?.backup_detail
  const overdueTotal = board.data?.overdue_total || 0
  const ctoShare = (board.data?.projects || []).reduce((sum, row) => sum + row.approvals.cto, 0)
  const poShare = (board.data?.projects || []).reduce((sum, row) => sum + row.approvals.po, 0)
  const alerts: { key: string; urgent: boolean; icon: ReactNode; title: string; text: string; to: string }[] = [
    ...(backup && backup.state !== 'healthy' ? [{ key: 'backup', urgent: true, icon: <TriangleAlert size={15} />, title: 'Dữ liệu chưa được sao lưu trong 24 giờ qua', text: backupSummary(backup), to: '/settings/system' }] : []),
    ...(isCto && user && !user.mfa_enabled ? [{ key: 'mfa', urgent: true, icon: <ShieldCheck size={15} />, title: 'Tài khoản CTO chưa bật xác thực hai lớp', text: 'Tài khoản này xem được nội dung gốc và phê duyệt mọi dự án; hiện chỉ có mật khẩu bảo vệ.', to: '/settings/account' }] : []),
    ...(watch.data?.tracks || []).filter((track) => track.warning).map((track) => ({
      key: `watch-${track.track}`, urgent: false, icon: <Eye size={15} />,
      title: `Mạch ${track.name}: ${watch.data!.check_hours} giờ qua chưa có bài quét về`,
      text: `${watchReasons[track.reason || 'NOTHING_SENT']} Còn thiếu ${track.remaining}/${track.wanted_per_week}${track.deadline ? `, hạn ${formatMoment(track.deadline)}` : ''}.`,
      to: '/rieng/nguon',
    })),
    ...(overdueTotal > 0 ? [{ key: 'overdue', urgent: false, icon: <TriangleAlert size={15} />, title: `${overdueTotal} việc chờ quá hạn`, text: overdueText(board.data!), to: '/' }] : []),
    ...(isCto && board.data ? (ctoShare > 0 ? [{ key: 'approvals', urgent: false, icon: <ClipboardCheck size={15} />, title: `${ctoShare} yêu cầu chờ anh duyệt`, text: poShare > 0 ? `${poShare} yêu cầu khác thuộc Project Owner.` : 'P0/P1, dự án chưa có Project Owner, hoặc chờ quá một ngày.', to: '/approvals' }] : []) : pending > 0 ? [{ key: 'approvals', urgent: false, icon: <ClipboardCheck size={15} />, title: `${pending} yêu cầu chờ phê duyệt`, text: 'Quyết định có làm không, ưu tiên nào, đi đâu.', to: '/approvals' }] : []),
    ...(unsynced > 0 ? [{ key: 'unsynced', urgent: false, icon: <ArrowUpRight size={15} />, title: `${unsynced} yêu cầu đã duyệt chưa đồng bộ`, text: 'Chưa có Issue nên chưa xếp được vào kế hoạch.', to: '/intakes?status=APPROVED' }] : []),
    ...(unread > 0 ? [{ key: 'reports', urgent: false, icon: <FileText size={15} />, title: `${unread} báo cáo do AI đọc chờ xác nhận`, text: 'Task trong các báo cáo này chưa được dùng cho kế hoạch.', to: '/reports' }] : []),
  ]
  const urgent = alerts.some((alert) => alert.urgent)
  return (
    <div className="alert-bell" ref={box}>
      <button type="button" className="icon-button" aria-label={alerts.length > 0 ? `Việc cần chú ý: ${alerts.length}` : 'Không có việc cần chú ý'} aria-expanded={open} onClick={() => setOpen(!open)}>
        <Bell size={17} />
        {alerts.length > 0 && <span className={urgent ? 'alert-count urgent' : 'alert-count'}>{alerts.length}</span>}
      </button>
      {open && (
        <div className="alert-menu" role="menu">
          <header><strong>Việc cần chú ý</strong>{alerts.length > 0 && <span>{alerts.length}</span>}</header>
          {alerts.length === 0 ? <p><CircleCheck size={16} aria-hidden="true" /> Không có việc nào đang chờ bạn.</p> : alerts.map((alert) => (
            <Link key={alert.key} to={alert.to} role="menuitem" className={alert.urgent ? 'urgent' : undefined}>
              <span className="alert-icon" aria-hidden="true">{alert.icon}</span>
              <span className="alert-text"><strong>{alert.title}</strong><small>{alert.text}</small></span>
              <ChevronRight size={15} aria-hidden="true" />
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

// A question asked in the middle of the screen before something that cannot be undone.
function ConfirmDialog({ title, children, confirmLabel, busyLabel = 'Đang xóa…', busy, confirmDisabled, error, plain, onConfirm, onCancel }: {
  title: string; children: ReactNode; confirmLabel: string; busyLabel?: string; busy?: boolean; confirmDisabled?: boolean; error?: unknown
  // `plain` is for a step that changes things but destroys nothing.
  plain?: boolean; onConfirm: () => void; onCancel: () => void
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busy) onCancel() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [busy, onCancel])
  return createPortal(
    <div className="confirm-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onCancel() }}>
      <div className="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-text">
        <span className={plain ? 'confirm-icon is-plain' : 'confirm-icon'} aria-hidden="true">{plain ? <CircleHelp size={18} /> : <Trash2 size={18} />}</span>
        <h2 id="confirm-title">{title}</h2>
        <div id="confirm-text" className="confirm-text">{children}</div>
        {error != null && <ErrorNotice error={error} />}
        <div className="confirm-actions">
          <button type="button" className="button button-secondary" autoFocus disabled={busy} onClick={onCancel}>Hủy</button>
          <button type="button" className={plain ? 'button button-primary' : 'button button-danger-solid'} disabled={busy || confirmDisabled} onClick={onConfirm}>{busy ? busyLabel : confirmLabel}</button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function ErrorNotice({ error, onRetry, retryLabel = 'Thử lại' }: { error: unknown; onRetry?: () => void; retryLabel?: string }) {
  const requestId = error instanceof ApiError ? error.requestId : undefined
  return (
    <div className="notice notice-error notice-with-action" role="alert">
      <div><strong>{formatError(error)}</strong>{requestId && <small>Request ID: {requestId}</small>}</div>
      {onRetry && <button className="button button-secondary button-small" type="button" onClick={onRetry}>{retryLabel}</button>}
    </div>
  )
}

function LoadingBlock({ label = 'Đang tải dữ liệu…' }: { label?: string }) {
  return <div className="loading-block"><span className="spinner" />{label}</div>
}

function LoginPage() {
  const { user, loading, login } = useAuth()
  const navigate = useNavigate()
  const { text } = useLocale()
  const initialToken = (() => { try { return window.location.hash.startsWith('#reset=') ? decodeURIComponent(window.location.hash.slice(7)) : '' } catch { return '' } })()
  const [mode, setMode] = useState<'login' | 'request' | 'reset'>(initialToken ? 'reset' : 'login')
  const [subject, setSubject] = useState('cto')
  const [password, setPassword] = useState('')
  const [otp, setOtp] = useState('')
  const [recoveryCode, setRecoveryCode] = useState('')
  const [showSecondFactor, setShowSecondFactor] = useState(false)
  const [error, setError] = useState<unknown>()
  const [submitting, setSubmitting] = useState(false)
  const [identifier, setIdentifier] = useState('')
  const [requestMessage, setRequestMessage] = useState('')
  const [resetToken] = useState(initialToken)
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [resetDone, setResetDone] = useState(false)
  const bootstrap = useQuery({ queryKey: ['setup-status'], queryFn: () => api<{ needs_bootstrap: boolean }>('/setup/status'), retry: false })

  if (bootstrap.data?.needs_bootstrap && mode !== 'reset') return <Navigate to="/welcome" replace />
  // A reset link must remain usable even when this browser still carries another (or soon-to-be-revoked) session.
  if (!loading && user && mode !== 'reset') return <Navigate to="/" replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(undefined)
    setSubmitting(true)
    try {
      await login(subject.trim(), password, otp.trim() || undefined, recoveryCode.trim() || undefined)
      navigate('/')
    } catch (requestError) {
      setError(requestError)
      if (requestError instanceof ApiError && requestError.message.toLowerCase().includes('mfa')) {
        setShowSecondFactor(true)
      }
    } finally {
      setSubmitting(false)
    }
  }

  const requestReset = async (event: FormEvent) => {
    event.preventDefault()
    setError(undefined)
    setSubmitting(true)
    try {
      const result = await api<{ accepted: boolean; message: string }>('/auth/password-reset/request', {
        method: 'POST', body: JSON.stringify({ identifier: identifier.trim() }),
      })
      setRequestMessage(result.message)
    } catch (requestError) {
      setError(requestError)
    } finally {
      setSubmitting(false)
    }
  }

  const confirmReset = async (event: FormEvent) => {
    event.preventDefault()
    setError(undefined)
    if (newPassword.length < 12) { setError(new Error(text('Mật khẩu mới phải có ít nhất 12 ký tự.', 'The new password must contain at least 12 characters.'))); return }
    if (newPassword !== confirmPassword) { setError(new Error(text('Hai lần nhập mật khẩu chưa khớp.', 'The passwords do not match.'))); return }
    if (!resetToken) { setError(new Error(text('Link đặt lại mật khẩu không hợp lệ.', 'The password reset link is invalid.'))); return }
    setSubmitting(true)
    try {
      await api('/auth/password-reset/confirm', {
        method: 'POST', body: JSON.stringify({ token: resetToken, new_password: newPassword }),
      })
      window.history.replaceState(null, '', '/login')
      setPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setResetDone(true)
      setMode('login')
    } catch (requestError) {
      setError(requestError)
    } finally {
      setSubmitting(false)
    }
  }

  const backToLogin = () => { setMode('login'); setError(undefined); setRequestMessage('') }

  return (
    <main className="login-page">
      <section className="login-panel">
        <form className="login-form" onSubmit={mode === 'login' ? submit : mode === 'request' ? requestReset : confirmReset}>
          <div className="brand login-brand"><img className="brand-mark" src="/icon.svg" alt="" /><span><strong>Private Intake</strong><small>Private Intake workspace</small></span></div>

          <h1>{mode === 'login' ? text('Đăng nhập không gian làm việc', 'Sign in to your workspace') : mode === 'request' ? text('Quên mật khẩu', 'Forgot password') : text('Đặt mật khẩu mới', 'Set a new password')}</h1>
          {mode === 'request' && <p>{text('Nhập tài khoản hoặc email đã đăng ký. Nếu thông tin khớp, hệ thống sẽ gửi link đặt lại qua Mailgun.', 'Enter your account name or registered email. If it matches, the system will send a reset link through Mailgun.')}</p>}
          {mode === 'reset' && <p>{text('Link chỉ dùng một lần. Mật khẩu mới phải có ít nhất 12 ký tự.', 'The link can be used once. Your new password must contain at least 12 characters.')}</p>}
          {resetDone && mode === 'login' && <div className="notice notice-success" role="status">{text('Đã đặt lại mật khẩu. Bạn có thể đăng nhập bằng mật khẩu mới.', 'Password reset complete. You can now sign in with the new password.')}</div>}
          {error != null && <ErrorNotice error={error} />}
          {mode === 'login' ? (
            <>
              <label>{text('Email hoặc tên tài khoản', 'Email or account name')}<input value={subject} onChange={(e) => setSubject(e.target.value)} autoComplete="username" required /></label>
              <label>{text('Mật khẩu', 'Password')}<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
              {showSecondFactor && (
                <div className="second-factor">
                  <label>{text('Mã authenticator', 'Authenticator code')}<input value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" placeholder={text('6 chữ số', '6 digits')} /></label>
                  <div className="or"><span>{text('hoặc', 'or')}</span></div>
                  <label>Recovery code<input value={recoveryCode} onChange={(e) => setRecoveryCode(e.target.value)} placeholder="XXXX-XXXX" /></label>
                </div>
              )}
              <button className="button button-primary button-wide" disabled={submitting}>{submitting ? text('Đang xác thực…', 'Signing in…') : <><ShieldCheck size={16} /> {text('Đăng nhập an toàn', 'Secure sign in')}</>}</button>
              <button type="button" className="text-button login-recovery-link" onClick={() => { setMode('request'); setIdentifier(subject === 'cto' ? '' : subject); setError(undefined); setResetDone(false) }}>{text('Quên mật khẩu?', 'Forgot password?')}</button>
            </>
          ) : mode === 'request' ? (
            <>
              {requestMessage ? <div className="notice notice-success" role="status">{requestMessage}</div> : <label>{text('Tài khoản hoặc email', 'Account or email')}<input value={identifier} onChange={(event) => setIdentifier(event.target.value)} autoComplete="username" required /></label>}
              {!requestMessage && <button className="button button-primary button-wide" disabled={submitting || identifier.trim().length < 3}>{submitting ? text('Đang gửi…', 'Sending…') : text('Gửi link đặt lại mật khẩu', 'Send password reset link')}</button>}
              <button type="button" className="text-button login-recovery-link" onClick={backToLogin}>← {text('Quay lại đăng nhập', 'Back to sign in')}</button>
            </>
          ) : (
            <>
              <label>{text('Mật khẩu mới', 'New password')}<input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" minLength={12} required /></label>
              <label>{text('Nhập lại mật khẩu', 'Confirm password')}<input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" minLength={12} required /></label>
              <button className="button button-primary button-wide" disabled={submitting || !resetToken}>{submitting ? text('Đang đặt lại…', 'Resetting…') : text('Đặt mật khẩu mới', 'Set new password')}</button>
              <button type="button" className="text-button login-recovery-link" onClick={backToLogin}>← {text('Quay lại đăng nhập', 'Back to sign in')}</button>
            </>
          )}
        </form>
        <div className="security-line"><ShieldCheck size={15} aria-hidden="true" /> {text('Kết nối nội bộ · MFA · Human approval', 'Private connection · MFA · Human approval')}</div>
      </section>
    </main>
  )
}

type RightPanel = { title: string; content: ReactNode; onClose: () => void }
type ShellContext = { setRightPanel: (panel: RightPanel | null) => void }

const NAV_COLLAPSED_KEY = 'intake.nav.collapsed'

// Where the sound of a recording is right now, in one short line; nothing when all is well.
function syncLine(recording: RecordingState): { text: string; warn: boolean } | null {
  const { sync, streamLag, streamHealth, phase } = recording
  // The recording's own uploads come first; the live transcript's legs after, since the sound is safe either way.
  const waiting = sync ? Math.max(sync.stored - sync.uploaded, 0) : 0
  if (sync?.failing) return { text: `Đường truyền gián đoạn: ${waiting} đoạn đang giữ trên máy, tự thử lại`, warn: true }
  if (phase === 'stopping' && sync) return { text: `Đang gửi nốt ${waiting} đoạn lên server…`, warn: false }
  // Which leg of the live transcript is slow, in the order the sound travels.
  if (streamLag >= 3) return { text: `Máy này → server chậm: ${streamLag} giây âm thanh đang chờ gửi; bản ghi vẫn giữ trên máy`, warn: true }
  if (streamHealth && streamHealth.clientGapMs >= 2000) return { text: `Âm thanh tới server ngắt quãng (${(streamHealth.clientGapMs / 1000).toFixed(1)} giây): đường máy này → Cloudflare → server`, warn: true }
  if (streamHealth && streamHealth.backlogSeconds >= 3) return { text: `Server → dịch vụ chuyển chữ nghẽn: trễ ${streamHealth.backlogSeconds} giây (đường ra của server)`, warn: true }
  if (streamHealth && streamHealth.providerRttMs !== null && streamHealth.providerRttMs >= 1000) return { text: `Dịch vụ chuyển chữ phản hồi chậm (${streamHealth.providerRttMs} ms)`, warn: true }
  if (waiting >= 2) return { text: `${waiting} đoạn đang chờ lên server`, warn: false }
  return null
}

// Sound this browser still owes the server from an earlier meeting: it goes up on its own; this says so.
function PendingRecordings() {
  const pending = usePendingSync()
  useEffect(() => { void resumePendingRecordings() }, [])
  if (pending.meetings > 0) {
    return (
      <div className={pending.failing ? 'recording-indicator is-pending is-failing' : 'recording-indicator is-pending'} role="status">
        <span className="recording-dot" aria-hidden="true" />
        <span>{pending.failing ? 'Chưa gửi được bản ghi cũ lên server, đang thử lại' : 'Đang gửi nốt bản ghi cũ lên server'}{pending.chunks > 0 ? ` · ${pending.chunks} đoạn` : ''}</span>
      </div>
    )
  }
  if (pending.finished) {
    return (
      <div className="recording-indicator is-done" role="status">
        <CircleCheck size={15} aria-hidden="true" />
        <Link to={`/meetings?id=${pending.finished}`} onClick={dismissPendingSync}>Bản ghi cũ đã lên đủ · mở bản ghi</Link>
        <button type="button" className="icon-button" aria-label="Ẩn thông báo" onClick={dismissPendingSync}><X size={14} /></button>
      </div>
    )
  }
  return null
}

// A meeting being recorded follows the person around the app: where they are, how long it has run, and a way to end it.
function RecordingIndicator() {
  const recording = useRecording()
  const { pathname, search } = useLocation()
  const active = recording.phase === 'starting' || recording.phase === 'recording' || recording.phase === 'stopping'
  // The composer with its recording panel open already shows the transcript and the clock; anywhere else, including
  // the composer being used for a different request while the meeting goes on, the top bar carries them.
  const onRecordPanel = pathname === '/intakes/new' && new URLSearchParams(search).get('panel') === 'record'
  if (recording.kind !== 'MEETING' || onRecordPanel) return null
  if (active) {
    return (
      <div className="recording-indicator" role="status">
        <span className={recording.phase === 'recording' ? 'recording-dot live' : 'recording-dot'} aria-hidden="true" />
        <Link to="/intakes/new?panel=record" title="Mở bản chữ đang ghi">{recording.phase === 'stopping' ? 'Đang lưu bản ghi…' : 'Đang ghi cuộc họp'} <b>{formatClock(recording.elapsed)}</b></Link>
        {syncLine(recording)?.warn && <span className="recording-sync-warn" title={syncLine(recording)?.text}><TriangleAlert size={14} aria-hidden="true" /></span>}
        <button type="button" className="button button-danger button-small" disabled={recording.phase !== 'recording'} onClick={() => { void stopRecording() }}>Kết thúc</button>
      </div>
    )
  }
  if (recording.phase === 'done' && recording.meetingId) {
    return (
      <div className="recording-indicator is-done" role="status">
        <CircleCheck size={15} aria-hidden="true" />
        <Link to={`/meetings?id=${recording.meetingId}`} onClick={() => resetRecording()}>Đã ghi xong cuộc họp · mở bản ghi</Link>
        <button type="button" className="icon-button" aria-label="Ẩn thông báo ghi âm" onClick={() => resetRecording()}><X size={14} /></button>
      </div>
    )
  }
  return null
}

// Reports read by AI that still wait for the CTO, among those recent enough to matter: the day's plan is built from the
// last working day's reports, so one left unconfirmed weeks ago is no longer a thing to do.
const REPORT_WINDOW_DAYS = 3
function reportsWaiting(reports: DailyReport[] | undefined) {
  const since = new Date(Date.now() - REPORT_WINDOW_DAYS * 86400000).toISOString().slice(0, 10)
  return (Array.isArray(reports) ? reports : []).filter((report) => report.parsed_by === 'AI' && !report.review_decision && (report.report_date || report.received_at.slice(0, 10)) >= since)
}
function reportsToConfirm(reports: DailyReport[] | undefined) {
  return reportsWaiting(reports).length
}

// Counts beside the menu entries of the daily work, so the menu itself says where something is waiting.
function NavCount({ kind }: { kind: 'approvals' | 'reports' | 'review' }) {
  const intakes = useQuery({ queryKey: ['alert-intakes'], queryFn: () => api<IntakePage>('/intakes?limit=1'), refetchInterval: 60000, enabled: kind === 'approvals' })
  const reports = useQuery({ queryKey: ['daily-reports'], queryFn: () => api<DailyReport[]>('/reports/daily'), refetchInterval: 120000, enabled: kind === 'reports' })
  const review = useQuery({ queryKey: ['work-review'], queryFn: () => api<WorkItem[]>('/work/review'), refetchInterval: 60000, enabled: kind === 'review' })
  const count = kind === 'approvals'
    ? intakes.data?.summary?.pending_approval || 0
    : kind === 'review' ? (review.data || []).length
    : reportsToConfirm(reports.data)
  const waiting = kind === 'reports' ? reportsWaiting(reports.data) : []
  const title = waiting.length > 0 ? `Chưa xác nhận: ${waiting.map((report) => `${report.member_name || 'ai đó'} ${changelogDay(report.report_date || report.received_at.slice(0, 10))}`).join(', ')}` : undefined
  return count > 0 ? <span className="nav-count" title={title}>{count > 99 ? '99+' : count}</span> : null
}

// Typing without Vietnamese marks still finds the word.
const plainText = (value: string) => value.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'D').toLowerCase()

type QuickResult = { key: string; group: string; label: string; hint?: string; to: string; icon: ReactNode }

// Ctrl+K from anywhere: pages, requests by code or title, meetings by name.
const CHANGELOG_SEEN_KEY = 'intake-changelog-seen'

function readSeen(): string {
  try { return localStorage.getItem(CHANGELOG_SEEN_KEY) || '' } catch { return '' }
}

function changelogDay(value: string) {
  const [year, month, day] = value.split('-')
  return `${day}/${month}/${year}`
}

// One change as the user reads it: the title, what they can see, and the codes for whoever wants the paper trail.
function ChangelogItem({ entry }: { entry: ChangelogEntry }) {
  return (
    <li className="changelog-entry">
      <strong>{entry.title}{entry.cto_only && <span className="status" title="Chỉ CTO thấy phần này">riêng</span>}</strong>
      {entry.bullets.length > 0 && <ul>{entry.bullets.map((line) => <li key={line}>{line}</li>)}</ul>}
      {(entry.refs.length > 0 || entry.commits.length > 0) && <small>{[...entry.refs, ...entry.commits.map((sha) => sha.slice(0, 7))].join(' · ')}</small>}
    </li>
  )
}

function groupByDay(entries: ChangelogEntry[]) {
  const days: { date: string; entries: ChangelogEntry[] }[] = []
  for (const entry of entries) {
    const last = days.at(-1)
    if (last && last.date === entry.date) last.entries.push(entry)
    else days.push({ date: entry.date, entries: [entry] })
  }
  return days
}

// "What's new" in the top bar: a dot while there is a day the person has not looked at, the latest changes in a
// menu, and which build is running so a report of a problem can name it (FR-UI-14).
const PRIVATE_OPEN_KEY = 'intake-nav-private-open'

// A small menu anchored to a top bar button; closes on a click outside or Escape.
function TopMenu({ label, icon, className, children, button }: { label: string; icon: ReactNode; className?: string; children: (close: () => void) => ReactNode; button?: string }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const { pathname } = useLocation()
  useEffect(() => { setOpen(false) }, [pathname])
  useEffect(() => {
    if (!open) return
    const away = (event: MouseEvent) => { if (!box.current?.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', escape) }
  }, [open])
  return (
    <div className={`alert-bell ${className || ''}`} ref={box}>
      <button type="button" className={button || 'icon-button'} aria-label={label} title={label} aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen(!open)}>{icon}</button>
      {open && <div className="alert-menu top-menu" role="menu">{children(() => setOpen(false))}</div>}
    </div>
  )
}

// The two things a person makes here, from any page.
function QuickCreate() {
  return (
    <TopMenu label="Thêm mới" icon={<Plus size={18} />} className="quick-create" button="button button-primary button-small quick-create-button">
      {(close) => (
        <>
          <Link to="/intakes/new" role="menuitem" className="top-menu-item" onClick={close}><Plus size={15} aria-hidden="true" /><span><strong>Tạo Intake</strong><small>Dán tin nhắn, email hay ghi chú của khách</small></span></Link>
          <Link to="/intakes/new?panel=record" role="menuitem" className="top-menu-item" onClick={close}><Mic size={15} aria-hidden="true" /><span><strong>Ghi âm họp</strong><small>Ghi trực tiếp, AI viết note và mục hành động</small></span></Link>
          <Link to="/viec-rieng?them=1" role="menuitem" className="top-menu-item" onClick={close}><ListChecks size={15} aria-hidden="true" /><span><strong>Việc riêng</strong><small>Việc của mình ngoài dự án; chỉ mình thấy, trừ giờ trống</small></span></Link>
        </>
      )}
    </TopMenu>
  )
}

// The commands a person types to their agent (FR-MCP-07): the server's prompts as Claude Code slashes, a Codex
// sentence for each, and when to use it. One list, so the app and the server never disagree.
function useAgentCommands() {
  return useQuery({ queryKey: ['agent-commands'], queryFn: () => api<AgentCommandSheet>('/auth/agent-commands'), staleTime: 5 * 60_000 })
}

function CopyText({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)
  return <button type="button" className="text-button" onClick={() => { void navigator.clipboard.writeText(text).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1500) }) }}>{copied ? 'Đã chép' : label}</button>
}

// The sheet reads differently for a marketing owner: their commands first, the developer's ones left out, and one
// sentence per tool with the project's code filled in (FR-MCP-09).
function marketingSheet(sheet: AgentCommandSheet | undefined, marketing: boolean) {
  if (!sheet) return { commands: [] as AgentCommand[], tools: [] as NonNullable<AgentCommandSheet['marketing']>['tools'] }
  const wanted = sheet.marketing?.commands || []
  if (!marketing) return { commands: sheet.commands, tools: [] }
  return { commands: wanted.map((name) => sheet.commands.find((row) => row.name === name)).filter((row): row is AgentCommand => Boolean(row)), tools: sheet.marketing?.tools || [] }
}

function MarketingToolLines({ tools, projectCode }: { tools: NonNullable<AgentCommandSheet['marketing']>['tools']; projectCode: string }) {
  if (tools.length === 0) return null
  return (
    <ul className="agent-tool-list" aria-label="Câu nhắc cho từng tool">
      {tools.map((row) => {
        const sentence = row.sentence.replace(/\{project\}/g, projectCode || '<mã dự án>')
        return <li key={row.tool}><div><span>{sentence}</span><small>{row.when} · <code>{row.tool}</code></small></div><CopyText text={sentence} label="Chép" /></li>
      })}
    </ul>
  )
}

function AgentCommandsSheet({ onClose }: { onClose: () => void }) {
  const { user } = useAuth()
  const commands = useAgentCommands()
  const marketing = user?.mode === 'MARKETING'
  const view = marketingSheet(commands.data, marketing)
  const projectCode = (user?.projects || []).find((p) => isPostProject(p.kind))?.code || ''
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
  return createPortal(
    <div className="confirm-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <div className="agent-sheet" role="dialog" aria-modal="true" aria-labelledby="agent-sheet-title">
        <header><h2 id="agent-sheet-title">Lệnh cho agent <Hint k="account.commands" /></h2><button type="button" className="icon-button" aria-label="Đóng" onClick={onClose}><X size={18} /></button></header>
        <p className="field-help">Lệnh ngắn dùng trong Claude Code và Codex sau khi cài một lần trên máy (dòng dưới); chưa cài thì trong Claude Code vẫn gõ được dạng dài <code>/mcp__intake__today</code>. Agent gọi Intake với đúng quyền của bạn. Chưa nối thì tạo token ở <Link to="/settings/account" onClick={onClose}>Tài khoản & bảo mật</Link>.</p>
        {commands.data && (() => {
          const url = `${window.location.origin}/api/v1/agent-commands`
          const lines = { bash: `curl -fsSL ${url}/install.sh | bash`, powershell: `irm ${url}/install.ps1 | iex`, repo: `curl -fsSL ${url}/install.sh | bash -s -- --repo <mã dự án>` }
          return (
            <div className="agent-install">
              <div><span>Cài lệnh một lần mỗi máy (bash, macOS hoặc Git Bash)</span><code>{lines.bash}</code><CopyText text={lines.bash} label="Chép" /></div>
              <div><span>Cài lệnh (PowerShell)</span><code>{lines.powershell}</code><CopyText text={lines.powershell} label="Chép" /></div>
              <div><span>Thêm vào repo dự án, kèm /fix-issue và mã dự án</span><code>{lines.repo}</code><CopyText text={lines.repo} label="Chép" /></div>
            </div>
          )
        })()}
        {commands.error != null && <ErrorNotice error={commands.error} />}
        {commands.isLoading ? <LoadingBlock /> : (
          <ul className="agent-command-list">
            {view.commands.map((command) => (
              <li key={command.name}>
                <div className="agent-command-head"><code>{command.slash}</code><CopyText text={command.slash} label="Chép" /></div>
                <strong>{command.description}</strong>
                <small>{command.when}</small>
                <div className="agent-command-codex"><span>Codex: "{command.codex}"</span><CopyText text={command.codex} label="Chép câu nhắc" /></div>
              </li>
            ))}
          </ul>
        )}
        {marketing && view.tools.length > 0 && <><h3 className="agent-sheet-sub">Câu nhắc cho từng tool</h3><MarketingToolLines tools={view.tools} projectCode={projectCode} /></>}
      </div>
    </div>,
    document.body,
  )
}

// On the sources page of a marketing project: the commands and tool sentences with this project's code, to copy.
function MarketingCommandsPanel({ projectCode }: { projectCode: string }) {
  const commands = useAgentCommands()
  const view = marketingSheet(commands.data, true)
  if (commands.isLoading) return null
  return (
    <section className="panel voice-form" aria-label={POST_WORDS.agentCommands}>
      <div className="panel-heading"><div><h2>{POST_WORDS.agentCommands} <Hint k="sources.agent" /></h2><p className="muted">Chép rồi dán vào Claude Code hoặc Codex đã nối Intake; agent gọi với đúng quyền của anh/chị.</p></div></div>
      {commands.error != null && <ErrorNotice error={commands.error} />}
      <ul className="agent-command-list">
        {view.commands.map((command) => (
          <li key={command.name}>
            <div className="agent-command-head"><code>{command.slash}</code><CopyText text={command.slash} label="Chép" /></div>
            <strong>{command.description}</strong>
            <small>{command.when}</small>
            <div className="agent-command-codex"><span>Codex: "{command.codex}"</span><CopyText text={command.codex} label="Chép câu nhắc" /></div>
          </li>
        ))}
      </ul>
      <h3 className="agent-sheet-sub">Câu nhắc cho từng tool</h3>
      <MarketingToolLines tools={view.tools} projectCode={projectCode} />
      <p className="field-help">Chưa nối agent: tạo token ở <Link to="/settings/account">Tài khoản & bảo mật</Link>, dán lệnh nối, rồi chạy dòng cài lệnh ngắn trong "Lệnh cho agent" ở menu tài khoản.</p>
    </section>
  )
}

// One line on the page where the command belongs; "Đã hiểu" hides it on this browser.
function AgentHint({ command, argument }: { command: string; argument?: string }) {
  const key = `intake-agent-hint-${command}`
  const [hidden, setHidden] = useState(() => { try { return localStorage.getItem(key) === '1' } catch { return false } })
  const commands = useAgentCommands()
  const row = commands.data?.commands.find((item) => item.name === command)
  if (hidden || !row) return null
  const slash = argument ? `${row.slash.replace(/ <.*>$/, '')} ${argument}` : row.slash
  return (
    <div className="agent-hint" role="note">
      <span>Trong terminal: <code>{slash}</code><CopyText text={slash} label="Chép" /><InfoTip label={`Dùng ${row.slash} lúc nào`} text={row.when} /></span>
      <button type="button" className="text-button" onClick={() => { try { localStorage.setItem(key, '1') } catch { /* private window */ } setHidden(true) }}>Đã hiểu</button>
    </div>
  )
}

// Who is signed in, their account page, the agent commands, and the way out.
function UserMenu({ person, initials, role, onSignOut, onCommands }: { person: string; initials: string; role: string; onSignOut: () => void; onCommands: () => void }) {
  return (
    <TopMenu label={`Tài khoản: ${person}`} icon={<span className="avatar">{initials}</span>} className="user-menu" button="avatar-button">
      {(close) => (
        <>
          <div className="top-menu-head"><strong>{person}</strong><small>{role}</small></div>
          <button type="button" role="menuitem" className="top-menu-item" onClick={() => { close(); onCommands() }}><Terminal size={15} aria-hidden="true" /><span><strong>Lệnh cho agent</strong><small>Claude Code, Codex: lệnh nào, lúc nào</small></span></button>
          <Link to="/settings/account" role="menuitem" className="top-menu-item" onClick={close}><ShieldCheck size={15} aria-hidden="true" /><span><strong>Tài khoản & bảo mật</strong></span></Link>
          <Link to="/huong-dan" role="menuitem" className="top-menu-item" onClick={close}><CircleHelp size={15} aria-hidden="true" /><span><strong>Hướng dẫn nhanh</strong><small>Mỗi trang để làm gì, mỗi nút nghĩa là gì</small></span></Link>
          <button type="button" role="menuitem" className="top-menu-item" onClick={() => { close(); onSignOut() }}><LogOut size={15} aria-hidden="true" /><span><strong>Đăng xuất</strong></span></button>
        </>
      )}
    </TopMenu>
  )
}

function ChangelogButton() {
  const [open, setOpen] = useState(false)
  const [seen, setSeen] = useState(readSeen)
  const box = useRef<HTMLDivElement>(null)
  const changelog = useQuery({ queryKey: ['changelog'], queryFn: () => api<Changelog>('/changelog'), staleTime: 5 * 60_000, refetchInterval: 10 * 60_000 })
  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => { if (box.current && !box.current.contains(event.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  const latest = changelog.data?.latest || ''
  const unseen = Boolean(latest) && latest > seen
  // Looking at the menu is what counts as having seen the latest day, even when the list arrives after the click.
  useEffect(() => {
    if (!open || !latest || latest <= seen) return
    try { localStorage.setItem(CHANGELOG_SEEN_KEY, latest) } catch { /* a private window keeps no memory */ }
    setSeen(latest)
  }, [open, latest, seen])
  const show = () => setOpen(!open)
  const days = groupByDay(changelog.data?.entries || []).slice(0, 3)
  const build = changelog.data?.build
  return (
    <div className="alert-bell changelog" ref={box}>
      <button type="button" className="icon-button" aria-label={unseen ? 'Có gì mới: có thay đổi chưa xem' : 'Có gì mới'} title="Có gì mới" aria-expanded={open} onClick={show}>
        <Sparkles size={17} />
        {unseen && <span className="alert-dot" aria-hidden="true" />}
      </button>
      {open && (
        <div className="alert-menu changelog-menu" role="menu">
          <header><strong>Có gì mới</strong>{build && <span title={build.built_at ? `Build ${formatDate(build.built_at)}` : undefined}>bản {build.sha.slice(0, 7)}</span>}</header>
          {changelog.isLoading ? <p>Đang tải…</p> : days.length === 0 ? <p>Chưa có mục nào.</p> : days.map((day) => (
            <section key={day.date} className="changelog-day">
              <h3>{changelogDay(day.date)}</h3>
              <ol>{day.entries.map((entry) => <ChangelogItem key={`${entry.date}-${entry.title}`} entry={entry} />)}</ol>
            </section>
          ))}
          <Link className="changelog-all" to="/changelog" role="menuitem" onClick={() => setOpen(false)}>Xem tất cả <ChevronRight size={15} aria-hidden="true" /></Link>
        </div>
      )}
    </div>
  )
}

const acceptanceLevel: Record<string, string> = { SELF_REPORTED: 'Tự khai', CLOSED: 'Đã đóng, chưa có dấu vết', TRACED: 'Có dấu vết code', ACCEPTED: 'Đã nghiệm thu' }
const syncText: Record<string, string> = { PENDING: 'đang ghi lên tracker', RETRY: 'ghi lên tracker, thử lại', DONE: 'đã ghi và đóng Issue', FAILED: 'ghi lên tracker lỗi', SKIPPED: 'dự án không có tracker', QUEUE_FAILED: 'chưa gửi được lệnh ghi' }

// One card: what was reported, what the tracker shows, what the request asked for, two buttons (FR-PLAN-31).
const evidenceKindWords: Record<string, string> = { COMMIT: 'commit', MR: 'MR', LINK: 'link' }
const evidenceSourceWords: Record<string, string> = { WORKER: 'người làm', ACCEPTOR: 'người nghiệm thu', AGENT: 'agent', WORK_LOG: 'lịch sử xử lý', REPORT: 'báo cáo ngày' }
const evidenceStatusWords: Record<string, string> = { OK: 'đủ bằng chứng', WEAK: 'bằng chứng chưa đủ', MISSING: 'chưa có bằng chứng' }

// The pasted address, typed by what it is: a commit or MR for code, a link to a document, video or picture otherwise (FR-PLAN-36).
function EvidenceAdder({ onAdd, busy, error }: { onAdd: (link: { kind: string; url: string; note: string }) => void; busy: boolean; error?: unknown }) {
  const [kind, setKind] = useState('LINK')
  const [url, setUrl] = useState('')
  const [note, setNote] = useState('')
  const ok = /^https?:\/\//i.test(url.trim())
  return (
    <div className="evidence-add">
      <select aria-label="Loại bằng chứng" value={kind} onChange={(event) => setKind(event.target.value)}><option value="LINK">Link tài liệu, video, ảnh</option><option value="COMMIT">Commit</option><option value="MR">MR đã merge</option></select>
      <input aria-label="Link bằng chứng" placeholder="https://…" value={url} onChange={(event) => setUrl(event.target.value)} />
      <input aria-label="Ghi chú bằng chứng" placeholder="ghi chú ngắn (tùy chọn)" value={note} maxLength={300} onChange={(event) => setNote(event.target.value)} />
      <button type="button" className="button button-secondary button-small" disabled={!ok || busy} onClick={() => { onAdd({ kind, url: url.trim(), note: note.trim() }); setUrl(''); setNote('') }}>Thêm bằng chứng</button>
      {error != null && <ErrorNotice error={error} />}
    </div>
  )
}

function EvidenceBlock({ item, canAdd }: { item: AcceptanceItem; canAdd: boolean }) {
  const queryClient = useQueryClient()
  const add = useMutation({
    mutationFn: (link: { kind: string; url: string; note: string }) => api<AcceptanceItem>(`/acceptance/${item.id}/evidence`, { method: 'POST', body: JSON.stringify({ links: [{ kind: link.kind, url: link.url, note: link.note || null }] }) }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['acceptance'] }) },
  })
  const check = item.evidence_check
  const links = item.evidence_links || []
  return (
    <div className={`evidence-block evidence-${(check?.status || 'MISSING').toLowerCase()}`}>
      <div className="evidence-head">
        <strong>Bằng chứng</strong>
        {check && <span className={`status evidence-status evidence-status-${check.status.toLowerCase()}`} title={check.why}>{evidenceStatusWords[check.status] || check.status}{check.work === 'CODE' ? ' · việc code' : check.work === 'OTHER' ? ' · việc không phải code' : ''}</span>}
        {check && <small>{check.why}</small>}
      </div>
      {links.length > 0 && (
        <ul className="evidence-links">
          {links.map((link) => (
            <li key={link.id}>
              <span className="evidence-kind">{evidenceKindWords[link.kind] || link.kind}</span>
              {link.url ? <a href={link.url} target="_blank" rel="noreferrer">{link.ref || link.url.replace(/^https?:\/\//, '').slice(0, 90)}</a> : <code>{link.ref}</code>}
              <small>{evidenceSourceWords[link.source] || link.source}{link.added_by_name ? ` · ${link.added_by_name}` : ''} · {formatDate(link.created_at)}{link.note ? ` · ${link.note}` : ''}</small>
            </li>
          ))}
        </ul>
      )}
      {canAdd && <EvidenceAdder onAdd={(link) => add.mutate(link)} busy={add.isPending} error={add.error ?? undefined} />}
    </div>
  )
}

function AcceptanceCard({ item, isCto, onDecide, busy }: { item: AcceptanceItem; isCto: boolean; onDecide: (item: AcceptanceItem, decision: 'accept' | 'reject') => void; busy: boolean }) {
  const traces = [
    item.evidence.commits > 0 ? `${item.evidence.commits} commit nhắc Issue` : null,
    item.evidence.merge_requests > 0 ? `${item.evidence.merged}/${item.evidence.merge_requests} MR đã merge` : null,
    item.evidence.pipeline ? `pipeline ${item.evidence.pipeline === 'success' ? 'xanh' : item.evidence.pipeline === 'failed' ? 'đỏ' : item.evidence.pipeline}` : null,
  ].filter(Boolean)
  const open = item.decision === 'PENDING' && (isCto || !item.po_decision)
  return (
    <li className={`acceptance-card decision-${item.decision.toLowerCase()} level-${item.level_name.toLowerCase()}`}>
      <div className="acceptance-head">
        <PriorityBadge priority={item.priority as Priority} />
        <strong>{item.intake_id ? <Link to={`/intakes/${item.intake_id}`}>#{item.issue_external_id} {item.title}</Link> : `#${item.issue_external_id} ${item.title}`}</strong>
        {item.web_url && <a className="acceptance-tracker-link" href={item.web_url} target="_blank" rel="noreferrer">GitLab #{item.issue_external_id}</a>}
        <span className="status verification-level">{acceptanceLevel[item.level_name] || item.level_name}</span>
      </div>
      <small>
        {[item.project_name,
          item.source === 'REPORT' ? `${item.reporter_name || 'ai đó'} báo xong ${item.reported_on ? changelogDay(item.reported_on) : ''}${item.reported_hours != null ? ` · ${hours(item.reported_hours)} giờ` : ''}` : item.source === 'PLAN' ? `${item.reporter_name || 'ai đó'} báo xong trên kế hoạch${item.reported_on ? ` ${changelogDay(item.reported_on)}` : ''}` : `đóng trên tracker${item.closed_at ? ` ${formatDate(item.closed_at)}` : ''}`,
          item.state ? (item.state === 'closed' ? 'Issue đã đóng' : 'Issue còn mở') : 'Issue chưa có trong danh sách',
          traces.length > 0 ? traces.join(', ') : item.evidence_fetched_at ? 'không có commit hay MR nào nhắc Issue' : 'chưa đọc dấu vết code',
          item.intake_public_id ? `từ ${item.intake_public_id}` : null,
        ].filter(Boolean).join(' · ')}
      </small>
      {item.report_item_title && item.report_item_title !== item.title && <p className="acceptance-reported">Trong báo cáo: {item.report_item_title}</p>}
      {item.source_note && <p className="acceptance-reported">Ghi chú khi hủy việc chờ: {item.source_note}. Dòng này được ghi lên Issue khi bạn xác nhận.</p>}
      {item.acceptance.length > 0 && <ul className="verification-acceptance">{item.acceptance.map((line, index) => <li key={index}>{line}</li>)}</ul>}
      <EvidenceBlock item={item} canAdd={open} />
      {item.evidence_missing_reason && <p className="acceptance-reported evidence-missing-note">Nghiệm thu không bằng chứng: {item.evidence_missing_reason}</p>}
      {item.po_decision && <p className={`acceptance-po ${item.po_decision === 'ACCEPTED' ? 'is-ok' : 'is-no'}`}>Project Owner{item.po_decided_by_name ? ` (${item.po_decided_by_name})` : ''}: {item.po_decision === 'ACCEPTED' ? 'xác nhận xong' : `chưa xong: ${item.po_reason}`}</p>}
      {item.decision !== 'PENDING' && (
        <p className={`acceptance-cto ${item.decision === 'ACCEPTED' ? 'is-ok' : 'is-no'}`}>
          CTO{item.decided_by_name ? ` (${item.decided_by_name})` : ''}: {item.decision === 'ACCEPTED' ? 'đúng là xong' : `chưa xong: ${item.reason}`}{item.decided_at ? ` · ${formatDate(item.decided_at)}` : ''}
          {item.decision === 'ACCEPTED' && item.sync_status ? ` · ${syncText[item.sync_status] || item.sync_status}${item.sync_error && item.sync_status !== 'DONE' ? ` (${item.sync_error})` : ''}` : ''}
        </p>
      )}
      {open && (
        <span className="waiting-actions">
          <button className="button button-primary button-small" type="button" disabled={busy} onClick={() => onDecide(item, 'accept')}>{isCto ? 'Đúng là xong' : 'Xác nhận xong'}</button>
          <button className="button button-secondary button-small" type="button" disabled={busy} onClick={() => onDecide(item, 'reject')}>Chưa xong</button>
        </span>
      )}
    </li>
  )
}

function AcceptanceWorkLogCard({ item, busy, onConfirm, onReturn }: { item: AcceptanceWorkLog; busy: boolean; onConfirm: (item: AcceptanceWorkLog) => void; onReturn: (item: AcceptanceWorkLog) => void }) {
  const details = item.details || {}
  const decisionLabel = item.review_decision === 'PENDING' ? 'Chờ nghiệm thu' : item.review_decision === 'CONFIRMED' ? 'Đã nghiệm thu' : 'Đã trả lại'
  const issue = item.issue_external_id
  const detailLine = [
    details.branch ? `nhánh ${details.branch}` : null,
    details.commit ? `commit ${details.commit}` : null,
    details.tests ? `test: ${details.tests}` : null,
    details.worked_on ? `làm ngày ${formatDay(details.worked_on)}` : null,
    details.actual_minutes != null ? `${hoursText(details.actual_minutes / 60)} thực tế` : null,
    details.deployed === true ? 'đã có bản triển khai' : details.deployed === false ? 'chưa triển khai' : null,
  ].filter(Boolean).join(' · ')
  return (
    <li className={`acceptance-card acceptance-work-log decision-${item.review_decision.toLowerCase()}`}>
      <div className="acceptance-head">
        <strong><Link to={`/intakes/${item.intake_id}`}>{item.intake_public_id} · {item.title}</Link></strong>
        <span className={`status decision-${item.review_decision.toLowerCase()}`}>{decisionLabel}</span>
      </div>
      <p>{item.summary}</p>
      <small>{item.project_name || 'Dự án'} · {item.executor} · {formatDate(item.created_at)}{issue ? <> · {item.web_url ? <a href={item.web_url} target="_blank" rel="noreferrer">Issue #{issue}</a> : `Issue #${issue}`}</> : ''}</small>
      {detailLine && <small>{detailLine}</small>}
      {item.review_note && <p className="acceptance-reported">{item.review_decision === 'RETURNED' ? 'Trả lại' : 'Ghi chú'}: {item.review_note}{item.reviewed_by_name ? ` · ${item.reviewed_by_name}` : ''}</p>}
      {item.review_decision === 'PENDING' && (
        <div className="waiting-actions">
          <button type="button" className="button button-primary button-small" disabled={busy} onClick={() => onConfirm(item)}>Đạt nghiệm thu</button>
          <button type="button" className="button button-secondary button-small" disabled={busy} onClick={() => onReturn(item)}>Chưa đúng</button>
        </div>
      )}
    </li>
  )
}

// Acceptance as its own queue: the CTO's five of the day, the rest on request, the last week's decisions (FR-PLAN-31).
function AcceptancePage() {
  const { user } = useAuth()
  const isCto = user?.role === 'CTO'
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const projectFilter = searchParams.get('project') || ''
  const projectList = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const queue = useQuery({ queryKey: ['acceptance', projectFilter], queryFn: () => api<AcceptanceQueue>(`/acceptance${projectFilter ? `?project_id=${projectFilter}` : ''}`), refetchInterval: 60_000 })
  const [error, setError] = useState<unknown>()
  const [rejecting, setRejecting] = useState<AcceptanceItem>()
  const [reason, setReason] = useState('')
  const [confirming, setConfirming] = useState<AcceptanceItem>()
  const [missingReason, setMissingReason] = useState('')
  const [returningWorkLog, setReturningWorkLog] = useState<AcceptanceWorkLog>()
  const [workLogReason, setWorkLogReason] = useState('')
  const [showMore, setShowMore] = useState(false)
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['acceptance'] }); void queryClient.invalidateQueries({ queryKey: ['planning-overview'] }) }
  const decide = useMutation({
    mutationFn: ({ id, decision, why, missing }: { id: string; decision: 'accept' | 'reject'; why?: string; missing?: string }) => api<AcceptanceItem>(`/acceptance/${id}/${decision}`, { method: 'POST', body: JSON.stringify({ reason: why || null, evidence_missing_reason: missing || null }) }),
    onMutate: () => setError(undefined), onSuccess: () => { setRejecting(undefined); setReason(''); setConfirming(undefined); setMissingReason(''); refresh() }, onError: setError,
  })
  const more = useMutation({ mutationFn: () => api<{ added: number }>('/acceptance/sample?extra=5', { method: 'POST' }), onSuccess: refresh, onError: setError })
  const collect = useMutation({ mutationFn: () => api<{ from_reports: number; from_closed: number }>('/acceptance/collect', { method: 'POST' }), onSuccess: refresh, onError: setError })
  const reviewWorkLog = useMutation({
    mutationFn: ({ item, decision, why }: { item: AcceptanceWorkLog; decision: 'CONFIRMED' | 'RETURNED'; why?: string }) => api<IntakeWorkLog>(`/intakes/${item.intake_id}/work-log/${item.id}/review`, { method: 'POST', body: JSON.stringify({ decision, note: why || null }) }),
    onMutate: () => setError(undefined),
    onSuccess: () => { setReturningWorkLog(undefined); setWorkLogReason(''); refresh(); void queryClient.invalidateQueries({ queryKey: ['planning-day-plans'] }) },
    onError: setError,
  })
  const data = queue.data
  const pendingWorkLogs = data?.work_logs_pending || []
  const decidedWorkLogs = data?.work_logs_decided || []
  const workLogPendingTotal = data?.work_log_pending_total ?? pendingWorkLogs.length
  const onDecide = (item: AcceptanceItem, decision: 'accept' | 'reject') => {
    if (decision === 'reject') { setReason(''); setRejecting(item); return }
    // Nothing behind "done": the acceptor says why they still say yes (FR-PLAN-36).
    if (item.evidence_check && item.evidence_check.status !== 'OK') { setMissingReason(''); setConfirming(item); return }
    decide.mutate({ id: item.id, decision })
  }
  const projectName = data && projectFilter ? [...data.today, ...data.more, ...data.decided, ...pendingWorkLogs, ...decidedWorkLogs].find((item) => item.project_id === projectFilter)?.project_name : null
  return (
    <>
      <PageHeader title="Nghiệm thu" helper={isCto ? [
        'Mỗi việc báo "xong" đã gắn Issue, và mỗi Issue đóng trên tracker, là một việc chờ nghiệm thu.',
        'Việc phát sinh ngoài kế hoạch do người hoặc agent ghi trong Lịch sử xử lý cũng hiện đủ ở đây để anh xác nhận hoặc trả lại.',
        'Mỗi ngày hệ thống chọn năm việc cho anh: P0/P1 trước, việc không có dấu vết code, dự án và người lâu chưa được xem. Muốn xem thêm thì bấm "Thêm 5 việc".',
        '"Đúng là xong": Intake ghi chú lên Issue và đóng Issue. "Chưa xong": việc về kế hoạch đang mở dưới dạng "Làm lại", kèm lý do.',
      ] : [
        'Việc báo "xong" của người trong dự án anh chị chờ xác nhận ở đây. Xác nhận của Project Owner được ghi cạnh nghiệm thu của CTO.',
        '"Chưa xong" kèm lý do: việc về kế hoạch đang mở dưới dạng "Làm lại".',
      ]} action={isCto ? <button type="button" className="button button-secondary" disabled={collect.isPending} title="Gom mọi việc báo xong và Issue đóng gần đây thành việc chờ nghiệm thu ngay, không đợi 07:00" onClick={() => collect.mutate()}>{collect.isPending ? 'Đang gom…' : 'Gom việc mới'}</button> : undefined} />
      <div className="toolbar-row">
        <label className="inline-field">Dự án
          <select aria-label="Lọc theo dự án" value={projectFilter} onChange={(event) => setSearchParams(event.target.value ? { project: event.target.value } : {})}>
            <option value="">Mọi dự án</option>
            {(projectList.data ?? []).filter((project) => project.status === 'ACTIVE' || project.id === projectFilter).map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        </label>
        {projectFilter && <span className="field-help">{projectName ? `Đang lọc ${projectName}.` : 'Đang lọc theo dự án.'} <Link to="/nghiem-thu">Xem mọi dự án</Link></span>}
      </div>
      {error != null && <ErrorNotice error={error} />}
      {queue.error != null && <ErrorNotice error={queue.error} onRetry={() => { void queue.refetch() }} />}
      {confirming && (
        <ConfirmDialog title={`Xác nhận không có bằng chứng: ${confirming.title}`} confirmLabel={isCto ? 'Vẫn đúng là xong' : 'Vẫn xác nhận xong'} busyLabel="Đang ghi…" plain busy={decide.isPending} error={decide.error ?? undefined} onConfirm={() => { if (missingReason.trim().length >= 3) decide.mutate({ id: confirming.id, decision: 'accept', missing: missingReason.trim() }) }} onCancel={() => { if (!decide.isPending) setConfirming(undefined) }}>
          <p className="field-help">{confirming.evidence_check?.why}. Dán link hoặc commit ở ô "Thêm bằng chứng" trên thẻ thì không cần dòng này.</p>
          <label>Vì sao vẫn xác nhận<textarea rows={3} value={missingReason} maxLength={500} onChange={(event) => setMissingReason(event.target.value)} placeholder="Ví dụ: đã xem trực tiếp trên máy khách, không có gì để link" /></label>
          <ul><li>Thẻ ghi "nghiệm thu không bằng chứng" kèm dòng này; Tuần qua đếm riêng.</li></ul>
        </ConfirmDialog>
      )}
      {rejecting && (
        <ConfirmDialog title={`Chưa xong: ${rejecting.title}`} confirmLabel="Ghi chưa xong" busyLabel="Đang ghi…" plain busy={decide.isPending} error={decide.error ?? undefined} onConfirm={() => { if (reason.trim().length >= 3) decide.mutate({ id: rejecting.id, decision: 'reject', why: reason.trim() }) }} onCancel={() => { if (!decide.isPending) setRejecting(undefined) }}>
          <label>Chưa xong ở chỗ nào<textarea rows={3} value={reason} maxLength={1000} onChange={(event) => setReason(event.target.value)} placeholder="Ví dụ: đơn vẫn tạo trùng khi khách bấm hai lần" /></label>
          <ul><li>Việc quay lại kế hoạch đang mở của dự án dưới dạng "Làm lại", kèm lý do này.</li><li>Issue trên tracker không bị mở lại từ đây.</li></ul>
        </ConfirmDialog>
      )}
      {returningWorkLog && (
        <ConfirmDialog title={`Chưa đúng: ${returningWorkLog.title}`} confirmLabel="Trả lại" busyLabel="Đang ghi…" plain busy={reviewWorkLog.isPending} error={reviewWorkLog.error ?? undefined} onConfirm={() => { if (workLogReason.trim().length >= 3) reviewWorkLog.mutate({ item: returningWorkLog, decision: 'RETURNED', why: workLogReason.trim() }) }} onCancel={() => { if (!reviewWorkLog.isPending) { setReturningWorkLog(undefined); setWorkLogReason('') } }}>
          <label>Chưa đúng ở chỗ nào<textarea rows={3} value={workLogReason} maxLength={1000} onChange={(event) => setWorkLogReason(event.target.value)} placeholder="Ví dụ: danh sách vẫn thiếu khi lọc theo dự án" /></label>
          <ul><li>Người hoặc agent làm lại sẽ đọc lý do này trước.</li><li>Issue và trạng thái yêu cầu không đổi.</li></ul>
        </ConfirmDialog>
      )}
      {queue.isLoading || !data ? <LoadingBlock /> : (
        <>
          {isCto && (
            <section className="panel today" aria-label="Việc phát sinh chờ nghiệm thu">
              <header><div><h2>Việc phát sinh chờ nghiệm thu</h2><p>{workLogPendingTotal} việc ngoài kế hoạch do người hoặc agent đã ghi</p></div></header>
              {pendingWorkLogs.length === 0 ? <EmptyState icon={<BadgeCheck size={20} />} title="Không có việc phát sinh chờ nghiệm thu" text="Lịch sử xử lý mới do người hoặc agent ghi sẽ xuất hiện ở đây và trong Daily Planning." /> : (
                <ul className="acceptance-list">{pendingWorkLogs.map((item) => <AcceptanceWorkLogCard key={item.id} item={item} busy={reviewWorkLog.isPending} onConfirm={(row) => reviewWorkLog.mutate({ item: row, decision: 'CONFIRMED' })} onReturn={(row) => { setWorkLogReason(''); setReturningWorkLog(row) }} />)}</ul>
              )}
            </section>
          )}
          <section className="panel today" aria-label={isCto ? 'Hôm nay' : 'Chờ xác nhận'}>
            <header><div><h2>{isCto ? `Hôm nay ${changelogDay(data.plan_date)}` : 'Chờ xác nhận'}</h2><p>{isCto ? `${data.today.filter((item) => item.decision === 'PENDING').length} việc trong mẫu hôm nay · còn ${data.more.length} việc khác chờ` : `${data.today.length} việc`}</p></div>{isCto && data.more.length > 0 && <button type="button" className="button button-secondary button-small" disabled={more.isPending} onClick={() => more.mutate()}>{more.isPending ? 'Đang thêm…' : 'Thêm 5 việc'}</button>}</header>
            {data.today.length === 0 ? <EmptyState icon={<BadgeCheck size={20} />} title={data.pending_total === 0 ? 'Không có việc nào chờ nghiệm thu' : 'Mẫu hôm nay đã xem xong'} text={data.pending_total === 0 ? 'Việc báo "xong" đã gắn Issue sẽ xuất hiện ở đây.' : `Còn ${data.more.length} việc khác; bấm "Thêm 5 việc" nếu muốn xem tiếp.`} /> : (
              <ul className="acceptance-list">{data.today.map((item) => <AcceptanceCard key={item.id} item={item} isCto={isCto} busy={decide.isPending} onDecide={onDecide} />)}</ul>
            )}
          </section>
          {isCto && data.more.length > 0 && (
            <section className="panel today" aria-label="Còn lại">
              <header><div><h2>Còn lại</h2><p>{data.more.length} việc chưa vào mẫu</p></div><button type="button" className="text-button" onClick={() => setShowMore(!showMore)}>{showMore ? 'Thu gọn' : 'Xem danh sách'}</button></header>
              {showMore && <ul className="acceptance-list">{data.more.map((item) => <AcceptanceCard key={item.id} item={item} isCto={isCto} busy={decide.isPending} onDecide={onDecide} />)}</ul>}
            </section>
          )}
          {data.decided.length > 0 && (
            <section className="panel today" aria-label="Đã quyết">
              <header><div><h2>Đã quyết</h2><p>{isCto ? 'bảy ngày qua' : 'gần đây'}</p></div></header>
              <ul className="acceptance-list is-decided">{data.decided.map((item) => <AcceptanceCard key={item.id} item={item} isCto={isCto} busy={decide.isPending} onDecide={onDecide} />)}</ul>
            </section>
          )}
          {isCto && decidedWorkLogs.length > 0 && (
            <section className="panel today" aria-label="Việc phát sinh đã quyết">
              <header><div><h2>Việc phát sinh đã quyết</h2><p>bảy ngày qua</p></div></header>
              <ul className="acceptance-list is-decided">{decidedWorkLogs.map((item) => <AcceptanceWorkLogCard key={item.id} item={item} busy={reviewWorkLog.isPending} onConfirm={(row) => reviewWorkLog.mutate({ item: row, decision: 'CONFIRMED' })} onReturn={(row) => { setWorkLogReason(''); setReturningWorkLog(row) }} />)}</ul>
            </section>
          )}
        </>
      )}
    </>
  )
}

// Monday of the week that holds `value` (YYYY-MM-DD), in the planning timezone's calendar.
function mondayOf(value: string) {
  const [year, month, day] = value.slice(0, 10).split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7))
  return date.toISOString().slice(0, 10)
}
function shiftDays(value: string, days: number) {
  const [year, month, day] = value.slice(0, 10).split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day + days))
  return date.toISOString().slice(0, 10)
}
const weekHours = (value: number) => (Number.isInteger(value) ? `${value}` : value.toFixed(1))

// The week in counts: what was planned, reported, really done, and where the process waited (FR-PLAN-29).
function WeekPage() {
  const { user } = useAuth()
  const isCto = user?.role === 'CTO'
  const thisMonday = mondayOf(todayInPlanningTimezone())
  const [week, setWeek] = useState(() => {
    const asked = new URLSearchParams(window.location.search).get('week')
    return asked && /^\d{4}-\d{2}-\d{2}$/.test(asked) ? mondayOf(asked) : shiftDays(thisMonday, -7)
  })
  const summary = useQuery({ queryKey: ['planning-week', week], queryFn: () => api<WeekSummary>(`/planning/week/${week}`), staleTime: 60_000 })
  const [copied, setCopied] = useState(false)
  const data = summary.data
  const copyText = () => { if (data) void navigator.clipboard.writeText(data.text).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 2500) }) }
  const doneText = (row: WeekProject) => `${row.done.reported} → ${row.done.issues_closed} → ${row.done.accepted}${row.done.rejected > 0 ? ` (trả lại ${row.done.rejected})` : ''}${row.done.po_accepted > 0 ? ` · PO xác nhận ${row.done.po_accepted}` : ''}`
  const ctoTotal = data?.cto_days ? data.cto_days.reduce((sum, day) => sum + day.minutes, 0) : 0
  const label = `${formatDay(week)} - ${formatDay(shiftDays(week, 6))}`
  return (
    <>
      <AgentHint command="week" />
      <PageHeader title="Tuần qua" helper={[
        'Ba mức "xong" đứng cạnh nhau: báo cáo nói xong, Issue đã đóng, CTO đã nghiệm thu. Khoảng cách giữa chúng là điều cần nhìn.',
        'Giờ có tính trên những ngày đã qua của tuần; giờ xếp cộng mọi kế hoạch của ngày, kể cả nháp.',
        'Cột "Bảng đầu ngày" lấy từ ảnh chụp lúc 23:55 mỗi tối, có từ ngày 13/10/2026.',
      ]} action={<button type="button" className="button button-secondary" disabled={!data} title="Chép tóm tắt tuần dạng chữ: tên dự án, tên người và các con số; không có nội dung yêu cầu" onClick={copyText}>{copied ? <><Check size={14} /> Đã chép</> : <><Copy size={14} /> Chép tóm tắt</>}</button>} />
      <div className="week-bar">
        <button type="button" className="button button-secondary button-small" onClick={() => setWeek(shiftDays(week, -7))}><ChevronLeft size={14} aria-hidden="true" /> Tuần trước</button>
        <strong>Tuần {label}{week === thisMonday ? ' (đang diễn ra)' : ''}</strong>
        <button type="button" className="button button-secondary button-small" disabled={week >= thisMonday} onClick={() => setWeek(shiftDays(week, 7))}>Tuần sau <ChevronRight size={14} aria-hidden="true" /></button>
        {week !== shiftDays(thisMonday, -7) && <button type="button" className="text-button" onClick={() => setWeek(shiftDays(thisMonday, -7))}>Về tuần trước</button>}
      </div>
      {summary.error != null && <ErrorNotice error={summary.error} onRetry={() => { void summary.refetch() }} />}
      {summary.isLoading || !data ? <LoadingBlock /> : (
        <>
          <section className="panel today" aria-label="Theo dự án">
            <header><div><h2>Theo dự án</h2><p>{data.projects.length} dự án · {data.days_passed}/7 ngày đã qua</p></div></header>
            {data.projects.length === 0 ? <EmptyState icon={<CalendarRange size={20} />} title="Chưa có dự án phần mềm" text="Tạo dự án loại phần mềm ở Cài đặt > Dự án." /> : (
              <div className="today-board week-board">
                <table>
                  <thead><tr><th>Dự án</th><th>Giờ có / xếp / báo cáo</th><th>Kế hoạch chốt</th><th title="Báo cáo nói xong → Issue đóng → CTO nghiệm thu">Xong: báo cáo → Issue → nghiệm thu</th><th>Việc chưa gắn Issue</th><th>Báo cáo</th><th>Yêu cầu mới / duyệt</th><th>Bảng đầu ngày</th></tr></thead>
                  <tbody>
                    {data.projects.map((row) => (
                      <tr key={row.id}>
                        <td className="board-project"><Link to={`/planning?project=${row.id}`}><strong>{row.name}</strong></Link><small className="muted"> {row.people} người</small></td>
                        <td className={row.hours.reported < row.hours.planned * 0.7 && row.hours.planned > 0 ? 'board-attn' : undefined}>{weekHours(row.hours.available)} / {weekHours(row.hours.planned)} / {weekHours(row.hours.reported)}</td>
                        <td className={row.plans.closed < row.plans.total ? 'board-attn' : undefined}>{row.plans.closed}/{row.plans.total}</td>
                        <td className={row.done.reported > 0 && row.done.accepted === 0 ? 'board-attn' : undefined}>{doneText(row)}{row.done.work_logs_confirmed > 0 ? <small className="muted"> · {row.done.work_logs_confirmed} lịch sử xác nhận</small> : null}</td>
                        <td className={row.items.without_issue > 0 ? 'board-overdue' : undefined}><Link to="/reports?unlinked=1">{row.items.without_issue}/{row.items.reported}</Link>{row.items.no_issue_needed > 0 ? <small className="muted"> · {row.items.no_issue_needed} không cần</small> : null}</td>
                        <td className={row.reports.missing > 0 || row.reports.late > 0 ? 'board-attn' : undefined}><Link to="/reports">{row.reports.received}/{row.reports.expected}{row.reports.late > 0 ? ` · trễ ${row.reports.late}` : ''}</Link></td>
                        <td><Link to={`/intakes?project=${row.code}`}>{row.requests.new} / {row.requests.approved}{row.requests.approved > 0 ? ` (24h: ${row.requests.approved_within_24h}${row.requests.avg_wait_hours !== null ? `, chờ ${weekHours(row.requests.avg_wait_hours)} giờ` : ''})` : ''}</Link></td>
                        <td className={row.board.overdue_days > 0 ? 'board-overdue' : undefined}>{row.board.days === 0 ? <span className="muted">chưa có ảnh chụp</span> : `đủ cơ sở ${row.board.ready_days}/${row.board.days}${row.board.overdue_days > 0 ? ` · quá hạn ${row.board.overdue_days} ngày` : ''}`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <section className="panel today" aria-label="Theo nhân sự">
            <header><div><h2>Theo nhân sự</h2><p>Giờ xếp và giờ báo cáo cộng qua mọi dự án; báo cáo đếm theo ngày có giờ làm</p></div></header>
            {data.people.length === 0 ? <EmptyState icon={<UserRound size={20} />} title="Chưa có nhân sự" text="Thêm người ở Cài đặt > Nhân sự." /> : (
              <div className="today-board week-board">
                <table>
                  <thead><tr><th>Người</th><th>Giờ xếp / có</th><th>Giờ báo cáo</th><th>Xong</th><th>Chưa gắn Issue</th><th>Báo cáo</th><th>Dự án</th></tr></thead>
                  <tbody>
                    {data.people.map((person) => (
                      <tr key={person.member_id}>
                        <td className="board-project"><strong>{person.display_name}</strong></td>
                        <td className={person.hours.planned > person.hours.available + 0.01 ? 'board-overdue' : person.hours.planned < person.hours.available * 0.5 ? 'board-attn' : undefined}>{weekHours(person.hours.planned)}/{weekHours(person.hours.available)}</td>
                        <td>{weekHours(person.hours.reported)}</td>
                        <td>{person.done_reported}/{person.items.reported}</td>
                        <td className={person.items.without_issue > 0 ? 'board-overdue' : undefined}>{person.items.without_issue}</td>
                        <td className={person.reports.missing > 0 || person.reports.late > 0 ? 'board-attn' : undefined}>{person.reports.received}/{person.reports.expected}{person.reports.late > 0 ? ` · trễ ${person.reports.late}` : ''}</td>
                        <td>{person.projects.length === 0 ? <span className="muted">không có việc</span> : person.projects.map((project) => <span key={project.id} className="people-project">{project.name} {weekHours(project.planned)}/{weekHours(project.reported)} giờ</span>)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="field-help">Dự án: giờ xếp/giờ báo cáo. Đỏ: xếp quá giờ có hoặc có việc không gắn Issue; cam: xếp dưới nửa giờ có, thiếu hoặc trễ báo cáo.</p>
              </div>
            )}
          </section>
          <section className="panel today" aria-label="Quy trình">
            <header><div><h2>Quy trình</h2><p>Chờ ở đâu, bao lâu</p></div></header>
            <div className="attention-grid week-process" role="list">
              <div className="attention-card" role="listitem"><span>Yêu cầu mới / duyệt</span><strong>{data.process.requests_new} / {data.process.approved}</strong><small>{data.process.from_planning} duyệt từ Daily Planning</small></div>
              <div className="attention-card" role="listitem"><span>Duyệt trong 24 giờ</span><strong>{data.process.approved > 0 ? `${Math.round((data.process.approved_within_24h / data.process.approved) * 100)}%` : '–'}</strong><small>{data.process.avg_wait_hours !== null ? `chờ trung bình ${weekHours(data.process.avg_wait_hours)} giờ` : 'chưa có quyết định nào'}</small></div>
              <div className="attention-card" role="listitem"><span>Issue tạo</span><strong>{data.process.issues_created}</strong><small>{data.process.avg_to_issue_hours !== null ? `từ duyệt đến Issue ${weekHours(data.process.avg_to_issue_hours)} giờ` : 'chưa có'}</small></div>
              <div className="attention-card" role="listitem"><span>Đủ cơ sở review</span><strong>{data.process.board_days > 0 ? `${data.process.ready_days}/${data.process.board_days}` : '–'}</strong><small>dự án-ngày, theo ảnh chụp 23:55</small></div>
              <div className="attention-card" role="listitem"><span>Có việc quá hạn</span><strong>{data.process.board_days > 0 ? data.process.overdue_project_days : '–'}</strong><small>dự án-ngày · leo thang lên CTO {data.process.escalated_project_days}</small></div>
              <div className="attention-card" role="listitem"><span>Kẹt ở AI</span><strong>{data.process.board_days > 0 ? data.process.max_stuck : '–'}</strong><small>nhiều nhất trong một tối</small></div>
            </div>
            {isCto && data.personal && (data.personal.done_total > 0 || data.personal.delegated > 0 || data.personal.open.some((row) => row.count > 0)) && <PersonalWeekPanel block={data.personal} />}
            {isCto && data.cto_days && (
              <div className="week-cto">
                <p><Timer size={14} aria-hidden="true" /><span>CTO điều hành <strong>{minutesText(ctoTotal)}</strong> cả tuần · trung bình <strong>{minutesText(Math.round(ctoTotal / Math.max(data.days_passed, 1)))}</strong>/ngày</span><small>đo theo thao tác để lại dấu trong app; mục tiêu 2 giờ/ngày</small></p>
                <ol className="week-days">{data.cto_days.map((day) => <li key={day.date}><span>{formatDay(day.date)}</span><i style={{ width: `${Math.min(100, (day.minutes / 120) * 100)}%` }} /><b>{day.minutes}'</b></li>)}</ol>
              </div>
            )}
          </section>
        </>
      )}
    </>
  )
}

// The CTO's own week: finished by the quadrant it stood in, open by quadrant, handed on, rolled over (FR-PER-06).
function PersonalWeekPanel({ block }: { block: PersonalWeekBlock }) {
  const q = (rows: PersonalWeekBlock['done'], id: number) => rows.find((row) => row.quadrant === id) || { count: 0, hours: 0, label: '' }
  return (
    <div className="week-personal" aria-label="Việc riêng của tôi">
      <p><ListChecks size={14} aria-hidden="true" /><span>Việc riêng của tôi: xong <strong>{block.done_total}</strong> ({hoursText(block.done_hours)}) · Làm ngay <strong>{hoursText(q(block.done, 1).hours)}</strong> so với Lên lịch <strong>{hoursText(q(block.done, 2).hours)}</strong>{block.schedule_share != null ? ` (${Math.round(block.schedule_share * 100)}% giờ có kế hoạch)` : ''} · giao đi <strong>{block.delegated}</strong> · dời <strong>{block.rollovers}</strong> lần · còn mở {block.open.reduce((sum, row) => sum + row.count, 0)}</span></p>
    </div>
  )
}

// The whole history, newest first.
function ChangelogPage() {
  const changelog = useQuery({ queryKey: ['changelog'], queryFn: () => api<Changelog>('/changelog'), staleTime: 5 * 60_000 })
  const build = changelog.data?.build
  return (
    <>
      <PageHeader title="Nhật ký thay đổi" />
      {changelog.error != null && <ErrorNotice error={changelog.error} onRetry={() => { void changelog.refetch() }} />}
      <section className="panel changelog-page">
        <div className="panel-heading"><div><h2>Có gì mới</h2></div>{build && <span className="muted">Bản đang chạy: {build.sha.slice(0, 7)}{build.built_at ? ` · build ${formatDate(build.built_at)}` : ''}</span>}</div>
        {changelog.isLoading ? <LoadingBlock /> : groupByDay(changelog.data?.entries || []).map((day) => (
          <section key={day.date} className="changelog-day">
            <h3>{changelogDay(day.date)}</h3>
            <ol>{day.entries.map((entry) => <ChangelogItem key={`${entry.date}-${entry.title}`} entry={entry} />)}</ol>
          </section>
        ))}
      </section>
    </>
  )
}

function QuickSearch() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const { pathname, search } = useLocation()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [settled, setSettled] = useState('')
  const [active, setActive] = useState(0)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setOpen((current) => !current) }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])
  useEffect(() => { setOpen(false) }, [pathname, search])
  useEffect(() => { if (!open) { setText(''); setSettled('') } }, [open])
  useEffect(() => { const timer = window.setTimeout(() => setSettled(text.trim()), 220); return () => window.clearTimeout(timer) }, [text])
  useEffect(() => { setActive(0) }, [text, settled])

  const intakes = useQuery({ queryKey: ['quick-intakes', settled], queryFn: () => api<IntakePage>(`/intakes?limit=6&search=${encodeURIComponent(settled)}`), enabled: open && settled.length >= 2 })
  const meetings = useQuery({ queryKey: ['meetings', false], queryFn: () => api<Meeting[]>('/meetings'), enabled: open, staleTime: 60000 })

  const wanted = plainText(text.trim())
  const pages: QuickResult[] = [
    { key: 'p-today', group: 'Trang', label: 'Hôm nay', to: '/', icon: <House size={15} /> },
    { key: 'p-reports', group: 'Trang', label: 'Báo cáo ngày', to: '/reports', icon: <FileText size={15} /> },
    { key: 'p-approvals', group: 'Trang', label: 'Chờ phê duyệt', to: '/approvals', icon: <ClipboardCheck size={15} /> },
    { key: 'p-planning', group: 'Trang', label: 'Daily Planning', hint: 'Kế hoạch sáng, chiều', to: '/planning', icon: <CalendarDays size={15} /> },
    { key: 'p-week', group: 'Trang', label: 'Tuần qua', hint: 'Kế hoạch, báo cáo, xong thật, quy trình', to: '/tuan-qua', icon: <CalendarRange size={15} /> },
    { key: 'p-acceptance', group: 'Trang', label: 'Nghiệm thu', hint: 'Việc báo xong, đúng là xong chưa', to: '/nghiem-thu', icon: <BadgeCheck size={15} /> },
    { key: 'p-intakes', group: 'Trang', label: 'Tất cả Intake', to: '/intakes', icon: <List size={15} /> },
    { key: 'p-meetings', group: 'Trang', label: 'Cuộc họp', to: '/meetings', icon: <MessagesSquare size={15} /> },
    { key: 'p-new', group: 'Trang', label: 'Tạo Intake', hint: 'Gõ, dán hoặc nói để nhập', to: '/intakes/new', icon: <Plus size={15} /> },
    { key: 'p-record', group: 'Trang', label: 'Ghi âm cuộc họp', to: '/intakes/new?panel=record', icon: <Mic size={15} /> },
    { key: 'p-settings', group: 'Trang', label: 'Cài đặt', hint: 'Dự án, nhân sự, tài khoản', to: '/settings', icon: <Settings size={15} /> },
    ...(user?.role === 'CTO' ? [
      { key: 'p-ideas', group: 'Trang', label: 'Kho ý tưởng', hint: 'Riêng: ý tưởng và nháp bài đăng', to: '/rieng', icon: <Lightbulb size={15} /> },
      { key: 'p-voice', group: 'Trang', label: 'Giọng của tôi', hint: 'Riêng: định vị, trụ, bài mẫu', to: '/rieng/giong', icon: <UserRound size={15} /> },
      { key: 'p-watch', group: 'Trang', label: 'Nguồn theo dõi', hint: 'Riêng: web, kênh và từ khóa cho công cụ quét', to: '/rieng/nguon', icon: <Eye size={15} /> },
    ] : []),
  ]
  const results: QuickResult[] = [
    ...(intakes.data?.items || []).map((intake) => ({
      key: `i-${intake.id}`, group: 'Yêu cầu', label: `${intake.public_id} · ${intake.normalized_title || 'Chưa có tiêu đề'}`,
      hint: statusLabels[intake.status], to: `/intakes/${intake.id}`, icon: <Inbox size={15} />,
    })),
    ...(wanted.length >= 2 ? (meetings.data || []).filter((meeting) => plainText(meeting.title).includes(wanted)).slice(0, 4).map((meeting) => ({
      key: `m-${meeting.id}`, group: 'Cuộc họp', label: meeting.title, hint: formatDate(meeting.started_at), to: `/meetings?id=${meeting.id}`, icon: <MessagesSquare size={15} />,
    })) : []),
    ...pages.filter((page) => !wanted || plainText(`${page.label} ${page.hint || ''}`).includes(wanted)),
  ]
  const go = (result: QuickResult | undefined) => { if (result) { setOpen(false); navigate(result.to) } }
  const move = (step: number) => {
    if (results.length === 0) return
    const next = (active + step + results.length) % results.length
    setActive(next)
    listRef.current?.querySelector(`[data-index="${next}"]`)?.scrollIntoView({ block: 'nearest' })
  }
  const searching = settled.length >= 2 && intakes.isFetching

  return (
    <>
      <button type="button" className="quick-search-button" aria-label="Tìm nhanh" title="Tìm nhanh (Ctrl+K)" onClick={() => setOpen(true)}>
        <Search size={15} aria-hidden="true" /><span>Tìm…</span><kbd>Ctrl K</kbd>
      </button>
      {open && createPortal(
        <div className="quick-search" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false) }}>
          <div className="quick-search-box" role="dialog" aria-modal="true" aria-label="Tìm nhanh">
            <label className="quick-search-input">
              <Search size={17} aria-hidden="true" />
              <input autoFocus value={text} onChange={(event) => setText(event.target.value)} placeholder="Tìm mã hoặc tiêu đề yêu cầu, cuộc họp, trang…" aria-label="Tìm nhanh"
                role="combobox" aria-expanded="true" aria-controls="quick-search-results" aria-activedescendant={results[active] ? `quick-${results[active].key}` : undefined}
                onKeyDown={(event) => {
                  if (event.key === 'ArrowDown') { event.preventDefault(); move(1) }
                  else if (event.key === 'ArrowUp') { event.preventDefault(); move(-1) }
                  else if (event.key === 'Enter') { event.preventDefault(); go(results[active]) }
                  else if (event.key === 'Escape') setOpen(false)
                }} />
              {searching && <span className="spinner" aria-hidden="true" />}
            </label>
            <div className="quick-search-results" id="quick-search-results" role="listbox" aria-label="Kết quả" ref={listRef}>
              {results.length === 0 && <p>{searching ? 'Đang tìm…' : 'Không thấy kết quả nào. Thử mã yêu cầu (ví dụ KIN-26W41) hoặc một từ trong tiêu đề.'}</p>}
              {results.map((result, index) => (
                <div key={result.key}>
                  {(index === 0 || results[index - 1].group !== result.group) && <span className="quick-search-group">{result.group}</span>}
                  <button type="button" role="option" id={`quick-${result.key}`} data-index={index} aria-selected={index === active} className={index === active ? 'active' : undefined}
                    onMouseEnter={() => setActive(index)} onClick={() => go(result)}>
                    <span className="quick-search-icon" aria-hidden="true">{result.icon}</span>
                    <strong>{result.label}</strong>
                    {result.hint && <small>{result.hint}</small>}
                  </button>
                </div>
              ))}
            </div>
            <footer><span><kbd>↑</kbd><kbd>↓</kbd> chọn</span><span><kbd>Enter</kbd> mở</span><span><kbd>Esc</kbd> đóng</span><span className="quick-search-scope">Tìm trong yêu cầu, cuộc họp và trang</span></footer>
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}

function useShell() {
  return useOutletContext<ShellContext>()
}

function ProtectedLayout() {
  const { user, loading, logout, refresh } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const { text } = useLocale()
  const [menuOpen, setMenuOpen] = useState(false)
  const [titleSlot, setTitleSlot] = useState<HTMLElement | null>(null)
  const [actionSlot, setActionSlot] = useState<HTMLElement | null>(null)
  const slots = useMemo(() => ({ title: titleSlot, action: actionSlot }), [titleSlot, actionSlot])
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(NAV_COLLAPSED_KEY) === '1')
  const [rightPanel, setRightPanel] = useState<RightPanel | null>(null)
  // Hooks stay above the early returns below; the private group's open state is one of them.
  const [privateOpen, setPrivateOpen] = useState(() => { try { return localStorage.getItem(PRIVATE_OPEN_KEY) === '1' } catch { return false } })
  const [commandsOpen, setCommandsOpen] = useState(false)
  // A fresh install sends the CTO to first-run setup once; a failed check never blocks the app.
  const setupState = useQuery({ queryKey: ['setup'], queryFn: () => api<SetupState>('/setup'), enabled: user?.role === 'CTO', retry: false })

  if (loading) return <LoadingBlock label={text('Đang xác minh phiên đăng nhập…', 'Checking your session…')} />
  if (!user) return <Navigate to="/login" replace />

  const signOut = async () => {
    await logout()
    navigate('/login')
  }
  if (user.must_change_password) return <ForcedPasswordPage onChanged={() => { void refresh() }} onSignOut={() => { void signOut() }} />

  const toggleCollapsed = () => {
    localStorage.setItem(NAV_COLLAPSED_KEY, collapsed ? '0' : '1')
    setCollapsed(!collapsed)
  }

  const { pathname, search } = location
  // A Developer's workspace is the terminal: the web shows only their account and how to connect an agent.
  const marketing = user.mode === 'MARKETING'
  if (user.role === 'DEVELOPER' && !pathname.startsWith('/settings/account') && !pathname.startsWith('/viec-rieng') && !pathname.startsWith('/viec-cua-toi') && !pathname.startsWith('/viec') && !pathname.startsWith('/tuan-nay') && !pathname.startsWith('/gop-y') && !pathname.startsWith('/huong-dan')) return <Navigate to={marketing ? '/tuan-nay' : '/viec-cua-toi'} replace />
  if (user.role === 'CTO' && setupState.data && !setupState.data.completed && !pathname.startsWith('/setup') && !pathname.startsWith('/settings')) return <Navigate to="/setup" replace />
  // A marketing-only account lands on the week, not on the day of a software team (FR-MKT-03).
  if (marketing && pathname === '/') return <Navigate to="/tuan-nay" replace />
  const recording = pathname === '/intakes/new' && new URLSearchParams(search).get('panel') === 'record'
  // Shown in the top bar by pages that set no title of their own.
  const pageName = pathname === '/intakes/new'
    ? (recording ? text('Ghi âm họp', 'Record meeting') : text('Tạo Intake', 'Create Intake'))
    : pathname.startsWith('/intakes/') ? text('Chi tiết Intake', 'Intake details')
      : pathname.startsWith('/rieng/y/') ? text('Kho ý tưởng', 'Idea library') : 'Private Intake'
  // The menu follows a working day in the order the CTO meets it (reports, decisions, the plan, acceptance), then
  // the places to look things up. Actions live in the "+" button up top; the private space folds into one entry.
  const betaOn = user.beta_features_enabled !== false
  const groups0: { label: string | null; links: { to: string; icon: ReactNode; label: string; active: boolean; count?: 'approvals' | 'reports' | 'review'; beta?: boolean }[] }[] = marketing ? [
    { label: null, links: [
      { to: '/tuan-nay', icon: <CalendarDays size={17} />, label: POST_WORDS.week, active: pathname.startsWith('/tuan-nay') },
      { to: '/viec', icon: <Columns3 size={17} />, label: POST_WORDS.board, active: pathname.startsWith('/viec') && !pathname.startsWith('/viec-') },
      ...(user.role !== 'DEVELOPER' ? [{ to: '/duyet', icon: <BadgeCheck size={17} />, label: POST_WORDS.review, active: pathname.startsWith('/duyet'), count: 'review' as const }] : []),
      ...(user.role !== 'DEVELOPER' ? [{ to: '/meetings', icon: <MessagesSquare size={17} />, label: 'Cuộc họp', active: pathname.startsWith('/meetings') }] : []),
      ...(user.role !== 'DEVELOPER' ? [{ to: '/nguon', icon: <Eye size={17} />, label: POST_WORDS.sourcesPage, active: pathname.startsWith('/nguon') }] : []),
    ] },
    { label: 'Khác', links: [
      ...(user.role !== 'DEVELOPER' ? [{ to: '/projects', icon: <UserRound size={17} />, label: 'Dự án', active: pathname.startsWith('/projects') }] : []),
      { to: '/viec-rieng', icon: <ListChecks size={17} />, label: 'Việc riêng', active: pathname.startsWith('/viec-rieng') },
      { to: '/gop-y', icon: <MessageSquarePlus size={17} />, label: 'Góp ý', active: pathname.startsWith('/gop-y') },
      { to: '/huong-dan', icon: <CircleHelp size={17} />, label: 'Hướng dẫn', active: pathname.startsWith('/huong-dan') },
      { to: '/settings/account', icon: <UserRound size={17} />, label: 'Tài khoản', active: pathname.startsWith('/settings') },
    ] },
  ] : user.role === 'DEVELOPER' ? [
    { label: null, links: [
      { to: '/viec-cua-toi', icon: <CalendarDays size={17} />, label: 'Việc của tôi', active: pathname.startsWith('/viec-cua-toi') },
      { to: '/viec-rieng', icon: <ListChecks size={17} />, label: 'Việc riêng', active: pathname.startsWith('/viec-rieng') },
      { to: '/viec', icon: <Columns3 size={17} />, label: 'Việc', active: pathname.startsWith('/viec') && !pathname.startsWith('/viec-') },
      { to: '/gop-y', icon: <MessageSquarePlus size={17} />, label: 'Góp ý', active: pathname.startsWith('/gop-y') },
      { to: '/huong-dan', icon: <CircleHelp size={17} />, label: 'Hướng dẫn', active: pathname.startsWith('/huong-dan') },
      { to: '/settings/account', icon: <UserRound size={17} />, label: 'Tài khoản và agent', active: pathname.startsWith('/settings') },
    ] },
  ] : [
    { label: null, links: [{ to: '/', icon: <House size={17} />, label: text('Hôm nay', 'Today'), active: pathname === '/' }] },
    {
      label: text('Việc trong ngày', 'Daily work'),
      links: [
        { to: '/reports', icon: <FileText size={17} />, label: text('Báo cáo ngày', 'Daily reports'), active: pathname.startsWith('/reports'), count: 'reports' },
        { to: '/approvals', icon: <ClipboardCheck size={17} />, label: text('Chờ phê duyệt', 'Pending approval'), active: pathname.startsWith('/approvals'), count: 'approvals' },
        { to: '/planning', icon: <CalendarDays size={17} />, label: 'Daily Planning', active: pathname.startsWith('/planning') },
        { to: '/nghiem-thu', icon: <BadgeCheck size={17} />, label: text('Nghiệm thu', 'Acceptance'), active: pathname.startsWith('/nghiem-thu') },
        { to: '/viec', icon: <Columns3 size={17} />, label: text('Việc', 'Work'), active: pathname.startsWith('/viec') && !pathname.startsWith('/viec-') },
        // An owner or the CTO who is also a member has their own day, like any Developer.
        ...(user.member_id ? [{ to: '/viec-cua-toi', icon: <ListChecks size={17} />, label: text('Việc của tôi', 'My work'), active: pathname.startsWith('/viec-cua-toi') }] : []),
      ],
    },
    {
      label: text('Tra cứu', 'Browse'),
      links: [
        { to: '/projects', icon: <UserRound size={17} />, label: text('Dự án', 'Projects'), active: pathname.startsWith('/projects') },
        { to: '/gop-y', icon: <MessageSquarePlus size={17} />, label: text('Góp ý', 'Feedback'), active: pathname.startsWith('/gop-y') },
        { to: '/tuan-qua', icon: <CalendarRange size={17} />, label: text('Tuần qua', 'Last week'), active: pathname.startsWith('/tuan-qua') },
        { to: '/intakes', icon: <List size={17} />, label: text('Tất cả Intake', 'All Intake'), active: pathname.startsWith('/intakes') && pathname !== '/intakes/new' },
        { to: '/meetings', icon: <MessagesSquare size={17} />, label: text('Cuộc họp', 'Meetings'), active: pathname.startsWith('/meetings') },
        { to: '/huong-dan', icon: <CircleHelp size={17} />, label: text('Hướng dẫn', 'Guide'), active: pathname.startsWith('/huong-dan') },
      ],
    },
  ]
  // With the Beta flag off, the Beta areas leave the menu (their routes answer "not found").
  const groups = groups0.map((group) => ({ ...group, links: group.links.filter((link) => betaOn || !isBetaPath(link.to)) }))
  // The private space belongs to the CTO role (ADR-0031): one entry that opens its three pages.
  const privateLinks = user.role === 'CTO' && betaOn ? [
    { to: '/rieng', icon: <Lightbulb size={17} />, label: 'Kho ý tưởng', active: pathname === '/rieng' || pathname.startsWith('/rieng/y/') },
    { to: '/rieng/giong', icon: <UserRound size={17} />, label: 'Giọng của tôi', active: pathname === '/rieng/giong' },
    { to: '/rieng/nguon', icon: <Eye size={17} />, label: 'Nguồn theo dõi', active: pathname === '/rieng/nguon' },
  ] : []
  const inPrivate = pathname.startsWith('/rieng')
  const togglePrivate = () => { try { localStorage.setItem(PRIVATE_OPEN_KEY, privateOpen ? '0' : '1') } catch { /* no memory in a private window */ } setPrivateOpen(!privateOpen) }
  const showPrivate = privateOpen || inPrivate || collapsed
  const person = user.display_name?.trim() && user.display_name.trim() !== user.email.split('@')[0] ? user.display_name.trim() : user.email
  const initials = person.split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((word) => word[0]).join('').toUpperCase()

  return (
    <div className={`app-shell ${collapsed ? 'nav-collapsed' : ''}`}>
      <aside className={`sidebar ${menuOpen ? 'sidebar-open' : ''}`}>
        <div className="sidebar-head">
          <div className="brand"><img className="brand-mark" src="/icon.svg" alt="" /><span className="nav-text"><strong>Private Intake</strong></span></div>
        </div>
        <nav aria-label={text('Điều hướng chính', 'Main navigation')}>
          {groups.map((group) => (
            <div className="nav-group" key={group.label ?? 'main'}>
              {group.label && <div className="nav-group-label nav-text">{group.label}</div>}
              {group.links.map(({ to, icon, label, active, count }) => (
                <Link key={to} to={to} className={active ? 'active' : undefined} aria-current={active ? 'page' : undefined} title={collapsed ? label : undefined} onClick={() => setMenuOpen(false)}>
                  <span className="nav-icon" aria-hidden="true">{icon}</span><span className="nav-text">{label}</span>{isBetaPath(to) && <span className="nav-beta nav-text">Beta</span>}{count && <NavCount kind={count} />}
                </Link>
              ))}
            </div>
          ))}
          {privateLinks.length > 0 && (
            <div className="nav-group nav-private">
              {!collapsed && (
                <button type="button" className={`nav-toggle${inPrivate ? ' active' : ''}`} aria-expanded={showPrivate} onClick={togglePrivate}>
                  <span className="nav-icon" aria-hidden="true"><Lock size={17} /></span><span className="nav-text">Riêng</span><ChevronDown size={14} className={`nav-chevron${showPrivate ? ' is-open' : ''}`} aria-hidden="true" />
                </button>
              )}
              {showPrivate && privateLinks.map(({ to, icon, label, active }) => (
                <Link key={to} to={to} className={`nav-sub${active ? ' active' : ''}`} aria-current={active ? 'page' : undefined} title={collapsed ? label : undefined} onClick={() => setMenuOpen(false)}>
                  <span className="nav-icon" aria-hidden="true">{icon}</span><span className="nav-text">{label}</span>{isBetaPath(to) && <span className="nav-beta nav-text">Beta</span>}
                </Link>
              ))}
            </div>
          )}
        </nav>
      </aside>
      <div className="app-content">
        <header className="topbar">
          <button className="menu-button" onClick={() => setMenuOpen(!menuOpen)} aria-label={menuOpen ? text('Đóng menu', 'Close menu') : text('Mở menu', 'Open menu')}>{menuOpen ? <X size={20} /> : <Menu size={20} />}</button>
          <button className="icon-button collapse-button" type="button" onClick={toggleCollapsed} aria-label={collapsed ? text('Mở rộng thanh bên', 'Expand sidebar') : text('Thu gọn thanh bên', 'Collapse sidebar')} aria-pressed={collapsed}><PanelLeft size={17} /></button>
          <div className="topbar-title" ref={setTitleSlot} />
          <strong className="topbar-fallback">{pageName}</strong>
          <div className="topbar-action" ref={setActionSlot} />
          <PendingRecordings />
          <RecordingIndicator />
          {user.role !== 'DEVELOPER' && !marketing && <Link to="/intakes/new" className="button button-primary button-small topbar-quick" title={text('Dán tin nhắn, email hay ghi chú của khách', 'Paste a customer message, email, or note')}><Plus size={15} aria-hidden="true" /> {text('Tạo Intake', 'Create Intake')}</Link>}
          <Link to="/viec-rieng?them=1" className="button button-secondary button-small topbar-quick" title="Việc của mình ngoài dự án; chỉ mình thấy"><ListChecks size={15} aria-hidden="true" /> Việc riêng</Link>
          <QuickCreate />
          <QuickSearch />
          <ChangelogButton />
          <AlertBell />
          {user.role === 'CTO' && <Link to="/settings" className={`icon-button topbar-settings${pathname.startsWith('/settings') ? ' active' : ''}`} aria-label={text('Cài đặt', 'Settings')} title={text('Cài đặt', 'Settings')}><Settings size={17} /></Link>}
          {commandsOpen && <AgentCommandsSheet onClose={() => setCommandsOpen(false)} />}
          <UserMenu onCommands={() => setCommandsOpen(true)} person={person} initials={initials} role={user.role === 'CTO' ? text('CTO · mọi dự án', 'CTO · all projects') : user.role === 'DEVELOPER' ? 'Developer' : `Project Owner${user.project_ids && user.project_ids.length > 0 ? text(` · ${user.project_ids.length} dự án`, ` · ${user.project_ids.length} projects`) : ''}`} onSignOut={signOut} />
        </header>
        {menuOpen && <button className="sidebar-backdrop" onClick={() => setMenuOpen(false)} aria-label={text('Đóng menu', 'Close menu')} />}
        <div className="app-body">
          <main className="page"><TopBarSlots.Provider value={slots}><Outlet context={{ setRightPanel } satisfies ShellContext} /></TopBarSlots.Provider></main>
          {rightPanel && (
            <aside className="right-panel" aria-label={rightPanel.title}>
              <header><h2>{rightPanel.title}</h2><button className="icon-button" type="button" onClick={rightPanel.onClose} aria-label="Đóng bảng cài đặt"><X size={17} /></button></header>
              <div className="right-panel-body">{rightPanel.content}</div>
            </aside>
          )}
        </div>
      </div>
    </div>
  )
}

// Approving straight from Daily Planning is the shortcut for urgent work. This shows how often it is taken.
function ApprovalSources() {
  const sources = useQuery({ queryKey: ['approval-sources'], queryFn: () => api<ApprovalSourceWeek[]>('/approvals/sources?weeks=4') })
  const weeks = sources.data || []
  if (weeks.every((week) => week.from_queue + week.from_planning === 0)) return null
  const most = Math.max(...weeks.map((week) => week.from_queue + week.from_planning), 1)
  const current = weeks[0]
  const currentTotal = current.from_queue + current.from_planning
  const mostlyShortcut = currentTotal >= 4 && current.from_planning * 2 > currentTotal
  return (
    <section className="panel approval-sources">
      <div className="panel-heading"><div><h2>Yêu cầu được duyệt ở đâu</h2></div><span className="approval-legend"><i className="from-queue" /> Hàng chờ phê duyệt <i className="from-planning" /> Thẳng từ Daily Planning</span></div>
      <ul>
        {weeks.map((week, index) => {
          const total = week.from_queue + week.from_planning
          return (
            <li key={week.week_start}>
              <span>{index === 0 ? 'Tuần này' : `Tuần ${formatDay(week.week_start)}`}</span>
              <div className="approval-bar" role="img" aria-label={`${week.from_queue} từ hàng chờ, ${week.from_planning} từ Daily Planning`}>
                {week.from_queue > 0 && <i className="from-queue" style={{ width: `${(week.from_queue / most) * 100}%` }} />}
                {week.from_planning > 0 && <i className="from-planning" style={{ width: `${(week.from_planning / most) * 100}%` }} />}
              </div>
              <small>{total === 0 ? 'Chưa duyệt yêu cầu nào' : `${total} yêu cầu · ${week.from_planning} từ Planning (${Math.round((week.from_planning / total) * 100)}%)`}</small>
            </li>
          )
        })}
      </ul>
      {mostlyShortcut && <p className="notice notice-warn">Tuần này hơn nửa số yêu cầu được duyệt thẳng từ Daily Planning. Lối này dành cho việc gấp; nếu thành thói quen thì hàng chờ phê duyệt không còn tác dụng sàng lọc.</p>}
    </section>
  )
}

const readinessText: Record<string, string> = { READY: 'Đủ cơ sở', MISSING: 'Thiếu cơ sở', NO_WORK: 'Không có việc hôm qua' }

function nextDay(value: string) {
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day + 1))
  return date.toISOString().slice(0, 10)
}

const names = (list: string[]) => (list.length === 0 ? 'không' : list.length <= 3 ? list.join(', ') : `${list.slice(0, 3).join(', ')} +${list.length - 3}`)
const hours = (value: number) => (Number.isInteger(value) ? `${value}` : value.toFixed(1))

// What went on too long, in words, for the bell (thresholds in ADR-0052).
function overdueText(board: PlanningOverview) {
  const sum = (key: keyof PlanningOverviewProject['overdue']) => board.projects.reduce((total, row) => total + row.overdue[key], 0)
  const parts = [
    ...(sum('approvals') > 0 ? [`${sum('approvals')} chờ duyệt quá 24 giờ`] : []),
    ...(sum('waiting') > 0 ? [`${sum('waiting')} chờ phân công quá 2 ngày`] : []),
    ...(sum('work_log') > 0 ? [`${sum('work_log')} lịch sử xử lý chờ xác nhận quá 1 ngày`] : []),
    ...(sum('p0_open') > 0 ? [`${sum('p0_open')} Issue P0 mở quá 1 ngày`] : []),
  ]
  return `${parts.join(' · ')}.`
}

const minutesText = (value: number) => (value >= 60 ? `${Math.floor(value / 60)} giờ ${value % 60} phút` : `${value} phút`)
const peopleStateText: Record<PeopleDayPerson['state'], string> = { OVER: 'Quá giờ', FREE: 'Còn trống', OK: 'Đủ', OFF: 'Nghỉ' }

// The CTO's lines under the board: minutes spent running the team, and how far the server is behind main (FR-UI-15).
function CtoLines({ time }: { time: CtoTime | null }) {
  const changelog = useQuery({ queryKey: ['changelog'], queryFn: () => api<Changelog>('/changelog'), staleTime: 5 * 60_000 })
  const [copied, setCopied] = useState(false)
  const behind = changelog.data?.behind ?? null
  const sha = changelog.data?.build.sha || ''
  const command = 'bash scripts/deploy.sh'
  return (
    <section className="today-cto-lines" aria-label="Dành cho CTO">
      {time && (
        <p><Timer size={14} aria-hidden="true" /><span>Điều hành hôm nay <strong>{minutesText(time.today_minutes)}</strong> ({time.actions_today} thao tác) · trung bình 7 ngày <strong>{minutesText(time.avg7_minutes)}</strong></span><small>đo theo thao tác để lại dấu trong app, không tính thời gian đọc; mục tiêu 2 giờ/ngày</small></p>
      )}
      {behind !== null && (
        <p className={behind > 0 ? 'is-behind' : undefined}><Rocket size={14} aria-hidden="true" />
          <span>{behind > 0 ? <><strong>{behind} mục mới</strong> chưa deploy · bản đang chạy {sha.slice(0, 7)}</> : <>Server đang chạy bản mới nhất ({sha.slice(0, 7)})</>}</span>
          {behind > 0 && <button type="button" className="text-button" title="Chép lệnh rồi chạy trong thư mục repo trên server: pull, build, up, kiểm sức khỏe" onClick={() => { void navigator.clipboard.writeText(command).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 2000) }) }}><Copy size={13} aria-hidden="true" /> {copied ? 'Đã chép' : `Chép "${command}"`}</button>}
        </p>
      )}
    </section>
  )
}

// One row per person for a day, across every project's plan (FR-PLAN-28).
function PeopleBoard({ day }: { day: string }) {
  const people = useQuery({ queryKey: ['planning-people', day], queryFn: () => api<PeopleDay>(`/planning/people/${day}`), refetchInterval: 60_000 })
  if (people.isLoading) return <LoadingBlock />
  if (people.error) return <ErrorNotice error={people.error} onRetry={() => { void people.refetch() }} />
  const rows = people.data?.people || []
  if (rows.length === 0) return <EmptyState icon={<UserRound size={20} />} title="Chưa có nhân sự đang hoạt động" text="Thêm người ở Cài đặt > Nhân sự." />
  return (
    <div className="today-board people-board">
      <table>
        <thead><tr><th>Người</th><th>Tình trạng</th><th>Đã xếp / có</th><th>Theo dự án</th></tr></thead>
        <tbody>
          {rows.map((person) => (
            <tr key={person.member_id} className={person.state === 'OVER' ? 'is-p0' : undefined}>
              <td className="board-project"><strong>{person.display_name}</strong></td>
              <td><span className={`people-state people-${person.state.toLowerCase()}`}>{peopleStateText[person.state]}{person.state === 'FREE' ? ` ${hours(person.free_hours)} giờ` : person.state === 'OVER' ? ` +${hours(person.planned_hours - person.available_hours)}` : ''}</span></td>
              <td className={person.state === 'OVER' ? 'board-overdue' : undefined}>{hours(person.planned_hours)}/{hours(person.available_hours)} giờ</td>
              <td>{person.projects.length === 0 ? <span className="text-muted">chưa có việc</span> : person.projects.map((project) => <Link key={project.id} to={`/planning?project=${project.id}&date=${day}`} className="people-project">{project.name} {hours(project.hours)} giờ{project.run_status && ['DRAFT', 'REVIEW_REQUIRED'].includes(project.run_status) ? ' (nháp)' : ''}</Link>)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="field-help">Giờ đã xếp cộng qua mọi kế hoạch của ngày, kể cả nháp. "Quá giờ" là người được hai dự án xếp quá số giờ có; "Còn trống" là còn giờ chưa có việc.</p>
    </div>
  )
}

// The first page: every project on one line, and first of all whether the data behind the day is complete enough
// to review it. Each cell opens the page where that number is dealt with.
// A person's own tasks: outside any project, seen by nobody else, their hours off the day's free hours (FR-PER-01..05).
const personalStatusLabels: Record<string, string> = { PLANNED: 'Chưa làm', DONE: 'Xong', SKIPPED: 'Bỏ qua', DELEGATED: 'Đã giao' }
const repeatWeekdays = ['Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ nhật']

// Hand a task to a staff member: it becomes support work in their plan for a day (FR-PER-06).
function DelegateDialog({ task, today, onDone, onCancel }: { task: PersonalTask; today: string; onDone: () => void; onCancel: () => void }) {
  const { user } = useAuth()
  const members = useQuery({ queryKey: ['settings-members'], queryFn: () => api<WorkforceMember[]>('/planning/members?include_inactive=true') })
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const allowed = (projectId: string) => user?.project_ids == null || user.project_ids.includes(projectId)
  const people = (members.data || []).filter((member) => member.status === 'ACTIVE' && member.project_mappings.some((mapping) => mapping.active && allowed(mapping.project_id)))
  const [memberId, setMemberId] = useState('')
  const [projectId, setProjectId] = useState('')
  const [day, setDay] = useState(task.task_date && task.task_date >= today ? task.task_date : shiftDay(today, 1))
  const [hours, setHours] = useState(String(task.hours || 1))
  const chosen = people.find((member) => member.id === memberId)
  const choices = (chosen?.project_mappings || []).filter((mapping) => mapping.active && allowed(mapping.project_id)).map((mapping) => projects.data?.find((project) => project.id === mapping.project_id)).filter((project): project is Project => Boolean(project && project.kind === 'SOFTWARE'))
  useEffect(() => { if (choices.length === 1) setProjectId(choices[0].id); else if (!choices.some((project) => project.id === projectId)) setProjectId('') }, [memberId, choices.length])
  const give = useMutation({
    mutationFn: () => api<PersonalTask>(`/personal-tasks/${task.id}/delegate`, { method: 'POST', body: JSON.stringify({ member_id: memberId, project_id: projectId, task_date: day, hours: Number(hours) || null }) }),
    onSuccess: onDone,
  })
  return (
    <ConfirmDialog title={`Giao "${task.title}" cho ai?`} confirmLabel="Giao việc" busyLabel="Đang giao…" busy={give.isPending} error={give.error ?? undefined} plain onConfirm={() => { if (memberId && projectId && day) give.mutate() }} onCancel={onCancel}>
      <div className="delegate-form">
        <label>Nhân sự<select value={memberId} onChange={(event) => setMemberId(event.target.value)}><option value="">Chọn người</option>{people.map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>
        <label>Kế hoạch của dự án<select value={projectId} onChange={(event) => setProjectId(event.target.value)} disabled={!memberId}><option value="">Chọn dự án</option>{choices.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
        <label>Ngày<input type="date" value={day} min={today} onChange={(event) => setDay(event.target.value)} /></label>
        <label>Giờ<input type="number" min={0.5} max={24} step={0.5} value={hours} onChange={(event) => setHours(event.target.value)} /></label>
        <p className="field-help">Việc vào kế hoạch ngày của người đó như việc hỗ trợ (không Issue), trừ giờ của họ; kế hoạch ngày đó phải đang mở. Việc riêng của bạn chuyển thành "Đã giao".</p>
      </div>
    </ConfirmDialog>
  )
}
// The Eisenhower matrix: what to do with each quadrant, and the flags that put a task there.
const quadrants: { id: 1 | 2 | 3 | 4; label: string; hint: string; important: boolean; urgent: boolean }[] = [
  { id: 1, label: 'Làm ngay', hint: 'Quan trọng và khẩn', important: true, urgent: true },
  { id: 2, label: 'Lên lịch', hint: 'Quan trọng, chưa khẩn: chọn ngày', important: true, urgent: false },
  { id: 3, label: 'Ủy quyền', hint: 'Khẩn nhưng không quan trọng', important: false, urgent: true },
  { id: 4, label: 'Bỏ', hint: 'Không nhắc; tự lưu trữ sau 7 ngày', important: false, urgent: false },
]
const weekdayAbbr = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']
const shortDay = (value: string) => { const d = new Date(`${value}T00:00:00`); return `${weekdayAbbr[(d.getDay() + 6) % 7]} ${d.getDate()}/${d.getMonth() + 1}` }
const shiftDay = (value: string, days: number) => { const d = new Date(`${value}T00:00:00`); d.setDate(d.getDate() + days); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }

function usePersonalTasks(start: string, end: string) {
  return useQuery({ queryKey: ['personal-tasks', start, end], queryFn: () => api<PersonalTask[]>(`/personal-tasks?from=${start}&to=${end}`) })
}

function usePersonalRefresh() {
  const queryClient = useQueryClient()
  return () => { void queryClient.invalidateQueries({ queryKey: ['personal-tasks'] }); void queryClient.invalidateQueries({ queryKey: ['personal-matrix'] }); void queryClient.invalidateQueries({ queryKey: ['planning-overview'] }) }
}

// One line: tick, the title, when; the buttons show on hover (or tap). `today` tells which day label to leave out.
function PersonalTaskRow({ task, today, onChanged, cellActions, badge = 'quadrant' }: { task: PersonalTask; today: string; onChanged: () => void; cellActions?: boolean; badge?: 'quadrant' | 'hours' }) {
  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<PersonalTask>(`/personal-tasks/${task.id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    onSuccess: onChanged,
  })
  const remove = useMutation({ mutationFn: () => api(`/personal-tasks/${task.id}`, { method: 'DELETE' }), onSuccess: onChanged })
  const { user } = useAuth()
  const [delegating, setDelegating] = useState(false)
  const done = task.status === 'DONE'
  const delegated = task.status === 'DELEGATED'
  const isToday = task.task_date === today
  const when = [
    task.task_date == null ? 'chưa có ngày' : isToday ? '' : task.task_date < today ? `tồn từ ${shortDay(task.task_date)}` : shortDay(task.task_date),
    task.start_time, badge === 'quadrant' && task.hours > 0 ? hoursText(task.hours) : '', task.remind_at ? `nhắc ${task.remind_at}` : '', task.repeat_label || '',
    task.rollover_count > 2 ? `dời ${task.rollover_count} lần` : '', task.status === 'SKIPPED' ? personalStatusLabels.SKIPPED : '',
    delegated ? `đã giao cho ${task.delegated_member_name || 'nhân sự'}` : '',
  ].filter(Boolean).join(' · ')
  return (
    <li className={`personal-task is-${task.status.toLowerCase()} q-${task.quadrant}${isToday ? ' is-today' : ''}${task.rollover_count > 2 ? ' is-rolled' : ''}`} draggable={!delegated} onDragStart={(event) => { event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', task.id) }}>
      {delegating && <DelegateDialog task={task} today={today} onDone={() => { setDelegating(false); onChanged() }} onCancel={() => setDelegating(false)} />}
      <label className="personal-check"><input type="checkbox" checked={done} aria-label={`Xong: ${task.title}`} disabled={update.isPending || delegated} onChange={(event) => update.mutate({ status: event.target.checked ? 'DONE' : 'PLANNED' })} /></label>
      <div className="personal-body" title={task.note || undefined}>
        <strong>{badge === 'hours' ? <span className={`hours-mark q-${task.quadrant}`} title={task.hours > 0 ? `${hoursText(task.hours)} dự kiến` : 'chưa ước lượng giờ'}>{task.hours > 0 ? hoursText(task.hours) : '–'}</span> : <span className={`quadrant-mark q-${task.quadrant}`} title={`${task.quadrant_label}: ${task.important ? 'quan trọng' : 'không quan trọng'}, ${task.urgent_effective ? 'khẩn' : 'không khẩn'}${task.urgent == null ? ' (tự tính theo ngày)' : ''}`}>{task.quadrant}</span>}{task.title}</strong>
        {when && <small>{when}</small>}
      </div>
      <div className="personal-actions">
        {delegated && task.plan && <Link className="text-button is-action" to={`/planning?date=${task.plan.plan_date}&project=${task.plan.project_id}`}>Xem kế hoạch</Link>}
        {!delegated && task.status === 'PLANNED' && user?.role !== 'DEVELOPER' && (task.quadrant === 3 || cellActions) && <button type="button" className="text-button is-action" disabled={update.isPending} onClick={() => setDelegating(true)}>Giao cho…</button>}
        {task.repeat_rule && !delegated && <button type="button" className="text-button" title={task.repeat_label || ''} disabled={update.isPending} onClick={() => { if (window.confirm('Dừng lặp việc này? Các lần đã tạo giữ nguyên.')) update.mutate({ repeat_rule: '' }) }}>Dừng lặp</button>}
        {cellActions && task.quadrant === 1 && !isToday && !delegated && <button type="button" className="text-button is-action" disabled={update.isPending} onClick={() => update.mutate({ task_date: today })}>Hôm nay</button>}
        {cellActions && task.quadrant === 1 && task.task_date !== shiftDay(today, 1) && <button type="button" className="text-button is-action" disabled={update.isPending} onClick={() => update.mutate({ task_date: shiftDay(today, 1) })}>Ngày mai</button>}
        {cellActions && (task.quadrant === 2 || task.quadrant === 4) && <input type="date" className="personal-date" aria-label={`Ngày cho ${task.title}`} value={task.task_date || ''} onChange={(event) => update.mutate({ task_date: event.target.value || null })} />}
        {!delegated && <button type="button" className={`text-button${task.important ? ' is-on' : ''}`} title={task.important ? 'Bỏ đánh dấu quan trọng' : 'Đánh dấu quan trọng'} disabled={update.isPending} onClick={() => update.mutate({ important: !task.important })}>{task.important ? 'Quan trọng' : 'Thường'}</button>}
        {!delegated && <button type="button" className={`text-button${task.urgent_effective ? ' is-on' : ''}`} title={task.urgent == null ? 'Khẩn tự tính theo ngày; bấm để ghi đè' : 'Bấm để đổi; giữ Shift để về tự tính'} disabled={update.isPending} onClick={(event) => update.mutate({ urgent: event.shiftKey ? null : !task.urgent_effective })}>{task.urgent_effective ? 'Khẩn' : 'Không khẩn'}{task.urgent == null ? '' : ' *'}</button>}
        {task.status === 'PLANNED' && <button type="button" className="text-button" disabled={update.isPending} onClick={() => update.mutate({ status: 'SKIPPED' })}>Bỏ qua</button>}
        {task.status === 'SKIPPED' && <button type="button" className="text-button" disabled={update.isPending} onClick={() => update.mutate({ status: 'PLANNED' })}>Làm lại</button>}
        <button type="button" className="text-button" disabled={remove.isPending} onClick={() => { if (window.confirm(`Xóa việc "${task.title}"?`)) remove.mutate() }}>Xóa</button>
      </div>
    </li>
  )
}

// Type, Enter: today, one hour, urgency by the date; "!" first marks it important. The details fold out when needed.
function PersonalQuickAdd({ today, autoFocus, onAdded }: { today: string; autoFocus?: boolean; onAdded: () => void }) {
  const [title, setTitle] = useState('')
  const [more, setMore] = useState(false)
  const [taskDate, setTaskDate] = useState<string>(today)
  const [hours, setHours] = useState('1')
  const [startTime, setStartTime] = useState('')
  const [remindAt, setRemindAt] = useState('')
  const [note, setNote] = useState('')
  const [urgent, setUrgent] = useState<'auto' | 'yes' | 'no'>('auto')
  const [repeat, setRepeat] = useState<'none' | 'WEEKLY' | 'MONTHLY'>('none')
  const [repeatOn, setRepeatOn] = useState('0')
  const [error, setError] = useState<unknown>()
  const important = title.trimStart().startsWith('!')
  const create = useMutation({
    mutationFn: () => api<PersonalTask>('/personal-tasks', { method: 'POST', body: JSON.stringify({
      title: title.trim().replace(/^!\s*/, ''), task_date: taskDate || null, hours: Number(hours) || 0, start_time: startTime || null, remind_at: remindAt || null,
      note: note.trim() || null, important, urgent: urgent === 'auto' ? null : urgent === 'yes', repeat_rule: repeat === 'none' ? null : `${repeat}:${repeatOn}`,
    }) }),
    onMutate: () => setError(undefined),
    onSuccess: () => { setTitle(''); setHours('1'); setStartTime(''); setRemindAt(''); setNote(''); setUrgent('auto'); setRepeat('none'); setRepeatOn('0'); setTaskDate(today); onAdded() },
    onError: setError,
  })
  return (
    <form className={`personal-quick${more ? ' is-open' : ''}`} onSubmit={(event) => { event.preventDefault(); if (title.trim().replace(/^!\s*/, '')) create.mutate() }}>
      <div className="personal-quick-line">
        <input value={title} autoFocus={autoFocus} maxLength={201} onChange={(event) => setTitle(event.target.value)} placeholder='Việc riêng, Enter để thêm hôm nay 1 giờ; gõ "!" đầu dòng nếu quan trọng' aria-label="Việc riêng mới" />
        <button type="button" className="text-button" aria-expanded={more} onClick={() => setMore(!more)}>{more ? 'Ẩn chi tiết' : 'Thêm chi tiết'}</button>
        <button className="button button-primary button-small" type="submit" disabled={!title.trim().replace(/^!\s*/, '') || create.isPending}>{create.isPending ? 'Đang thêm…' : 'Thêm'}</button>
      </div>
      {more && (
        <div className="personal-quick-more">
          <label>Ngày<input type="date" value={taskDate} onChange={(event) => setTaskDate(event.target.value)} /><button type="button" className="text-button" onClick={() => setTaskDate('')}>Chưa có ngày</button></label>
          <label>Giờ<input type="number" min={0} max={24} step={0.5} value={hours} onChange={(event) => setHours(event.target.value)} /></label>
          <label>Bắt đầu<input type="time" value={startTime} onChange={(event) => setStartTime(event.target.value)} /></label>
          <label>Nhắc lúc<input type="time" value={remindAt} onChange={(event) => setRemindAt(event.target.value)} /></label>
          <label>Khẩn cấp<select value={urgent} onChange={(event) => setUrgent(event.target.value as 'auto' | 'yes' | 'no')}><option value="auto">Tự tính theo ngày</option><option value="yes">Khẩn</option><option value="no">Không khẩn</option></select></label>
          <label>Lặp<span className="repeat-pick"><select value={repeat} onChange={(event) => { const next = event.target.value as 'none' | 'WEEKLY' | 'MONTHLY'; setRepeat(next); setRepeatOn(next === 'MONTHLY' ? '1' : '0') }}><option value="none">Không</option><option value="WEEKLY">Hằng tuần</option><option value="MONTHLY">Hằng tháng</option></select>
            {repeat === 'WEEKLY' && <select value={repeatOn} aria-label="Thứ" onChange={(event) => setRepeatOn(event.target.value)}>{repeatWeekdays.map((label, index) => <option key={label} value={String(index)}>{label}</option>)}</select>}
            {repeat === 'MONTHLY' && <select value={repeatOn} aria-label="Ngày trong tháng" onChange={(event) => setRepeatOn(event.target.value)}>{Array.from({ length: 31 }, (_, index) => <option key={index + 1} value={String(index + 1)}>Ngày {index + 1}</option>)}</select>}
          </span></label>
          <label className="personal-note">Ghi chú<input value={note} maxLength={2000} onChange={(event) => setNote(event.target.value)} placeholder="tùy ý" /></label>
        </div>
      )}
      {error != null && <ErrorNotice error={error} />}
    </form>
  )
}

function PersonalTodayPanel({ day }: { day: string }) {
  const tasks = usePersonalTasks(day, day)
  const refresh = usePersonalRefresh()
  const rows = tasks.data || []
  if (tasks.isLoading || rows.length === 0) return null
  const open = rows.filter((row) => row.status === 'PLANNED')
  return (
    <section className="panel personal-panel" aria-label="Việc riêng hôm nay">
      <div className="panel-heading"><div><h2>Việc riêng hôm nay</h2><p>{open.length === 0 ? 'Đã xong hết' : `${open.length} việc còn lại · ${hoursText(open.reduce((sum, row) => sum + row.hours, 0))}`}. Chỉ bạn thấy danh sách này.</p></div><Link className="button button-secondary button-small" to="/viec-rieng">Tất cả việc riêng</Link></div>
      <ul className="personal-list">{rows.map((task) => <PersonalTaskRow key={task.id} task={task} today={day} onChanged={refresh} />)}</ul>
    </section>
  )
}

// The 2 by 2: drop a task on a quadrant to set its flags; today's work first in each cell.
function PersonalMatrix({ tasks, today, onChanged, only }: { tasks: PersonalTask[]; today: string; onChanged: () => void; only: number | null }) {
  const [over, setOver] = useState<number | null>(null)
  const move = useMutation({
    mutationFn: ({ id, important, urgent }: { id: string; important: boolean; urgent: boolean }) => api(`/personal-tasks/${id}`, { method: 'PATCH', body: JSON.stringify({ important, urgent }) }),
    onSuccess: onChanged,
  })
  // Given-away tasks stay visible, dimmed, in the quadrant they left from; only planned ones count in the hours.
  const open = tasks.filter((task) => task.status === 'PLANNED' || task.status === 'DELEGATED')
  const cellOf = (task: PersonalTask) => (task.status === 'DELEGATED' ? task.done_quadrant || task.quadrant : task.quadrant)
  return (
    <div className={`personal-matrix${only ? ' is-focused' : ''}`} role="grid" aria-label="Ma trận Eisenhower">
      {quadrants.filter((cell) => !only || cell.id === only).map((cell) => {
        const rows = open.filter((task) => cellOf(task) === cell.id)
        const planned = rows.filter((task) => task.status === 'PLANNED')
        return (
          <section key={cell.id} className={`matrix-cell q-${cell.id}${over === cell.id ? ' is-over' : ''}`} role="gridcell" aria-label={cell.label}
            onDragOver={(event) => { event.preventDefault(); setOver(cell.id) }} onDragLeave={() => setOver(null)}
            onDrop={(event) => { event.preventDefault(); setOver(null); const id = event.dataTransfer.getData('text/plain'); if (id) move.mutate({ id, important: cell.important, urgent: cell.urgent }) }}>
            <header><strong><span className={`quadrant-mark q-${cell.id}`}>{cell.id}</span>{cell.label}</strong><small>{cell.hint} · {planned.length} việc · {hoursText(planned.reduce((sum, row) => sum + row.hours, 0))}{rows.length > planned.length ? ` · ${rows.length - planned.length} đã giao` : ''}</small></header>
            {rows.length === 0 ? <p className="matrix-empty">Kéo việc vào đây</p> : <ul className="personal-list">{rows.map((task) => <PersonalTaskRow key={task.id} task={task} today={today} onChanged={onChanged} cellActions badge="hours" />)}</ul>}
          </section>
        )
      })}
    </div>
  )
}

// A Developer's day on the web (FR-PLAN-34): the same list the agent reads with get_my_day, each piece with its status.
// A member proposes work for a day (FR-PLAN-35): an Issue, an Intake code or words; the Project Owner places it.
function ProposeWorkDialog({ day, projects, onDone, onCancel }: { day: string; projects: { id: string; code: string; name: string }[]; onDone: (text: string) => void; onCancel: () => void }) {
  const [project, setProject] = useState(projects[0]?.code || '')
  const [date, setDate] = useState(day)
  const [issue, setIssue] = useState('')
  const [text, setText] = useState('')
  const [hours, setHours] = useState('2')
  const [slot, setSlot] = useState<'' | PlanningSlot>('')
  const send = useMutation({
    mutationFn: () => api<PlanningCandidate & { created: boolean; project_name: string }>('/planning/proposals', { method: 'POST', body: JSON.stringify({
      project, plan_date: date, issue: issue.trim() || null, intake: /^[A-Z]{2,6}-\d{2}W\d{2}-\d{3}$/i.test(text.trim()) ? text.trim() : null,
      text: text.trim() || null, hours: Number(hours) > 0 ? Number(hours) : null, slot: slot || null,
    }) }),
    onSuccess: (result) => onDone(result.created ? `Đã gửi đề xuất "${result.title}" cho kế hoạch ${changelogDay(date)} của ${result.project_name}; Project Owner sẽ xếp hoặc bỏ qua.` : `Đề xuất "${result.title}" cho ${changelogDay(date)} đã có từ trước.`),
  })
  const ready = Boolean(project) && (issue.trim().length > 0 || text.trim().length >= 3)
  return (
    <ConfirmDialog title="Đề xuất việc cho một ngày" confirmLabel="Gửi đề xuất" busyLabel="Đang gửi…" busy={send.isPending} error={send.error} plain onConfirm={() => { if (ready) send.mutate() }} onCancel={onCancel}>
      <div className="propose-form">
        <label>Dự án<select value={project} onChange={(event) => setProject(event.target.value)}>{projects.map((row) => <option key={row.id} value={row.code}>{row.name}</option>)}</select></label>
        <label>Ngày<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>
        <label>Số Issue (nếu có)<input value={issue} onChange={(event) => setIssue(event.target.value)} placeholder="#12" /></label>
        <label>Việc muốn làm, hoặc mã Intake<textarea rows={2} value={text} onChange={(event) => setText(event.target.value)} placeholder="vd. Sửa lỗi đăng nhập trên iOS, hoặc SAV-26W42-003" /></label>
        <div className="propose-row">
          <label>Giờ dự kiến<input inputMode="decimal" value={hours} onChange={(event) => setHours(event.target.value)} /></label>
          <label>Buổi<select value={slot} onChange={(event) => setSlot(event.target.value as '' | PlanningSlot)}><option value="">Tùy</option><option value="MORNING">Sáng</option><option value="AFTERNOON">Chiều</option></select></label>
        </div>
        <small className="field-help">Việc có Issue vào thẳng danh sách chờ; việc bằng lời chờ Project Owner tạo Issue rồi xếp. Kế hoạch ngày đó đã chốt thì chọn ngày khác.</small>
      </div>
    </ConfirmDialog>
  )
}

function MyDayPage() {
  const [day, setDay] = useState(todayInPlanningTimezone())
  const [proposing, setProposing] = useState(false)
  const [sent, setSent] = useState<string | null>(null)
  const query = useQuery({ queryKey: ['my-day', day], queryFn: () => api<MyDay>(`/planning/my-day/${day}`), refetchInterval: 60_000 })
  const data = query.data
  const today = todayInPlanningTimezone()
  const dayName = day === today ? 'Hôm nay' : day === shiftDay(today, 1) ? 'Ngày mai' : day === shiftDay(today, -1) ? 'Hôm qua' : formatDay(day)
  return (
    <div className="page">
      <AgentHint command="today" />
      <PageHeader title="Việc của tôi" description={data ? `${data.member} · ${dayName}` : dayName} helper={['Việc trong kế hoạch ngày của bạn, ưu tiên cao trước. Khi hoàn tất, tại thẻ việc chọn trạng thái "Xong", rồi thêm link/commit/MR nếu có. Việc có Issue sẽ tự chuyển vào Nghiệm thu để CTO kiểm.', 'Muốn làm một việc chưa có trong kế hoạch: bấm "Đề xuất việc", Project Owner xếp hoặc bỏ qua.', 'Cuối ngày vẫn gửi báo cáo ngày (trong terminal: /in-end-day).']}
        action={data && data.projects.length > 0 ? <button className="button button-primary" type="button" onClick={() => { setSent(null); setProposing(true) }}><Plus size={16} /> Đề xuất việc</button> : undefined} />
      <PageIntro k="my_day" />
      {sent && <div className="notice notice-success" role="status">{sent}</div>}
      {proposing && data && <ProposeWorkDialog day={day} projects={data.projects} onDone={(text) => { setProposing(false); setSent(text); void query.refetch() }} onCancel={() => setProposing(false)} />}
      <div className="plan-bar">
        <button type="button" className="button button-secondary button-small" onClick={() => setDay(shiftDay(day, -1))}>← Hôm trước</button>
        <input type="date" aria-label="Ngày" value={day} onChange={(event) => setDay(event.target.value)} />
        <button type="button" className="button button-secondary button-small" onClick={() => setDay(shiftDay(day, 1))}>Hôm sau →</button>
        {day !== today && <button type="button" className="text-button" onClick={() => setDay(today)}>Về hôm nay</button>}
        <span className="plan-bar-note plan-bar-right">{data && data.items.length > 0 ? `${data.items.length} việc · ${hoursText(data.items.reduce((sum, item) => sum + item.hours, 0))}` : ''}{data && data.projects.length > 0 && <> <Hint k="myday.propose" /></>}</span>
      </div>
      {query.error != null ? <ErrorNotice error={query.error} onRetry={() => { void query.refetch() }} /> : query.isLoading || !data ? <LoadingBlock /> : data.items.length === 0 ? (
        <div className="panel"><EmptyState icon={<CalendarDays size={20} />} title="Chưa có việc trong kế hoạch" text={data.note || 'Project Owner chưa xếp việc cho ngày này.'} /></div>
      ) : (
        <ul className="my-day-list">
          {data.items.map((item) => (
            <li key={item.assignment_id} className={`panel my-day-item work-${item.work_status.toLowerCase()}${item.accepted_at ? ' is-accepted' : ''}`}>
              <div className="plan-card-top"><PriorityBadge priority={item.priority} /><strong>{item.issue && item.issue_url
                ? <a className="ref-link" href={item.issue_url} target="_blank" rel="noreferrer" title={`Mở chi tiết Issue #${item.issue} để làm`}>#{item.issue} {item.title}</a>
                : <>{item.issue ? `#${item.issue} ` : ''}{item.title}</>}</strong><span className="plan-card-hours">{hoursText(item.hours)}</span></div>
              <div className="plan-card-meta">
                <span>{item.project_name} · {item.slot === 'MORNING' ? 'Sáng' : 'Chiều'}{item.primary ? '' : ' · việc phụ'}{item.plan_closed ? '' : ' · kế hoạch chưa chốt'}{!item.plan_closed && <> <Hint k="myday.plan_open" /></>}</span>
                {item.intake && <span>Intake {item.intake}</span>}
                {item.accepted_at ? <span className="plan-mark work-accepted" title={`CTO nghiệm thu ${formatDate(item.accepted_at)}`}>Đã nghiệm thu</span> : <MyDayStatus item={item} onChanged={() => { void query.refetch() }} />}
              </div>
            </li>
          ))}
        </ul>
      )}
      {data && data.personal.length > 0 && (
        <section className="panel my-day-personal">
          <strong>Việc riêng trong ngày</strong>
          <ul>{data.personal.map((task) => <li key={task.task_id}>{task.title}{task.hours > 0 ? ` · ${hoursText(task.hours)}` : ''}{task.start_time ? ` · ${task.start_time}` : ''} <small>· {task.quadrant_label}</small></li>)}</ul>
          <Link to="/viec-rieng">Mở Việc riêng <ArrowUpRight size={12} /></Link>
        </section>
      )}
    </div>
  )
}

function MyDayStatus({ item, onChanged }: { item: MyDay['items'][number]; onChanged: () => void }) {
  const [said, setSaid] = useState<string | null>(null)
  const [asking, setAsking] = useState(false)
  const [kind, setKind] = useState('LINK')
  const [url, setUrl] = useState('')
  const change = useMutation({
    mutationFn: ({ status, evidence }: { status: WorkStatus; evidence?: { kind: string; url: string }[] }) => api<WorkStatusResult>(`/planning/runs/${item.run_id}/assignments/${item.assignment_id}/work-status`, { method: 'PATCH', body: JSON.stringify({ status, evidence: evidence || [] }) }),
    onSuccess: (result) => { setAsking(false); setUrl(''); setSaid(result.acceptance_queued ? `Đã vào Nghiệm thu${result.evidence_added ? ' kèm bằng chứng' : ''}` : result.evidence_added ? 'Đã ghi bằng chứng' : null); onChanged() },
    onError: (error) => setSaid(formatError(error)),
  })
  // "Done" with an Issue asks what stands behind it: a commit or MR for code, a link for anything else (FR-PLAN-36).
  const pick = (status: WorkStatus) => { if (status === 'DONE' && item.issue) { setAsking(true); return } change.mutate({ status }) }
  const ok = /^https?:\/\//i.test(url.trim())
  return (
    <span className={`work-status-pick work-${item.work_status.toLowerCase()}`} title={item.work_status_note || undefined}>
      <select aria-label="Trạng thái việc" value={asking ? 'DONE' : item.work_status} disabled={change.isPending} onChange={(event) => pick(event.target.value as WorkStatus)}>
        {(Object.keys(workStatusWords) as WorkStatus[]).map((key) => <option key={key} value={key}>{workStatusWords[key]}</option>)}
      </select>
      <Hint k="myday.status" />
      {asking && (
        <span className="evidence-ask">
          <select aria-label="Loại bằng chứng" value={kind} onChange={(event) => setKind(event.target.value)}><option value="LINK">Link tài liệu, video, ảnh</option><option value="COMMIT">Commit</option><option value="MR">MR đã merge</option></select>
          <input aria-label="Link bằng chứng" placeholder="https://… (bằng chứng xong)" value={url} onChange={(event) => setUrl(event.target.value)} />
          <button type="button" className="button button-primary button-small" disabled={!ok || change.isPending} onClick={() => change.mutate({ status: 'DONE', evidence: [{ kind, url: url.trim() }] })}>Xong, kèm bằng chứng</button>
          <button type="button" className="text-button" disabled={change.isPending} onClick={() => change.mutate({ status: 'DONE' })}>Xong, chưa có link</button>
          <button type="button" className="text-button" disabled={change.isPending} onClick={() => { setAsking(false); setUrl('') }}>Thôi</button>
        </span>
      )}
      {said && <small>{said}</small>}
    </span>
  )
}

function PersonalTasksPage() {
  const [params] = useSearchParams()
  const today = todayInPlanningTimezone()
  const [weekOf, setWeekOf] = useState(today)
  const [view, setView] = useState<'matrix' | 'list'>(() => { try { return localStorage.getItem('intake-personal-view') === 'list' ? 'list' : 'matrix' } catch { return 'matrix' } })
  const [only, setOnly] = useState<number | null>(null)
  const [showArchived, setShowArchived] = useState(false)
  const switchView = (next: 'matrix' | 'list') => { try { localStorage.setItem('intake-personal-view', next) } catch { /* private window */ } setView(next) }
  const matrix = useQuery({ queryKey: ['personal-matrix', weekOf], queryFn: () => api<PersonalMatrix>(`/personal-tasks/matrix?week_of=${weekOf}`) })
  const archived = useQuery({ queryKey: ['personal-tasks', 'archived'], queryFn: () => api<PersonalTask[]>('/personal-tasks/archived'), enabled: showArchived })
  const refresh = usePersonalRefresh()
  const data = matrix.data
  const thisWeek = shiftDay(today, -((new Date(`${today}T00:00:00`).getDay() + 6) % 7))
  const isThisWeek = data?.week_start === thisWeek
  const isNextWeek = data?.week_start === shiftDay(thisWeek, 7)
  const byDay = useMemo(() => {
    const groups = new Map<string, PersonalTask[]>()
    for (const row of data?.tasks || []) groups.set(row.task_date || 'chưa có ngày', [...(groups.get(row.task_date || 'chưa có ngày') || []), row])
    return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [data])
  const summary = data?.summary
  return (
    <>
      <PageHeader title="Việc riêng" helper={['Việc của chính bạn ngoài dự án: hành chính, gặp đối tác, học. Không ai khác thấy; đội chỉ thấy giờ trống của bạn giảm đi.', 'Giờ của việc trừ vào giờ còn trống trong kế hoạch ngày. Đặt "Nhắc lúc" thì bot Telegram nhắc riêng bạn đúng giờ, kể cả cuối tuần.', 'Ma trận Eisenhower theo tuần: Quan trọng là bạn đánh dấu; Khẩn tự tính theo ngày (hôm nay, ngày mai, có giờ nhắc) và ghi đè được. Ô 1 Làm ngay, 2 Lên lịch, 3 Ủy quyền, 4 Bỏ (không nhắc, tự lưu trữ sau 7 ngày). Kéo việc giữa các ô.', 'Việc chưa xong cuối ngày tự dời sang ngày làm việc kế tiếp, có đếm số lần. Agent trong terminal thấy việc riêng theo ô trong get_my_day và /in-today.']} />
      {matrix.error != null && <ErrorNotice error={matrix.error} onRetry={() => { void matrix.refetch() }} />}
      {summary && (
        <div className="personal-strip" role="list">
          <button type="button" role="listitem" className={`strip-item${only === null ? ' active' : ''}`} onClick={() => setOnly(null)}><strong>{summary.today_open}</strong><span>việc hôm nay · {hoursText(summary.today_hours)}</span></button>
          {summary.quadrants.map((cell) => <button type="button" role="listitem" key={cell.quadrant} className={`strip-item q-${cell.quadrant}${only === cell.quadrant ? ' active' : ''}`} onClick={() => setOnly(only === cell.quadrant ? null : cell.quadrant)}><strong>{cell.open}</strong><span>{cell.label} · {hoursText(cell.hours)}</span></button>)}
          {summary.rolled_over > 0 && <span role="listitem" className="strip-item is-warn"><strong>{summary.rolled_over}</strong><span>việc dời quá 2 lần</span></span>}
          {summary.undated > 0 && <span role="listitem" className="strip-item is-warn"><strong>{summary.undated}</strong><span>việc chưa có ngày</span></span>}
          {summary.overdue > 0 && <span role="listitem" className="strip-item is-warn"><strong>{summary.overdue}</strong><span>việc tồn từ trước</span></span>}
        </div>
      )}
      <section className="panel personal-panel">
        <PersonalQuickAdd today={today} autoFocus={params.get('them') === '1'} onAdded={refresh} />
        <div className="panel-heading personal-week-heading">
          <div className="personal-week-nav">
            <button type="button" className="icon-button" aria-label="Tuần trước" onClick={() => setWeekOf(shiftDay(weekOf, -7))}><ChevronLeft size={16} /></button>
            <div className="today-tabs" role="tablist"><button type="button" role="tab" aria-selected={isThisWeek} className={isThisWeek ? 'active' : undefined} onClick={() => setWeekOf(today)}>Tuần này</button><button type="button" role="tab" aria-selected={isNextWeek} className={isNextWeek ? 'active' : undefined} onClick={() => setWeekOf(shiftDay(thisWeek, 7))}>Tuần sau</button></div>
            <button type="button" className="icon-button" aria-label="Tuần sau nữa" onClick={() => setWeekOf(shiftDay(weekOf, 7))}><ChevronRight size={16} /></button>
            {data && <h2>{shortDay(data.week_start)} đến {shortDay(data.week_end)}</h2>}
          </div>
          <div className="personal-view-tools">
            <div className="today-tabs" role="tablist"><button type="button" role="tab" aria-selected={view === 'matrix'} className={view === 'matrix' ? 'active' : undefined} onClick={() => switchView('matrix')}>Ma trận</button><button type="button" role="tab" aria-selected={view === 'list'} className={view === 'list' ? 'active' : undefined} onClick={() => switchView('list')}>Theo ngày</button></div>
            <button type="button" className="text-button" onClick={() => setShowArchived(!showArchived)}>{showArchived ? 'Ẩn lưu trữ' : 'Đã lưu trữ'}</button>
          </div>
        </div>
        {matrix.isLoading || !data ? <LoadingBlock /> : view === 'matrix' ? <PersonalMatrix tasks={data.tasks} today={today} onChanged={refresh} only={only} /> : byDay.length === 0 ? <EmptyState icon={<ListChecks size={22} />} title="Chưa có việc riêng tuần này" text="Gõ vào dòng trên rồi Enter." /> : byDay.map(([day, rows]) => (
          <div className="personal-day" key={day}>
            <h3>{day === 'chưa có ngày' ? 'Chưa có ngày' : `${shortDay(day)}${day === today ? ' · hôm nay' : ''}`} <small>{hoursText(rows.filter((row) => row.status !== 'SKIPPED').reduce((sum, row) => sum + row.hours, 0))}</small></h3>
            <ul className="personal-list">{rows.map((task) => <PersonalTaskRow key={task.id} task={task} today={today} onChanged={refresh} cellActions />)}</ul>
          </div>
        ))}
        {showArchived && (
          <div className="personal-day personal-archived">
            <h3>Đã lưu trữ <small>{archived.data?.length ?? 0}</small></h3>
            {archived.isLoading ? <LoadingBlock /> : (archived.data || []).length === 0 ? <p className="matrix-empty">Chưa có việc nào bị lưu trữ.</p> : (
              <ul className="personal-list">{(archived.data || []).map((task) => <ArchivedTaskRow key={task.id} task={task} onChanged={refresh} />)}</ul>
            )}
          </div>
        )}
      </section>
    </>
  )
}

function ArchivedTaskRow({ task, onChanged }: { task: PersonalTask; onChanged: () => void }) {
  const queryClient = useQueryClient()
  const restore = useMutation({
    mutationFn: () => api(`/personal-tasks/${task.id}`, { method: 'PATCH', body: JSON.stringify({ archived: false, important: true }) }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['personal-tasks', 'archived'] }); onChanged() },
  })
  const remove = useMutation({ mutationFn: () => api(`/personal-tasks/${task.id}`, { method: 'DELETE' }), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['personal-tasks', 'archived'] }); onChanged() } })
  return (
    <li className="personal-task is-archived">
      <span className="personal-check" />
      <div className="personal-body"><strong>{task.title}</strong><small>lưu trữ {task.archived_at ? formatDate(task.archived_at) : ''}{task.task_date ? ` · ${shortDay(task.task_date)}` : ''}</small></div>
      <div className="personal-actions"><button type="button" className="text-button is-action" disabled={restore.isPending} onClick={() => restore.mutate()}>Khôi phục (vào Lên lịch)</button><button type="button" className="text-button" disabled={remove.isPending} onClick={() => { if (window.confirm(`Xóa hẳn "${task.title}"?`)) remove.mutate() }}>Xóa</button></div>
    </li>
  )
}

function TodayPage() {
  const { user } = useAuth()
  const isCto = user?.role === 'CTO'
  const today = todayInPlanningTimezone()
  const tomorrow = nextDay(today)
  const [view, setView] = useState<'today' | 'tomorrow' | 'people'>('today')
  const [peopleDay, setPeopleDay] = useState<'today' | 'tomorrow'>('tomorrow')
  const boardDate = view === 'tomorrow' ? tomorrow : today
  const overview = useQuery({ queryKey: ['planning-overview', boardDate], queryFn: () => api<PlanningOverview>(`/planning/overview/${boardDate}`), refetchInterval: 60_000 })
  const unclear = useQuery({ queryKey: ['intakes', 'today-unclear'], queryFn: () => api<IntakePage>('/intakes?limit=1&status=NEEDS_INFORMATION') })
  const summary = useQuery({ queryKey: ['intakes', 'today-summary'], queryFn: () => api<IntakePage>('/intakes?limit=1') })
  const data = overview.data
  const dateLabel = new Intl.DateTimeFormat('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', weekday: 'long', day: 'numeric', month: 'numeric' }).format(new Date())
  const unclearCount = unclear.data?.summary?.total_items || 0
  const syncFailed = summary.data?.summary?.sync_failed || 0
  const notes = [
    ...(unclearCount > 0 ? [{ key: 'unclear', text: `${unclearCount} yêu cầu đang chờ làm rõ với người gửi`, to: '/intakes?status=NEEDS_INFORMATION' }] : []),
    ...(syncFailed > 0 ? [{ key: 'failed', text: `${syncFailed} lần đồng bộ bị lỗi`, to: '/intakes?target=FAILED' }] : []),
  ]
  const planText = (row: PlanningOverviewProject) => {
    if (!row.plan.run_id) return 'Chưa có kế hoạch'
    const state = runStatusLabels[row.plan.status || ''] || row.plan.status
    const by = view === 'tomorrow' && row.plan.made_by ? ` · ${row.plan.made_by} xếp` : ''
    return `${state}${by} · ${row.plan.assigned_people}/${row.plan.people_today} người · ${hours(row.plan.assigned_hours)}/${hours(row.plan.available_hours)} giờ${row.plan.scope === 'ALL' ? ' · trong kế hoạch tổng' : ''}${row.plan.warnings > 0 ? ` · ${row.plan.warnings} cảnh báo` : ''}`
  }
  // The approvals cell: how many, how many are urgent, whose they are (for the CTO), how many waited too long.
  const approvalsText = (row: PlanningOverviewProject) => {
    const parts: string[] = []
    if (row.approvals.urgent > 0) parts.push(`${row.approvals.urgent} P0/P1`)
    if (isCto && row.approvals.po > 0) parts.push(`${row.approvals.po} chờ Project Owner`)
    if (row.approvals.overdue > 0) parts.push(`quá hạn ${row.approvals.overdue}`)
    return parts.length > 0 ? `${row.approvals.pending} (${parts.join(', ')})` : `${row.approvals.pending}`
  }
  const approvalsClass = (row: PlanningOverviewProject) => (row.approvals.overdue > 0 ? 'board-overdue' : row.approvals.pending > 0 ? 'board-attn' : undefined)
  const approvalsLink = (row: PlanningOverviewProject) => `/approvals?project=${row.id}&owner=ALL`
  const reportsText = (row: PlanningOverviewProject) => {
    if (row.reports.expected === 0) return 'không ai làm'
    const parts = [`${row.reports.received}/${row.reports.expected} người`]
    if (row.reports.unreviewed > 0) parts.push(`${row.reports.unreviewed} chờ xác nhận`)
    if (row.reports.malformed > 0) parts.push(`${row.reports.malformed} sai định dạng`)
    if (row.reports.late > 0) parts.push(`${row.reports.late} trễ`)
    if (row.reports.items_without_issue > 0) parts.push(`${row.reports.items_without_issue} việc chưa gắn Issue`)
    return parts.join(' · ')
  }

  return (
    <>
      <PageHeader title={user ? greeting(user) : 'Hôm nay'} />
      <AgentHint command={isCto ? 'board' : 'today'} />
      {overview.error != null && <ErrorNotice error={overview.error} onRetry={() => { void overview.refetch() }} />}
      <PersonalTodayPanel day={today} />
      <section className="panel today" aria-label="Các dự án hôm nay">
        <header>
          <div>
            <div className="today-tabs" role="tablist">
              <button type="button" role="tab" aria-selected={view === 'today'} className={view === 'today' ? 'active' : undefined} onClick={() => setView('today')}>Hôm nay</button>
              <button type="button" role="tab" aria-selected={view === 'tomorrow'} className={view === 'tomorrow' ? 'active' : undefined} onClick={() => setView('tomorrow')}>Ngày mai</button>
              {isCto && <button type="button" role="tab" aria-selected={view === 'people'} className={view === 'people' ? 'active' : undefined} onClick={() => setView('people')}>Người</button>}
            </div>
            {view === 'people' ? (
              <p>Giờ đã xếp qua mọi dự án cho <select aria-label="Ngày" value={peopleDay} onChange={(event) => setPeopleDay(event.target.value as 'today' | 'tomorrow')}><option value="tomorrow">ngày mai {changelogDay(tomorrow)}</option><option value="today">hôm nay {changelogDay(today)}</option></select></p>
            ) : (
              <p>{view === 'today' ? dateLabel.charAt(0).toUpperCase() + dateLabel.slice(1) : `Kế hoạch cho ${changelogDay(tomorrow)}`}{data && view === 'today' ? ` · danh sách Issue ${data.gitlab_snapshot_at ? `cập nhật ${formatDate(data.gitlab_snapshot_at)}` : 'chưa lấy'}` : ''}</p>
            )}
          </div>
          {view === 'today' && data && data.overdue_total > 0 && <span className="today-left is-overdue">{data.overdue_total} việc quá hạn</span>}
          {view === 'today' && data && data.projects.length > 0 && <span className={data.missing_projects === 0 ? 'today-left is-clear' : 'today-left'}>{data.missing_projects === 0 ? 'Đủ cơ sở review' : `${data.missing_projects} dự án thiếu cơ sở`}</span>}
          {view === 'tomorrow' && data && data.projects.length > 0 && <span className={data.projects.every((row) => row.plan.run_id && !['DRAFT', 'REVIEW_REQUIRED'].includes(row.plan.status || '')) ? 'today-left is-clear' : 'today-left'}>{data.projects.filter((row) => !row.plan.run_id).length} dự án chưa có kế hoạch</span>}
        </header>
        {view === 'people' ? <PeopleBoard day={peopleDay === 'today' ? today : tomorrow} /> : overview.isLoading ? <LoadingBlock /> : !data || data.projects.length === 0 ? (
          <EmptyState icon={<CalendarDays size={20} />} title="Chưa có dự án phần mềm nào để lập kế hoạch" text={isCto ? 'Tạo dự án loại phần mềm ở Cài đặt > Dự án.' : 'Hãy nhờ CTO thêm bạn vào dự án.'} />
        ) : (
          <div className="today-board">
            {view === 'tomorrow' ? (
              <table>
                <thead>
                  <tr><th>Dự án</th><th>Kế hoạch ngày mai</th><th>Người nghỉ</th><th>Có giờ, chưa có việc</th><th>Chuyển tiếp dự kiến</th><th>Chờ duyệt</th><th>Chưa có Issue</th><th>Báo cáo hôm nay</th></tr>
                </thead>
                <tbody>
                  {data.projects.map((row) => (
                    <tr key={row.id} className={row.p0 ? 'is-p0' : undefined}>
                      <td className="board-project"><Link to={`/planning?project=${row.id}&date=${tomorrow}`}><strong>{row.name}</strong></Link>{row.p0 && <span className="status status-rejected" title="Có yêu cầu P0 chờ duyệt hoặc Issue P0 đang mở">P0</span>}</td>
                      <td><Link to={`/planning?project=${row.id}&date=${tomorrow}`} className={!row.plan.run_id || ['DRAFT', 'REVIEW_REQUIRED'].includes(row.plan.status || '') ? 'board-attn' : undefined}>{planText(row)}</Link></td>
                      <td>{names(row.people_off)}</td>
                      <td className={row.unassigned.length > 0 ? 'board-attn' : undefined}>{row.plan.run_id ? names(row.unassigned) : 'chưa xếp'}</td>
                      <td className={row.carry_over > 0 ? 'board-attn' : undefined}>{row.carry_over} việc</td>
                      <td><Link to={approvalsLink(row)} className={approvalsClass(row)}>{approvalsText(row)}</Link></td>
                      <td><Link to={`/intakes?status=APPROVED&project=${row.code}`} className={row.unsynced > 0 ? 'board-attn' : undefined}>{row.unsynced}</Link></td>
                      <td><Link to="/reports">{row.reports.expected === 0 ? 'không ai làm' : `${row.reports.received}/${row.reports.expected} người`}</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
            <table>
              <thead>
                <tr><th>Dự án</th><th>Cơ sở review</th><th title="Hồ sơ ngữ cảnh docs/agent/CONTEXT.md của dự án, như Intake đọc gần nhất">Ngữ cảnh</th><th>Báo cáo hôm qua</th><th>Chờ duyệt</th><th>Chưa có Issue</th><th>Chờ phân công</th><th>Kế hoạch hôm nay</th>{isCto && <th>Chờ nghiệm thu</th>}</tr>
              </thead>
              <tbody>
                {data.projects.map((row) => (
                  <tr key={row.id} className={row.p0 ? 'is-p0' : undefined}>
                    <td className="board-project"><Link to={`/planning?project=${row.id}&date=${today}`}><strong>{row.name}</strong></Link>{row.p0 && <span className="status status-rejected" title={row.overdue.p0_open > 0 ? `${row.overdue.p0_open} Issue P0 mở quá 1 ngày` : 'Có yêu cầu P0 chờ duyệt hoặc Issue P0 đang mở'}>P0{row.overdue.p0_open > 0 ? ' quá hạn' : ''}</span>}</td>
                    <td>
                      {row.readiness.reasons.length === 0 ? <span className={`readiness-cell readiness-${row.readiness.state.toLowerCase()}`}>{readinessText[row.readiness.state]}</span> : (
                        <details className="readiness-details">
                          <summary className={`readiness-cell readiness-${row.readiness.state.toLowerCase()}`}>{readinessText[row.readiness.state]} · {row.readiness.reasons.length}</summary>
                          <ul>{row.readiness.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                        </details>
                      )}
                    </td>
                    <td>
                      {isCto
                        ? <Link to={`/settings/projects/${row.code}`} className={`status context-band band-${row.context.band.toLowerCase()}`} title={row.context.missing.length > 0 ? `Thiếu: ${row.context.missing.join(' · ')}` : row.context.approved ? 'Hồ sơ đủ, CTO đã duyệt' : 'Hồ sơ đủ, chưa duyệt'}>{contextBandWords[row.context.band] || row.context.band} · {row.context.score}</Link>
                        : <span className={`status context-band band-${row.context.band.toLowerCase()}`} title={row.context.missing.length > 0 ? `Thiếu: ${row.context.missing.join(' · ')}` : 'Hồ sơ đủ'}>{contextBandWords[row.context.band] || row.context.band} · {row.context.score}</span>}
                    </td>
                    <td><Link to={row.reports.items_without_issue > 0 && row.reports.report_date ? `/reports?date=${row.reports.report_date}&unlinked=1` : '/reports'} className={row.reports.missing.length > 0 || row.reports.unreviewed > 0 ? 'board-attn' : undefined}>{reportsText(row)}</Link></td>
                    <td><Link to={approvalsLink(row)} className={approvalsClass(row)}>{approvalsText(row)}</Link></td>
                    <td><Link to={`/intakes?status=APPROVED&project=${row.code}`} className={row.unsynced > 0 ? 'board-attn' : undefined}>{row.unsynced}</Link></td>
                    <td><Link to={`/planning?project=${row.id}&date=${today}`} className={row.overdue.waiting > 0 ? 'board-overdue' : row.plan.waiting > 0 ? 'board-attn' : undefined}>{row.plan.run_id ? `${row.plan.waiting}${row.overdue.waiting > 0 ? ` (quá hạn ${row.overdue.waiting})` : ''}` : 'chưa có kế hoạch'}</Link></td>
                    <td><Link to={`/planning?project=${row.id}&date=${today}`} className={!row.plan.run_id || ['DRAFT', 'REVIEW_REQUIRED'].includes(row.plan.status || '') ? 'board-attn' : undefined}>{planText(row)}</Link></td>
                    {isCto && <td><Link to={`/nghiem-thu?project=${row.id}`} className={row.overdue.work_log > 0 ? 'board-overdue' : row.acceptance.verifications_pending + row.acceptance.work_log_pending > 0 ? 'board-attn' : undefined}>{row.acceptance.verifications_pending} nghiệm thu · {row.acceptance.work_log_pending} xác nhận{row.overdue.work_log > 0 ? ` (quá hạn ${row.overdue.work_log})` : ''}</Link></td>}
                  </tr>
                ))}
              </tbody>
            </table>
            )}
            <p className="field-help">{view === 'tomorrow' ? 'Xem từ 17:30: báo cáo hôm nay về đến đâu thì "chuyển tiếp dự kiến" đúng đến đó. Project Owner xếp và chốt kế hoạch dự án mình; 07:00 hệ thống tạo nháp cho dự án còn trống.' : 'Thứ tự: dự án có P0 trước, rồi theo số việc đang chờ anh chị. "Cơ sở review" đủ khi mọi người có giờ hôm qua đã gửi báo cáo đọc được, danh sách Issue đã cập nhật hôm nay, họp hôm qua đã có note và mục hành động đã thành Intake, không có yêu cầu kẹt ở bước AI. "Quá hạn": chờ duyệt quá 24 giờ, chờ phân công quá 2 ngày, lịch sử xử lý chờ xác nhận quá 1 ngày, Issue P0 mở quá 1 ngày.'}</p>
          </div>
        )}
      </section>
      {notes.length > 0 && (
        <section className="today-notes" aria-label="Cần để ý">
          {notes.map((note) => <Link key={note.key} to={note.to}><TriangleAlert size={15} aria-hidden="true" /><span>{note.text}</span><ArrowRight size={14} aria-hidden="true" /></Link>)}
        </section>
      )}
      {isCto && <CtoLines time={data?.cto_time || null} />}
      {isCto && <PrivateSpaceLine />}
      {isCto && <ApprovalSources />}
    </>
  )
}

function HealthLine({ label, value }: { label: string; value?: string }) {
  const okay = value === 'healthy' || value === 'ok'
  return <div className="health-line"><span>{label}</span><strong className={okay ? 'text-good' : 'text-warn'}>{okay ? 'Ổn định' : value || 'Chưa rõ'}</strong></div>
}

function EmptyState({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return <div className="empty-state"><span aria-hidden="true">{icon}</span><strong>{title}</strong><p>{text}</p></div>
}

function SyncTargetChip({ target }: { target: IntakeSyncSummary }) {
  const system = target.system === 'GITLAB' ? 'GitLab' : target.system === 'GITHUB' ? 'GitHub' : 'Plane · lịch sử'
  const reference = target.system === 'GITLAB' || target.system === 'GITHUB'
    ? (target.external_id ? ` #${target.external_id}` : '')
    : (target.sequence_id ? ` #${target.sequence_id}` : '')
  const stateLabel = {
    PENDING: `Chờ Sync · ${system}`,
    RUNNING: `Đang Sync · ${system}`,
    RETRY: `Đang thử lại · ${system}`,
    FAILED: `Sync lỗi · ${system}`,
    SUCCEEDED: `${system}${reference}`,
  }[target.status]
  const className = `target-chip target-${target.status.toLowerCase()} target-${target.system.toLowerCase()}${target.superseded ? ' target-superseded' : ''}`
  if (target.superseded) {
    const label = `${stateLabel} · đã rút`
    const why = 'Mục của quyết định đã rút lại. Duyệt lại cùng tuyến sẽ dùng lại mục này (mở lại nếu đã đóng); chọn tuyến khác thì tự đóng hoặc xóa nó.'
    return target.external_url
      ? <a className={className} href={target.external_url} target="_blank" rel="noreferrer" title={why} aria-label={`Mở ${label}`}>{label} <ArrowUpRight size={13} /></a>
      : <span className={className} title={why}>{label}</span>
  }
  if (target.status === 'SUCCEEDED' && target.external_url) {
    return <a className={className} href={target.external_url} target="_blank" rel="noreferrer" aria-label={`Mở ${stateLabel}`}>{stateLabel} <ArrowUpRight size={13} /></a>
  }
  return <span className={className} title={target.error_code || undefined}>{stateLabel}</span>
}

// A request that produced nothing outside Intake can be deleted: not approved, not being read by AI, never synced.
const removableStatuses = ['NEW', 'PENDING_APPROVAL', 'NEEDS_INFORMATION', 'PROCESSING_FAILED', 'REJECTED', 'DEFERRED']
const canRemove = (intake: Intake) => removableStatuses.includes(intake.status) && !(intake.sync_targets || []).some((target) => target.status === 'SUCCEEDED')
const removeErrors: Record<string, string> = {
  INTAKE_PROCESSING: 'AI đang phân tích yêu cầu này. Thử lại khi phân tích xong.',
  INTAKE_DECIDED: 'Yêu cầu đã được duyệt nên không xóa được. Rút lại phê duyệt trước.',
  INTAKE_HAS_EXTERNAL: 'Đã có mục ngoài hệ thống tạo từ yêu cầu này, nên không xóa được.',
  INTAKE_PLANNED: 'Yêu cầu đang nằm trong một kế hoạch ngày. Gỡ khỏi kế hoạch trước.',
}
const removeError = (error: unknown) => (error instanceof ApiError && error.code && removeErrors[error.code] ? new Error(removeErrors[error.code]) : error)

function RemoveIntakeDialog({ intake, onDone, onCancel }: { intake: Intake; onDone: () => void; onCancel: () => void }) {
  const remove = useMutation({ mutationFn: () => api(`/intakes/${intake.id}`, { method: 'DELETE' }), onSuccess: onDone })
  return (
    <ConfirmDialog title="Xóa yêu cầu này?" confirmLabel="Xóa hẳn" busy={remove.isPending} error={remove.error != null ? removeError(remove.error) : undefined} onConfirm={() => remove.mutate()} onCancel={onCancel}>
      <p><strong>{intake.public_id}</strong><br />{intake.normalized_title || 'Chưa có tiêu đề'}</p>
      <ul>
        <li>Nội dung gốc, tệp đính kèm, kết quả AI, câu trả lời làm rõ và lịch sử quyết định bị xóa hẳn.</li>
        <li>Không khôi phục được. Chỉ còn một dòng nhật ký: mã yêu cầu, ai xóa, lúc nào.</li>
        <li>Nếu đây là yêu cầu trùng và bạn muốn giữ dấu vết, hãy dùng "Đánh dấu trùng" thay vì xóa.</li>
      </ul>
    </ConfirmDialog>
  )
}

// Choose the request that is kept; this one is closed as its repeat and stays on record.
function DuplicateDialog({ intake, onDone, onCancel }: { intake: Intake; onDone: () => void; onCancel: () => void }) {
  const [text, setText] = useState('')
  const [settled, setSettled] = useState('')
  const [chosen, setChosen] = useState<Intake>()
  const [issue, setIssue] = useState('')
  useEffect(() => { const timer = window.setTimeout(() => setSettled(text.trim()), 250); return () => window.clearTimeout(timer) }, [text])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onCancel() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onCancel])
  const found = useQuery({
    queryKey: ['duplicate-of', intake.project_id, settled],
    queryFn: () => api<IntakePage>(`/intakes?limit=8&project_id=${intake.project_id}${settled ? `&search=${encodeURIComponent(settled)}` : ''}`),
  })
  const options = (found.data?.items || []).filter((row) => row.id !== intake.id && !row.duplicate_of_id)
  const mark = useMutation({
    mutationFn: () => api<Intake>(`/intakes/${intake.id}/duplicate`, { method: 'POST', body: JSON.stringify({ of: chosen!.id, expected_version: intake.version }) }),
    onSuccess: onDone,
  })
  const markIssue = useMutation({
    mutationFn: () => api<Intake>(`/intakes/${intake.id}/duplicate-issue`, { method: 'POST', body: JSON.stringify({ issue: issue.trim(), expected_version: intake.version }) }),
    onSuccess: onDone,
  })
  const busy = mark.isPending || markIssue.isPending
  const issueError = markIssue.error instanceof ApiError && markIssue.error.code === 'DUPLICATE_TARGET_NOT_FOUND'
    ? new Error('Không tìm thấy Issue này trong dữ liệu GitLab mới nhất của dự án. Kiểm tra lại số Issue hoặc làm mới dữ liệu GitLab rồi thử lại.')
    : markIssue.error instanceof ApiError && markIssue.error.code === 'DUPLICATE_TARGET_INVALID'
      ? new Error('Issue này đã thuộc chính Intake hiện tại nên không thể đánh dấu là trùng.')
      : markIssue.error
  return createPortal(
    <div className="confirm-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onCancel() }}>
      <div className="confirm-dialog duplicate-dialog" role="dialog" aria-modal="true" aria-labelledby="duplicate-title">
        <h2 id="duplicate-title">Yêu cầu này trùng với đâu?</h2>
        <p className="confirm-text">{intake.public_id} sẽ được đóng lại và dẫn sang Intake hoặc Issue bạn chọn. Nó không bị xóa, nên lịch sử xử lý vẫn được giữ để truy vết.</p>
        <strong className="duplicate-section-title">Một Intake khác</strong>
        <label className="search-field"><Search size={15} aria-hidden="true" /><input autoFocus value={text} onChange={(event) => { setText(event.target.value); setChosen(undefined) }} placeholder="Tìm theo mã hoặc tiêu đề trong cùng dự án…" aria-label="Tìm yêu cầu được giữ" /></label>
        <div className="duplicate-options" role="listbox" aria-label="Yêu cầu được giữ">
          {found.isLoading ? <LoadingBlock /> : options.length === 0 ? <p className="muted">Không thấy yêu cầu nào khớp trong dự án này.</p> : options.map((row) => (
            <button type="button" role="option" aria-selected={chosen?.id === row.id} key={row.id} className={chosen?.id === row.id ? 'active' : undefined} onClick={() => { setChosen(row); setIssue('') }}>
              <strong>{row.public_id}</strong><span>{row.normalized_title || 'Chưa có tiêu đề'}</span><small>{statusLabels[row.status]}</small>
            </button>
          ))}
        </div>
        <div className="duplicate-issue-choice">
          <label htmlFor="duplicate-issue"><strong>Hoặc một Issue GitLab đã có</strong><small>Nhập số Issue trong đúng dự án, ví dụ #32.</small></label>
          <div><input id="duplicate-issue" value={issue} onChange={(event) => { setIssue(event.target.value); setChosen(undefined) }} placeholder="#Issue" aria-label="Số Issue GitLab đã có" onKeyDown={(event) => { if (event.key === 'Enter' && issue.trim() && !busy) markIssue.mutate() }} /><button type="button" className="button button-secondary" disabled={!issue.trim() || busy} onClick={() => markIssue.mutate()}>{markIssue.isPending ? 'Đang kiểm tra…' : 'Trùng với Issue'}</button></div>
        </div>
        {mark.error != null && <ErrorNotice error={mark.error} />}
        {issueError != null && <ErrorNotice error={issueError} />}
        <div className="confirm-actions">
          <button type="button" className="button button-secondary" disabled={busy} onClick={onCancel}>Hủy</button>
          <button type="button" className="button button-primary" disabled={!chosen || busy} onClick={() => mark.mutate()}>{mark.isPending ? 'Đang đánh dấu…' : chosen ? `Trùng với ${chosen.public_id}` : 'Chọn một Intake'}</button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function IntakeRow({ intake, onRemove }: { intake: Intake; onRemove?: (intake: Intake) => void }) {
  const targets = intake.sync_targets || []
  const waitingTarget = targets.length === 0 && intake.status === 'APPROVED' && (intake.approved_route === 'GITLAB' || intake.approved_route === 'GITHUB')
  const stoppedReason = intake.lifecycle_stage !== 'STOPPED' ? null
    : intake.duplicate_of_id || intake.duplicate_issue ? 'Trùng'
      : intake.status === 'REJECTED' ? 'Từ chối'
        : intake.status === 'DEFERRED' ? 'Đã hoãn'
          : intake.approved_route === 'WORK' && intake.work_item?.status === 'CANCELLED' ? 'Đã bỏ'
            : intake.status === 'CLOSED' ? 'Đã đóng' : null
  return (
    <article className={`intake-row ${intake.approved_priority === 'P0' || intake.suggested_priority === 'P0' ? 'intake-row-critical' : ''}`}>
      <Link className="row-main" to={`/intakes/${intake.id}`}><span className="public-id">{intake.public_id}</span><strong>{intake.normalized_title || 'Chưa có tiêu đề'}</strong><small>{channelLabels[intake.channel]} · {formatDate(intake.updated_at)}</small></Link>
      <PriorityBadge priority={intake.approved_priority || intake.suggested_priority} />
      <div className="row-targets">
        <LifecycleBadge stage={intake.lifecycle_stage} />
        {stoppedReason && <span className="status lifecycle-reason" title="Lý do kết thúc">{stoppedReason}</span>}
        <ReadinessChip readiness={intake.agent_readiness} compact />
        {targets.map((target) => <SyncTargetChip key={`${target.system}-${target.updated_at}`} target={target} />)}
        {intake.work_item && intake.approved_route === 'WORK' && <Link className="target-chip target-work" to={`/viec?project=${intake.work_item.project_id}&work=${intake.work_item.id}`}>Việc {intake.work_item.code}</Link>}
        {waitingTarget && <span className="target-chip target-ready">Chờ Sync · {intake.approved_route === 'GITHUB' ? 'GitHub' : 'GitLab'}</span>}
        {onRemove && canRemove(intake) && <button type="button" className="icon-button row-remove" aria-label={`Xóa ${intake.public_id}`} title="Xóa yêu cầu" onClick={() => onRemove(intake)}><Trash2 size={15} /></button>}
      </div>
      <Link className="row-arrow" to={`/intakes/${intake.id}`} aria-label={`Mở ${intake.public_id}`}><ArrowRight size={17} /></Link>
    </article>
  )
}

const ACCEPTED_FILE_TYPES = ['application/pdf', 'image/jpeg', 'image/png', 'image/webp']

const recordingSources: { value: RecordingSource; label: string; hint: string }[] = [
  { value: 'TAB_AND_MIC', label: 'Cuộc họp online + micro', hint: 'Zoom, Google Meet, MS Teams: chọn tab hoặc màn hình và tích "chia sẻ âm thanh"' },
  { value: 'MIC', label: 'Chỉ micro', hint: 'Họp trực tiếp trong phòng' },
  { value: 'FILE', label: 'Tải file ghi âm có sẵn', hint: 'MP3, M4A, WAV, WebM, OGG; bản chữ có sau khi tải xong' },
]

function formatClock(seconds: number) {
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

// Settings for recording a meeting. The words themselves appear in the middle of the page (LiveRecording).
function RecordingPanel() {
  const queryClient = useQueryClient()
  const recording = useRecording()
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const [source, setSource] = useState<RecordingSource>('TAB_AND_MIC')
  const [projectCode, setProjectCode] = useState('')
  const [error, setError] = useState<unknown>()
  const [term, setTerm] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const glossary = useQuery({
    queryKey: ['meeting-glossary', projectCode],
    queryFn: () => api<GlossaryTerm[]>(`/meetings/glossary${projectCode ? `?project_id=${projectCode}` : ''}`),
  })
  const addTerm = useMutation({
    mutationFn: () => api<GlossaryTerm>('/meetings/glossary', { method: 'POST', body: JSON.stringify({ term: term.trim(), project_id: projectCode || null }) }),
    onSuccess: () => { setTerm(''); setError(undefined); void queryClient.invalidateQueries({ queryKey: ['meeting-glossary'] }) },
    onError: setError,
  })
  const removeTerm = useMutation({
    mutationFn: (id: string) => api(`/meetings/glossary/${id}`, { method: 'DELETE' }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['meeting-glossary'] }) },
    onError: setError,
  })
  const idle = recording.phase === 'idle' || recording.phase === 'done'
  const dictating = !idle && recording.kind === 'DICTATION'

  return (
    <div className="recording-panel">
      {error != null && <ErrorNotice error={error} />}
      {idle ? (
        <>
          <label><span className="req-label">Dự án của cuộc họp<Req /></span><select value={projectCode} onChange={(e) => setProjectCode(e.target.value)} required><option value="" disabled>Chọn dự án…</option>{projects.data?.map((project) => <option key={project.id} value={project.code}>{project.name}</option>)}</select><small className="field-help">Mọi mục của meeting note sẽ thuộc dự án này; đổi lại được ở trang Cuộc họp.</small></label>
          <fieldset className="option-list option-list-tight">
            <legend>Nguồn âm thanh</legend>
            {recordingSources.map(({ value, label, hint }) => (
              <label key={value} className={source === value ? 'option active' : 'option'}>
                <input type="radio" name="recording-source" value={value} checked={source === value} onChange={() => setSource(value)} />
                <span><strong>{label}</strong></span>
                {/* The explanation is one hover, focus or tap away, not three lines under every choice. */}
                <span className="tip" tabIndex={0} role="img" aria-label={hint}><CircleHelp size={15} aria-hidden="true" /><span className="tip-text" role="tooltip">{hint}</span></span>
              </label>
            ))}
          </fieldset>
          {/* Only the chosen source keeps its instruction in view: missing "share audio" makes the recording fail. */}
          <p className="field-help option-current-hint" role="note">{recordingSources.find((item) => item.value === source)?.hint}</p>
          <div className="glossary">
            <span className="glossary-title">Thuật ngữ {projectCode ? 'chung và của dự án' : 'chung'}</span>
            <div className="glossary-terms">
              {glossary.data?.length === 0 && <small>Chưa có thuật ngữ nào.</small>}
              {glossary.data?.map((item) => <span className="chip" key={item.id} title={item.usable_in_realtime ? undefined : 'Dài hơn 20 ký tự: chỉ dùng cho bản chữ sau cuộc họp'}><span className="chip-label">{item.term}{item.project_code && <small>{item.project_code}</small>}</span><button type="button" aria-label={`Xóa thuật ngữ ${item.term}`} onClick={() => removeTerm.mutate(item.id)}><X size={13} /></button></span>)}
            </div>
            <form onSubmit={(event) => { event.preventDefault(); if (term.trim()) addTerm.mutate() }}>
              <input value={term} onChange={(e) => setTerm(e.target.value)} maxLength={50} placeholder={projectCode ? 'Thêm thuật ngữ cho dự án này' : 'Thêm thuật ngữ chung'} aria-label="Thuật ngữ mới" />
              <button className="button button-secondary button-small" disabled={!term.trim() || addTerm.isPending}>Thêm</button>
            </form>
          </div>
          <dl className="setting-facts">
            <div><dt>Bản chữ</dt><dd>Hiện dần khi đang ghi</dd></div>
            <div><dt>Tách người nói</dt><dd>Sau cuộc họp, ở trang Cuộc họp</dd></div>
            <div><dt>Meeting note</dt><dd>AI tự tổng hợp sau cuộc họp</dd></div>
            <div><dt>Thời lượng tối đa</dt><dd>60 phút mỗi lần ghi</dd></div>
            <div><dt>Lưu audio</dt><dd>90 ngày, có mã hóa</dd></div>
          </dl>
          <p className="field-help">Hãy thông báo cho người tham dự trước khi ghi âm.</p>
          <input ref={fileRef} type="file" hidden accept="audio/mpeg,audio/mp4,audio/x-m4a,audio/wav,audio/webm,audio/ogg,.mp3,.m4a,.wav,.webm,.ogg" onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void uploadRecording(file, projectCode) }} />
          <button className="button button-primary button-wide" type="button" disabled={!projectCode} title={projectCode ? undefined : 'Chọn dự án của cuộc họp trước'} onClick={() => { if (source === 'FILE') fileRef.current?.click(); else void startRecording({ source, projectCode, kind: 'MEETING' }) }}><Mic size={16} /> {source === 'FILE' ? 'Chọn file ghi âm' : 'Bắt đầu ghi âm'}</button>
        </>
      ) : (
        <>
          <div className="recording-status" role="status">
            <span className={recording.phase === 'recording' ? 'recording-dot live' : 'recording-dot'} aria-hidden="true" />
            <strong>{recording.phase === 'starting' ? 'Đang chuẩn bị…' : recording.phase === 'recording' ? (dictating ? 'Đang nói để nhập' : 'Đang ghi cuộc họp') : 'Đang lưu…'}</strong>
            <span>{formatClock(recording.elapsed)}</span>
          </div>
          <p className="field-help">{dictating ? 'Kết thúc lượt nói này rồi mới ghi được cuộc họp.' : 'Bản chữ đang hiện ở giữa trang, kèm thời điểm của từng câu. Âm thanh được giữ trên máy này trước, rồi gửi dần lên server.'}</p>
          {syncLine(recording) && <p className={syncLine(recording)?.warn ? 'recording-sync is-warn' : 'recording-sync'} role="status">{syncLine(recording)?.text}</p>}
          <button className="button button-danger button-wide" type="button" disabled={recording.phase !== 'recording'} onClick={() => { void stopRecording() }}>{recording.phase === 'stopping' ? 'Đang lưu…' : 'Kết thúc ghi âm'}</button>
        </>
      )}
    </div>
  )
}

// What is being said, in the middle of the page: each sentence with the time it began and whether it has ended.
// When the recording is over, the person chooses what goes into the composer.
function LiveRecording({ onUse }: { onUse: (text: string) => void }) {
  const recording = useRecording()
  const [used, setUsed] = useState<'raw' | 'ai'>()
  const [aiError, setAiError] = useState<unknown>()
  const linesRef = useRef<HTMLOListElement>(null)
  const { phase, lines, partial, kind, meetingId } = recording

  useEffect(() => { linesRef.current?.scrollTo({ top: linesRef.current.scrollHeight }) }, [lines.length, partial])
  useEffect(() => { if (phase === 'starting') { setUsed(undefined); setAiError(undefined) } }, [phase])

  if (phase === 'idle') return recording.error != null ? <ErrorNotice error={recording.error} /> : null

  const dictation = kind === 'DICTATION'
  const file = recording.source === 'FILE'
  const useRaw = () => { onUse(lines.map((line) => line.text).join('\n')); setUsed('raw'); setAiError(undefined) }
  const useAi = async () => {
    setAiError(undefined)
    try {
      const text = await rewriteRecording()
      const when = recording.startedAt ? formatDate(new Date(recording.startedAt).toISOString()) : ''
      onUse(`${text}\n\n(AI viết lại từ bản ghi âm${when ? ` lúc ${when}` : ''}. Bản gốc: ${window.location.origin}/meetings?id=${meetingId})`)
      setUsed('ai')
    } catch (error) {
      setAiError(error)
    }
  }

  return (
    <section className="live-recording" aria-label={dictation ? 'Nói để nhập' : 'Ghi âm cuộc họp'}>
      <header>
        <span className={phase === 'recording' ? 'recording-dot live' : 'recording-dot'} aria-hidden="true" />
        <strong role="status">{phase === 'starting' ? 'Đang chuẩn bị…' : phase === 'recording' ? (dictation ? 'Đang nghe bạn nói' : 'Đang ghi cuộc họp') : phase === 'stopping' ? 'Đang lưu…' : 'Đã ghi xong'}</strong>
        <span className="live-clock">{formatClock(recording.elapsed)}{(recording.partNumber || 1) > 1 && <small className="live-part">phần {recording.partNumber}</small>}</span>
        {phase !== 'done' && <button className="button button-danger button-small" type="button" disabled={phase !== 'recording'} onClick={() => { void stopRecording() }}>{dictation ? 'Nói xong' : 'Kết thúc ghi âm'}</button>}
        {phase === 'done' && <button className="icon-button" type="button" aria-label="Đóng bản ghi này" onClick={resetRecording}><X size={16} /></button>}
      </header>
      {recording.error != null && <ErrorNotice error={recording.error} />}
      {recording.notice && <div className="notice notice-warn" role="status">{recording.notice}</div>}
      {syncLine(recording) && <p className={syncLine(recording)?.warn ? 'recording-sync is-warn' : 'recording-sync'} role="status">{syncLine(recording)?.text}</p>}
      <ol className="live-lines" ref={linesRef} aria-label="Bản chữ" aria-live="polite">
        {lines.length === 0 && !partial && <li className="live-empty">{file ? 'File đang được chuyển chữ; bản chữ sẽ có ở trang Cuộc họp.' : phase === 'done' ? 'Không có câu nào được ghi lại.' : 'Hãy bắt đầu nói. Từng câu sẽ hiện ở đây kèm thời điểm.'}</li>}
        {lines.map((line, index) => (
          <li key={index}>
            <time>{formatClock(line.at)}</time>
            <p>{line.text}</p>
            <span className="line-state is-done"><Check size={12} aria-hidden="true" /> Hết câu</span>
          </li>
        ))}
        {partial && (
          <li className="is-speaking">
            <time>{formatClock(recording.partialAt ?? recording.elapsed)}</time>
            <p>{partial}</p>
            <span className="line-state">Đang nói…</span>
          </li>
        )}
      </ol>
      {phase === 'done' && (
        <footer>
          {aiError != null && <ErrorNotice error={aiError} />}
          {lines.length > 0 && (
            <>
              <p className="live-question">{used ? (used === 'raw' ? 'Đã đưa bản thô vào ô soạn. Sửa tiếp ở ô bên dưới, hoặc đổi sang bản AI viết lại.' : 'Đã đưa bản AI viết lại vào ô soạn. Đọc lại và sửa ở ô bên dưới, hoặc đổi về bản thô.') : 'Đưa nội dung nào vào ô soạn?'}</p>
              <div className="live-actions">
                <button className={used === 'raw' ? 'button button-secondary is-used' : 'button button-secondary'} type="button" disabled={recording.rewriting} title="Đúng từng câu bạn đã nói" onClick={useRaw}><FileText size={15} aria-hidden="true" /> Dùng bản thô</button>
                <button className={used === 'ai' ? 'button button-primary is-used' : 'button button-primary'} type="button" disabled={recording.rewriting} title="Viết lại thành yêu cầu gọn: bỏ từ thừa và ý lặp, giữ nguyên tên và số liệu. Mất khoảng 5–15 giây" onClick={() => { void useAi() }}>{recording.rewriting ? <><span className="spinner" /> AI đang viết lại…</> : <><Sparkles size={15} aria-hidden="true" /> Tóm tắt bằng AI</>}</button>
              </div>
              <p className="field-help">Cả hai đều vào ô soạn để bạn sửa trước khi lưu. Bản ghi âm và bản chữ gốc vẫn được giữ làm nguồn.</p>
            </>
          )}
          {!dictation && meetingId && <p className="field-help">Bản chữ tách người nói và meeting note sẽ có ở <Link to={`/meetings?id=${meetingId}`}>trang Cuộc họp</Link> sau ít phút.</p>}
        </footer>
      )}
    </section>
  )
}

type ComposerPopover = 'menu' | 'date' | 'sender' | null

function NewIntakePage() {
  const navigate = useNavigate()
  const { setRightPanel } = useShell()
  const { locale, text } = useLocale()
  const [searchParams, setSearchParams] = useSearchParams()
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const { user: composerUser } = useAuth()
  const [hard, setHard] = useState(false)
  const [projectId, setProjectId] = useState('')
  const [channel, setChannel] = useState<Channel>('MANUAL')
  const [rawText, setRawText] = useState('')
  const [senderReference, setSenderReference] = useState('')
  const [receivedAt, setReceivedAt] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [error, setError] = useState<unknown>()
  const [stage, setStage] = useState('')
  const [popover, setPopover] = useState<ComposerPopover>(null)
  const [dragging, setDragging] = useState(false)
  const textRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const recordOpen = searchParams.get('panel') === 'record'
  const recording = useRecording()
  // What the recording last put into the composer, so choosing the other version replaces it instead of adding a second copy.
  const spokenRef = useRef<string | undefined>(undefined)
  const useSpoken = (text: string) => {
    const previous = spokenRef.current
    spokenRef.current = text
    setRawText((current) => (previous && current.includes(previous) ? current.replace(previous, () => text) : current.trim() ? `${current.trim()}\n\n${text}` : text))
    textRef.current?.focus()
  }
  // Leaving the page ends the recording and clears it from the screen; the recording itself stays saved as a source.
  useEffect(() => () => { void leaveRecording() }, [])

  useEffect(() => {
    const list = projects.data
    if (!list || list.length === 0) return
    // Default to the first project the person can see.
    setProjectId(list[0].code)
  }, [projects.data])

  useEffect(() => {
    if (!recordOpen) {
      // The panel closed without its transcript being used: this composer is for some other request now.
      if (!spokenRef.current) setChannel((current) => (current === 'MEETING' ? 'MANUAL' : current))
      return
    }
    setChannel('MEETING')
    setRightPanel({
      title: text('Ghi âm cuộc họp', 'Record meeting'),
      content: <RecordingPanel />,
      onClose: () => setSearchParams({}, { replace: true }),
    })
    return () => setRightPanel(null)
  }, [recordOpen, setRightPanel, setSearchParams])

  useEffect(() => {
    const element = textRef.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${element.scrollHeight}px`
  }, [rawText])

  useEffect(() => {
    if (!popover) return
    const close = (event: MouseEvent) => {
      if (!(event.target as Element).closest('[data-popover-zone]')) setPopover(null)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [popover])

  const mutation = useMutation({
    mutationFn: async () => {
      setStage(text('Đang lưu nội dung nguồn…', 'Saving the original request…'))
      const created = await api<Intake>('/intakes', {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({
          project_id: projectId,
          channel,
          raw_text: rawText.trim(),
          sender_reference: senderReference.trim() || null,
          received_at: receivedAt ? new Date(receivedAt).toISOString() : null,
          needs_cto_acceptance: composerUser?.role === 'CTO' && hard,
        }),
      })
      for (let index = 0; index < files.length; index += 1) {
        setStage(text(`Đang tải file ${index + 1}/${files.length}…`, `Uploading file ${index + 1}/${files.length}…`))
        const body = new FormData()
        body.append('file', files[index])
        await api(`/intakes/${created.id}/attachments`, { method: 'POST', body })
      }
      setStage(files.length > 0 ? text('AI đang đọc ảnh và chuẩn hóa yêu cầu…', 'AI is reading the attachments and organizing the request…') : text('AI đang chuẩn hóa yêu cầu…', 'AI is organizing the request…'))
      try {
        await api(`/intakes/${created.id}/process`, { method: 'POST' })
      } catch (processError) {
        return { id: created.id, warning: formatError(processError) }
      }
      return { id: created.id }
    },
    // The recording has gone into this request; the next request starts with none.
    onSuccess: (result) => navigate(`/intakes/${result.id}`, { state: result.warning ? { notice: text(`Intake đã lưu nhưng AI chưa xử lý được: ${result.warning}`, `The Intake was saved, but AI processing did not finish: ${result.warning}`) } : undefined }),
    onError: setError,
  })

  const addFiles = (next: File[]) => {
    if (next.length === 0) return
    const invalid = next.find((file) => file.size > 5 * 1024 * 1024 || !ACCEPTED_FILE_TYPES.includes(file.type))
    if (invalid) {
      setError(new Error(text(`File ${invalid.name} không hợp lệ. Chỉ nhận PDF/JPG/PNG/WebP, tối đa 5 MB.`, `File ${invalid.name} is invalid. Use PDF, JPG, PNG, or WebP up to 5 MB.`)))
      return
    }
    setError(undefined)
    setFiles((current) => [...current, ...next])
  }

  const submit = (event?: FormEvent) => {
    event?.preventDefault()
    if (mutation.isPending) return
    setError(undefined)
    if (!rawText.trim()) {
      setError(new Error(text('Hãy nhập nội dung phản hồi trước khi lưu.', 'Enter the request before saving.')))
      return
    }
    mutation.mutate()
  }

  const toggleRecording = () => setSearchParams(recordOpen ? {} : { panel: 'record' }, { replace: true })
  const recordingBusy = recording.phase === 'starting' || recording.phase === 'recording' || recording.phase === 'stopping'
  const dictating = recordingBusy && recording.kind === 'DICTATION'
  // The microphone on the composer is for one person speaking a request into this Intake. Recording a meeting is in the menu.
  const toggleDictation = () => {
    if (dictating) void stopRecording()
    else if (!recordingBusy) { spokenRef.current = undefined; void startRecording({ source: 'MIC', projectCode: projectId, kind: 'DICTATION' }) }
  }
  const nowLocal = () => {
    const now = new Date()
    return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
  }
  const busy = mutation.isPending || projects.isLoading || Boolean(projects.error)
  const hasChips = files.length > 0 || Boolean(receivedAt) || Boolean(senderReference.trim())

  return (
    <div className="composer-page">
      <header className="composer-hero">
        <h1>{text('Tạo Intake mới', 'Create a new Intake')}</h1>
        <p>{text('Dán nguyên văn phản hồi hoặc ghi chú họp. Nội dung được lưu trước, sau đó AI mới chuẩn hóa.', 'Paste the original customer message or meeting note. Intake saves the source first, then AI organizes it.')}</p>
      </header>
      {projects.error && <ErrorNotice error={projects.error} onRetry={() => { void projects.refetch() }} />}
      {error != null && <ErrorNotice error={error} />}
      {/* A meeting's transcript belongs to the recording panel; with the panel closed this page is a plain composer
          and the top bar carries the clock. A spoken request always shows here, it is this page's own. */}
      {(recordOpen || recording.kind !== 'MEETING') && <LiveRecording onUse={useSpoken} />}
      <form
        className={dragging ? 'composer composer-dragging' : 'composer'}
        onSubmit={submit}
        onKeyDown={(event) => { if (event.key === 'Escape') setPopover(null) }}
        onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => { event.preventDefault(); setDragging(false); addFiles(Array.from(event.dataTransfer.files)) }}
      >
        <textarea
          ref={textRef}
          aria-label={text('Nội dung gốc', 'Original request')}
          rows={3}
          value={rawText}
          onChange={(e) => setRawText(e.target.value)}
          onPaste={(event) => {
            const pasted = Array.from(event.clipboardData.files)
            if (pasted.length > 0) { event.preventDefault(); addFiles(pasted) }
          }}
          onKeyDown={(event) => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) submit() }}
          placeholder={text('Dán nguyên văn phản hồi hoặc ghi chú meeting tại đây…', 'Paste the original customer message or meeting note here…')}
        />
        {hasChips && (
          <div className="composer-chips">
            {receivedAt && <span className="chip"><CalendarClock size={14} aria-hidden="true" /><button type="button" className="chip-label" data-popover-zone onClick={() => setPopover('date')}>{formatDate(receivedAt)}</button><button type="button" aria-label={text('Xóa thời điểm tiếp nhận', 'Remove received time')} onClick={() => setReceivedAt('')}><X size={13} /></button></span>}
            {senderReference.trim() && <span className="chip"><UserRound size={14} aria-hidden="true" /><button type="button" className="chip-label" data-popover-zone onClick={() => setPopover('sender')}>{senderReference.trim()}</button><button type="button" aria-label={text('Xóa người gửi', 'Remove sender')} onClick={() => setSenderReference('')}><X size={13} /></button></span>}
            {files.map((file, index) => <span className="chip" key={`${file.name}-${index}`}><FileText size={14} aria-hidden="true" /><span className="chip-label">{file.name}<small>{(file.size / 1024).toFixed(0)} KB</small></span><button type="button" aria-label={text(`Xóa ${file.name}`, `Remove ${file.name}`)} onClick={() => setFiles(files.filter((_, fileIndex) => fileIndex !== index))}><X size={13} /></button></span>)}
          </div>
        )}
        <div className="composer-bar">
          <div className="composer-anchor" data-popover-zone>
            <button type="button" className={popover ? 'icon-button active' : 'icon-button'} aria-label={text('Thêm file, thời điểm hoặc người gửi', 'Add a file, received time, or sender')} aria-haspopup="menu" aria-expanded={popover === 'menu'} onClick={() => setPopover(popover ? null : 'menu')}><Plus size={18} /></button>
            {popover === 'menu' && (
              <div className="composer-popover composer-menu" role="menu">
                <button type="button" role="menuitem" onClick={() => { setPopover(null); fileRef.current?.click() }}><Paperclip size={16} aria-hidden="true" /><span>{text('Đính kèm file', 'Attach a file')}<small>{text('PDF hoặc hình ảnh, tối đa 5 MB', 'PDF or image, up to 5 MB')}</small></span></button>
                <button type="button" role="menuitem" onClick={() => setPopover('date')}><CalendarClock size={16} aria-hidden="true" /><span>{text('Thời điểm tiếp nhận', 'Received time')}<small>{text('Bỏ trống nếu là lúc lưu', 'Leave blank to use the save time')}</small></span></button>
                <button type="button" role="menuitem" onClick={() => setPopover('sender')}><UserRound size={16} aria-hidden="true" /><span>{text('Người gửi / tham chiếu', 'Sender or reference')}<small>{text('Ví dụ: Khách hàng A, nhóm Zalo', 'Example: Customer A, support chat')}</small></span></button>
                <button type="button" role="menuitem" onClick={() => { setPopover(null); if (!recordOpen) toggleRecording() }}><MessagesSquare size={16} aria-hidden="true" /><span>{text('Ghi âm cuộc họp', 'Record a meeting')}<small>{text('Nhiều người nói; có tách người nói và meeting note', 'Multiple speakers, transcript, and meeting note')}</small></span></button>
              </div>
            )}
            {popover === 'date' && (
              <div className="composer-popover composer-field">
                <label>{text('Thời điểm tiếp nhận', 'Received time')}<input type="datetime-local" value={receivedAt} onChange={(e) => setReceivedAt(e.target.value)} autoFocus /></label>
                <div><button type="button" className="button button-secondary button-small" onClick={() => setReceivedAt(nowLocal())}>{text('Bây giờ', 'Now')}</button><button type="button" className="button button-primary button-small" onClick={() => setPopover(null)}>{text('Xong', 'Done')}</button></div>
              </div>
            )}
            {popover === 'sender' && (
              <div className="composer-popover composer-field">
                <label>{text('Người gửi / tham chiếu', 'Sender or reference')}<input value={senderReference} onChange={(e) => setSenderReference(e.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); setPopover(null) } }} placeholder={text('Ví dụ: Khách hàng A, nhóm Zalo', 'Example: Customer A, support chat')} autoFocus /></label>
                <div><button type="button" className="button button-primary button-small" onClick={() => setPopover(null)}>{text('Xong', 'Done')}</button></div>
              </div>
            )}
          </div>
          <select className="chip-select" aria-label={text('Dự án', 'Project')} value={projectId} onChange={(e) => setProjectId(e.target.value)} disabled={projects.isLoading || Boolean(projects.error)}>{projects.isLoading && <option>{text('Đang tải dự án…', 'Loading projects…')}</option>}{projects.data?.map((project) => <option value={project.code} key={project.id}>{project.name}</option>)}</select>
          <select className="chip-select" aria-label={text('Kênh', 'Channel')} value={channel} onChange={(e) => setChannel(e.target.value as Channel)}>{Object.entries(locale === 'en' ? channelLabelsEn : channelLabels).filter(([value]) => value !== 'FEEDBACK').map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select>
          {composerUser?.role === 'CTO' && <label className="chip-select hard-flag" title={text('Việc khó: nghiệm thu luôn về CTO, dù Project Owner đã xác nhận', 'High-risk work: acceptance always returns to the CTO, even after Project Owner review')}><input type="checkbox" checked={hard} onChange={(e) => setHard(e.target.checked)} /> {text('Việc khó', 'High-risk work')}</label>}
          <span className="composer-spacer" />
          <button type="button" className={dictating ? 'icon-button active is-recording' : 'icon-button'} aria-label={dictating ? text('Nói xong', 'Finish dictation') : text('Nói để nhập', 'Dictate request')} title={recordingBusy && !dictating ? text('Đang ghi cuộc họp; kết thúc ghi âm rồi mới nói để nhập được', 'Finish the meeting recording before starting dictation') : dictating ? text('Nói xong', 'Finish dictation') : text('Nói để nhập: bản chữ hiện ngay phía trên, nói xong chọn bản thô hoặc AI tóm tắt', 'Dictate the request, then choose the raw transcript or AI summary')} aria-pressed={dictating} disabled={recording.phase === 'starting' || recording.phase === 'stopping' || (recordingBusy && !dictating)} onClick={toggleDictation}><Mic size={18} /></button>
          <button className="send-button" aria-label={text('Lưu & phân tích', 'Save and analyze')} disabled={busy}>{mutation.isPending ? <span className="spinner" /> : <><span>{text('Lưu & phân tích', 'Save and analyze')}</span><ArrowUp size={16} aria-hidden="true" /></>}</button>
        </div>
        <input ref={fileRef} type="file" hidden multiple accept={ACCEPTED_FILE_TYPES.join(',')} onChange={(e) => { addFiles(Array.from(e.target.files ?? [])); e.target.value = '' }} />
      </form>
      {mutation.isPending && <p className="composer-stage" role="status">{stage}</p>}
      <p className="composer-note"><ShieldCheck size={15} aria-hidden="true" /> {text('Chỉ CTO xem được nội dung nguồn. Không có dữ liệu nào được gửi sang hệ thống delivery trước khi bạn duyệt.', 'Only the CTO can view the original content. Nothing is sent to a delivery system before you approve it.')}</p>
    </div>
  )
}

function IntakeListPage() {
  const [linked, setLinked] = useSearchParams()
  const queryClient = useQueryClient()
  const [removing, setRemoving] = useState<Intake>()
  const linkedStage = linked.get('stage')
  const linkedStatus = linked.get('status') as IntakeStatus | null
  const stage = linkedStage && linkedStage in lifecycleLabels ? linkedStage : linkedStatus && legacyStatusStages[linkedStatus] ? legacyStatusStages[linkedStatus]! : 'ALL'
  const projectRef = linked.get('project') || 'ALL'
  const target = ['GITLAB', 'GITHUB', 'PLANE', 'UNSYNCED', 'FAILED'].includes(linked.get('target') || '') ? linked.get('target')! : 'ALL'
  const priority = ['P0', 'P1', 'P2', 'P3'].includes(linked.get('priority') || '') ? linked.get('priority')! : 'ALL'
  const search = linked.get('search') || ''
  const [searchDraft, setSearchDraft] = useState(search)
  const [copied, setCopied] = useState(false)
  const pagination = readCursorPagination(linked)
  const pageNumber = pagination.page
  const cursor = pagination.cursor
  const [cursorHistory, setCursorHistory] = useState<Record<number, string>>({})
  const [paginationNotice, setPaginationNotice] = useState<string>()
  const pageSize = 10
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const selectedProject = projects.data?.find((entry) => entry.code === projectRef || entry.id === projectRef)
  const project = projectRef === 'ALL' ? 'ALL' : selectedProject?.code || projectRef
  const projectMissing = projectRef !== 'ALL' && projects.isSuccess && !selectedProject

  // Old links used status and a project UUID. Keep them working, then replace them with the canonical, shareable form.
  useEffect(() => {
    const next = new URLSearchParams(linked)
    let changed = false
    if (linkedStatus && !linkedStage && legacyStatusStages[linkedStatus]) { next.set('stage', legacyStatusStages[linkedStatus]!); changed = true }
    if (next.has('status')) { next.delete('status'); changed = true }
    if (selectedProject && projectRef === selectedProject.id) { next.set('project', selectedProject.code); changed = true }
    if (linkedStage && !(linkedStage in lifecycleLabels)) { next.delete('stage'); changed = true }
    if (linked.get('target') && target === 'ALL') { next.delete('target'); changed = true }
    if (linked.get('priority') && priority === 'ALL') { next.delete('priority'); changed = true }
    if (pagination.needsReset) {
      next.delete('page')
      next.delete('cursor')
      changed = true
      setPaginationNotice('Liên kết phân trang không đầy đủ nên danh sách đã trở về trang đầu.')
    }
    if (changed) setLinked(next, { replace: true })
  }, [linked, linkedStage, linkedStatus, pagination.needsReset, priority, projectRef, selectedProject, setLinked, target])

  const setFilter = useCallback((key: 'project' | 'stage' | 'target' | 'priority' | 'search', value: string | null, replace = false) => {
    setCursorHistory({})
    setPaginationNotice(undefined)
    setLinked((current) => {
      const next = clearCursorPagination(current)
      next.delete('status')
      if (value && value !== 'ALL') next.set(key, value)
      else next.delete(key)
      return next
    }, { replace })
  }, [setLinked])

  useEffect(() => { setSearchDraft(search) }, [search])
  useEffect(() => {
    const normalized = searchDraft.trim()
    if (normalized === search) return
    const timer = window.setTimeout(() => setFilter('search', normalized || null, true), 350)
    return () => window.clearTimeout(timer)
  }, [search, searchDraft, setFilter])
  useEffect(() => {
    if (!cursor) return
    setCursorHistory((current) => current[pageNumber] === cursor ? current : { ...current, [pageNumber]: cursor })
  }, [cursor, pageNumber])

  const query = useQuery({
    queryKey: ['intakes', search, stage, project, target, priority, cursor],
    queryFn: () => {
      const params = new URLSearchParams({ limit: String(pageSize) })
      if (search.trim()) params.set('search', search.trim())
      if (stage !== 'ALL') params.set('stage', stage)
      if (selectedProject) params.set('project_id', selectedProject.id)
      if (target !== 'ALL') params.set('target_system', target)
      if (priority !== 'ALL') params.set('priority', priority)
      if (cursor) params.set('cursor', cursor)
      return api<IntakePage>(`/intakes?${params.toString()}`)
    },
    enabled: projectRef === 'ALL' || Boolean(selectedProject),
  })
  useEffect(() => {
    if (!(query.error instanceof ApiError) || query.error.code !== 'INVALID_CURSOR') return
    setCursorHistory({})
    setPaginationNotice('Vị trí trang đã hết hạn hoặc không còn phù hợp với dữ liệu hiện tại. Danh sách đã trở về trang đầu.')
    setLinked((current) => clearCursorPagination(current), { replace: true })
  }, [query.error, setLinked])
  useEffect(() => {
    if (!query.isSuccess || pageNumber === 1 || (query.data?.items.length || 0) > 0) return
    setCursorHistory({})
    setPaginationNotice('Trang này không còn dữ liệu. Danh sách đã trở về trang đầu.')
    setLinked((current) => clearCursorPagination(current), { replace: true })
  }, [pageNumber, query.data?.items.length, query.isSuccess, setLinked])
  const filtered = query.data?.items || []
  const summary = query.data?.summary || { total_items: 0, p0_attention: 0, p1_attention: 0, pending_approval: 0, sync_failed: 0 }
  const projectScopeLabel = selectedProject ? `${selectedProject.intake_key} · ${selectedProject.name}` : 'Tất cả dự án'
  const hasFilters = Boolean(search || stage !== 'ALL' || project !== 'ALL' || target !== 'ALL' || priority !== 'ALL')
  const hasLinkedState = hasFilters || pageNumber > 1
  const resetFilters = () => { setCursorHistory({}); setPaginationNotice(undefined); setLinked(new URLSearchParams()) }
  const copyFilters = () => {
    const pendingSearch = searchDraft.trim()
    const shareParams = pendingSearch === search ? new URLSearchParams(linked) : clearCursorPagination(linked)
    if (pendingSearch) shareParams.set('search', pendingSearch)
    else shareParams.delete('search')
    const shareUrl = new URL(window.location.href)
    shareUrl.search = shareParams.toString()
    void navigator.clipboard.writeText(shareUrl.toString()).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    })
  }
  const rangeStart = summary.total_items === 0 ? 0 : (pageNumber - 1) * pageSize + 1
  const rangeEnd = Math.min((pageNumber - 1) * pageSize + filtered.length, summary.total_items)
  const previousCursor = cursorHistory[pageNumber - 1]
  const previousReturnsToStart = pageNumber > 2 && !previousCursor
  const goPrevious = () => {
    if (pageNumber <= 1) return
    setPaginationNotice(undefined)
    if (pageNumber === 2) {
      setLinked((current) => clearCursorPagination(current))
      return
    }
    if (previousCursor) {
      setLinked((current) => writeCursorPagination(current, pageNumber - 1, previousCursor))
      return
    }
    setPaginationNotice('Liên kết được mở trực tiếp nên không có cursor của trang trước. Danh sách đã trở về trang đầu.')
    setLinked((current) => clearCursorPagination(current))
  }
  const goNext = () => {
    const nextCursor = query.data?.next_cursor
    if (!nextCursor) return
    const nextPage = pageNumber + 1
    setPaginationNotice(undefined)
    setCursorHistory((current) => ({ ...current, [nextPage]: nextCursor }))
    setLinked((current) => writeCursorPagination(current, nextPage, nextCursor))
  }

  return (
    <>
      {removing && <RemoveIntakeDialog intake={removing} onCancel={() => setRemoving(undefined)} onDone={() => { setRemoving(undefined); void queryClient.invalidateQueries({ queryKey: ['intakes'] }); void queryClient.invalidateQueries({ queryKey: ['approvals'] }); void queryClient.invalidateQueries({ queryKey: ['alert-intakes'] }) }} />}
      {/* The top bar already carries "Tạo Intake" on every page (44bab21); a second one here showed twice. */}
      <PageHeader title="Tất cả Intake" helper="Danh sách chỉ hiển thị dữ liệu đã chuẩn hóa; nội dung nguồn không xuất hiện ở đây." />
      {(projects.data?.length || 0) > 1 && <div className="summary-scope"><span>Thống kê theo</span><strong>{projectScopeLabel}</strong></div>}
      <section className="attention-grid" aria-label="Tổng quan ưu tiên">
        <button className={`attention-card attention-p0 ${priority === 'P0' ? 'active' : ''}`} onClick={() => setFilter('priority', priority === 'P0' ? null : 'P0')}><span>P0 cần xử lý</span><strong>{summary.p0_attention}</strong><small>Khẩn cấp, chưa hoàn tất Intake</small></button>
        <button className={`attention-card attention-p1 ${priority === 'P1' ? 'active' : ''}`} onClick={() => setFilter('priority', priority === 'P1' ? null : 'P1')}><span>P1 cần xử lý</span><strong>{summary.p1_attention}</strong><small>Ưu tiên cao cần theo dõi</small></button>
        <button className={`attention-card attention-review ${stage === 'PENDING_APPROVAL' ? 'active' : ''}`} onClick={() => setFilter('stage', stage === 'PENDING_APPROVAL' ? null : 'PENDING_APPROVAL')}><span>Chờ CTO duyệt</span><strong>{summary.pending_approval}</strong><small>Cần ra quyết định</small></button>
        <button className={`attention-card attention-failed ${target === 'FAILED' ? 'active' : ''}`} onClick={() => setFilter('target', target === 'FAILED' ? null : 'FAILED')}><span>Sync cần chú ý</span><strong>{summary.sync_failed}</strong><small>Đồng bộ delivery lỗi</small></button>
      </section>
      <section className="panel filter-bar">
        <label className="search-field"><Search size={16} aria-hidden="true" /><input value={searchDraft} onChange={(e) => setSearchDraft(e.target.value)} placeholder="Tìm theo mã hoặc tiêu đề…" /></label>
        {(projects.data?.length || 0) > 1 && <select aria-label="Lọc dự án" value={project} onChange={(e) => setFilter('project', e.target.value === 'ALL' ? null : e.target.value)}><option value="ALL">Mọi dự án</option>{projects.data?.map((entry) => <option value={entry.code} key={entry.id}>{entry.intake_key} · {entry.name}</option>)}</select>}
        <select aria-label="Lọc chặng xử lý" value={stage} onChange={(e) => setFilter('stage', e.target.value === 'ALL' ? null : e.target.value)}><option value="ALL">Mọi chặng xử lý</option>{Object.entries(lifecycleLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select>
        <select aria-label="Lọc đích đồng bộ" value={target} onChange={(e) => setFilter('target', e.target.value === 'ALL' ? null : e.target.value)}><option value="ALL">Mọi đích</option><option value="GITLAB">GitLab</option><option value="GITHUB">GitHub</option><option value="PLANE">Plane · lịch sử</option><option value="UNSYNCED">Chưa Sync</option><option value="FAILED">Sync lỗi</option></select>
        <select aria-label="Lọc ưu tiên" value={priority} onChange={(e) => setFilter('priority', e.target.value === 'ALL' ? null : e.target.value)}><option value="ALL">Mọi ưu tiên</option>{['P0', 'P1', 'P2', 'P3'].map((value) => <option value={value} key={value}>{value}</option>)}</select>
        {hasLinkedState && <button className="filter-reset" onClick={resetFilters}>Đặt lại</button>}
        {hasLinkedState && <button className="filter-reset filter-copy" type="button" onClick={copyFilters}><Copy size={13} aria-hidden="true" /> {copied ? 'Đã chép link' : 'Chép liên kết'}</button>}
        <span className="result-count">{summary.total_items} kết quả</span>
      </section>
      {paginationNotice && <div className="notice notice-warn" role="status">{paginationNotice}</div>}
      <section className="panel list-panel">
        {projects.isLoading && projectRef !== 'ALL' ? <LoadingBlock />
          : projects.error && projectRef !== 'ALL' ? <ErrorNotice error={projects.error} onRetry={() => { void projects.refetch() }} />
            : projectMissing ? <EmptyState icon={<Search size={20} />} title="Không mở được dự án trong liên kết" text="Dự án không tồn tại hoặc tài khoản này không có quyền xem." />
              : query.isLoading ? <LoadingBlock />
                : query.error ? <ErrorNotice error={query.error} onRetry={() => { void query.refetch() }} />
                  : filtered.length === 0 ? <EmptyState icon={<Search size={20} />} title="Không tìm thấy Intake" text="Thử thay đổi bộ lọc hoặc tạo Intake mới." />
                    : <div className="item-list">{filtered.map((item) => <IntakeRow key={item.id} intake={item} onRemove={setRemoving} />)}</div>}
      </section>
      {summary.total_items > 0 && <nav className="pagination" aria-label="Phân trang Intake">
        <button className="button button-secondary" disabled={pageNumber === 1 || query.isFetching} title={previousReturnsToStart ? 'Link trực tiếp không chứa cursor của trang trước' : undefined} onClick={goPrevious}><ChevronLeft size={16} /> {previousReturnsToStart ? 'Trang đầu' : 'Trước'}</button>
        <div><strong>Trang {pageNumber}</strong><span>{rangeStart}–{rangeEnd} / {summary.total_items} Intake</span></div>
        <button className="button button-secondary" disabled={!query.data?.next_cursor || query.isFetching} onClick={goNext}>Tiếp <ChevronRight size={16} /></button>
      </nav>}
    </>
  )
}

const ocrWords: Record<string, string> = { NONE: 'chờ đọc', RUNNING: 'đang đọc', RETRY: 'đọc lại sau', DONE: 'đã đọc', FAILED: 'đọc lỗi', REJECTED: 'tệp bị từ chối', SKIPPED: 'không đọc' }
const ocrErrorWords: Record<string, string> = {
  ATTACHMENT_TYPE_MISMATCH: 'nội dung không đúng loại tệp', ATTACHMENT_PDF_UNREADABLE: 'PDF không mở được', ATTACHMENT_PDF_ENCRYPTED: 'PDF có mật khẩu',
  ATTACHMENT_PDF_EMBEDDED_FILES: 'PDF có tệp nhúng', UMODELVERSE_UNAVAILABLE: 'model không trả lời', UMODELVERSE_NOT_CONFIGURED: 'chưa cấu hình model',
  VISION_DISABLED: 'đọc ảnh đang tắt', STORAGE_UNAVAILABLE: 'kho tệp không trả lời', PARTIAL: 'chỉ đọc các trang đầu',
}

// The files on a request and whether the vision model read each; "Đọc lại" after an outage (FR-AI-14).
function AttachmentList({ intakeId, rows, onChanged }: { intakeId: string; rows: IntakeAttachment[]; onChanged: () => void }) {
  const reread = useMutation({ mutationFn: (attachmentId: string) => api(`/intakes/${intakeId}/attachments/${attachmentId}/read`, { method: 'POST' }), onSuccess: onChanged })
  const [preview, setPreview] = useState<{ name: string; url: string }>()
  const [previewing, setPreviewing] = useState<string>()
  const [previewError, setPreviewError] = useState<unknown>()

  useEffect(() => () => { if (preview?.url) URL.revokeObjectURL(preview.url) }, [preview?.url])
  useEffect(() => {
    if (!preview) return
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setPreview(undefined) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [preview])

  const openPreview = async (row: IntakeAttachment) => {
    setPreviewing(row.id)
    setPreviewError(undefined)
    try {
      const response = await fetch(`/api/v1/intakes/${intakeId}/attachments/${row.id}/file`, { credentials: 'include' })
      if (!response.ok) throw new Error(`Không thể mở ảnh (${response.status})`)
      const blob = await response.blob()
      if (!blob.type.startsWith('image/')) throw new Error('Tệp này không phải là ảnh có thể xem trước.')
      setPreview({ name: row.name || `Tệp ${row.index}`, url: URL.createObjectURL(blob) })
    } catch (error) {
      setPreviewError(error)
    } finally {
      setPreviewing(undefined)
    }
  }

  return (
    <>
      <ul className="attachment-list" aria-label="Tệp đính kèm">
        {rows.map((row) => {
          const fileUrl = `/api/v1/intakes/${intakeId}/attachments/${row.id}/file`
          return (
            <li key={row.id} className={`attachment-row ocr-${row.ocr_status.toLowerCase()}`}>
              <FileText size={14} aria-hidden="true" />
              <span className="attachment-name">{row.name || `Tệp ${row.index}`}<small>{row.mime_type === 'application/pdf' ? 'PDF' : 'Ảnh'} · {(row.size_bytes / 1024).toFixed(0)} KB{row.page_count && row.page_count > 1 ? ` · ${row.page_count} trang` : ''}</small></span>
              <span className="status attachment-ocr">{ocrWords[row.ocr_status] || row.ocr_status}{row.ocr_error ? `: ${ocrErrorWords[row.ocr_error] || row.ocr_error}` : ''}</span>
              <span className="attachment-actions">
                {row.mime_type?.startsWith('image/') && <button type="button" className="text-button attachment-preview-link" disabled={previewing === row.id} onClick={() => { void openPreview(row) }}><Eye size={13} aria-hidden="true" />{previewing === row.id ? 'Đang mở…' : 'Xem ảnh'}</button>}
                <a className="text-button attachment-download-link" href={fileUrl} download={row.name || undefined}><Download size={13} aria-hidden="true" />Tải tệp</a>
                {['FAILED', 'RETRY', 'REJECTED', 'SKIPPED', 'DONE'].includes(row.ocr_status) && <button type="button" className="text-button" disabled={reread.isPending} onClick={() => reread.mutate(row.id)}>Đọc lại</button>}
              </span>
            </li>
          )
        })}
      </ul>
      {previewError != null && <div className="attachment-preview-error"><ErrorNotice error={previewError} /></div>}
      {preview && createPortal(
        <div className="confirm-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setPreview(undefined) }}>
          <div className="attachment-preview-dialog" role="dialog" aria-modal="true" aria-labelledby="attachment-preview-title">
            <header><h2 id="attachment-preview-title">{preview.name}</h2><button type="button" className="icon-button" aria-label="Đóng xem ảnh" onClick={() => setPreview(undefined)}><X size={18} /></button></header>
            <img src={preview.url} alt={`Ảnh đính kèm ${preview.name}`} />
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}

function IntakeDetailPage() {
  const { locale, text } = useLocale()
  const { id = '' } = useParams()
  const location = useLocation()
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['intake', id],
    queryFn: () => api<Intake>(`/intakes/${id}`),
    refetchInterval: (query) => query.state.data?.status === 'PROCESSING' ? 2000 : false,
  })
  const projectCatalog = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const routeProject = projectCatalog.data?.find((project) => project.id === query.data?.project_id)
  const pipeline = useQuery({
    queryKey: ['pipeline', id],
    queryFn: () => api<PipelineStatus>(`/intakes/${id}/pipeline`),
    refetchInterval: (query) => ['QUEUED', 'RUNNING'].includes(query.state.data?.overall_state || '') ? 2000 : false,
  })
  const rawQuery = useQuery({ queryKey: ['raw', id], queryFn: () => api<IntakeRaw>(`/intakes/${id}/raw`), enabled: false })
  const attachments = useQuery({ queryKey: ['attachments', id], queryFn: () => api<IntakeAttachment[]>(`/intakes/${id}/attachments`), refetchInterval: (query) => (query.state.data || []).some((row) => ['NONE', 'RUNNING', 'RETRY'].includes(row.ocr_status)) ? 5000 : false })
  const syncStatus = useQuery({
    queryKey: ['sync-status', id],
    queryFn: () => api<SyncStatus>(`/intakes/${id}/sync-status`),
    refetchInterval: (query) => ['PENDING', 'RUNNING', 'RETRY'].includes(query.state.data?.job?.status || '') ? 2000 : false,
  })
  const [actionReason, setActionReason] = useState('')
  const [normalizedTitle, setNormalizedTitle] = useState('')
  const [normalizedSummary, setNormalizedSummary] = useState('')
  const [where, setWhere] = useState('')
  const [subtasks, setSubtasks] = useState('')
  const [acceptance, setAcceptance] = useState('')
  const [subtasksOpen, setSubtasksOpen] = useState(false)
  const [askApprove, setAskApprove] = useState(false)
  const [askApproveSync, setAskApproveSync] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [markingDuplicate, setMarkingDuplicate] = useState(false)
  const navigate = useNavigate()
  const [noteMissing, setNoteMissing] = useState(false)
  const noteRef = useRef<HTMLTextAreaElement>(null)
  const [splitting, setSplitting] = useState(false)
  const [splitInto, setSplitInto] = useState<Intake[]>()
  const { user: detailUser } = useAuth()
  const [priority, setPriority] = useState<Priority>('P2')
  const [route, setRoute] = useState<RouteTarget>('GITLAB')
  const [actionError, setActionError] = useState<unknown>()
  const notice = (location.state as { notice?: string } | null)?.notice
  // A request whose Issue is already in the delivery tracker is decided again for that tracker: the sync brings the
  // Issue up to date (reopened when closed) rather than making a second one. The AI is told the same (FR-AI-13).
  const deliveryLinkKey = (query.data?.sync_targets || []).filter((target) => target.external_id && (target.system === 'GITLAB' || target.system === 'GITHUB')).map((target) => `${target.system}#${target.external_id}`).join(',')

  useEffect(() => {
    if (query.data?.normalized_title != null) setNormalizedTitle(query.data.normalized_title)
    if (query.data?.normalized_summary != null) setNormalizedSummary(query.data.normalized_summary)
    if (query.data) {
      setWhere(query.data.details?.where || '')
      setSubtasks((query.data.details?.subtasks || []).join('\n'))
      setAcceptance((query.data.details?.acceptance || []).join('\n'))
    }
    if (query.data?.suggested_priority) setPriority(query.data.suggested_priority)
    if (query.data?.proposed_route) setRoute(deliveryLinkKey ? 'GITLAB' : query.data.proposed_route)
  }, [query.data?.normalized_title, query.data?.normalized_summary, query.data?.version, query.data?.suggested_priority, query.data?.proposed_route, deliveryLinkKey])

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['intake', id] }),
      queryClient.invalidateQueries({ queryKey: ['intakes'] }),
      queryClient.invalidateQueries({ queryKey: ['approvals'] }),
      queryClient.invalidateQueries({ queryKey: ['pipeline', id] }),
      queryClient.invalidateQueries({ queryKey: ['sync-status', id] }),
    ])
  }

  const processMutation = useMutation({ mutationFn: () => api<Intake>(`/intakes/${id}/process`, { method: 'POST' }), onMutate: () => setActionError(undefined), onSuccess: refresh, onError: setActionError })
  // What the fields were when AI started reading; when it ends, the ones that changed are marked for a moment.
  const [analysisStart, setAnalysisStart] = useState<{ at: number; fields: Record<string, string> } | null>(null)
  const [analysisDone, setAnalysisDone] = useState<{ at: number; changed: string[] } | null>(null)
  const analysingNow = query.data?.status === 'PROCESSING' || ['QUEUED', 'RUNNING'].includes(pipeline.data?.overall_state || '')
  const fieldsOf = (item: Intake | undefined): Record<string, string> => ({
    title: item?.normalized_title || '', summary: item?.normalized_summary || '',
    questions: (item?.details?.open_questions || []).join('\n'), acceptance: (item?.details?.acceptance || []).join('\n'),
    steps: (item?.details?.steps || []).join('\n'), priority: `${item?.item_type || ''}·${item?.suggested_priority || ''}·${item?.proposed_route || ''}`,
  })
  useEffect(() => {
    if (analysingNow && analysisStart === null) { setAnalysisStart({ at: Date.now(), fields: fieldsOf(query.data) }); setAnalysisDone(null) }
    if (!analysingNow && analysisStart !== null && query.data && query.data.status !== 'PROCESSING') {
      const after = fieldsOf(query.data)
      setAnalysisDone({ at: Date.now(), changed: Object.keys(after).filter((key) => after[key] !== analysisStart.fields[key]) })
      setAnalysisStart(null)
    }
  }, [analysingNow, analysisStart, query.data])
  useEffect(() => { if (!analysisDone) return; const timer = window.setTimeout(() => setAnalysisDone(null), 12000); return () => window.clearTimeout(timer) }, [analysisDone])
  const changedField = (key: string) => (analysisDone?.changed.includes(key) ? 'field-changed' : undefined)
  const reviewMutation = useMutation({
    mutationFn: (intake: Intake) => api<Intake>(`/intakes/${id}/review`, {
      method: 'PATCH',
      body: JSON.stringify({
        normalized_title: normalizedTitle.trim(),
        normalized_summary: normalizedSummary.trim(),
        suggested_priority: priority,
        proposed_route: route,
        expected_version: intake.version,
        details: { where: where.trim() || null, subtasks: linesOf(subtasks), acceptance: linesOf(acceptance) },
      }),
    }),
    onMutate: () => setActionError(undefined),
    onSuccess: refresh,
    onError: setActionError,
  })
  const actionMutation = useMutation({
    mutationFn: ({ action, body }: { action: string; body: object }) => api<Intake>(`/intakes/${id}/${action}`, { method: 'POST', body: JSON.stringify(body) }),
    onMutate: () => setActionError(undefined),
    onSuccess: async () => { setActionReason(''); await refresh() },
    onError: setActionError,
  })
  const hardFlag = useMutation({
    mutationFn: (value: boolean) => api<Intake>(`/intakes/${id}/hard-flag`, { method: 'PATCH', body: JSON.stringify({ needs_cto_acceptance: value }) }),
    onMutate: () => setActionError(undefined), onSuccess: refresh, onError: setActionError,
  })
  const approveAndSync = useMutation({
    mutationFn: async (intake: Intake) => {
      await api<Intake>(`/intakes/${id}/approve`, { method: 'POST', body: JSON.stringify({ approved_route: route, approved_priority: priority, reason: actionReason || null, expected_version: intake.version }) })
      try { await syncApproved(id) } catch (failure) { throw new Error(`Đã phê duyệt, nhưng chưa đồng bộ được: ${formatError(failure)} Bấm nút đồng bộ trong thanh để thử lại.`) }
    },
    onMutate: () => setActionError(undefined),
    onSuccess: () => setActionReason(''),
    onError: setActionError,
    onSettled: async () => { setAskApproveSync(false); await refresh() },
  })
  const unmarkDuplicate = useMutation({
    mutationFn: (intake: Intake) => api<Intake>(`/intakes/${id}/duplicate?expected_version=${intake.version}`, { method: 'DELETE' }),
    onMutate: () => setActionError(undefined), onSuccess: refresh, onError: setActionError,
  })
  // The AI pointed at an Issue that already exists; the approver confirms the request repeats it (INT-26W43-002).
  const markDuplicateIssue = useMutation({
    mutationFn: ({ intake, issue }: { intake: Intake; issue: string }) => api<Intake>(`/intakes/${id}/duplicate-issue`, { method: 'POST', body: JSON.stringify({ issue, expected_version: intake.version }) }),
    onMutate: () => setActionError(undefined), onSuccess: refresh, onError: setActionError,
  })
  const confirmDuplicateIssue = (intake: Intake, issue: IntakeDetails['related'][number]) => {
    if (!window.confirm(`Đóng ${intake.public_id} vì trùng với Issue #${issue.id}${issue.title ? ` "${issue.title}"` : ''}?\n\nYêu cầu rời Chờ phê duyệt và hiện nhãn "Trùng" dẫn sang Issue đó. Không có gì được ghi lên GitLab. Bỏ đánh dấu được sau.`)) return
    markDuplicateIssue.mutate({ intake, issue: issue.id })
  }
  const readyMutation = useMutation({
    mutationFn: (intake: Intake) => api<Intake>(`/intakes/${id}/ready`, { method: 'POST', body: JSON.stringify({ expected_version: intake.version }) }),
    onMutate: () => setActionError(undefined), onSuccess: refresh, onError: setActionError,
  })
  const splitMutation = useMutation({
    mutationFn: (intake: Intake) => api<{ original: Intake; children: Intake[] }>(`/intakes/${id}/split`, {
      method: 'POST', body: JSON.stringify({ expected_version: intake.version, items: linesOf(subtasks) }),
    }),
    onSuccess: async (result) => { setSplitting(false); setSplitInto(result.children); await refresh() },
  })
  const syncMutation = useMutation({
    mutationFn: (snapshotId: string) => api(`/approval-snapshots/${snapshotId}/sync`, { method: 'POST' }),
    onMutate: () => setActionError(undefined),
    onSuccess: refresh,
    onError: setActionError,
  })

  if (query.isLoading) return <LoadingBlock />
  if (query.error || !query.data) return <ErrorNotice error={query.error || new Error('Không tìm thấy Intake.')} onRetry={() => { void query.refetch() }} />
  const intake = query.data

  const doApprove = () => actionMutation.mutate({ action: 'approve', body: { approved_route: route, approved_priority: priority, reason: actionReason || null, expected_version: intake.version } })
  const openQuestions = unansweredOf(intake.details)
  // Where the request would go if approved now, when that place is a system outside Intake.
  const draftRoute = route === 'GITLAB' && routeProject?.delivery_system === 'GITHUB' ? 'GITHUB' : route
  const localizedRouteLabels = locale === 'en' ? routeLabelsEn : routeLabels
  const draftTarget = SYNCABLE_ROUTES.includes(draftRoute) ? localizedRouteLabels[draftRoute] : null
  // Open questions do not stop an approval; they make it a deliberate one.
  const approve = () => (openQuestions.length > 0 ? setAskApprove(true) : doApprove())
  const needNote = (message: string) => { setNoteMissing(true); setActionError(new Error(message)); noteRef.current?.focus() }
  // Why "Phê duyệt" cannot be pressed, and what to do about it.
  const canReady = ['NEEDS_INFORMATION', 'DEFERRED'].includes(intake.status)
  const blocked = intake.status === 'PENDING_APPROVAL' || ['APPROVED', 'SYNC_PENDING', 'SYNCED'].includes(intake.status) ? null
    : intake.status === 'NEEDS_INFORMATION' ? 'Yêu cầu đang ở "Cần làm rõ" nên chưa phê duyệt được. Khi đã đủ thông tin, đưa nó về chờ duyệt.'
    : intake.status === 'DEFERRED' ? 'Yêu cầu đang hoãn nên chưa phê duyệt được. Muốn quyết định lại thì đưa nó về chờ duyệt.'
    : intake.status === 'REJECTED' ? 'Yêu cầu đã bị từ chối hoặc đã được tách; không phê duyệt được nữa.'
    : intake.status === 'PROCESSING_FAILED' ? 'AI chưa phân tích được. Bấm "Phân tích lại", hoặc tự điền tiêu đề và tóm tắt rồi bấm "Lưu chỉnh sửa".'
    : 'AI đang phân tích. Phê duyệt được khi phân tích xong.'

  const transition = (action: string) => actionMutation.mutate({ action, body: { reason: actionReason || null, expected_version: intake.version } })
  const syncLocked = intake.status === 'SYNC_PENDING'
  const splitItems = linesOf(subtasks)
  const canSplit = splitItems.length >= 2 && ['PENDING_APPROVAL', 'NEEDS_INFORMATION'].includes(intake.status)
  const contentLocked = ['SYNC_PENDING', 'SYNCED'].includes(intake.status)
  const analysing = intake.status === 'PROCESSING' || ['QUEUED', 'RUNNING'].includes(pipeline.data?.overall_state || '')
  const decisionLocked = ['APPROVED', 'SYNC_PENDING', 'SYNCED'].includes(intake.status)
  // What each tracker already holds for this request; approving for it again updates that item (FR-APR-10).
  const heldItems = new Map<string, string>(intake.sync_targets.filter((target) => target.external_id || target.sequence_id).map((target) => [target.system, target.system === 'PLANE' ? (target.sequence_id ? `#${target.sequence_id}` : 'mục đã có') : `#${target.external_id}`]))
  const externalSync = syncStatus.data
  const syncTarget = intake.approved_route === 'PLANE' || intake.approved_route === 'GITLAB' || intake.approved_route === 'GITHUB' ? intake.approved_route : null
  const syncTargetLabel = syncTarget === 'GITLAB' ? 'GitLab' : syncTarget === 'GITHUB' ? 'GitHub' : 'Plane · lịch sử'
  const queueExternalSync = () => {
    if (!externalSync?.snapshot_id) {
      setActionError(new Error('Không tìm thấy approval snapshot hợp lệ.'))
      return
    }
    if (!window.confirm(`Tạo mục mới trên ${syncTargetLabel} cho ${intake.public_id}?\n\nThao tác này tạo dữ liệu ở ${syncTargetLabel} và Intake không tự xóa được. Nếu chọn nhầm nơi, bấm Hủy rồi "Rút lại phê duyệt".`)) return
    syncMutation.mutate(externalSync.snapshot_id)
  }
  // Taking a decision back: before the sync it only reopens the request; after it, what was created outside stays there.
  const reopen = () => {
    if (actionReason.trim().length < 5) { needNote('Cần ghi lý do (ít nhất 5 ký tự) ở ô ghi chú trước khi đổi quyết định.'); return }
    const question = intake.status === 'SYNCED'
      ? `Chuyển hướng ${intake.public_id}?\n\nYêu cầu quay về "Chờ phê duyệt" để bạn duyệt lại với nơi nhận khác. Mục đã tạo trên ${syncTargetLabel} KHÔNG bị xóa: bạn cần tự đóng hoặc xóa nó ở đó.`
      : `Rút lại phê duyệt của ${intake.public_id}?\n\nYêu cầu quay về "Chờ phê duyệt". Chưa có gì được tạo ở hệ thống ngoài.`
    if (window.confirm(question)) actionMutation.mutate({ action: 'reopen', body: { reason: actionReason.trim(), expected_version: intake.version } })
  }

  return (
    <>
      <div className="detail-top"><Link className="back-link" to="/intakes"><ArrowLeft size={15} /> {text('Tất cả Intake', 'All intakes')}</Link><div className="detail-actions">
        {canRemove(intake) && !intake.duplicate_of_id && !intake.duplicate_issue && <button type="button" className="button button-secondary" title="Đóng yêu cầu này vì đã có một yêu cầu khác nói cùng việc" onClick={() => setMarkingDuplicate(true)}>Đánh dấu trùng</button>}
        {canRemove(intake) && <button type="button" className="icon-button detail-remove" aria-label="Xóa yêu cầu" title="Xóa yêu cầu" onClick={() => setRemoving(true)}><Trash2 size={16} /></button>}
        <button className="button button-secondary" onClick={() => processMutation.mutate()} disabled={processMutation.isPending || contentLocked}>{processMutation.isPending ? text('Đang xử lý…', 'Processing…') : <><RotateCcw size={15} /> {text('Phân tích lại', 'Analyze again')}</>}</button></div></div>
      {notice && <div className="notice notice-warn">{notice}</div>}
      {removing && <RemoveIntakeDialog intake={intake} onCancel={() => setRemoving(false)} onDone={() => { void queryClient.invalidateQueries({ queryKey: ['intakes'] }); void queryClient.invalidateQueries({ queryKey: ['approvals'] }); void queryClient.invalidateQueries({ queryKey: ['alert-intakes'] }); navigate('/intakes') }} />}
      {markingDuplicate && <DuplicateDialog intake={intake} onCancel={() => setMarkingDuplicate(false)} onDone={() => { setMarkingDuplicate(false); void refresh() }} />}
      {intake.duplicate_of && (
        <div className="notice notice-warn duplicate-note" role="note">
          <span>Yêu cầu này đã được đóng vì trùng với <Link to={`/intakes/${intake.duplicate_of.id}`}>{intake.duplicate_of.public_id}</Link>{intake.duplicate_of.title ? `: ${intake.duplicate_of.title}` : ''}.</span>
          <button type="button" className="button button-secondary button-small" disabled={unmarkDuplicate.isPending} onClick={() => unmarkDuplicate.mutate(intake)}>{unmarkDuplicate.isPending ? 'Đang bỏ…' : 'Bỏ đánh dấu trùng'}</button>
        </div>
      )}
      {intake.duplicate_issue && (
        <div className="notice notice-warn duplicate-note" role="note">
          <span>Yêu cầu này đã được đóng vì trùng với Issue {intake.duplicate_issue.url ? <a href={intake.duplicate_issue.url} target="_blank" rel="noreferrer">#{intake.duplicate_issue.external_id}</a> : `#${intake.duplicate_issue.external_id}`}{intake.duplicate_issue.title ? `: ${intake.duplicate_issue.title}` : ''} trên GitLab.</span>
          <button type="button" className="button button-secondary button-small" disabled={unmarkDuplicate.isPending} onClick={() => unmarkDuplicate.mutate(intake)}>{unmarkDuplicate.isPending ? 'Đang bỏ…' : 'Bỏ đánh dấu trùng'}</button>
        </div>
      )}
      {splitInto && <div className="notice notice-success" role="status">Đã tách thành {splitInto.length} yêu cầu: {splitInto.map((child, index) => <span key={child.id}>{index > 0 ? ', ' : ''}<Link to={`/intakes/${child.id}`}>{child.public_id}</Link></span>)}. AI đang phân tích từng cái; chúng sẽ hiện ở Chờ phê duyệt.</div>}
      <header className="detail-header">
        <div><div className="detail-meta"><span className="public-id">{intake.public_id}</span><LifecycleBadge stage={intake.lifecycle_stage} />{intake.sync_targets.map((target) => <SyncTargetChip key={`${target.system}-${target.updated_at}`} target={target} />)}<ReadinessChip readiness={intake.agent_readiness} /></div><h1>{intake.normalized_title || text('Chưa có tiêu đề', 'Untitled')}</h1><p>{(locale === 'en' ? channelLabelsEn : channelLabels)[intake.channel]} · {text('cập nhật', 'updated')} {formatDate(intake.updated_at)} · {text('phiên bản', 'version')} {intake.version}</p></div>
        <PriorityBadge priority={intake.approved_priority || intake.suggested_priority} />
      </header>
      <IntakeJourney intakeId={intake.id} refreshKey={`${intake.status}-${intake.version}-${intake.sync_targets.length}`} humanWork={intake.agent_readiness?.band === 'HUMAN'} onChanged={refresh} />
      <ReadinessBox intake={intake} project={routeProject} />
      <div className="review-grid">
        <section className="panel source-panel">
          <div className="panel-heading"><div><h2>{text('Nội dung nguồn', 'Source request')}</h2></div><span className="restricted-tag">CTO only</span></div>
          {!rawQuery.data && !rawQuery.isFetching && !rawQuery.error && <div className="raw-guard"><ShieldCheck size={22} aria-hidden="true" /><strong>{text('Nội dung được bảo vệ', 'Protected content')}</strong><p>{text('Chỉ tải khi bạn cần đối chiếu. Hành động xem raw data thuộc phạm vi audit.', 'Load this only when you need to verify the source. Viewing raw data is audited.')}</p><button className="button button-secondary" onClick={() => rawQuery.refetch()}><Eye size={15} /> {text('Hiển thị nội dung nguồn', 'Show source request')}</button></div>}
          {rawQuery.isFetching && <LoadingBlock />}
          {rawQuery.error && <ErrorNotice error={rawQuery.error} onRetry={() => { void rawQuery.refetch() }} />}
          {rawQuery.data && <div className="raw-content">{rawQuery.data.raw_text || 'Nội dung đã hết thời hạn lưu hoặc không tồn tại.'}</div>}
          {rawQuery.data?.attachments?.filter((row) => row.text).map((row) => (
            <details className="raw-attachment" key={row.id} open>
              <summary>Chữ đọc từ ảnh {row.index}{row.name ? ` · ${row.name}` : ''}{row.page_count && row.page_count > 1 ? ` · ${row.pages_read}/${row.page_count} trang` : ''}</summary>
              <div className="raw-content">{row.text}</div>
            </details>
          ))}
          {attachments.data && attachments.data.length > 0 && <AttachmentList intakeId={intake.id} rows={attachments.data} onChanged={() => { void attachments.refetch(); void rawQuery.refetch() }} />}
        </section>
        <section className="panel normalized-panel">
          <div className="panel-heading"><div><h2>{text('Kết quả chuẩn hóa', 'Normalized result')}</h2></div><span className="ai-tag" title={text('Loại · Ưu tiên đề xuất · Route đề xuất', 'Type · Suggested priority · Suggested route')}>{text('AI đề xuất:', 'AI suggests:')} {[intake.item_type, intake.suggested_priority, intake.proposed_route && localizedRouteLabels[intake.proposed_route]].filter(Boolean).join(' · ') || text('chưa có', 'not available')}</span></div>
          <div className="normalized-form">
            <label className={changedField('title')}><span className="req-label">{text('Tiêu đề đã chuẩn hóa', 'Normalized title')}<Req /></span><input value={normalizedTitle} onChange={(event) => setNormalizedTitle(event.target.value)} maxLength={255} /></label>
            <label className={changedField('summary')}><span className="req-label">{text('Tóm tắt đã chuẩn hóa', 'Normalized summary')}<Req /></span><textarea rows={5} value={normalizedSummary} onChange={(event) => setNormalizedSummary(event.target.value)} /></label>
            <IntakeDetailsView details={intake.details} only={['steps', 'expected', 'related']} onDuplicateIssue={canRemove(intake) && !intake.duplicate_of_id && !intake.duplicate_issue && !markDuplicateIssue.isPending ? (issue) => confirmDuplicateIssue(intake, issue) : undefined} />
            <ClarifyQuestions intake={intake} locked={decisionLocked} analysing={analysing} onSaved={refresh} onError={setActionError} />
            <AnalysisStrip intake={intake} pipeline={pipeline.data} analysing={analysing} done={analysisDone} retrying={processMutation.isPending} onRetry={() => processMutation.mutate()} changedQuestions={Boolean(changedField('questions'))} />
            <label>{text('Ở đâu trong sản phẩm', 'Where in the product')}<input value={where} maxLength={600} onChange={(event) => setWhere(event.target.value)} placeholder={text('Module, màn hình hoặc chức năng liên quan', 'Related module, screen, or feature')} /></label>
            <label>{text('Tiêu chí nghiệm thu', 'Acceptance criteria')}<textarea rows={4} value={acceptance} onChange={(event) => setAcceptance(event.target.value)} placeholder={text('Mỗi dòng một kết quả kiểm được. Thành danh sách đánh dấu trong Issue khi đồng bộ.', 'One testable result per line. These become a checklist in the synced Issue.')} /></label>
            {subtasksOpen || subtasks.trim() !== '' ? (
              <label>Việc con<textarea rows={Math.max(linesOf(subtasks).length + 1, 3)} value={subtasks} onChange={(event) => setSubtasks(event.target.value)} placeholder="Chỉ dùng khi yêu cầu có vài ý nhỏ cùng loại, cùng chỗ. Mỗi dòng một việc." autoFocus={subtasksOpen && subtasks === ''} /></label>
            ) : (
              <button type="button" className="text-button details-add" onClick={() => setSubtasksOpen(true)}><Plus size={14} aria-hidden="true" /> Thêm việc con</button>
            )}
            {canSplit && (intake.details?.split_suggested ? (
              <div className="details-split-box" role="note">
                <p><TriangleAlert size={15} aria-hidden="true" /> <span><strong>Các việc con này không nên nằm chung một Issue.</strong> Chúng khác loại hoặc khác độ gấp: gộp lại thì không xếp ưu tiên, không giao và không đóng riêng từng việc được.</span></p>
                <button type="button" className="button button-secondary button-small" onClick={() => { splitMutation.reset(); setSplitting(true) }}>Tách thành {splitItems.length} yêu cầu riêng</button>
              </div>
            ) : (
              <button type="button" className="text-button details-add" onClick={() => { splitMutation.reset(); setSplitting(true) }}>Tách {splitItems.length} việc con thành yêu cầu riêng</button>
            ))}
            <button className="button button-secondary" onClick={() => reviewMutation.mutate(intake)} disabled={reviewMutation.isPending || syncLocked || analysing || !normalizedTitle.trim() || !normalizedSummary.trim()} title={analysing ? text('Chờ AI phân tích xong rồi lưu, để kết quả AI không bị ghi đè', 'Wait for AI analysis to finish before saving.') : undefined}>{reviewMutation.isPending ? text('Đang lưu…', 'Saving…') : text('Lưu chỉnh sửa', 'Save edits')}</button>
          </div>
          <details className="run-history"><summary><span className="field-label">Lịch sử chạy AI · {(pipeline.data?.stages || []).length} lần · {pipeline.data?.overall_state || 'NOT_STARTED'}</span></summary>{pipeline.isLoading ? <LoadingBlock /> : pipeline.error ? <ErrorNotice error={pipeline.error} onRetry={() => { void pipeline.refetch() }} /> : (pipeline.data?.stages || []).length === 0 ? <p className="muted">Chưa có lần xử lý nào.</p> : pipeline.data?.stages.map((run) => <div className="run-row" key={run.run_id}><span className={`run-dot ${run.status === 'SUCCEEDED' ? 'success' : ''}`} /><div><strong>{run.stage}</strong><small>{run.status} · lần {run.attempt}{run.finished_at ? ` · ${formatDate(run.finished_at)}` : ''}{run.error_code ? ` · ${run.error_code}` : ''}</small></div></div>)}</details>
        </section>
      </div>
      <WorkLogSection intake={intake} onChanged={refresh} />
      {splitting && (
        <ConfirmDialog plain title={`Tách thành ${splitItems.length} yêu cầu riêng?`} confirmLabel="Tách" busyLabel="Đang tách…" busy={splitMutation.isPending} error={splitMutation.error ?? undefined}
          onConfirm={() => splitMutation.mutate(intake)} onCancel={() => setSplitting(false)}>
          <ul>{splitItems.map((item) => <li key={item}>{item}</li>)}</ul>
          <ul>
            <li>Mỗi dòng thành một yêu cầu mới trong cùng dự án; AI phân tích lại từng cái với nguyên văn gốc làm tham khảo.</li>
            <li>{intake.public_id} được đóng lại, kèm ghi chú tên các yêu cầu mới.</li>
            <li>Chưa có Issue hay liên kết ngoài nào được tạo.</li>
          </ul>
        </ConfirmDialog>
      )}
      {askApproveSync && draftTarget && <ApproveSyncDialog intake={intake} target={draftTarget} priority={priority} openQuestions={openQuestions} busy={approveAndSync.isPending} onConfirm={() => approveAndSync.mutate(intake)} onCancel={() => setAskApproveSync(false)} />}
      {askApprove && (
        <ConfirmDialog plain title={`Còn ${openQuestions.length} câu chưa làm rõ. Vẫn phê duyệt?`} confirmLabel="Vẫn phê duyệt" busyLabel="Đang duyệt…" busy={actionMutation.isPending}
          onConfirm={() => { setAskApprove(false); doApprove() }} onCancel={() => setAskApprove(false)}>
          <ul>{openQuestions.map((question) => <li key={question}>{question}</li>)}</ul>
          <p>Các câu này sẽ nằm trong Issue dưới mục "Cần làm rõ". Muốn trả lời trước thì bấm Hủy rồi điền ở khối "Cần làm rõ trước khi làm".</p>
        </ConfirmDialog>
      )}
      <section className={decisionLocked ? 'decision-bar is-decided' : 'decision-bar'} aria-label={text('Quyết định', 'Decision')}>
        {actionError != null && <ErrorNotice error={actionError} onRetry={actionError instanceof ApiError && actionError.status === 409 ? () => { setActionError(undefined); void refresh() } : undefined} retryLabel={text('Tải phiên bản mới', 'Load latest version')} />}
        <div className="decision-bar-row">
          <strong className="decision-bar-title"><ClipboardCheck size={16} aria-hidden="true" /> {text('Quyết định', 'Decision')}</strong>
          <select aria-label={text('Độ ưu tiên', 'Priority')} title={text('Độ ưu tiên', 'Priority')} value={decisionLocked && intake.approved_priority ? intake.approved_priority : priority} onChange={(e) => setPriority(e.target.value as Priority)} disabled={decisionLocked}>{['P0', 'P1', 'P2', 'P3'].map((value) => <option key={value}>{value}</option>)}</select>
          {detailUser?.role === 'CTO' && <label className="hard-flag" title="Việc khó: nghiệm thu luôn về CTO, dù Project Owner đã xác nhận"><input type="checkbox" checked={intake.needs_cto_acceptance} disabled={hardFlag.isPending} onChange={(e) => hardFlag.mutate(e.target.checked)} /> Việc khó</label>}
          <select aria-label={text('Chuyển đến', 'Route to')} title={text('Chuyển đến', 'Route to')} value={decisionLocked && intake.approved_route ? intake.approved_route : route === 'GITLAB' && routeProject?.delivery_system === 'GITHUB' ? 'GITHUB' : route} onChange={(e) => setRoute(e.target.value as RouteTarget)} disabled={decisionLocked}>{Object.entries(localizedRouteLabels).filter(([value]) => value !== (routeProject?.delivery_system === 'GITHUB' ? 'GITLAB' : 'GITHUB') && (value !== 'PLANE' || intake.approved_route === 'PLANE')).map(([value, label]) => { const unlinked = routeProject != null && ((value === 'GITLAB' && !routeProject.gitlab_project_id) || (value === 'GITHUB' && !routeProject.github_repository)); return <option value={value} key={value} disabled={unlinked}>{label}{heldItems.has(value) ? ` · ${text('cập nhật', 'update')} ${heldItems.get(value)}` : unlinked ? ` · ${text('dự án chưa liên kết', 'project not linked')}` : ''}</option> })}</select>
          <textarea ref={noteRef} className={noteMissing ? 'decision-bar-note is-missing' : 'decision-bar-note'} rows={1} aria-label={text('Ghi chú quyết định', 'Decision note')} aria-invalid={noteMissing || undefined} value={actionReason} onChange={(e) => { setActionReason(e.target.value); setNoteMissing(false) }}
            onInput={(event) => { const box = event.currentTarget; box.style.height = 'auto'; box.style.height = `${Math.min(box.scrollHeight + 2, 64)}px` }}
            placeholder={intake.status === 'SYNC_PENDING' ? text('Đang đồng bộ: chờ xong mới đổi được quyết định', 'Sync in progress: wait before changing the decision') : decisionLocked ? text('Lý do đổi quyết định (bắt buộc khi rút lại hoặc chuyển hướng)', 'Reason for changing the decision (required)') : text('Ghi chú: lý do, thông tin còn thiếu… (bắt buộc khi từ chối)', 'Note: rationale or missing information (required when rejecting)')} />
          <div className="decision-bar-actions">
{!decisionLocked && draftTarget && <button className="button button-primary" title={text(`Phê duyệt rồi tạo mục trên ${draftTarget}. Sẽ hỏi lại một lần.`, `Approve, then create an item on ${draftTarget}. You will confirm once.`)} onClick={() => setAskApproveSync(true)} disabled={actionMutation.isPending || approveAndSync.isPending || intake.status !== 'PENDING_APPROVAL'}><ArrowUpRight size={15} aria-hidden="true" /> {text(`Duyệt và đồng bộ sang ${draftTarget}`, `Approve and sync to ${draftTarget}`)}</button>}
            {!decisionLocked && <button className={draftTarget ? 'button button-secondary' : 'button button-primary'} title={draftTarget ? text(`Phê duyệt nhưng chưa tạo gì trên ${draftTarget}; đồng bộ sau.`, `Approve without creating anything on ${draftTarget}; sync later.`) : text('Nơi nhận này không có hệ thống ngoài để đồng bộ.', 'This route has no external system to sync.')} onClick={approve} disabled={actionMutation.isPending || approveAndSync.isPending || intake.status !== 'PENDING_APPROVAL'}>{draftTarget ? text('Chỉ duyệt', 'Approve only') : text('Phê duyệt', 'Approve')}</button>}
            {syncTarget && decisionLocked && <button className="button button-primary" onClick={queueExternalSync} disabled={syncMutation.isPending || !externalSync?.sync_available}>{syncMutation.isPending ? text('Đang đưa vào hàng đợi…', 'Queueing…') : <><ArrowUpRight size={15} />{externalSync?.job?.status === 'FAILED' ? text(`Thử lại đồng bộ ${syncTargetLabel}`, `Retry ${syncTargetLabel} sync`) : text(`Đồng bộ sang ${syncTargetLabel}`, `Sync to ${syncTargetLabel}`)}</>}</button>}
            {['APPROVED', 'SYNCED'].includes(intake.status) && <button className="button button-secondary" onClick={reopen} disabled={actionMutation.isPending} title="Đưa yêu cầu về Chờ phê duyệt để quyết định lại. Cần ghi lý do.">{intake.status === 'SYNCED' ? 'Chuyển hướng' : 'Rút lại phê duyệt'}</button>}
            {!decisionLocked && <button className="button button-secondary" onClick={() => transition('needs-information')} disabled={actionMutation.isPending}>{text('Cần làm rõ', 'Needs information')}</button>}
            {!decisionLocked && <button className="button button-secondary" onClick={() => transition('defer')} disabled={actionMutation.isPending}>{text('Hoãn', 'Defer')}</button>}
            {!decisionLocked && <button className="button button-danger" onClick={() => actionReason.trim() ? transition('reject') : needNote(text('Cần nhập lý do ở ô ghi chú trước khi từ chối.', 'Enter a reason in the note before rejecting.'))} disabled={actionMutation.isPending}>{text('Từ chối', 'Reject')}</button>}
          </div>
        </div>
        {blocked && (
          <p className="decision-bar-why" role="note">
            <CircleHelp size={14} aria-hidden="true" /><span>{blocked}</span>
            {canReady && <button type="button" className="button button-secondary button-small" disabled={readyMutation.isPending} onClick={() => readyMutation.mutate(intake)}>{readyMutation.isPending ? 'Đang chuyển…' : 'Đưa về chờ duyệt'}</button>}
          </p>
        )}
        {intake.work_item && intake.approved_route === 'WORK' && decisionLocked && <div className="sync-result sync-work"><span>Việc nội bộ · {workColumnLabels[intake.work_item.status]}</span><small>Bàn, giao và theo dõi trên bảng việc của dự án.</small><Link to={`/viec?project=${intake.work_item.project_id}&work=${intake.work_item.id}`}>Mở {intake.work_item.code}</Link></div>}
        {syncTarget && decisionLocked && <div className={`sync-result sync-${(externalSync?.job?.status || 'ready').toLowerCase()}`}><span>{syncTargetLabel} · {externalSync?.job?.status || (syncStatus.isLoading ? 'LOADING' : 'READY')}</span>{externalSync?.job?.error_code && <small>{externalSync.job.error_code} · lần {externalSync.job.attempt}/{externalSync.job.max_attempts}</small>}{syncTarget !== 'PLANE' && (externalSync?.job?.status === 'SUCCEEDED' || intake.sync_targets.some((target) => target.system === syncTarget && target.external_id && !target.superseded)) && <AgentCommand intake={intake} issue={intake.sync_targets.find((target) => target.system === syncTarget && !target.superseded)?.external_id || null} />}{externalSync?.job?.external_url && <a href={externalSync.job.external_url} target="_blank" rel="noreferrer">Mở work item <ArrowUpRight size={13} /></a>}</div>}
      </section>
    </>
  )
}

const FLOW_GUIDE_KEY = 'intake-flow-guide-hidden'
const flowSteps = [
  { key: 'receive', label: 'Intake', hint: 'Yêu cầu vào Intake và được AI chuẩn hóa.' },
  { key: 'approve', label: 'Phê duyệt', hint: 'Quyết định yêu cầu có làm không, ưu tiên nào, đi đâu. Chưa ai được giao việc.' },
  { key: 'issue', label: 'Issue', hint: 'Đồng bộ tạo Issue trên GitLab/GitHub. Chỉ việc có Issue mới lập kế hoạch được.' },
  { key: 'assign', label: 'Xếp việc', hint: 'Giao Issue cho một người, một buổi, một số giờ trong ngày.' },
  { key: 'close', label: 'Chốt kế hoạch', hint: 'Chốt bảng phân công của ngày. Không phê duyệt yêu cầu nào.' },
] as const

const flowStepsEn = [
  { key: 'receive', label: 'Intake', hint: 'The request enters Intake and AI organizes it.' },
  { key: 'approve', label: 'Approve', hint: 'Decide whether to do it, its priority, and where it goes. No one is assigned yet.' },
  { key: 'issue', label: 'Issue', hint: 'Sync creates a GitLab or GitHub Issue. Only work with an Issue can be planned.' },
  { key: 'assign', label: 'Plan', hint: 'Assign the Issue to a person, a time slot, and a number of hours.' },
  { key: 'close', label: 'Close plan', hint: 'Close the daily assignment board. This does not approve requests.' },
] as const

// One line that shows where a page sits in the whole flow; it can be hidden once it is familiar.
// A small (i) with a sentence behind it: hover shows it, a tap opens it (phones), a tap elsewhere closes it.
function InfoTip({ label, text }: { label: string; text: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!open) return
    const away = (event: PointerEvent) => { if (!ref.current?.contains(event.target as Node)) setOpen(false) }
    document.addEventListener('pointerdown', away)
    return () => document.removeEventListener('pointerdown', away)
  }, [open])
  return (
    <span className={`info-tip${open ? ' is-open' : ''}`} ref={ref}>
      <button type="button" aria-label={label} aria-expanded={open} onClick={() => setOpen((value) => !value)}><Info size={14} aria-hidden="true" /></button>
      <span className="info-tip-text" role="tooltip">{text}</span>
    </span>
  )
}

// Keeps a bar fixed at the foot of the viewport but aligned with the page column, whatever the sidebar and right panel do.
function usePinnedToPageColumn(ref: { current: HTMLElement | null }, active: boolean) {
  useLayoutEffect(() => {
    if (!active) return
    const bar = ref.current
    const page = bar?.closest('.page') as HTMLElement | null
    if (!bar || !page) return
    const apply = () => {
      const rect = page.getBoundingClientRect()
      const style = getComputedStyle(page)
      bar.style.left = `${rect.left + parseFloat(style.paddingLeft)}px`
      bar.style.width = `${rect.width - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)}px`
    }
    apply()
    const observer = new ResizeObserver(apply)
    observer.observe(page)
    window.addEventListener('resize', apply)
    return () => { observer.disconnect(); window.removeEventListener('resize', apply) }
  }, [ref, active])
}

function FlowGuide({ here, note }: { here: readonly string[]; note: string }) {
  const { locale, text } = useLocale()
  const [hidden, setHidden] = useState(() => localStorage.getItem(FLOW_GUIDE_KEY) !== '0')
  const toggle = (next: boolean) => { localStorage.setItem(FLOW_GUIDE_KEY, next ? '1' : '0'); setHidden(next) }
  if (hidden) return <button className="flow-guide-reopen" type="button" onClick={() => toggle(false)}><CircleHelp size={14} /> {text('Luồng xử lý một yêu cầu', 'Request lifecycle')}</button>
  return (
    <section className="flow-guide" aria-label={text('Luồng xử lý một yêu cầu', 'Request lifecycle')}>
      <ol>
        {(locale === 'en' ? flowStepsEn : flowSteps).map((step) => <li key={step.key} className={here.includes(step.key) ? 'here' : undefined} title={step.hint}><span>{step.label}</span></li>)}
      </ol>
      <p>{note}</p>
      <button className="button button-secondary button-small" type="button" onClick={() => toggle(true)}>{text('Đã hiểu', 'Got it')}</button>
    </section>
  )
}

// What was done about the request and what the CTO made of it; and the hints the CTO leaves for whoever does it.
function WorkLogSection({ intake, onChanged }: { intake: Intake; onChanged: () => void }) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const isCto = user?.role === 'CTO'
  const [hints, setHints] = useState<string>()
  const [hintsSaved, setHintsSaved] = useState(false)
  const [adding, setAdding] = useState(false)
  const [summary, setSummary] = useState('')
  const [commit, setCommit] = useState('')
  const [branch, setBranch] = useState('')
  const [tests, setTests] = useState('')
  const [workedOn, setWorkedOn] = useState(todayInPlanningTimezone())
  const [actualMinutes, setActualMinutes] = useState('')
  const [deployed, setDeployed] = useState(false)
  const [returning, setReturning] = useState<IntakeWorkLog>()
  const [note, setNote] = useState('')
  const [error, setError] = useState<unknown>()
  const log = useQuery({ queryKey: ['work-log', intake.id], queryFn: () => api<IntakeWorkLog[]>(`/intakes/${intake.id}/work-log`) })
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['work-log', intake.id] }); void queryClient.invalidateQueries({ queryKey: ['intake-journey', intake.id] }); onChanged() }
  const saveHints = useMutation({
    mutationFn: (text: string) => api<Intake>(`/intakes/${intake.id}/fix-hints`, { method: 'PATCH', body: JSON.stringify({ fix_hints: text.trim() || null }) }),
    onMutate: () => setError(undefined), onSuccess: () => { setHints(undefined); setHintsSaved(true); window.setTimeout(() => setHintsSaved(false), 2500); onChanged() }, onError: setError,
  })
  const add = useMutation({
    mutationFn: () => api<IntakeWorkLog>(`/intakes/${intake.id}/work-log`, { method: 'POST', body: JSON.stringify({ summary: summary.trim(), details: { commit: commit.trim() || null, branch: branch.trim() || null, tests: tests.trim() || null, worked_on: workedOn, actual_minutes: actualMinutes ? Number(actualMinutes) : null, deployed } }) }),
    onMutate: () => setError(undefined), onSuccess: () => { setAdding(false); setSummary(''); setCommit(''); setBranch(''); setTests(''); setWorkedOn(todayInPlanningTimezone()); setActualMinutes(''); setDeployed(false); refresh() }, onError: setError,
  })
  const review = useMutation({
    mutationFn: ({ id, decision, why }: { id: string; decision: 'CONFIRMED' | 'RETURNED'; why?: string }) => api<IntakeWorkLog>(`/intakes/${intake.id}/work-log/${id}/review`, { method: 'POST', body: JSON.stringify({ decision, note: why || null }) }),
    onMutate: () => setError(undefined), onSuccess: () => { setReturning(undefined); setNote(''); refresh() }, onError: setError,
  })
  const hintsText = hints ?? intake.fix_hints ?? ''
  const hintsDirty = hintsText !== (intake.fix_hints ?? '')
  const rows = log.data || []
  const decisionLabel = { PENDING: 'Chờ CTO nghiệm thu', CONFIRMED: 'Đã nghiệm thu', RETURNED: 'Chưa đúng, trả lại' } as const
  const list = (items?: string[]) => (items && items.length > 0 ? <ul>{items.map((item, index) => <li key={index}>{item}</li>)}</ul> : null)
  return (
    <section className="panel work-log" id="intake-work-log" aria-label="Lịch sử xử lý">
      {returning && (
        <ConfirmDialog plain title="Chưa đúng ở chỗ nào?" confirmLabel="Trả lại" busyLabel="Đang ghi…" busy={review.isPending} error={review.error ?? undefined} onConfirm={() => { if (note.trim().length >= 3) review.mutate({ id: returning.id, decision: 'RETURNED', why: note.trim() }) }} onCancel={() => { setReturning(undefined); setNote('') }}>
          <label>Lý do<textarea rows={3} value={note} maxLength={1000} onChange={(event) => setNote(event.target.value)} placeholder="Ví dụ: vẫn 0 khi lọc theo dự án" /></label>
          <ul><li>Người hay agent làm lại sẽ đọc lý do này trước.</li><li>Issue và trạng thái yêu cầu không đổi.</li></ul>
        </ConfirmDialog>
      )}
      <div className="panel-heading"><div><h2>Lịch sử xử lý</h2></div><span className="muted">{rows.length > 0 ? `${rows.length} mục` : 'chưa có'}</span></div>
      {error != null && <ErrorNotice error={error} />}
      <label className="work-hints">
        <span>Gợi ý cho người sửa <small>(đi cùng yêu cầu khi agent hay dev đọc qua MCP)</small></span>
        <textarea rows={3} value={hintsText} maxLength={2000} onChange={(event) => setHints(event.target.value)} placeholder="Vùng code nghi ngờ, điều kiện tái hiện, điều không được đụng…" />
        <div><button type="button" className="button button-secondary button-small" disabled={!hintsDirty || saveHints.isPending} onClick={() => saveHints.mutate(hintsText)}>{saveHints.isPending ? 'Đang lưu…' : hintsSaved && !hintsDirty ? 'Đã lưu' : 'Lưu gợi ý'}</button></div>
      </label>
      {log.error != null && <ErrorNotice error={log.error} onRetry={() => { void log.refetch() }} />}
      {rows.length > 0 && (
        <ol className="work-log-list">
          {rows.map((row) => (
            <li key={row.id} className={`decision-${row.review_decision.toLowerCase()}`}>
              <header>
                <strong>{row.summary}</strong>
                <small>{row.agent_name ? `agent ${row.agent_name}` : row.actor_name || 'không rõ'} · {formatDate(row.created_at)}</small>
                <span className={`status work-decision decision-${row.review_decision.toLowerCase()}`}>{decisionLabel[row.review_decision]}</span>
              </header>
              {(row.details.cause || row.details.tests || row.details.commit || row.details.branch || row.details.changes?.length || row.details.verify_steps?.length || row.details.deploy_steps?.length || row.details.context_suggestions?.length || row.details.worked_on || row.details.actual_minutes != null || row.details.deployed != null) ? (
                <details>
                  <summary>Chi tiết{row.details.commit ? ` · commit ${row.details.commit}` : ''}{row.details.branch ? ` · ${row.details.branch}` : ''}</summary>
                  <dl>
                    {row.details.cause && <><dt>Nguyên nhân</dt><dd>{row.details.cause}</dd></>}
                    {row.details.changes && row.details.changes.length > 0 && <><dt>Đã đổi</dt><dd>{list(row.details.changes)}</dd></>}
                    {row.details.tests && <><dt>Test</dt><dd>{row.details.tests}</dd></>}
                    {(row.details.branch || row.details.commit) && <><dt>Nhánh · commit</dt><dd>{[row.details.branch, row.details.commit].filter(Boolean).join(' · ')}</dd></>}
                    {row.details.verify_steps && row.details.verify_steps.length > 0 && <><dt>Cách kiểm</dt><dd>{list(row.details.verify_steps)}</dd></>}
                    {row.details.deploy_steps && row.details.deploy_steps.length > 0 && <><dt>Triển khai</dt><dd>{list(row.details.deploy_steps)}</dd></>}
                    {row.details.worked_on && <><dt>Ngày làm thực tế</dt><dd>{formatDay(row.details.worked_on)}</dd></>}
                    {row.details.actual_minutes != null && <><dt>Thời gian thực tế</dt><dd>{hoursText(row.details.actual_minutes / 60)}</dd></>}
                    {row.details.deployed != null && <><dt>Trạng thái triển khai</dt><dd>{row.details.deployed ? 'Đã có bản triển khai để kiểm' : 'Chưa triển khai'}</dd></>}
                    {row.details.context_suggestions && row.details.context_suggestions.length > 0 && <><dt>Gợi ý cho hồ sơ</dt><dd>{list(row.details.context_suggestions)}<small className="field-help">CTO quyết ở Cài đặt › Dự án › Hồ sơ ngữ cảnh.</small></dd></>}
                  </dl>
                </details>
              ) : null}
              {row.review_note && <p className="work-note">{row.review_decision === 'RETURNED' ? 'Trả lại' : 'Ghi chú'}: {row.review_note}{row.reviewed_by_name ? ` — ${row.reviewed_by_name}` : ''}</p>}
              {isCto && row.review_decision === 'PENDING' && (
                <div className="work-actions">
                  <button type="button" className="button button-primary button-small" disabled={review.isPending} onClick={() => review.mutate({ id: row.id, decision: 'CONFIRMED' })}>Đạt nghiệm thu</button>
                  <button type="button" className="button button-secondary button-small" disabled={review.isPending} onClick={() => { setNote(''); setReturning(row) }}>Chưa đúng</button>
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
      {adding ? (
        <form className="work-add" onSubmit={(event) => { event.preventDefault(); if (summary.trim().length >= 5) add.mutate() }}>
          <input value={summary} maxLength={1000} onChange={(event) => setSummary(event.target.value)} placeholder="Đã làm gì (một câu)" aria-label="Tóm tắt việc đã làm" />
          <div className="work-add-row">
            <input value={branch} maxLength={200} onChange={(event) => setBranch(event.target.value)} placeholder="Nhánh" aria-label="Nhánh" />
            <input value={commit} maxLength={200} onChange={(event) => setCommit(event.target.value)} placeholder="Commit" aria-label="Commit" />
          </div>
          <input value={tests} maxLength={500} onChange={(event) => setTests(event.target.value)} placeholder="Test đã chạy" aria-label="Test đã chạy" />
          <div className="work-add-row">
            <label>Ngày làm thực tế<input type="date" value={workedOn} onChange={(event) => setWorkedOn(event.target.value)} /></label>
            <label>Phút thực tế<input type="number" min={0} max={1440} value={actualMinutes} onChange={(event) => setActualMinutes(event.target.value)} placeholder="vd. 90" /></label>
          </div>
          <label className="check-row"><input type="checkbox" checked={deployed} onChange={(event) => setDeployed(event.target.checked)} /> Đã có bản triển khai để CTO kiểm</label>
          <div className="work-add-row"><button className="button button-primary button-small" disabled={summary.trim().length < 5 || add.isPending}>{add.isPending ? 'Đang ghi…' : 'Ghi vào lịch sử'}</button><button type="button" className="text-button" onClick={() => setAdding(false)}>Hủy</button></div>
        </form>
      ) : (
        <button type="button" className="text-button details-add" onClick={() => setAdding(true)}><Plus size={14} aria-hidden="true" /> Ghi việc đã làm</button>
      )}
      <p className="field-help">Agent (Claude Code, Codex) ghi vào đây bằng tool <code>log_work</code> sau khi sửa trên nhánh riêng; người ghi tay bằng nút trên. Chỉ CTO xác nhận hoặc trả lại.</p>
    </section>
  )
}

function IntakeJourney({ intakeId, refreshKey, humanWork, onChanged }: { intakeId: string; refreshKey: string; humanWork: boolean; onChanged: () => void }) {
  const { locale, text } = useLocale()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [returning, setReturning] = useState<string>()
  const [note, setNote] = useState('')
  const [confirmingVerification, setConfirmingVerification] = useState(false)
  const [rejectingVerification, setRejectingVerification] = useState(false)
  const [verificationNote, setVerificationNote] = useState('')
  const [verificationError, setVerificationError] = useState<unknown>()
  const [reconciling, setReconciling] = useState(false)
  const [reconcileSummary, setReconcileSummary] = useState('')
  const [reconcileMinutes, setReconcileMinutes] = useState('')
  const [reconcileDeployed, setReconcileDeployed] = useState(true)
  const journey = useQuery({ queryKey: ['intake-journey', intakeId, refreshKey], queryFn: () => api<IntakeJourney>(`/intakes/${intakeId}/journey`) })
  // Keep the CTA available while web and API are rolled out separately: older Journey responses do not include latest_id.
  const workLog = useQuery({
    queryKey: ['work-log', intakeId],
    queryFn: () => api<IntakeWorkLog[]>(`/intakes/${intakeId}/work-log`),
    enabled: user?.role === 'CTO',
  })
  const review = useMutation({
    mutationFn: ({ id, decision, why }: { id: string; decision: 'CONFIRMED' | 'RETURNED'; why?: string }) => api<IntakeWorkLog>(`/intakes/${intakeId}/work-log/${id}/review`, { method: 'POST', body: JSON.stringify({ decision, note: why || null }) }),
    onSuccess: () => {
      setReturning(undefined)
      setNote('')
      void queryClient.invalidateQueries({ queryKey: ['work-log', intakeId] })
      void queryClient.invalidateQueries({ queryKey: ['intake-journey', intakeId] })
      onChanged()
    },
  })
  const reconcile = useMutation({
    mutationFn: () => api<IntakeWorkLog>(`/intakes/${intakeId}/work-log`, { method: 'POST', body: JSON.stringify({
      summary: reconcileSummary.trim(),
      details: { worked_on: todayInPlanningTimezone(), actual_minutes: reconcileMinutes ? Number(reconcileMinutes) : null, deployed: reconcileDeployed },
    }) }),
    onMutate: () => setVerificationError(undefined),
    onSuccess: () => {
      setReconciling(false); setReconcileSummary(''); setReconcileMinutes(''); setReconcileDeployed(true)
      void queryClient.invalidateQueries({ queryKey: ['work-log', intakeId] })
      void queryClient.invalidateQueries({ queryKey: ['intake-journey', intakeId] })
      onChanged()
    },
    onError: setVerificationError,
  })
  const refreshJourney = () => {
    void queryClient.invalidateQueries({ queryKey: ['intake-journey', intakeId] })
    void queryClient.invalidateQueries({ queryKey: ['acceptance'] })
    onChanged()
  }
  const markDone = useMutation({
    mutationFn: ({ runId, assignmentId }: { runId: string; assignmentId: string }) => api<WorkStatusResult>(`/planning/runs/${runId}/assignments/${assignmentId}/work-status`, { method: 'PATCH', body: JSON.stringify({ status: 'DONE' }) }),
    onMutate: () => setVerificationError(undefined), onSuccess: refreshJourney, onError: setVerificationError,
  })
  const decideVerification = useMutation({
    mutationFn: ({ id, decision, text }: { id: string; decision: 'accept' | 'reject'; text?: string }) => api<AcceptanceItem>(`/acceptance/${id}/${decision}`, { method: 'POST', body: JSON.stringify({ reason: decision === 'reject' ? text || null : null, evidence_missing_reason: decision === 'accept' ? text || null : null }) }),
    onMutate: () => setVerificationError(undefined),
    onSuccess: () => { setConfirmingVerification(false); setRejectingVerification(false); setVerificationNote(''); refreshJourney() },
    onError: setVerificationError,
  })
  const data = journey.data
  if (!data) return null
  const decision = data.decision
  const approved = decision?.action === 'APPROVE' && ['APPROVED', 'SYNC_PENDING', 'SYNCED'].includes(data.status)
  const stopped = ['REJECTED', 'DEFERRED', 'NEEDS_INFORMATION'].includes(data.status)
  const trackerName = data.issue?.system === 'GITHUB' ? 'GitHub' : 'GitLab'
  const noIssueRoute = approved && !data.issue && decision?.route !== 'GITLAB' && decision?.route !== 'GITHUB'
  const latest = data.plans[0]
  const linkedPlan = latest || data.waiting_in_plan
  const planningLink = linkedPlan
    ? `/planning?date=${encodeURIComponent(linkedPlan.plan_date)}&project=${encodeURIComponent(data.project_id)}&intake=${encodeURIComponent(data.intake_public_id)}`
    : '/planning'
  const slotName = (slot: string) => (slot === 'MORNING' ? text('sáng', 'morning') : text('chiều', 'afternoon'))
  const canOpenPlan = user?.role === 'CTO'
  const latestListedWork = workLog.data?.[0]
  const pendingWorkId = data.work?.latest_id || (latestListedWork?.review_decision === 'PENDING' ? latestListedWork.id : undefined)
  const canReviewWork = user?.role === 'CTO' && (data.work?.latest_decision || latestListedWork?.review_decision) === 'PENDING' && Boolean(pendingWorkId)
  const pendingVerification = data.verification?.decision === 'PENDING' ? data.verification : null
  const canDecideVerification = user?.role === 'CTO' && Boolean(pendingVerification)
  const canMarkHumanDone = user?.role === 'CTO' && humanWork && Boolean(latest) && !data.accepted_at && !pendingVerification && latest?.work_status !== 'DONE'
  const canReconcileWork = user?.role === 'CTO' && !data.work && Boolean(data.unlogged_evidence)
  type Step = { label: string; state: 'done' | 'now' | 'todo' | 'skip'; text: ReactNode; actions?: ReactNode }
  const steps: Step[] = [
    { label: text('Tiếp nhận', 'Captured'), state: 'done', text: `${(locale === 'en' ? channelLabelsEn : channelLabels)[data.channel as Channel] || data.channel} · ${formatDate(data.received_at)}` },
    {
      label: text('Phê duyệt', 'Approved'), state: approved ? 'done' : stopped ? 'skip' : 'now',
      text: approved ? `${decision?.by || text('Đã duyệt', 'Approved')} · ${formatDate(decision!.at)}${decision?.priority ? ` · ${decision.priority}` : ''}`
        : stopped ? (statusLabels[data.status as IntakeStatus] || data.status) : text('Đang chờ quyết định', 'Waiting for a decision'),
    },
    {
      label: 'Issue', state: data.issue ? 'done' : noIssueRoute || stopped ? 'skip' : approved ? 'now' : 'todo',
      text: data.issue ? (data.issue.url ? <a href={data.issue.url} target="_blank" rel="noreferrer">{trackerName} #{data.issue.external_id}</a> : `${trackerName} #${data.issue.external_id}`)
        : noIssueRoute && data.work_item ? <>Thành việc nội bộ <Link to={`/viec?project=${data.work_item.project_id}&work=${data.work_item.id}`}>{data.work_item.code}</Link> · {workColumnLabels[data.work_item.status]}{data.work_item.status === 'DONE' || data.work_item.status === 'CANCELLED' ? '' : ': bàn và giao trên bảng việc; thành Issue từ đó khi cần'}</>
        : noIssueRoute ? `Đi tuyến ${routeLabels[(decision?.route || 'RESPONSE') as RouteTarget] || decision?.route}: không tạo Issue nên không lập kế hoạch`
        : stopped ? text('Không áp dụng', 'Not applicable') : approved ? (data.sync_status === 'FAILED' ? text('Đồng bộ lỗi, chưa có Issue', 'Sync failed; no Issue yet') : data.sync_status ? text('Đang tạo Issue', 'Creating Issue') : text('Đã duyệt, chưa bấm đồng bộ', 'Approved; not synced yet'))
        : text('Có sau khi duyệt và đồng bộ', 'Available after approval and sync'),
    },
    {
      label: text('Xếp việc', 'Planned'), state: latest ? 'done' : data.work?.off_plan ? 'skip' : data.waiting_in_plan ? 'now' : data.issue ? 'now' : noIssueRoute || stopped ? 'skip' : 'todo',
      text: latest ? `${latest.member_name} · ${slotName(latest.slot)} ${formatDay(latest.plan_date)} · ${latest.planned_hours}h${latest.accepted_at ? ' · đã nghiệm thu' : latest.work_status && latest.work_status !== 'PLANNED' ? ` · ${latest.work_status === 'IN_PROGRESS' ? 'đang làm' : latest.work_status === 'DONE' ? 'báo xong, chờ nghiệm thu' : 'bị chặn'}` : ''}${data.plans.length > 1 ? ` (và ${data.plans.length - 1} lần khác)` : ''}`
        : data.work?.off_plan ? `Đã làm ngoài kế hoạch · ${data.work.latest_by || 'không rõ'}${data.work.actual_minutes != null ? ` · ${hoursText(data.work.actual_minutes / 60)} thực tế` : ''}`
        : data.waiting_in_plan ? (data.waiting_in_plan.plan_closed ? `Chưa được xếp: kế hoạch ${formatDay(data.waiting_in_plan.plan_date)} đã chốt mà việc này còn chờ phân công; sẽ hiện lại ở kế hoạch kế tiếp` : `Đang chờ phân công trong kế hoạch ${formatDay(data.waiting_in_plan.plan_date)}`)
        : data.issue ? text('Chưa nằm trong kế hoạch ngày nào', 'Not in a daily plan yet') : noIssueRoute || stopped ? text('Không áp dụng', 'Not applicable') : text('Cần có Issue trước', 'An Issue is required first'),
    },
    {
      label: text('Chốt kế hoạch', 'Plan closed'), state: latest?.settled ? 'done' : latest ? 'now' : data.work?.off_plan || noIssueRoute || stopped ? 'skip' : 'todo',
      text: latest ? (latest.settled ? `Kế hoạch ${formatDay(latest.plan_date)} đã chốt` : `Kế hoạch ${formatDay(latest.plan_date)} chưa chốt`) : data.work?.off_plan ? 'Không áp dụng cho việc phát sinh ngoài kế hoạch' : noIssueRoute || stopped ? 'Không áp dụng' : 'Sau khi được xếp việc',
    },
    {
      label: text('Nghiệm thu', 'Accepted'), state: data.accepted_at ? 'done' : pendingVerification || data.work || data.unlogged_evidence || (humanWork && latest) ? 'now' : noIssueRoute || stopped ? 'skip' : 'todo',
      text: data.accepted_at
        ? `Đã nghiệm thu, đang đóng Issue · ${data.work?.latest_by || 'CTO'} · ${formatDate(data.accepted_at)}`
        : pendingVerification
        ? `${latest?.member_name || 'Dev'} đã báo xong, chờ CTO nghiệm thu · ${formatDate(pendingVerification.created_at)}`
        : data.verification?.decision === 'REJECTED'
        ? `CTO đã trả lại: ${data.verification.reason || 'chưa đạt yêu cầu'}`
        : data.work?.latest_decision === 'PENDING'
        ? `Đã sửa, chờ CTO nghiệm thu · ${data.work.latest_by || 'không rõ'} · ${formatDate(data.work.latest_at)}${data.work.deployed === true ? ' · đã có bản triển khai' : data.work.deployed === false ? ' · chưa triển khai' : ''}`
        : data.work?.latest_decision === 'RETURNED'
        ? `Trả lại, chờ làm lại · ${data.work.latest_by || 'không rõ'} · ${formatDate(data.work.latest_at)}`
        : data.work?.latest_decision === 'CONFIRMED'
        ? `CTO đã xác nhận, chưa ghi nhận nghiệm thu Issue · ${data.work.latest_by || 'không rõ'} · ${formatDate(data.work.latest_at)}`
        : data.unlogged_evidence
        ? `Tracker đã có ${data.unlogged_evidence.commits} commit và ${data.unlogged_evidence.merge_requests} MR nhưng Intake chưa có work-log để nghiệm thu`
        : humanWork && latest
        ? `${latest.member_name} · ${latest.work_status === 'IN_PROGRESS' ? 'đang làm; khi xong, dev vào “Việc của tôi”, chọn “Xong” và thêm bằng chứng' : latest.work_status === 'BLOCKED' ? 'đang bị chặn; dev cập nhật lý do tại “Việc của tôi”' : latest.work_status === 'DONE' ? 'đã báo xong, đang tạo lượt nghiệm thu' : 'chưa bắt đầu; dev cập nhật trạng thái tại “Việc của tôi” và chọn “Xong” để gửi nghiệm thu'}`
        : noIssueRoute || stopped ? 'Không áp dụng' : 'Chưa có ai ghi việc đã làm',
      actions: canDecideVerification ? (
        <div className="journey-actions">
          <button type="button" className="button button-primary button-small" disabled={decideVerification.isPending} onClick={() => { setVerificationNote(''); setConfirmingVerification(true) }}>Đúng là xong</button>
          <button type="button" className="button button-secondary button-small" disabled={decideVerification.isPending} onClick={() => { setVerificationNote(''); setRejectingVerification(true) }}>Chưa xong</button>
        </div>
      ) : canReviewWork ? (
        <div className="journey-actions">
          <button type="button" className="button button-primary button-small" disabled={review.isPending} onClick={() => review.mutate({ id: pendingWorkId!, decision: 'CONFIRMED' })}>Đạt nghiệm thu</button>
          <button type="button" className="button button-secondary button-small" disabled={review.isPending} onClick={() => { setNote(''); setReturning(pendingWorkId!) }}>Chưa đúng</button>
        </div>
      ) : canReconcileWork ? (
        <div className="journey-actions">
          <small className="journey-action-help">Không tự nghiệm thu từ commit/MR. Ghi nhận kết quả trước để lưu người làm, thời gian và trạng thái triển khai.</small>
          <button type="button" className="button button-secondary button-small" onClick={() => { setReconcileSummary(''); setReconcileMinutes(''); setReconcileDeployed(true); setReconciling(true) }}>Ghi nhận kết quả ngoài kế hoạch</button>
        </div>
      ) : canMarkHumanDone && latest ? (
        <div className="journey-actions">
          <small className="journey-action-help">Luồng chuẩn: dev mở “Việc của tôi” → chọn “Xong” → thêm bằng chứng. Chỉ dùng nút dưới đây nếu dev đã báo xong ngoài hệ thống.</small>
          <button type="button" className="button button-secondary button-small" disabled={markDone.isPending} onClick={() => { if (window.confirm(`Chỉ dùng khi ${latest.member_name} đã báo xong ngoài hệ thống. Xác nhận đưa Issue vào Nghiệm thu?`)) markDone.mutate({ runId: latest.run_id, assignmentId: latest.assignment_id }) }}>{markDone.isPending ? 'Đang chuyển…' : 'CTO đưa vào nghiệm thu'}</button>
        </div>
      ) : undefined,
    },
  ]
  return (
    <>
      {returning && (
        <ConfirmDialog plain title="Chưa đúng ở chỗ nào?" confirmLabel="Trả lại" busyLabel="Đang ghi…" busy={review.isPending} error={review.error ?? undefined} onConfirm={() => { if (note.trim().length >= 3) review.mutate({ id: returning, decision: 'RETURNED', why: note.trim() }) }} onCancel={() => { setReturning(undefined); setNote('') }}>
          <label>Lý do<textarea rows={3} value={note} maxLength={1000} onChange={(event) => setNote(event.target.value)} placeholder="Ví dụ: vẫn lỗi khi tải lại trang" /></label>
          <ul><li>Người hay agent làm lại sẽ đọc lý do này trước.</li><li>Issue và trạng thái yêu cầu không đổi.</li></ul>
        </ConfirmDialog>
      )}
      {reconciling && (
        <ConfirmDialog plain title="Ghi nhận kết quả ngoài kế hoạch" confirmLabel="Ghi nhận" busyLabel="Đang ghi…" busy={reconcile.isPending} error={reconcile.error ?? undefined} onConfirm={() => { if (reconcileSummary.trim().length >= 5) reconcile.mutate() }} onCancel={() => { if (!reconcile.isPending) setReconciling(false) }}>
          <p>Tracker đã có dấu vết code nhưng agent chưa ghi work-log. Mục này chỉ tạo kết quả chờ CTO nghiệm thu, không tạo hoặc sửa Daily Planning.</p>
          <label>Đã làm gì<input value={reconcileSummary} maxLength={1000} autoFocus onChange={(event) => setReconcileSummary(event.target.value)} placeholder="Ví dụ: Đã sửa danh sách nghiệm thu và kiểm tra trên live" /></label>
          <label>Phút thực tế <small>(nếu biết)</small><input type="number" min={0} max={1440} value={reconcileMinutes} onChange={(event) => setReconcileMinutes(event.target.value)} placeholder="vd. 90" /></label>
          <label className="check-row"><input type="checkbox" checked={reconcileDeployed} onChange={(event) => setReconcileDeployed(event.target.checked)} /> Đã có bản triển khai để kiểm</label>
        </ConfirmDialog>
      )}
      {confirmingVerification && pendingVerification && (
        <ConfirmDialog plain title="Xác nhận đúng là xong?" confirmLabel="Đúng là xong" busyLabel="Đang nghiệm thu…" busy={decideVerification.isPending} error={verificationError} onConfirm={() => decideVerification.mutate({ id: pendingVerification.id, decision: 'accept', text: verificationNote.trim() || undefined })} onCancel={() => { if (!decideVerification.isPending) { setConfirmingVerification(false); setVerificationNote(''); setVerificationError(undefined) } }}>
          <p>Intake sẽ ghi kết quả nghiệm thu và đưa lệnh đóng Issue lên tracker.</p>
          <label>Ghi chú kiểm tra <small>(bắt buộc nếu chưa có commit/MR/link bằng chứng)</small><textarea rows={3} value={verificationNote} maxLength={500} onChange={(event) => setVerificationNote(event.target.value)} placeholder="Ví dụ: đã kiểm trực tiếp trên môi trường live" /></label>
        </ConfirmDialog>
      )}
      {rejectingVerification && pendingVerification && (
        <ConfirmDialog plain title="Chưa xong ở chỗ nào?" confirmLabel="Trả lại" busyLabel="Đang ghi…" busy={decideVerification.isPending} error={verificationError} onConfirm={() => { if (verificationNote.trim().length >= 3) decideVerification.mutate({ id: pendingVerification.id, decision: 'reject', text: verificationNote.trim() }) }} onCancel={() => { if (!decideVerification.isPending) { setRejectingVerification(false); setVerificationNote(''); setVerificationError(undefined) } }}>
          <label>Lý do<textarea rows={3} value={verificationNote} maxLength={1000} onChange={(event) => setVerificationNote(event.target.value)} placeholder="Ví dụ: endpoint hủy đơn vẫn trả 500" /></label>
          <ul><li>Việc quay lại kế hoạch để dev tiếp tục làm.</li><li>Issue trên tracker không bị đóng.</li></ul>
        </ConfirmDialog>
      )}
      <section className="panel intake-journey" aria-label={text('Yêu cầu này đang ở bước nào', 'Current lifecycle stage')}>
        {review.error != null && !returning && <ErrorNotice error={review.error} />}
        {verificationError != null && !confirmingVerification && !rejectingVerification && <ErrorNotice error={verificationError} />}
        <ol>
          {steps.map((step) => (
            <li key={step.label} className={`journey-${step.state}`}>
              <span className="journey-dot" aria-hidden="true">{step.state === 'done' ? <Check size={12} /> : null}</span>
              <strong>{step.label}</strong>
              <small>{step.text}</small>
              {step.actions}
            </li>
          ))}
        </ol>
        {canOpenPlan && linkedPlan && <Link className="journey-link" to={planningLink}>{text('Mở Daily Planning', 'Open Daily Planning')} <ArrowRight size={13} /></Link>}
        {data.previous_targets.length > 0 && (
          <p className="notice notice-warn journey-previous">
            <strong>Mục tạo theo quyết định cũ vẫn còn ở hệ thống ngoài.</strong> Duyệt lại cùng tuyến sẽ dùng lại nó (mở lại nếu đã đóng). Chọn tuyến khác thì tự đóng hoặc xóa: {data.previous_targets.map((target, index) => (
              <span key={`${target.system}-${target.external_id}`}>{index > 0 ? ', ' : ''}{target.url ? <a href={target.url} target="_blank" rel="noreferrer">{routeLabels[target.system as RouteTarget] || target.system} {target.external_id.slice(0, 12)}</a> : `${routeLabels[target.system as RouteTarget] || target.system} ${target.external_id.slice(0, 12)}`}</span>
            ))}.
          </p>
        )}
      </section>
    </>
  )
}

const SYNCABLE_ROUTES = ['GITLAB', 'GITHUB']

// The second half of "approve and sync". The approval has already happened when this runs, so a failure here is
// reported as "approved, not synced yet", never as a failed approval.
async function syncApproved(intakeId: string) {
  const status = await api<SyncStatus>(`/intakes/${intakeId}/sync-status`)
  if (!status.snapshot_id) throw new Error('Không tìm thấy bản phê duyệt hợp lệ để đồng bộ.')
  await api(`/approval-snapshots/${status.snapshot_id}/sync`, { method: 'POST' })
}

// One question before anything is created outside: where it goes, with what priority, and what is still unanswered.
function ApproveSyncDialog({ intake, target, priority, openQuestions, busy, onConfirm, onCancel }: {
  intake: Intake; target: string; priority: string; openQuestions: string[]; busy: boolean; onConfirm: () => void; onCancel: () => void
}) {
  return (
    <ConfirmDialog plain title={`Duyệt và tạo mục trên ${target}?`} confirmLabel={`Duyệt và đồng bộ sang ${target}`} busyLabel="Đang duyệt và đồng bộ…" busy={busy} onConfirm={onConfirm} onCancel={onCancel}>
      <p><strong>{intake.public_id}</strong><br />{intake.normalized_title || 'Chưa có tiêu đề'}</p>
      <ul>
        <li>Nơi nhận: <strong>{target}</strong> · Độ ưu tiên: <strong>{priority}</strong></li>
        <li>Một mục mới được tạo trên {target}. Intake không tự xóa được mục đó; chọn nhầm nơi thì phải dọn ở {target}.</li>
        {openQuestions.length > 0 && <li>Còn {openQuestions.length} câu chưa làm rõ; chúng sẽ nằm trong mục đó dưới phần "Cần làm rõ".</li>}
      </ul>
    </ConfirmDialog>
  )
}

const priorityRank = (intake: Intake) => intake.suggested_priority || 'P3'
const linesOf = (text: string) => text.split('\n').map((line) => line.trim()).filter(Boolean)

// A star after the name of a field that must always be filled in.
const Req = () => <span className="req" aria-hidden="true" title="Bắt buộc"> *</span>

// Questions AI raised that nobody has answered or set aside yet.
function unansweredOf(details: IntakeDetails | null | undefined) {
  if (!details) return []
  const settled = new Set(details.clarifications.filter((row) => (row.answer || '').trim() || row.skipped).map((row) => row.question))
  return details.open_questions.filter((question) => !settled.has(question))
}

// The questions AI raised, each with a place for what the team found out. Answers are kept, sent to AI on the next
// analysis and written into the work item.
const readinessLabel: Record<AgentReadiness['band'], string> = { READY: 'Sẵn sàng cho agent', NEEDS_WORK: 'Cần bổ sung', HUMAN: 'Việc cho người' }

function ReadinessChip({ readiness, compact }: { readiness: AgentReadiness | null | undefined; compact?: boolean }) {
  if (!readiness) return null
  const title = [...readiness.reasons, ...readiness.missing.map((row) => `thiếu: ${row}`)].join('\n')
  return <span className={`status readiness readiness-${readiness.band.toLowerCase()}`} title={title}>{compact ? `Agent ${readiness.score}` : `${readinessLabel[readiness.band]} · ${readiness.score}`}</span>
}

// What is missing before an agent can take the request, and the project's own readiness switch (CTO).
function ReadinessBox({ intake, project }: { intake: Intake; project: Project | undefined }) {
  const { user } = useAuth()
  const readiness = intake.agent_readiness
  if (!readiness) return null
  return (
    <details className={`readiness-box readiness-${readiness.band.toLowerCase()}`}>
      <summary><ReadinessChip readiness={readiness} />{readiness.missing.length > 0 ? <small>Thiếu: {readiness.missing.join(' · ')}</small> : <small>Đủ để agent nhận; chép lệnh ở dòng đồng bộ bên dưới.</small>}</summary>
      <div className="readiness-body">
        {readiness.reasons.length > 0 && <p><strong>Đã có:</strong> {readiness.reasons.join(' · ')}</p>}
        {readiness.missing.length > 0 && <ul>{readiness.missing.map((row) => <li key={row}>{row}</li>)}</ul>}
        {user?.role === 'CTO' && project && <p className="field-help">Hồ sơ ngữ cảnh của dự án {project.name} quyết 20 điểm (đủ +20, cần bổ sung +10): xem, duyệt và nhận gợi ý ở <Link to={`/settings/projects/${project.code}`}>Cài đặt › Dự án › {project.name}</Link>.</p>}
        <p className="field-help">Điểm tính từ loại việc, bước tái hiện, kết quả mong đợi, tiêu chí, câu hỏi còn mở, gợi ý cho người sửa và hồ sơ ngữ cảnh của dự án. Từ 70 là sẵn sàng cho agent; dưới 40 là việc nên để người làm.</p>
      </div>
    </details>
  )
}

// The one line that hands a request to Claude Code: the Issue number to recognise it by, the Intake code to copy,
// since the code is unique across projects and the command reads the project from the repo it runs in.
function AgentCommand({ intake, issue }: { intake: Intake; issue: string | null }) {
  const [copied, setCopied] = useState(false)
  const command = `/fix-issue ${intake.public_id}`
  return (
    <span className="agent-command">
      <strong>AI Agent:</strong>
      <code title={command}>/fix-issue {issue ? `#${issue}` : intake.public_id}</code>
      <button type="button" className="text-button" title={`Chép "${command}" rồi dán vào Claude Code đang mở trong repo của dự án`} onClick={() => { void navigator.clipboard.writeText(command).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 2000) }) }}><Copy size={13} aria-hidden="true" /> {copied ? 'Đã chép' : 'Chép'}</button>
    </span>
  )
}

// Where AI stands with this request, right under the buttons that start it: running, just finished (and what it
// changed), or failed with a way to try again. One line; the run history stays folded at the bottom.
function AnalysisStrip({ intake, pipeline, analysing, done, retrying, onRetry, changedQuestions }: {
  intake: Intake; pipeline: PipelineStatus | undefined; analysing: boolean; done: { at: number; changed: string[] } | null; retrying: boolean; onRetry: () => void; changedQuestions: boolean
}) {
  const stages = pipeline?.stages || []
  const current = stages.find((run) => ['QUEUED', 'RUNNING'].includes(run.status)) || stages[stages.length - 1]
  const answered = (intake.details?.clarifications || []).filter((row) => row.answer).length
  const failed = intake.status === 'PROCESSING_FAILED' || (!analysing && current?.status === 'FAILED')
  const names: Record<string, string> = { title: 'tiêu đề', summary: 'tóm tắt', questions: 'câu hỏi còn mở', acceptance: 'tiêu chí', steps: 'các bước', priority: 'loại hoặc ưu tiên' }
  if (analysing) {
    return (
      <div className="analysis-strip is-running" role="status" aria-live="polite">
        <span className="spinner" aria-hidden="true" />
        <span>AI đang đọc lại yêu cầu{answered > 0 ? ` với ${answered} câu trả lời` : ''}{current ? (current.status === 'QUEUED' || current.attempt === 0 ? ' · đang xếp hàng' : ` · ${current.stage} lần ${current.attempt}`) : ''}{current?.started_at ? ` · bắt đầu ${formatDate(current.started_at)}` : ''} · thường dưới một phút</span>
      </div>
    )
  }
  if (failed) {
    return (
      <div className="analysis-strip is-failed" role="alert">
        <TriangleAlert size={15} aria-hidden="true" />
        <span>AI không đọc được yêu cầu{current?.error_code ? ` · ${current.error_code}` : ''}. Thử lại, hoặc tự điền tiêu đề và tóm tắt rồi bấm "Lưu chỉnh sửa".</span>
        <button type="button" className="button button-secondary button-small" disabled={retrying} onClick={onRetry}>{retrying ? 'Đang gửi…' : 'Thử lại'}</button>
      </div>
    )
  }
  if (done) {
    const changed = done.changed.map((key) => names[key] || key)
    return (
      <div className="analysis-strip is-done" role="status">
        <Check size={15} aria-hidden="true" />
        <span>Đã phân tích xong lúc {formatDate(new Date(done.at).toISOString())}{changed.length > 0 ? ` — đã đổi: ${changed.join(', ')}` : ' — không có gì đổi'}{changedQuestions ? '; xem lại các câu hỏi bên trên' : ''}.</span>
      </div>
    )
  }
  return null
}

function ClarifyQuestions({ intake, locked, analysing = false, onSaved, onError }: { intake: Intake; locked: boolean; analysing?: boolean; onSaved: () => Promise<void> | void; onError: (error: unknown) => void }) {
  const details = intake.details
  const stored = details?.clarifications || []
  const questions = Array.from(new Set([...(details?.open_questions || []), ...stored.map((row) => row.question)]))
  const [draft, setDraft] = useState<Record<string, { answer: string; skipped: boolean }>>({})
  useEffect(() => { setDraft({}) }, [intake.id, intake.version])
  const valueOf = (question: string) => draft[question] ?? { answer: stored.find((row) => row.question === question)?.answer || '', skipped: Boolean(stored.find((row) => row.question === question)?.skipped) }
  const save = useMutation({
    mutationFn: (reanalyse: boolean) => api<Intake>(`/intakes/${intake.id}/clarifications`, {
      method: 'PUT',
      body: JSON.stringify({
        expected_version: intake.version, reanalyse,
        answers: questions.map((question) => ({ question, answer: valueOf(question).answer.trim() || null, skipped: valueOf(question).skipped && !valueOf(question).answer.trim() })),
      }),
    }),
    onMutate: () => onError(undefined),
    onSuccess: async () => { await onSaved() },
    onError,
  })
  if (questions.length === 0) return null
  const settled = questions.filter((question) => valueOf(question).answer.trim() || valueOf(question).skipped).length
  const dirty = Object.keys(draft).length > 0
  const answered = questions.some((question) => valueOf(question).answer.trim())
  // Grouped by what is saved, so a row does not jump away while it is being typed in.
  const isStored = (question: string) => stored.some((row) => row.question === question && ((row.answer || '').trim() || row.skipped))
  const waiting = questions.filter((question) => !isStored(question))
  const done = questions.filter(isStored)
  const row = (question: string) => {
    const value = valueOf(question)
    const index = questions.indexOf(question)
    return (
      <div className={value.skipped ? 'clarify-row is-skipped' : value.answer.trim() ? 'clarify-row is-answered' : 'clarify-row'} key={question}>
        <label htmlFor={`clarify-${index}`}>{question}</label>
        <div>
          <input id={`clarify-${index}`} value={value.answer} disabled={locked || value.skipped} maxLength={1000} placeholder={value.skipped ? 'Đã đánh dấu không cần' : 'Câu trả lời của người gửi…'}
            onChange={(event) => setDraft({ ...draft, [question]: { answer: event.target.value, skipped: false } })} />
          <button type="button" className={value.skipped ? 'button button-secondary button-small is-on' : 'button button-secondary button-small'} disabled={locked} aria-pressed={value.skipped}
            onClick={() => setDraft({ ...draft, [question]: { answer: '', skipped: !value.skipped } })}>Không cần</button>
        </div>
      </div>
    )
  }
  const skipRest = () => setDraft({ ...draft, ...Object.fromEntries(waiting.filter((question) => !valueOf(question).answer.trim()).map((question) => [question, { answer: '', skipped: true }])) })
  return (
    <section className="clarify" aria-label="Cần làm rõ trước khi làm">
      <header><strong>{waiting.length > 0 ? `Cần làm rõ trước khi làm (${waiting.length})` : 'Đã làm rõ hết'}</strong><span>{settled}/{questions.length} đã xử lý</span></header>
      {waiting.length > 0 && <p className="field-help">Hỏi người gửi rồi ghi câu trả lời vào đây. Câu nào không quan trọng thì bấm "Không cần". Các câu này không chặn phê duyệt.</p>}
      {waiting.map(row)}
      {done.length > 0 && (
        <details className="clarify-done" open={waiting.length === 0}>
          <summary>Đã xử lý ({done.length})</summary>
          {done.map(row)}
        </details>
      )}
      {!locked && (
        <div className="clarify-actions">
          <button type="button" className="button button-secondary button-small" disabled={!dirty || save.isPending || analysing} onClick={() => save.mutate(false)}>{save.isPending && save.variables === false ? 'Đang lưu…' : 'Lưu câu trả lời'}</button>
          <button type="button" className="button button-primary button-small" disabled={!(dirty || answered) || save.isPending || analysing} aria-busy={analysing || undefined} title={analysing ? 'AI đang phân tích; nút mở lại khi xong' : "AI đọc lại nguyên văn gốc cùng các câu trả lời, viết lại tóm tắt và tiêu chí. Phần bạn đã sửa tay ở tiêu đề và tóm tắt sẽ bị thay."} onClick={() => save.mutate(true)}><Sparkles size={14} aria-hidden="true" /> {save.isPending && save.variables === true ? 'Đang gửi…' : 'Lưu và phân tích lại'}</button>
          {waiting.some((question) => !valueOf(question).answer.trim() && !valueOf(question).skipped) && <button type="button" className="text-button details-add" onClick={skipRest}>Không cần các câu còn lại</button>}
        </div>
      )}
    </section>
  )
}

// What a developer needs beyond the summary. `only` picks the parts to show: the detail page edits some of them itself.
// `onDuplicateIssue` puts a "Trùng với #n" button next to each Issue the AI thinks this request repeats (FR-APR-12).
function IntakeDetailsView({ details, only, onDuplicateIssue }: {
  details: IntakeDetails | null | undefined; only?: (keyof IntakeDetails)[]; onDuplicateIssue?: (issue: IntakeDetails['related'][number]) => void
}) {
  if (!details) return null
  const show = (key: keyof IntakeDetails) => !only || only.includes(key)
  const blocks = [
    show('where') && details.where ? <p key="where"><strong>Ở đâu:</strong> {details.where}</p> : null,
    show('steps') && details.steps.length > 0 ? <div key="steps"><strong>Các bước</strong><ol>{details.steps.map((step) => <li key={step}>{step}</li>)}</ol></div> : null,
    show('expected') && details.expected ? <p key="expected"><strong>Kết quả mong đợi:</strong> {details.expected}</p> : null,
    show('subtasks') && details.subtasks.length > 0 ? <div key="subtasks"><strong>Việc con ({details.subtasks.length})</strong><ul>{details.subtasks.map((item) => <li key={item}>{item}</li>)}</ul></div> : null,
    show('acceptance') && details.acceptance.length > 0 ? <div key="acceptance"><strong>Tiêu chí nghiệm thu</strong><ul>{details.acceptance.map((item) => <li key={item}>{item}</li>)}</ul></div> : null,
    show('open_questions') && details.clarifications.some((row) => (row.answer || '').trim()) ? <div key="answers"><strong>Đã làm rõ</strong><ul>{details.clarifications.filter((row) => (row.answer || '').trim()).map((row) => <li key={row.question}><em>{row.question}</em> {row.answer}</li>)}</ul></div> : null,
    show('open_questions') && unansweredOf(details).length > 0 ? <div key="questions" className="details-questions"><strong>Cần làm rõ trước khi làm ({unansweredOf(details).length})</strong><ul>{unansweredOf(details).map((item) => <li key={item}>{item}</li>)}</ul></div> : null,
    show('split_suggested') && details.split_suggested && details.subtasks.length >= 2 ? (
      <p key="split" className="details-split"><TriangleAlert size={14} aria-hidden="true" /> Các việc con khác loại hoặc khác độ gấp. Nên tách thành {details.subtasks.length} yêu cầu riêng ở trang chi tiết trước khi duyệt.</p>
    ) : null,
    show('related') && details.related.length > 0 ? (
      <p key="related" className="details-related"><TriangleAlert size={14} aria-hidden="true" /> <strong>Có thể trùng với việc đang có:</strong> {details.related.map((issue, index) => (
        <span key={issue.id} className="details-related-issue">{index > 0 ? ', ' : ''}{issue.url ? <a href={issue.url} target="_blank" rel="noreferrer">#{issue.id} {issue.title}</a> : `#${issue.id} ${issue.title || ''}`}
          {onDuplicateIssue && <button type="button" className="button button-secondary button-small" title={`Đóng yêu cầu này vì Issue #${issue.id} đã nói cùng việc`} onClick={() => onDuplicateIssue(issue)}>Trùng với #{issue.id}</button>}
        </span>
      ))}</p>
    ) : null,
  ].filter(Boolean)
  return blocks.length > 0 ? <div className="intake-details">{blocks}</div> : null
}

// The queue is only for triage. Every decision happens on the detail page, after the approver has seen the AI analysis.
function ApprovalItem({ intake, project, showProject, note }: {
  intake: Intake; project?: Project; showProject: boolean; note?: string
}) {
  const openQuestions = unansweredOf(intake.details).length
  return (
    <article className={`approval-item${priorityRank(intake) === 'P0' ? ' is-critical' : ''}`}>
      <Link className="approval-head" to={`/intakes/${intake.id}`} aria-label={`Mở chi tiết ${intake.public_id} để xem AI phân tích và duyệt`}>
        <PriorityBadge priority={intake.suggested_priority} />
        <span className="approval-title">
          <strong>{intake.normalized_title || 'Chưa có tiêu đề'}</strong>
          <small>{intake.public_id}{showProject && project ? ` · ${project.name}` : ''} · {channelLabels[intake.channel]} · {formatDate(intake.updated_at)}{note ? <> · <span className={intake.approval_overdue ? 'approval-overdue' : undefined}>{note}</span></> : null}</small>
          <small className="approval-analysis">AI đã phân tích{openQuestions > 0 ? ` · ${openQuestions} câu cần làm rõ` : ' · không còn câu hỏi mở'}{intake.agent_readiness ? ` · Agent ${intake.agent_readiness.score}` : ''}</small>
        </span>
        <span className="approval-open">Xem AI phân tích và duyệt <ChevronRight size={16} aria-hidden="true" /></span>
      </Link>
    </article>
  )
}

function ApprovalQueuePage() {
  const { user } = useAuth()
  const isCto = user?.role === 'CTO'
  const query = useQuery({ queryKey: ['approvals'], queryFn: () => api<IntakePage>('/approvals?limit=100') })
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const [projectFilter, setProjectFilter] = useState(() => new URLSearchParams(window.location.search).get('project') || 'ALL')
  // The CTO opens their own part by default: P0/P1, projects without a Project Owner, and what waited over a day (FR-APR-14).
  const [ownerFilter, setOwnerFilter] = useState<'MINE' | 'ALL'>(() => (new URLSearchParams(window.location.search).get('owner') === 'ALL' ? 'ALL' : 'MINE'))
  const projectList = projects.data || []
  const all = [...(query.data?.items || [])].sort((a, b) => priorityRank(a).localeCompare(priorityRank(b)) || a.updated_at.localeCompare(b.updated_at))
  const inProject = all.filter((item) => projectFilter === 'ALL' || item.project_id === projectFilter)
  const mine = isCto ? inProject.filter((item) => item.approval_owner === 'CTO') : inProject
  const items = ownerFilter === 'MINE' ? mine : inProject
  const overdue = items.filter((item) => item.approval_overdue).length
  const whose = (item: Intake) => [
    ...(item.approval_overdue ? ['quá hạn'] : []),
    ...(isCto && item.approval_owner === 'PO' ? ['Project Owner quyết'] : !isCto && item.approval_owner === 'CTO' ? ['CTO quyết'] : []),
  ].join(' · ')
  const urgent = items.filter((item) => ['P0', 'P1'].includes(priorityRank(item))).length

  return (
    <>
      <PageHeader title="Chờ phê duyệt" helper={[
        'Danh sách này chỉ dùng để chọn yêu cầu cần xem.',
        'Mở trang chi tiết để đọc nội dung nguồn, kết quả AI, câu hỏi cần làm rõ và đề xuất tuyến xử lý.',
        'Chỉ sau khi xem chi tiết mới có thể duyệt, yêu cầu làm rõ, hoãn hoặc từ chối.',
        'Đồng bộ sang hệ thống giao việc vẫn được hỏi lại trước khi tạo dữ liệu.',
      ]} />
      <FlowGuide here={['approve']} note="Chọn một yêu cầu, mở chi tiết để AI phân tích và làm rõ trước khi quyết định. Duyệt xong chưa ai được giao việc: việc chỉ vào kế hoạch sau khi có Issue và được xếp ở Daily Planning." />
      <div className="approval-bar-top">
        <span><strong>{items.length}</strong> yêu cầu đang chờ{urgent > 0 ? ` · ${urgent} yêu cầu P0/P1` : ''}{overdue > 0 ? ` · ${overdue} quá hạn` : ''}</span>
        {isCto && inProject.length !== mine.length && (
          <div className="today-tabs" role="tablist" aria-label="Của ai">
            <button type="button" role="tab" aria-selected={ownerFilter === 'MINE'} className={ownerFilter === 'MINE' ? 'active' : undefined} onClick={() => setOwnerFilter('MINE')}>Của tôi ({mine.length})</button>
            <button type="button" role="tab" aria-selected={ownerFilter === 'ALL'} className={ownerFilter === 'ALL' ? 'active' : undefined} onClick={() => setOwnerFilter('ALL')}>Tất cả ({inProject.length})</button>
          </div>
        )}
        {projectList.length > 1 && <select aria-label="Lọc dự án" value={projectFilter} onChange={(event) => setProjectFilter(event.target.value)}><option value="ALL">Mọi dự án</option>{projectList.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select>}
      </div>
      <FeedbackQueue projectFilter={projectFilter} />
      {query.isLoading ? <LoadingBlock /> : query.error ? <ErrorNotice error={query.error} onRetry={() => { void query.refetch() }} /> : items.length === 0 ? (
        <section className="panel"><EmptyState icon={<CircleCheck size={20} />} title={ownerFilter === 'MINE' && inProject.length > 0 ? 'Không có yêu cầu nào cần anh quyết' : 'Không còn quyết định tồn đọng'} text={ownerFilter === 'MINE' && inProject.length > 0 ? `${inProject.length} yêu cầu đang chờ Project Owner; sau 24 giờ chưa quyết sẽ về đây.` : 'Khi AI chuẩn hóa xong một yêu cầu mới, nó sẽ xuất hiện ở đây.'} /></section>
      ) : (
        <section className="approval-list" aria-label="Yêu cầu chờ phê duyệt">
          {items.map((item) => (
            <ApprovalItem key={`${item.id}-${item.version}`} intake={item} project={projectList.find((project) => project.id === item.project_id)} showProject={projectList.length > 1} note={whose(item)} />
          ))}
        </section>
      )}
      <DecisionHistory projectFilter={projectFilter} showProject={projectList.length > 1} />
    </>
  )
}

// What was decided lately, under the queue: a decision leaves the queue, not the record (FR-APR-15).
const decisionWords: Record<ApprovalDecision['action'], string> = { APPROVED: 'Đã duyệt', REJECTED: 'Từ chối', DEFERRED: 'Hoãn', NEEDS_INFORMATION: 'Cần làm rõ', REOPENED: 'Rút lại' }
function DecisionHistory({ projectFilter, showProject }: { projectFilter: string; showProject: boolean }) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [older, setOlder] = useState<ApprovalDecision[]>([])
  const [exhausted, setExhausted] = useState(false)
  const scoped = (params: URLSearchParams) => { if (projectFilter !== 'ALL') params.set('project_id', projectFilter); return params.toString() }
  const recent = useQuery({
    queryKey: ['approval-decisions', projectFilter],
    queryFn: () => api<ApprovalDecisionPage>(`/approvals/decisions?${scoped(new URLSearchParams({ days: '7', limit: '50' }))}`),
    enabled: open,
  })
  useEffect(() => { setOlder([]); setExhausted(false) }, [projectFilter])
  const more = useMutation({
    mutationFn: (before: string) => api<ApprovalDecisionPage>(`/approvals/decisions?${scoped(new URLSearchParams({ before, limit: '50' }))}`),
    onSuccess: (page) => { setOlder((current) => [...current, ...page.items]); if (page.items.length < 50) setExhausted(true) },
  })
  const rows = [...(recent.data?.items || []), ...older]
  const needle = search.trim().toLowerCase()
  const shown = needle ? rows.filter((row) => [row.public_id, row.title, row.reason || '', row.actor_name || '', row.project_name].some((value) => value.toLowerCase().includes(needle))) : rows
  // Older pages start where the loaded rows end; with nothing loaded, at the start of the 7-day window.
  const cursor = rows.length > 0 ? rows[rows.length - 1].at : recent.data?.since ?? null
  return (
    <details className="panel decision-history" open={open} onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}>
      <summary><History size={16} aria-hidden="true" /><strong>Đã quyết định gần đây</strong><small>7 ngày, mới nhất trước; mở ra để tìm lại một quyết định đã rời hàng chờ</small></summary>
      <div className="decision-history-bar">
        <input type="search" aria-label="Tìm quyết định" placeholder="Tìm theo mã, tiêu đề, lý do, người quyết" value={search} onChange={(event) => setSearch(event.target.value)} />
        <small className="muted">{rows.length} quyết định đã tải</small>
      </div>
      {recent.isLoading && <LoadingBlock />}
      {recent.error != null && <ErrorNotice error={recent.error} onRetry={() => { void recent.refetch() }} />}
      {more.error != null && <ErrorNotice error={more.error} />}
      {recent.data && shown.length === 0 && <p className="muted">{needle ? 'Không có quyết định nào khớp.' : 'Chưa có quyết định nào trong 7 ngày; bấm "Xem cũ hơn" để lùi về trước.'}</p>}
      <ul className="decision-rows">
        {shown.map((row) => (
          <li key={row.id}>
            <span className={`decision-kind kind-${row.action.toLowerCase()}`}>{decisionWords[row.action]}</span>
            <div>
              <Link className="ref-link" to={`/intakes/${row.intake_id}`}>{row.public_id}</Link> <strong>{row.title}</strong>
              <small>{dotted([
                formatDate(row.at),
                row.actor_name,
                showProject ? row.project_name : null,
                row.action === 'APPROVED' ? [row.approved_priority, row.approved_route ? routeLabels[row.approved_route as RouteTarget] || row.approved_route : null].filter(Boolean).join(' · ') : null,
                row.source === 'PLANNING' ? 'duyệt từ Daily Planning' : null,
                row.reason ? `lý do: ${row.reason}` : null,
                `hiện: ${statusLabels[row.status] || row.status}`,
              ])}</small>
            </div>
          </li>
        ))}
      </ul>
      {recent.data && !exhausted && cursor && <button type="button" className="button button-secondary button-small" disabled={more.isPending} onClick={() => more.mutate(cursor)}>{more.isPending ? 'Đang tải…' : 'Xem cũ hơn'}</button>}
    </details>
  )
}

const hoursText = (value: number) => `${Math.round(value * 100) / 100}h`
const busyHours = (row: DailyCapacity) => row.meeting_hours + row.review_hours + row.support_hours + row.fixed_hours

const addWorkErrors: Record<string, string> = {
  OVER_CAPACITY: 'vượt số giờ còn lại trong ngày của người này',
  SLOT_OVER_CAPACITY: 'buổi đó của người này đã quá 4 giờ',
  GITLAB_ASSIGNEE_REQUIRED: 'người này chưa có người dùng GitLab/GitHub ở dự án (gán ở Cài đặt > Nhân sự)',
  WARNING_UNACKNOWLEDGED: 'còn cảnh báo thiếu milestone hoặc hạn chót chưa đánh dấu đã xem',
  PLANNING_SYNC_IN_PROGRESS: 'đang ghi kế hoạch lên GitLab; đợi xong rồi mở lại',
  PLANNING_RUN_SUPERSEDED: 'kế hoạch này đã được thay bằng bản mới hơn; tải lại trang',
  MEMBER_NOT_ACTIVE: 'nhân sự không còn hoạt động',
  GITLAB_ISSUE_CLOSED: 'Issue đã đóng',
  GITLAB_ISSUE_NOT_FOUND: 'chưa thấy Issue trong danh sách',
  ISSUE_ALREADY_PLANNED: 'Issue này đã nằm trong kế hoạch ngày',
}

const capacityPresets = [
  { key: 'normal', label: 'Ngày thường', reason: '' },
  { key: 'half', label: 'Nghỉ nửa ngày', reason: 'Nghỉ nửa ngày' },
  { key: 'off', label: 'Nghỉ cả ngày', reason: 'Nghỉ cả ngày' },
  { key: 'extra', label: 'Làm thêm', reason: 'Làm thêm giờ' },
] as const
const capacityErrors: Record<string, string> = {
  OVERRIDE_REASON_REQUIRED: 'Cần ghi lý do khi đổi số giờ làm.',
  CAPACITY_NEGATIVE: 'Giờ bận nhiều hơn số giờ làm trong ngày.',
  CAPACITY_VERSION_CONFLICT: 'Giờ của người này vừa được sửa ở nơi khác. Đóng khung này rồi mở lại.',
}

function CapacityEditPanel({ workDate, scope, memberId, onDone }: { workDate: string; scope: string; memberId: string; onDone: () => void }) {
  const queryClient = useQueryClient()
  const capacities = useQuery({ queryKey: ['planning-capacities', workDate, scope], queryFn: () => api<DailyCapacity[]>(`/planning/capacities/${workDate}${scope === 'ALL' ? '' : `?project_id=${scope}`}`) })
  const row = capacities.data?.find((entry) => entry.member_id === memberId)
  const [dayHours, setDayHours] = useState<string>()
  const [busy, setBusy] = useState<string>()
  const [reason, setReason] = useState<string>()
  const [error, setError] = useState<unknown>()
  const hoursInput = useRef<HTMLInputElement>(null)
  const mutation = useMutation({
    mutationFn: (body: object) => api<DailyCapacity>(`/planning/capacities/${workDate}/${memberId}`, { method: 'PUT', body: JSON.stringify(body) }),
    onMutate: () => setError(undefined),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['planning-capacities'] }); onDone() },
    onError: setError,
  })
  if (!row) return capacities.isLoading ? <LoadingBlock /> : <p className="field-help">Không tìm thấy nhân sự này trong phạm vi đang chọn.</p>

  const base = row.base_hours
  const half = base > 0 ? base / 2 : 4
  const hoursValue = dayHours ?? (row.override_hours == null ? '' : String(row.override_hours))
  const busyValue = busy ?? String(busyHours(row))
  const reasonValue = reason ?? (row.override_reason || '')
  const changed = hoursValue.trim() !== ''
  const effective = changed ? Number(hoursValue) : base
  const canWork = effective - Number(busyValue || 0)
  const preset = !changed ? 'normal' : effective === 0 ? 'off' : effective === half ? 'half' : effective > base ? 'extra' : ''
  const autoReasons: string[] = capacityPresets.map((entry) => entry.reason)
  const choose = (key: typeof capacityPresets[number]['key']) => {
    setDayHours(key === 'normal' ? '' : key === 'off' ? '0' : key === 'half' ? String(half) : String(base + 2))
    // A day off has no busy hours; leaving it brings back the ones recorded before.
    if (key === 'off') setBusy('0')
    else if (preset === 'off') setBusy(undefined)
    // The suggested reason replaces an empty or previously suggested one, never something typed by hand.
    if (reasonValue.trim() === '' || autoReasons.includes(reasonValue)) setReason(capacityPresets.find((entry) => entry.key === key)?.reason || '')
    if (key === 'extra') hoursInput.current?.focus()
  }
  const invalid = Number.isNaN(effective) || canWork < 0 || (changed && reasonValue.trim() === '')
  const code = error instanceof ApiError ? error.code : undefined
  return (
    <form className="add-work capacity-edit" onSubmit={(e) => { e.preventDefault(); mutation.mutate({ expected_version: row.version, override_hours: changed ? effective : null, meeting_hours: 0, review_hours: 0, support_hours: 0, fixed_hours: Number(busyValue || 0), reason: reasonValue.trim() || null }) }}>
      <p className="capacity-edit-who"><strong>{row.display_name}</strong><small>{formatDay(workDate)} · bình thường làm {hoursText(base)}</small></p>
      {error != null && (code && capacityErrors[code] ? <p className="notice notice-error">{capacityErrors[code]}</p> : <ErrorNotice error={error} />)}
      <div className="capacity-presets" role="group" aria-label="Chọn nhanh">
        {capacityPresets.map((entry) => <button key={entry.key} type="button" className={preset === entry.key ? 'active' : undefined} aria-pressed={preset === entry.key} onClick={() => choose(entry.key)}>{entry.label}</button>)}
      </div>
      <div className="add-work-row">
        <label>Số giờ làm hôm nay<input ref={hoursInput} type="number" min="0" max="24" step="0.5" value={hoursValue} onChange={(e) => setDayHours(e.target.value)} placeholder={`${base}`} /></label>
        <label>Giờ bận việc khác<input type="number" min="0" max="24" step="0.5" value={busyValue} onChange={(e) => setBusy(e.target.value)} /></label>
      </div>
      <small className="field-help">Giờ bận là họp, review, hỗ trợ… Không xếp việc vào các giờ này.</small>
      <label>Lý do{changed ? '' : ' (không bắt buộc)'}<input value={reasonValue} onChange={(e) => setReason(e.target.value)} placeholder={changed ? 'Bắt buộc khi đổi số giờ làm' : 'Ví dụ: họp khách hàng buổi chiều'} maxLength={2000} /></label>
      <p className={`capacity-result${canWork < 0 ? ' is-over' : ''}`}>{canWork < 0 ? 'Giờ bận nhiều hơn số giờ làm.' : <>Có thể xếp việc: <strong>{hoursText(canWork)}</strong></>}</p>
      <button className="button button-primary" type="submit" disabled={invalid || mutation.isPending}>{mutation.isPending ? 'Đang lưu…' : 'Lưu giờ làm'}</button>
    </form>
  )
}

function IssueOption({ item, selected, disabled, onPick, extra }: { item: PlanningWorkItem; selected: boolean; disabled?: boolean; onPick: () => void; extra?: string }) {
  const who = item.assignee_names.length > 0 ? item.assignee_names.join(', ') : item.unknown_assignees > 0 ? 'gán cho người ngoài danh sách nhân sự' : 'chưa gán ai'
  const facts = [extra, who, item.milestone, item.due_date ? `hạn ${formatDay(item.due_date)}` : null, item.already_planned ? 'đã có trong kế hoạch hôm nay' : null].filter(Boolean)
  return (
    <div className={`issue-option${selected ? ' active' : ''}${item.already_planned ? ' dim' : ''}`}>
      <button type="button" role="option" aria-selected={selected} disabled={disabled} onClick={onPick}>
        <span><b>#{item.issue_external_id}</b>{item.priority ? ` · ${item.priority}` : ''} · {item.title}</span>
        <small>{facts.join(' · ')}</small>
      </button>
      {item.url && <a href={item.url} target="_blank" rel="noreferrer" title="Mở Issue ở tab mới" aria-label={`Mở Issue #${item.issue_external_id} ở tab mới`}><ArrowUpRight size={15} /></a>}
    </div>
  )
}

// Members of the project without a tracker user, fixed where the plan needs them (FR-PLAN-32): the user the Issue is
// already assigned to in one click, a match by name pre-chosen, or any user from the list.
function TrackerUserFix({ projectId, trackerName, team, hasTrackerUser, issue }: { projectId: string; trackerName: string; team: WorkforceMember[]; hasTrackerUser: (member: WorkforceMember) => boolean; issue?: string | null }) {
  const queryClient = useQueryClient()
  const missing = team.filter((member) => !hasTrackerUser(member))
  // The API keeps no tracker token: the worker reads the user list through a probe, and this box polls for it.
  const [probeId, setProbeId] = useState<string>()
  const [error, setError] = useState<unknown>()
  const start = useMutation({
    mutationFn: () => api<{ probe_id: string | null; status: string; error_code: string | null }>(`/planning/projects/${projectId}/tracker-users/lookup`, { method: 'POST' }),
    onMutate: () => setError(undefined),
    onSuccess: (started) => { if (started.probe_id) setProbeId(started.probe_id); else setError(new Error(probeErrors[started.error_code || ''] || 'Không đọc được danh sách người dùng của tracker.')) },
    onError: setError,
  })
  const startLookup = start.mutate
  useEffect(() => { if (missing.length > 0 && !probeId) startLookup() }, [missing.length, probeId, startLookup])
  const users = useQuery({
    queryKey: ['tracker-users', projectId, probeId || '', issue || ''],
    queryFn: () => api<TrackerUsers>(`/planning/projects/${projectId}/tracker-users?probe=${encodeURIComponent(probeId!)}${issue ? `&issue=${encodeURIComponent(issue)}` : ''}`),
    enabled: Boolean(probeId), retry: false,
    refetchInterval: (query) => (query.state.data?.status === 'PENDING' ? 1000 : false),
  })
  const [choice, setChoice] = useState<Record<string, string>>({})
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['planning-members'] }); void queryClient.invalidateQueries({ queryKey: ['tracker-users', projectId] }) }
  const save = useMutation({
    mutationFn: ({ memberId, userId }: { memberId: string; userId: string }) => api(`/planning/projects/${projectId}/members/${memberId}/tracker-user`, { method: 'PUT', body: JSON.stringify({ gitlab_user_external_id: userId }) }),
    onMutate: () => setError(undefined), onSuccess: refresh, onError: setError,
  })
  const auto = useMutation({
    mutationFn: () => api<{ filled: number; names: string[]; unmapped: number }>(`/planning/projects/${projectId}/tracker-users/auto-map?probe=${encodeURIComponent(probeId!)}`, { method: 'POST' }),
    onMutate: () => setError(undefined), onSuccess: refresh, onError: setError,
  })
  if (missing.length === 0) return null
  const pending = start.isPending || users.isLoading || users.data?.status === 'PENDING'
  const failed = users.data?.status === 'FAILED' ? (probeErrors[users.data.error_code || ''] || `Không đọc được danh sách người dùng của tracker (${users.data.error_code || 'lỗi'}).`) : null
  const data = users.data && users.data.status === 'DONE' ? users.data : undefined
  const free = (data?.users || []).filter((user) => !user.mapped_member_id)
  // The Issue's assignee on the tracker, when it is not mapped yet and a team member carries the same name.
  const assigneeHint = (data?.issue_assignees || []).map((id) => data!.users.find((user) => user.id === id)).find((user) => user && !user.mapped_member_id && user.suggested_member_id && missing.some((member) => member.id === user.suggested_member_id))
  return (
    <div className="tracker-fix" role="group" aria-label={`Gắn người dùng ${trackerName}`}>
      <p><strong>{missing.length} người chưa có người dùng {trackerName}</strong> ở dự án này, nên chưa gán việc được.{pending ? ` Đang đọc danh sách từ ${trackerName}…` : ''}</p>
      {error != null && <ErrorNotice error={error} onRetry={() => { setProbeId(undefined) }} />}
      {users.error != null && <ErrorNotice error={users.error} onRetry={() => { void users.refetch() }} />}
      {failed && <p className="tracker-fix-hint"><span>{failed}</span> <button type="button" className="text-button" onClick={() => setProbeId(undefined)}>Thử lại</button></p>}
      {assigneeHint && (
        <p className="tracker-fix-hint">Issue đang gán cho <strong>{assigneeHint.name}</strong> trên {trackerName}. <button type="button" className="button button-primary button-small" disabled={save.isPending} onClick={() => save.mutate({ memberId: assigneeHint.suggested_member_id!, userId: assigneeHint.id })}>Gắn với {missing.find((member) => member.id === assigneeHint.suggested_member_id)?.display_name}</button></p>
      )}
      {data && (
        <ul>
          {missing.map((member) => {
            const suggested = data.unmapped.find((row) => row.member_id === member.id)?.suggested_user_id || ''
            const picked = choice[member.id] ?? suggested
            return (
              <li key={member.id}>
                <span>{member.display_name}</span>
                <select aria-label={`Người dùng ${trackerName} của ${member.display_name}`} value={picked} onChange={(event) => setChoice({ ...choice, [member.id]: event.target.value })}>
                  <option value="">Chọn người dùng {trackerName}…</option>
                  {free.map((user) => <option key={user.id} value={user.id}>{user.name}{user.username ? ` (${user.username})` : ''}{user.id === suggested ? ' · khớp tên' : ''}</option>)}
                </select>
                <button type="button" className="button button-secondary button-small" disabled={!picked || save.isPending} onClick={() => save.mutate({ memberId: member.id, userId: picked })}>Gắn</button>
              </li>
            )
          })}
        </ul>
      )}
      {data && data.unmapped.some((row) => row.suggested_user_id) && <button type="button" className="text-button" disabled={auto.isPending} onClick={() => auto.mutate()}>{auto.isPending ? 'Đang khớp…' : 'Gắn mọi người khớp tên'}</button>}
    </div>
  )
}

function AddWorkPanel({ runId, canApprove }: { runId: string; canApprove: boolean }) {
  const queryClient = useQueryClient()
  const runQuery = useQuery({ queryKey: ['planning-run', runId], queryFn: () => api<PlanningRun>(`/planning/runs/${runId}`) })
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const members = useQuery({ queryKey: ['planning-members'], queryFn: () => api<WorkforceMember[]>('/planning/members') })
  const run = runQuery.data
  const scope = (projects.data || []).filter((project) => run?.project_ids.includes(project.id))
  const [mode, setMode] = useState<'EXISTING' | 'NEW'>('EXISTING')
  const [search, setSearch] = useState('')
  const [picked, setPicked] = useState<PlanningWorkItem>()
  const [projectId, setProjectId] = useState('')
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [itemType, setItemType] = useState<'BUG' | 'TASK' | 'FEATURE'>('BUG')
  const [priority, setPriority] = useState('P1')
  const [reason, setReason] = useState('')
  const [memberId, setMemberId] = useState('')
  const [slot, setSlot] = useState<PlanningSlot>('MORNING')
  const [hours, setHours] = useState('2')
  const [message, setMessage] = useState<{ tone: 'success' | 'warn'; text: string }>()
  const [error, setError] = useState<unknown>()
  const [waitingFor, setWaitingFor] = useState<string>()

  const results = useQuery({
    queryKey: ['planning-work-items', runId, search.trim()],
    queryFn: () => api<PlanningWorkItem[]>(`/planning/runs/${runId}/work-items${search.trim() ? `?search=${encodeURIComponent(search.trim())}` : ''}`),
    enabled: mode === 'EXISTING',
  })
  const targetProject = mode === 'EXISTING' ? picked?.project_id || '' : projectId || scope[0]?.id || ''
  const project = scope.find((entry) => entry.id === targetProject)
  const trackerName = project?.delivery_system === 'GITHUB' ? 'GitHub' : 'GitLab'
  const team = (members.data || []).filter((member) => member.project_mappings.some((mapping) => mapping.active && mapping.project_id === targetProject))
  const hasTrackerUser = (member: WorkforceMember) => Boolean(member.project_mappings.find((mapping) => mapping.active && mapping.project_id === targetProject)?.gitlab_user_external_id)
  const needsIssue = mode === 'NEW' || Boolean(picked?.needs_issue)

  // After asking for a new Issue, watch the run until the work shows up in the plan.
  useEffect(() => {
    if (!waitingFor) return
    let tries = 0
    const timer = window.setInterval(() => {
      tries += 1
      void queryClient.invalidateQueries({ queryKey: ['planning-run', runId] })
      if (tries >= 20) { window.clearInterval(timer); setWaitingFor(undefined); setMessage({ tone: 'warn', text: 'Issue chưa được tạo xong sau 40 giây. Việc vẫn nằm ở "Việc chờ phân công"; kiểm tra đồng bộ của Intake nếu nó không đổi trạng thái.' }) }
    }, 2000)
    return () => window.clearInterval(timer)
  }, [waitingFor, runId, queryClient])
  useEffect(() => {
    if (!waitingFor || !run) return
    const candidate = run.candidates.find((entry) => entry.id === waitingFor)
    if (!candidate || candidate.status === 'PENDING_TRIAGE') return
    setWaitingFor(undefined)
    setMessage(candidate.status === 'ASSIGNED'
      ? { tone: 'success', text: `Đã tạo Issue #${candidate.gitlab_issue_external_id} và đưa việc vào kế hoạch.` }
      : { tone: 'warn', text: `Đã tạo Issue #${candidate.gitlab_issue_external_id}. Việc đang ở "Việc chờ phân công" vì chưa phân công tự động được; hãy phân công ở thẻ của nó.` })
  }, [run, waitingFor])

  const add = useMutation({
    mutationFn: async () => {
      // The cached run goes stale whenever another Issue finishes or someone else edits the plan; send the current version.
      const fresh = await api<PlanningRun>(`/planning/runs/${runId}`)
      return api<PlanningAddWorkResult>(`/planning/runs/${runId}/work`, {
      method: 'POST',
      body: JSON.stringify({
        expected_run_version: fresh.version, project_id: targetProject,
        source: mode === 'NEW' ? 'NEW' : picked!.kind,
        issue_external_id: mode === 'EXISTING' ? picked!.issue_external_id : null,
        intake_id: mode === 'EXISTING' ? picked!.intake_id : null,
        title: mode === 'NEW' ? title.trim() : null, content: mode === 'NEW' ? content.trim() || null : null,
        item_type: itemType, priority, reason: needsIssue ? reason.trim() : null,
        member_id: memberId || null, slot: memberId ? slot : null, planned_hours: memberId ? Number(hours) : null,
      }),
      })
    },
    onMutate: () => { setError(undefined); setMessage(undefined) },
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['planning-run', runId] })
      void queryClient.invalidateQueries({ queryKey: ['planning-work-items', runId] })
      void queryClient.invalidateQueries({ queryKey: ['planning-capacities'] })
      const slotLabel = slot === 'MORNING' ? 'Buổi sáng' : 'Buổi chiều'
      if (result.state === 'PLANNED') setMessage({ tone: 'success', text: `Đã đưa vào cột ${slotLabel}.${result.added_as_secondary ? ' Người này đã có một việc chính trong ngày nên việc này được ghi là việc phụ.' : ''}` })
      else if (result.state === 'CREATING_ISSUE') { setWaitingFor(result.candidate.id); setMessage({ tone: 'success', text: `Đã ghi nhận. Đang tạo Issue trên ${trackerName}; việc sẽ tự vào kế hoạch khi Issue có.` }) }
      else if ((result.assignment_error === 'OVER_CAPACITY' || result.assignment_error === 'SLOT_OVER_CAPACITY') && memberId && result.candidate.gitlab_issue_external_id) setOverHours({ candidateId: result.candidate.id, code: result.assignment_error, issue: result.candidate.gitlab_issue_external_id })
      else setMessage({ tone: 'warn', text: result.assignment_error ? `Đã thêm vào "Việc chờ phân công", nhưng chưa phân công được: ${addWorkErrors[result.assignment_error] || result.assignment_error}.` : 'Đã thêm vào "Việc chờ phân công". Chọn người làm ở thẻ của nó khi sẵn sàng.' })
      setPicked(undefined); setTitle(''); setContent(''); setReason('')
    },
    onError: (failure) => {
      void queryClient.invalidateQueries({ queryKey: ['planning-run', runId] })
      setError(failure instanceof ApiError && failure.code === 'PLANNING_VERSION_CONFLICT'
        ? new Error('Kế hoạch vừa thay đổi (có việc khác vừa vào hoặc được xếp). Đã tải lại, hãy bấm lại để tiếp tục.')
        : failure)
    },
  })
  const [overHours, setOverHours] = useState<{ candidateId: string; code: string; issue: string | null } | null>(null)
  const force = useMutation({
    mutationFn: async () => {
      const fresh = await api<PlanningRun>(`/planning/runs/${runId}`)
      return api<PlanningAddWorkResult>(`/planning/runs/${runId}/candidates/${overHours!.candidateId}/assign`, {
        method: 'POST',
        body: JSON.stringify({
          expected_run_version: fresh.version, member_id: memberId, slot, planned_hours: Number(hours),
          issue_mode: 'EXISTING', issue_external_id: overHours!.issue, priority, reason: null, override_reason: 'Người xếp việc xác nhận xếp quá giờ',
        }),
      })
    },
    onSuccess: (result) => {
      setOverHours(null)
      void queryClient.invalidateQueries({ queryKey: ['planning-run', runId] }); void queryClient.invalidateQueries({ queryKey: ['planning-capacities'] })
      setMessage(result.state === 'PLANNED' ? { tone: 'success', text: `Đã xếp dù quá giờ; lý do được ghi trên việc.` } : { tone: 'warn', text: `Vẫn chưa xếp được: ${addWorkErrors[result.assignment_error || ''] || result.assignment_error}.` })
    },
    onError: (error) => { setOverHours(null); setError(error) },
  })
  if (!run) return <LoadingBlock />
  const ready = (canApprove || !needsIssue) && (mode === 'EXISTING' ? Boolean(picked) && !picked?.already_planned : title.trim().length > 0 && Boolean(targetProject))
    && (!needsIssue || reason.trim().length >= 5) && (!memberId || Number(hours) > 0)

  return (
    <div className="add-work">
      {overHours && (
        <ConfirmDialog title="Người này đã đủ giờ" confirmLabel="Vẫn xếp" busyLabel="Đang xếp…" busy={force.isPending} plain onConfirm={() => force.mutate()} onCancel={() => setOverHours(null)}>
          <p>{overHours.code === 'SLOT_OVER_CAPACITY' ? 'Buổi này của người đó đã quá 4 giờ.' : 'Số giờ trong ngày của người đó, kể cả ở dự án khác, đã hết.'} Việc đã nằm ở "Việc chờ phân công"; vẫn xếp thì lý do "xác nhận xếp quá giờ" được ghi trên việc và thẻ người hiện đỏ.</p>
        </ConfirmDialog>
      )}
      <div className="quick-tabs add-work-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={mode === 'EXISTING'} className={mode === 'EXISTING' ? 'active' : ''} onClick={() => { setMode('EXISTING'); setMessage(undefined) }}>Việc đã có</button>
        {canApprove && <button type="button" role="tab" aria-selected={mode === 'NEW'} className={mode === 'NEW' ? 'active' : ''} onClick={() => { setMode('NEW'); setMessage(undefined); setPicked(undefined); setPriority('P1'); setMemberId('') }}>Việc mới phát sinh</button>}
      </div>
      {mode === 'EXISTING' ? (
        <>
          <label className="search-field add-work-search"><Search size={16} aria-hidden="true" /><input value={search} onChange={(e) => { setSearch(e.target.value); setPicked(undefined) }} placeholder="Tìm theo tiêu đề, số Issue hoặc mã Intake…" aria-label="Tìm việc" /></label>
          <div className="add-work-results" role="listbox" aria-label="Việc tìm thấy">
            {results.isLoading ? <LoadingBlock /> : (results.data || []).length === 0 ? <p className="field-help">Không có Issue đang mở hay Intake chờ duyệt nào khớp. Nếu là việc chưa có ở đâu, chuyển sang tab "Việc mới phát sinh".</p> : (results.data || []).map((item) => {
              const key = `${item.kind}-${item.project_id}-${item.issue_external_id || item.intake_id}`
              const selected = picked != null && `${picked.kind}-${picked.project_id}-${picked.issue_external_id || picked.intake_id}` === key
              if (item.kind === 'ISSUE') return <IssueOption key={key} item={item} selected={selected} disabled={item.already_planned} extra={scope.length > 1 && item.project_name ? item.project_name : undefined} onPick={() => { setPicked(item); setMemberId(''); if (item.priority) setPriority(item.priority) }} />
              return (
                <button type="button" role="option" aria-selected={selected} key={key} className={selected ? 'add-work-item active' : 'add-work-item'} disabled={item.already_planned} onClick={() => { setPicked(item); setMemberId(''); if (item.priority) setPriority(item.priority) }}>
                  <strong>{item.title}</strong>
                  <small>{`Intake ${item.public_id}${item.issue_external_id ? ` · Issue #${item.issue_external_id}` : ''}`}{scope.length > 1 && item.project_name ? ` · ${item.project_name}` : ''}{item.priority ? ` · ${item.priority}` : ''}</small>
                  {item.already_planned ? <span className="status report-valid">Đã trong kế hoạch</span> : item.needs_issue ? <span className="status report-warning">Chưa có Issue</span> : null}
                </button>
              )
            })}
          </div>
        </>
      ) : (
        <>
          {scope.length > 1 && <label>Dự án<select value={targetProject} onChange={(e) => { setProjectId(e.target.value); setMemberId('') }}>{scope.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}</select></label>}
          <label><span className="req-label">Tiêu đề<Req /></span><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ví dụ: Khách không nhận được OTP khi đăng nhập" maxLength={255} /></label>
          <label>Mô tả<textarea rows={4} value={content} onChange={(e) => setContent(e.target.value)} placeholder="Điều gì đang xảy ra, ở đâu, ảnh hưởng thế nào. Có thể dán nguyên tin nhắn của khách." /></label>
          <div className="add-work-row">
            <label>Loại<select value={itemType} onChange={(e) => setItemType(e.target.value as typeof itemType)}><option value="BUG">Lỗi</option><option value="TASK">Việc cần làm</option><option value="FEATURE">Tính năng</option></select></label>
            <label>Ưu tiên<select value={priority} onChange={(e) => setPriority(e.target.value)}>{['P0', 'P1', 'P2', 'P3'].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
          </div>
        </>
      )}
      {needsIssue && !canApprove && <p className="notice notice-warn approve-note"><strong>Việc này cần CTO phê duyệt.</strong> Việc chưa có Issue chỉ CTO thêm thẳng vào kế hoạch được. Bạn có thể duyệt yêu cầu ở trang Chờ phê duyệt, đồng bộ để có Issue, rồi quay lại chọn.</p>}
      {needsIssue && canApprove && (
        <div className="add-work-reason">
          {mode === 'EXISTING' && <label>Ưu tiên<select value={priority} onChange={(e) => setPriority(e.target.value)}>{['P0', 'P1', 'P2', 'P3'].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>}
          <label><span className="req-label">Lý do đưa thẳng vào kế hoạch<Req /></span><textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Ví dụ: khách đang không đăng nhập được, cần xử lý trong sáng nay" /></label>
          <p className="notice notice-warn approve-note"><strong>Thao tác này phê duyệt Intake.</strong> Việc này chưa có Issue, nên bấm thêm nghĩa là bạn phê duyệt yêu cầu ngay tại đây (lý do được lưu lại): nó rời khỏi hàng Chờ phê duyệt, một Issue được tạo trên {trackerName} của dự án, rồi việc vào kế hoạch. Bạn sẽ không xem lại bản AI chuẩn hóa như ở trang Chờ phê duyệt. {project?.delivery_system === 'GITHUB' ? 'Issue trên GitHub của khách hàng chỉ gồm tiêu đề và mô tả.' : ''}</p>
        </div>
      )}
      <fieldset className="add-work-assign">
        <legend>Phân công</legend>
        <label>Người làm
          <select value={memberId} onChange={(e) => setMemberId(e.target.value)} disabled={!targetProject}>
            <option value="">Chưa chọn: để ở "Việc chờ phân công"</option>
            {team.map((member) => <option key={member.id} value={member.id} disabled={!hasTrackerUser(member)}>{member.display_name}{hasTrackerUser(member) ? '' : ` · thiếu người dùng ${trackerName}`}</option>)}
          </select>
          {targetProject && team.length === 0 && <small className="field-help">Dự án này chưa có nhân sự. Gán ở Cài đặt &gt; Dự án.</small>}
        </label>
        {targetProject && <TrackerUserFix projectId={targetProject} trackerName={trackerName} team={team} hasTrackerUser={hasTrackerUser} issue={mode === 'EXISTING' ? picked?.issue_external_id : null} />}
        {memberId && (
          <div className="add-work-row">
            <label>Buổi<select value={slot} onChange={(e) => setSlot(e.target.value as PlanningSlot)}><option value="MORNING">Buổi sáng</option><option value="AFTERNOON">Buổi chiều</option></select></label>
            <label><span className="req-label">Số giờ<Req /></span><input type="number" min="0.5" max="8" step="0.5" value={hours} onChange={(e) => setHours(e.target.value)} /></label>
          </div>
        )}
      </fieldset>
      {error != null && <ErrorNotice error={error} />}
      {message && <p className={`notice ${message.tone === 'success' ? 'notice-success' : 'notice-warn'}`} role="status">{message.text}</p>}
      <button className="button button-primary button-wide" type="button" disabled={!ready || add.isPending || Boolean(waitingFor)} onClick={() => add.mutate()}>{add.isPending ? 'Đang thêm…' : waitingFor ? 'Đang tạo Issue…' : needsIssue ? 'Phê duyệt và thêm vào kế hoạch' : memberId ? 'Thêm vào kế hoạch' : 'Thêm vào việc chờ phân công'}</button>
    </div>
  )
}

const reportStatusWords: Record<string, string> = { PLANNED: 'Kế hoạch', IN_PROGRESS: 'Đang làm', PENDING_REVIEW: 'Chờ review', BLOCKED: 'Bị chặn', DONE: 'Xong', CANCELLED: 'Đã hủy' }

// Older entries store the report status as its code; show it in plain words.
// The two ids a line of work carries, told apart and each a link: the Issue on the tracker, the request in Intake.
function IssueRef({ issue, url, label = 'Issue' }: { issue: string | null; url: string | null; label?: string }) {
  if (!issue) return null
  return url ? <a className="ref-link" href={url} target="_blank" rel="noreferrer" title="Mở Issue trên tracker">{label} #{issue} <ArrowUpRight size={11} /></a> : <span>{label} #{issue}</span>
}
function IntakeRef({ id, publicId, label = 'Intake' }: { id: string | null; publicId: string | null; label?: string }) {
  if (!id) return null
  return <Link className="ref-link" to={`/intakes/${id}`} title="Mở yêu cầu trong Intake">{label} {publicId || ''} <ArrowUpRight size={11} /></Link>
}

// One meta line for a waiting entry, the same on the project's plan page and on the overview:
// where it came from · priority badge · tracker Issue · when the work behind it began.
function WaitingMeta({ sourceType, intakeId, intakePublicId, priority, issue, issueUrl, memberName, originAt, tail }: {
  sourceType: string; intakeId: string | null; intakePublicId: string | null; priority: Priority | null; issue: string | null; issueUrl: string | null
  memberName: string | null; originAt: string | null; tail?: ReactNode
}) {
  const head = sourceType === 'INTAKE' && intakeId ? <IntakeRef id={intakeId} publicId={intakePublicId} label="Từ Intake" />
    : sourceType === 'REPORT' ? `Từ báo cáo${memberName ? ` của ${memberName}` : ''}`
    : sourceType === 'VERIFICATION' ? 'Làm lại'
    : sourceType === 'GITLAB' ? `Làm tiếp${memberName ? ` · ${memberName}` : ''}`
    : memberName ? `Đề xuất của ${memberName}` : 'Bạn thêm'
  const tracker = issueUrl && /github\.com/.test(issueUrl) ? 'GitHub' : 'GitLab'
  return <small>{dotted([
    head,
    priority ? <span className={`priority priority-inline priority-${priority.toLowerCase()}`}>{priority}</span> : null,
    issue ? <IssueRef issue={issue} url={issueUrl} label={tracker} /> : 'chưa có Issue',
    originAt ? `${sourceType === 'INTAKE' ? 'tạo' : 'từ'} ${formatDay(originAt)}` : null,
    sourceType !== 'INTAKE' && intakeId ? <IntakeRef id={intakeId} publicId={intakePublicId} /> : null,
    tail ?? null,
  ])}</small>
}
// Pieces of a meta line separated by " · "; empty pieces drop out.
function dotted(parts: ReactNode[]) {
  const kept = parts.filter((part) => part !== null && part !== undefined && part !== '' && part !== false)
  return kept.map((part, index) => <span key={index}>{index > 0 ? ' · ' : ''}{part}</span>)
}

function waitingNote(candidate: PlanningCandidate) {
  const text = (candidate.summary || '').replace(/Trạng thái báo cáo: ([A-Z_]+)/, (_, code: string) => reportStatusWords[code] || code)
  const parts = text.split(/\s·\s|\n/).map((part) => part.trim()).filter(Boolean)
  return { status: candidate.source_type === 'REPORT' ? parts[0] : undefined, rest: (candidate.source_type === 'REPORT' ? parts.slice(1) : parts).join(' · ') }
}

function AssignWorkPanel({ runId, candidateId, canApprove, onDone }: { runId: string; candidateId: string; canApprove: boolean; onDone: () => void }) {
  const queryClient = useQueryClient()
  const runQuery = useQuery({ queryKey: ['planning-run', runId], queryFn: () => api<PlanningRun>(`/planning/runs/${runId}`) })
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const members = useQuery({ queryKey: ['planning-members'], queryFn: () => api<WorkforceMember[]>('/planning/members') })
  const run = runQuery.data
  const candidate = run?.candidates.find((entry) => entry.id === candidateId)
  const project = (projects.data || []).find((entry) => entry.id === candidate?.project_id)
  const trackerName = project?.delivery_system === 'GITHUB' ? 'GitHub' : 'GitLab'
  const hasIssue = Boolean(candidate?.gitlab_issue_external_id)
  const [issueMode, setIssueMode] = useState<'EXISTING' | 'CREATE'>('EXISTING')
  const [search, setSearch] = useState('')
  const [issueId, setIssueId] = useState('')
  const [priority, setPriority] = useState('P2')
  const [reason, setReason] = useState('')
  const [memberId, setMemberId] = useState<string>()
  const [slot, setSlot] = useState<PlanningSlot>()
  const [hours, setHours] = useState<string>()
  const [error, setError] = useState<unknown>()
  const [message, setMessage] = useState<string>()
  const [creating, setCreating] = useState(false)
  const issues = useQuery({
    queryKey: ['planning-work-items', runId, candidateId, search.trim()],
    queryFn: () => api<PlanningWorkItem[]>(`/planning/runs/${runId}/work-items?candidate_id=${candidateId}${search.trim() ? `&search=${encodeURIComponent(search.trim())}` : ''}`),
    enabled: !hasIssue && issueMode === 'EXISTING',
  })
  const team = (members.data || []).filter((member) => member.project_mappings.some((mapping) => mapping.active && mapping.project_id === candidate?.project_id))
  const projectIssues = (issues.data || []).filter((item) => item.kind === 'ISSUE' && item.project_id === candidate?.project_id)
  const chosenIssue = projectIssues.find((item) => item.issue_external_id === issueId)
  const suggestedIssues = projectIssues.filter((item) => item.suggested && !item.already_planned)
  const otherIssues = projectIssues.filter((item) => !item.suggested && !item.assigned_to_other && !item.already_planned)
  const theirIssues = projectIssues.filter((item) => !item.suggested && item.assigned_to_other && !item.already_planned)
  const plannedIssues = projectIssues.filter((item) => item.already_planned)
  const hasTrackerUser = (member: WorkforceMember) => Boolean(member.project_mappings.find((mapping) => mapping.active && mapping.project_id === candidate?.project_id)?.gitlab_user_external_id)
  const defaultMember = candidate?.member_id && team.some((member) => member.id === candidate.member_id && hasTrackerUser(member)) ? candidate.member_id : ''
  const person = memberId ?? defaultMember
  const chosenSlot = slot ?? candidate?.target_slot ?? 'MORNING'
  const chosenHours = hours ?? String(candidate?.requested_hours || 2)

  // After asking for a new Issue, watch the run until this entry leaves the waiting state.
  useEffect(() => {
    if (!creating) return
    let tries = 0
    const timer = window.setInterval(() => {
      tries += 1
      void queryClient.invalidateQueries({ queryKey: ['planning-run', runId] })
      if (tries >= 20) { window.clearInterval(timer); setCreating(false); setMessage('Issue chưa được tạo xong sau 40 giây. Việc vẫn nằm trong danh sách chờ; kiểm tra đồng bộ của Intake nếu nó không đổi trạng thái.') }
    }, 2000)
    return () => window.clearInterval(timer)
  }, [creating, runId, queryClient])
  useEffect(() => {
    if (creating && candidate && candidate.status === 'ASSIGNED') { setCreating(false); onDone() }
    if (creating && candidate && candidate.status === 'READY') { setCreating(false); setMessage(`Đã tạo Issue #${candidate.gitlab_issue_external_id}, nhưng chưa phân công tự động được. Kiểm tra người làm và số giờ rồi bấm lại.`) }
  }, [creating, candidate, onDone])

  const assign = useMutation({
    mutationFn: () => api<PlanningAddWorkResult>(`/planning/runs/${runId}/candidates/${candidateId}/assign`, {
      method: 'POST',
      body: JSON.stringify({
        expected_run_version: run!.version, member_id: person, slot: chosenSlot, planned_hours: Number(chosenHours),
        issue_mode: hasIssue ? 'EXISTING' : issueMode, issue_external_id: hasIssue ? candidate!.gitlab_issue_external_id : issueMode === 'EXISTING' ? issueId : null,
        priority, reason: !hasIssue && issueMode === 'CREATE' ? reason.trim() : null,
      }),
    }),
    onMutate: () => { setError(undefined); setMessage(undefined) },
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['planning-run', runId] })
      void queryClient.invalidateQueries({ queryKey: ['planning-capacities'] })
      if (result.state === 'PLANNED') onDone()
      else if (result.state === 'CREATING_ISSUE') { setCreating(true); setMessage(`Đang tạo Issue trên ${trackerName}; việc sẽ tự vào kế hoạch khi Issue có.`) }
      else if (result.assignment_error === 'OVER_CAPACITY' || result.assignment_error === 'SLOT_OVER_CAPACITY') setOverHours({ candidateId: result.candidate.id, code: result.assignment_error })
      else setMessage(`Chưa phân công được: ${addWorkErrors[result.assignment_error || ''] || result.assignment_error}.`)
    },
    onError: setError,
  })
  const [overHours, setOverHours] = useState<{ candidateId: string; code: string } | null>(null)
  const force = useMutation({
    mutationFn: async () => {
      const fresh = await api<PlanningRun>(`/planning/runs/${runId}`)
      return api<PlanningAddWorkResult>(`/planning/runs/${runId}/candidates/${overHours!.candidateId}/assign`, {
        method: 'POST',
        body: JSON.stringify({
          expected_run_version: fresh.version, member_id: person, slot: chosenSlot, planned_hours: Number(chosenHours),
          issue_mode: 'EXISTING', issue_external_id: candidate!.gitlab_issue_external_id, priority, reason: null, override_reason: 'Người xếp việc xác nhận xếp quá giờ',
        }),
      })
    },
    onSuccess: (result) => { setOverHours(null); void queryClient.invalidateQueries({ queryKey: ['planning-run', runId] }); void queryClient.invalidateQueries({ queryKey: ['planning-capacities'] }); if (result.state === 'PLANNED') onDone(); else setMessage(`Chưa phân công được: ${addWorkErrors[result.assignment_error || ''] || result.assignment_error}.`) },
    onError: (error) => { setOverHours(null); setError(error) },
  })
  if (!run || !candidate) return <LoadingBlock />
  const note = waitingNote(candidate)
  const overDialog = overHours && (
    <ConfirmDialog title="Người này đã đủ giờ" confirmLabel="Vẫn xếp" busyLabel="Đang xếp…" busy={force.isPending} plain onConfirm={() => force.mutate()} onCancel={() => setOverHours(null)}>
      <p>{overHours.code === 'SLOT_OVER_CAPACITY' ? 'Buổi này của người đó đã quá 4 giờ.' : 'Số giờ trong ngày của người đó, kể cả ở dự án khác, đã hết.'} Vẫn xếp thì lý do "xác nhận xếp quá giờ" được ghi trên việc và thẻ người hiện đỏ.</p>
    </ConfirmDialog>
  )
  const ready = Boolean(person) && Number(chosenHours) > 0 && (hasIssue || (issueMode === 'EXISTING' ? Boolean(issueId) : reason.trim().length >= 5))

  return (
    <div className="add-work">
      {overDialog}
      <div className="assign-work-title">
        <strong>{candidate.title}</strong>
        <small>{[project?.name, candidate.source_type === 'REPORT' ? candidate.source_reference.replace('Daily Report', 'Báo cáo ngày') : null, hasIssue ? `Issue #${candidate.gitlab_issue_external_id}` : null].filter(Boolean).join(' · ')}</small>
        {note.rest && <p>{note.rest}</p>}
      </div>
      {!hasIssue && (
        <fieldset className="option-list option-list-compact">
          <legend>Việc này chưa gắn Issue</legend>
          <label className={issueMode === 'EXISTING' ? 'option active' : 'option'} title={`Việc đã có Issue trên ${trackerName} nhưng báo cáo không ghi số.`}>
            <input type="radio" name="issue-mode" checked={issueMode === 'EXISTING'} onChange={() => setIssueMode('EXISTING')} />
            <span><strong>Chọn Issue đã có</strong></span>
          </label>
          <label className={issueMode === 'CREATE' ? 'option active' : 'option'} title={canApprove ? `Chưa có Issue nào cho việc này; hệ thống tạo trên ${trackerName} sau khi bạn xác nhận.` : 'Chỉ CTO tạo được Issue mới từ đây, vì thao tác này phê duyệt một yêu cầu.'}>
            <input type="radio" name="issue-mode" checked={issueMode === 'CREATE'} disabled={!canApprove} onChange={() => setIssueMode('CREATE')} />
            <span><strong>Tạo Issue mới</strong></span>
          </label>
        </fieldset>
      )}
      {!hasIssue && issueMode === 'EXISTING' && (
        <>
          {chosenIssue ? (
            // Once an Issue is chosen the list gets out of the way, so the assignment below is in view.
            <div className="issue-chosen">
              <small>Issue đã chọn</small>
              <IssueOption item={chosenIssue} selected onPick={() => undefined} />
              <button type="button" className="text-button" onClick={() => setIssueId('')}>Đổi Issue</button>
            </div>
          ) : (
            <>
              <label className="search-field add-work-search"><Search size={16} aria-hidden="true" /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Tìm Issue theo tiêu đề hoặc số…" aria-label="Tìm Issue" /></label>
              <div className="issue-groups" role="listbox" aria-label="Issue tìm thấy">
                {issues.isLoading ? <LoadingBlock /> : projectIssues.length === 0 ? <p className="field-help">Không có Issue đang mở nào khớp. Nếu việc này chưa có Issue, chọn "Tạo Issue mới".</p> : (
                  <>
                    {suggestedIssues.length > 0 && <section><h4>Gợi ý cho việc này</h4>{suggestedIssues.map((item) => <IssueOption key={item.issue_external_id} item={item} selected={false} extra={item.suggested === 'PERSON' ? 'đang gán cho người này' : 'tiêu đề gần giống'} onPick={() => setIssueId(item.issue_external_id || '')} />)}</section>}
                    {otherIssues.length > 0 && <section><h4>{suggestedIssues.length > 0 ? 'Issue khác' : 'Issue đang mở'}</h4>{otherIssues.map((item) => <IssueOption key={item.issue_external_id} item={item} selected={false} onPick={() => setIssueId(item.issue_external_id || '')} />)}</section>}
                    {theirIssues.length > 0 && <details open={search.trim() !== ''}><summary>Đang gán cho người khác <small>{theirIssues.length}</small></summary>{theirIssues.map((item) => <IssueOption key={item.issue_external_id} item={item} selected={false} onPick={() => setIssueId(item.issue_external_id || '')} />)}</details>}
                    {plannedIssues.length > 0 && <details open={search.trim() !== ''}><summary>Đã có trong kế hoạch hôm nay <small>{plannedIssues.length}</small></summary>{plannedIssues.map((item) => <IssueOption key={item.issue_external_id} item={item} selected={false} onPick={() => setIssueId(item.issue_external_id || '')} />)}</details>}
                  </>
                )}
              </div>
            </>
          )}
        </>
      )}
      {!hasIssue && issueMode === 'CREATE' && (
        <div className="add-work-reason">
          <label>Ưu tiên<select value={priority} onChange={(e) => setPriority(e.target.value)}>{['P0', 'P1', 'P2', 'P3'].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
          <label><span className="req-label">Lý do đưa thẳng vào kế hoạch<Req /></span><textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Ví dụ: việc đã thống nhất trong buổi họp sáng" /></label>
          <p className="notice notice-warn approve-note"><strong>Thao tác này phê duyệt Intake.</strong> Bấm xếp việc nghĩa là bạn phê duyệt việc này ngay tại đây (lý do được lưu lại): một Intake được tạo và duyệt, rồi Issue được tạo trên {trackerName} từ tiêu đề của việc. Nó sẽ không đi qua hàng Chờ phê duyệt.</p>
        </div>
      )}
      <fieldset className="add-work-assign">
        <legend>Phân công</legend>
        <label>Người làm
          <select value={person} onChange={(e) => setMemberId(e.target.value)}>
            <option value="" disabled>Chọn người làm…</option>
            {team.map((member) => <option key={member.id} value={member.id} disabled={!hasTrackerUser(member)}>{member.display_name}{hasTrackerUser(member) ? '' : ` · thiếu người dùng ${trackerName}`}</option>)}
          </select>
          {team.length === 0 && <small className="field-help">Dự án này chưa có nhân sự. Gán ở Cài đặt &gt; Dự án.</small>}
        </label>
        {candidate.project_id && <TrackerUserFix projectId={candidate.project_id} trackerName={trackerName} team={team} hasTrackerUser={hasTrackerUser} issue={candidate.gitlab_issue_external_id} />}
        <div className="add-work-row">
          <label>Buổi<select value={chosenSlot} onChange={(e) => setSlot(e.target.value as PlanningSlot)}><option value="MORNING">Buổi sáng</option><option value="AFTERNOON">Buổi chiều</option></select></label>
          <label>Số giờ<input type="number" min="0.5" max="8" step="0.5" value={chosenHours} onChange={(e) => setHours(e.target.value)} /></label>
        </div>
      </fieldset>
      {error != null && <ErrorNotice error={error} />}
      {message && <p className="notice notice-warn" role="status">{message}</p>}
      <button className="button button-primary button-wide" type="button" disabled={!ready || assign.isPending || creating} onClick={() => assign.mutate()}>{assign.isPending ? 'Đang xếp…' : creating ? 'Đang tạo Issue…' : !hasIssue && issueMode === 'CREATE' ? 'Phê duyệt và xếp vào kế hoạch' : 'Xếp vào kế hoạch'}</button>
    </div>
  )
}

// The day's spot checks: one or two Issues closed lately, what stands behind each, and the CTO's call.
function VerificationList({ run, members, projects, editable, onChanged }: { run: PlanningRun; members: WorkforceMember[]; projects: Project[]; editable: boolean; onChanged: () => void }) {
  const queryClient = useQueryClient()
  const [error, setError] = useState<unknown>()
  const [rejecting, setRejecting] = useState<IssueVerification>()
  const [reason, setReason] = useState('')
  const decide = useMutation({
    mutationFn: ({ id, decision, why }: { id: string; decision: 'accept' | 'reject'; why?: string }) => api<PlanningRun>(`/planning/runs/${run.id}/verifications/${id}/${decision}`, { method: 'POST', body: JSON.stringify({ expected_version: run.version, reason: why || null }) }),
    onMutate: () => setError(undefined), onSuccess: () => { setRejecting(undefined); setReason(''); onChanged() }, onError: setError,
  })
  const rule = useMutation({
    mutationFn: ({ projectId, value }: { projectId: string; value: 'COMMIT' | 'MR' }) => api(`/planning/projects/${projectId}/done-evidence`, { method: 'PUT', body: JSON.stringify({ done_evidence: value }) }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['projects'] }); onChanged() }, onError: setError,
  })
  const rows = run.verifications || []
  if (rows.length === 0) return null
  const nameOf = (id: string | null) => members.find((member) => member.id === id)?.display_name
  const projectOf = (id: string) => projects.find((project) => project.id === id)
  const levelLabel: Record<string, string> = { SELF_REPORTED: 'Tự khai', CLOSED: 'Đã đóng, chưa có dấu vết', TRACED: 'Có dấu vết code', ACCEPTED: 'Đã nghiệm thu' }
  const pending = rows.filter((row) => row.decision === 'PENDING').length
  return (
    <section className="planning-section" id="plan-verifications">
      <div className="planning-section-title"><div><h2>Nghiệm thu hôm nay</h2></div><span>{pending > 0 ? `${pending} việc cần xem` : 'Đã xem xong'}</span></div>
      {error != null && <ErrorNotice error={error} />}
      {rejecting && (
        <ConfirmDialog title={`Chưa xong: ${rejecting.title}`} confirmLabel="Ghi chưa xong" busyLabel="Đang ghi…" plain busy={decide.isPending} error={decide.error ?? undefined} onConfirm={() => { if (reason.trim().length >= 3) decide.mutate({ id: rejecting.id, decision: 'reject', why: reason.trim() }) }} onCancel={() => { setRejecting(undefined); setReason('') }}>
          <label>Chưa xong ở chỗ nào<textarea rows={3} value={reason} maxLength={1000} onChange={(event) => setReason(event.target.value)} placeholder="Ví dụ: đơn vẫn tạo trùng khi khách bấm hai lần" /></label>
          <ul><li>Việc quay lại "Việc chờ phân công" dưới dạng "Làm lại", người từng nhận được cảnh báo.</li><li>Issue trên GitLab không bị mở lại từ đây; mở lại bằng tay nếu cần.</li></ul>
        </ConfirmDialog>
      )}
      <div className="panel waiting-list verification-list">
        <ul>
          {rows.map((row) => {
            const project = projectOf(row.project_id)
            const evidence = row.evidence
            const traces = [
              evidence.commits > 0 ? `${evidence.commits} commit nhắc Issue` : null,
              evidence.merge_requests > 0 ? `${evidence.merged}/${evidence.merge_requests} MR đã merge` : null,
              evidence.pipeline ? `pipeline ${evidence.pipeline === 'success' ? 'xanh' : evidence.pipeline === 'failed' ? 'đỏ' : evidence.pipeline}` : null,
            ].filter(Boolean)
            return (
              <li key={row.id} className={`waiting-row verification-row level-${row.level_name.toLowerCase()} decision-${row.decision.toLowerCase()}`}>
                <div>
                  <strong>{row.web_url ? <a href={row.web_url} target="_blank" rel="noreferrer">#{row.issue_external_id} {row.title}</a> : `#${row.issue_external_id} ${row.title}`}</strong>
                  <small>
                    <span className={`status verification-level`}>{levelLabel[row.level_name] || row.level_name}</span>
                    {project ? ` · ${project.name}` : ''}
                    {row.closed_at ? ` · đóng ${formatDate(row.closed_at)}` : ''}
                    {row.closed_by_member_id ? ` bởi ${nameOf(row.closed_by_member_id)}` : ''}
                    {row.assignee_member_id ? ` · người làm ${nameOf(row.assignee_member_id)}` : ''}
                    {` · ${traces.length > 0 ? traces.join(', ') : row.evidence_fetched_at ? 'không có commit hay MR nào nhắc Issue' : 'chưa đọc dấu vết code'}`}
                    {row.intake_public_id ? ` · từ ${row.intake_public_id}` : ''}
                  </small>
                  {row.acceptance.length > 0 && <ul className="verification-acceptance">{row.acceptance.map((item, index) => <li key={index}>{item}</li>)}</ul>}
                  {row.decision === 'REJECTED' && <p className="verification-reason">Chưa xong: {row.reason}</p>}
                  {editable && project && (
                    <small className="verification-rule">Dự án này tính dấu vết bằng {row.done_evidence === 'MR' ? 'MR đã merge' : 'commit nhắc Issue'} · <button type="button" className="text-button" disabled={rule.isPending} onClick={() => rule.mutate({ projectId: project.id, value: row.done_evidence === 'MR' ? 'COMMIT' : 'MR' })}>đổi sang {row.done_evidence === 'MR' ? 'commit' : 'MR'}</button></small>
                  )}
                </div>
                {row.decision === 'PENDING' && editable ? (
                  <span className="waiting-actions">
                    <button className="button button-primary button-small" type="button" disabled={decide.isPending} onClick={() => decide.mutate({ id: row.id, decision: 'accept' })}>Đúng là xong</button>
                    <button className="button button-secondary button-small" type="button" disabled={decide.isPending} onClick={() => { setReason(''); setRejecting(row) }}>Chưa xong</button>
                  </span>
                ) : row.decision !== 'PENDING' ? <span className={`status decision-${row.decision.toLowerCase()}`}>{row.decision === 'ACCEPTED' ? 'Đã nghiệm thu' : 'Chưa xong'}</span> : null}
              </li>
            )
          })}
        </ul>
        <p className="field-help">Mỗi ngày hệ thống chọn tối đa hai Issue đóng trong tuần qua, ưu tiên việc ít dấu vết nhất. Bằng chứng đọc từ GitLab/GitHub ở lần làm mới 06:45.</p>
      </div>
    </section>
  )
}

function WaitingList({ run, members, editable, onAssign, onChanged }: { run: PlanningRun; members: WorkforceMember[]; editable: boolean; onAssign: (candidateId: string) => void; onChanged: () => void }) {
  const [error, setError] = useState<unknown>()
  const [cancelling, setCancelling] = useState<{ id: string; title: string } | null>(null)
  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'dismiss' | 'restore' }) => api<PlanningCandidate>(`/planning/runs/${run.id}/candidates/${id}/${action}`, { method: 'POST' }),
    onMutate: () => setError(undefined), onSuccess: onChanged, onError: setError,
  })
  const waiting = run.candidates.filter((candidate) => candidate.status === 'PENDING_TRIAGE' || candidate.status === 'READY')
  const dismissed = run.candidates.filter((candidate) => candidate.status === 'REJECTED')
  // Recorded as done outside the plan: waits for the CTO's acceptance, never for the plan (FR-PLAN-34).
  // Once the CTO accepted the Issue, the line is no longer "waiting for acceptance" and leaves Daily Planning (INT-26W43-001).
  const doneElsewhere = run.candidates.filter((candidate) => candidate.status === 'DONE_ELSEWHERE' && !candidate.accepted_at)
  const nameOf = (id: string | null) => members.find((member) => member.id === id)?.display_name
  // Suggestions from daily reports are grouped by the person who reported them; work the CTO added comes first.
  const groups = new Map<string, { source: string; tone: string; title: string; items: PlanningCandidate[] }>()
  for (const candidate of waiting) {
    const fromReport = candidate.source_type === 'REPORT'
    // A request with an Issue that nobody has taken: Intake put it here, not the person on the screen.
    const fromIntake = candidate.source_type === 'INTAKE' && Boolean(candidate.gitlab_issue_external_id)
    // An Issue the CTO looked at and found not done comes back here as rework.
    const fromRework = candidate.source_type === 'VERIFICATION'
    // Placed on an earlier day and not reported done: it comes back to be continued (FR-PLAN-34).
    const carried = candidate.source_type === 'GITLAB' && candidate.source_reference.startsWith('Kế hoạch ')
    // A member's own proposal (FR-PLAN-35): their name is on it, and they are the suggested person.
    const proposed = candidate.source_type === 'FORM' && Boolean(candidate.member_id) && candidate.source_reference.startsWith('Đề xuất của ')
    const key = fromReport ? `report:${candidate.member_id}:${candidate.source_reference}` : fromRework ? 'rework' : carried ? 'carried' : proposed ? 'proposed' : fromIntake ? 'intake' : 'added'
    // Where the work came from goes in a badge; the rest of the heading says whose or which.
    const source = fromReport ? 'Từ báo cáo' : fromRework ? 'Làm lại' : carried ? 'Làm tiếp' : proposed ? 'Đề xuất' : fromIntake ? 'Từ Intake' : 'Bạn thêm'
    const tone = fromReport ? 'report' : fromRework ? 'rework' : carried ? 'carried' : proposed ? 'proposed' : fromIntake ? 'intake' : 'added'
    const title = fromReport ? `${nameOf(candidate.member_id) || 'Nhân sự'} · ${formatDay(candidate.source_reference.replace('Daily Report ', ''))}` : fromRework ? 'CTO xem lại: chưa xong' : carried ? 'Chưa xong ở kế hoạch trước' : proposed ? 'Nhân sự đề xuất, chờ bạn xếp' : fromIntake ? 'Đã có Issue, chưa ai nhận' : 'Việc đưa thẳng vào kế hoạch'
    if (!groups.has(key)) groups.set(key, { source, tone, title, items: [] })
    groups.get(key)!.items.push(candidate)
  }
  const rank = (key: string) => (key === 'added' ? 0 : key === 'rework' ? 1 : key === 'proposed' ? 2 : key === 'carried' ? 3 : key === 'intake' ? 4 : 5)
  const ordered = [...groups.entries()].sort(([a], [b]) => rank(a) - rank(b))
  const row = (candidate: PlanningCandidate, isDismissed = false) => {
    const note = waitingNote(candidate)
    return (
      <li key={candidate.id} className="waiting-row">
        <div>
          <strong title={candidate.summary || undefined}>{candidate.title}</strong>
          <WaitingMeta sourceType={candidate.source_type} intakeId={candidate.intake_id} intakePublicId={candidate.intake_public_id} priority={candidate.proposed_priority}
            issue={candidate.gitlab_issue_external_id} issueUrl={candidate.issue_url} memberName={candidate.member_id ? nameOf(candidate.member_id) ?? null : null} originAt={candidate.origin_at}
            tail={candidate.source_type === 'INTAKE' ? (candidate.status === 'PENDING_TRIAGE' && !candidate.gitlab_issue_external_id ? 'đang tạo Issue' : null) : dotted([note.status, note.rest])} />
        </div>
        {editable && (isDismissed
          ? <button className="button button-secondary button-small" type="button" disabled={act.isPending} onClick={() => act.mutate({ id: candidate.id, action: 'restore' })}>Đưa lại</button>
          : <span className="waiting-actions">
              <button className="button button-primary button-small" type="button" onClick={() => onAssign(candidate.id)}>Xếp việc</button>
              <button className="button button-secondary button-small" type="button" title="Hôm nay không xếp việc này; ngày mai nó hiện lại nếu Issue còn mở" disabled={act.isPending} onClick={() => act.mutate({ id: candidate.id, action: 'dismiss' })}>Hoãn</button>
              <button className="button button-secondary button-small" type="button" title="Việc này đã làm xong ngoài kế hoạch: ghi ai làm, rồi bỏ khỏi danh sách chờ và đưa Issue vào Nghiệm thu" onClick={() => setCancelling({ id: candidate.id, title: candidate.title })}>Đã làm rồi</button>
            </span>)}
      </li>
    )
  }
  return (
    <section className="planning-section">
      <div className="planning-section-title"><div><h2>Việc chờ phân công</h2></div><span>{waiting.length} việc{dismissed.length > 0 ? ` · ${dismissed.length} đã hoãn` : ''}{doneElsewhere.length > 0 ? ` · ${doneElsewhere.length} đã làm rồi` : ''}</span></div>
      {error != null && <ErrorNotice error={error} />}
      {waiting.length === 0 && dismissed.length === 0 && doneElsewhere.length === 0 ? <div className="panel"><EmptyState icon={<Inbox size={20} />} title="Không có việc nào đang chờ" text="Việc chưa xong trong báo cáo ngày đã xác nhận sẽ tự hiện ở đây. Bấm 'Thêm việc vào kế hoạch' để đưa thêm việc." /></div> : (
        <div className="panel waiting-list">
          {waiting.length === 0 && <p className="field-help waiting-empty">Không còn việc nào chờ phân công.</p>}
          {ordered.map(([key, group]) => (
            <details key={key} open={key === 'added' || group.items.length <= 4 || ordered.length === 1}>
              <summary><span className={`status waiting-source source-${group.tone}`}>{group.source}</span>{group.title}<small>{group.items.length} việc</small></summary>
              <ul>{group.items.map((candidate) => row(candidate))}</ul>
            </details>
          ))}
          {dismissed.length > 0 && (
            <details>
              <summary>Đã hoãn hôm nay, mai hiện lại<small>{dismissed.length} việc</small></summary>
              <ul>{dismissed.map((candidate) => row(candidate, true))}</ul>
            </details>
          )}
          {doneElsewhere.length > 0 && (
            <details>
              <summary>Đã làm rồi ngoài kế hoạch, chờ nghiệm thu<small>{doneElsewhere.length} việc</small></summary>
              <ul>
                {doneElsewhere.map((candidate) => {
                  const note = waitingNote(candidate)
                  return (
                    <li key={candidate.id} className="waiting-row">
                      <div>
                        <strong title={candidate.summary || undefined}>{candidate.title}</strong>
                        <WaitingMeta sourceType={candidate.source_type} intakeId={candidate.intake_id} intakePublicId={candidate.intake_public_id} priority={candidate.proposed_priority}
                          issue={candidate.gitlab_issue_external_id} issueUrl={candidate.issue_url} memberName={candidate.member_id ? nameOf(candidate.member_id) ?? null : null} originAt={candidate.origin_at}
                          tail={dotted([note.status, note.rest])} />
                      </div>
                      {candidate.gitlab_issue_external_id ? <Link className="button button-secondary button-small" to="/nghiem-thu">Nghiệm thu</Link> : <span className="muted">Không có Issue để nghiệm thu</span>}
                    </li>
                  )
                })}
              </ul>
              <p className="field-help">Việc ghi "Đã làm rồi" không quay lại danh sách chờ; Issue của nó nằm ở Nghiệm thu với ghi chú ai làm. Chấp nhận ở đó thì Issue đóng.</p>
            </details>
          )}
        </div>
      )}
      {cancelling && <DoneElsewhereDialog runId={run.id} candidateId={cancelling.id} title={cancelling.title} onDone={() => { setCancelling(null); onChanged() }} onCancel={() => setCancelling(null)} />}
    </section>
  )
}

function SyncJobPanel({ syncStatus, onChanged, onError }: { syncStatus: PlanningRunSyncStatus; onChanged: () => void; onError: (error: unknown) => void }) {
  const retryMutation = useMutation({
    mutationFn: (jobId: string) => api(`/planning/runs/${syncStatus.planning_run_id}/sync-jobs/${jobId}/retry`, { method: 'POST' }),
    onMutate: () => onError(undefined),
    onSuccess: onChanged,
    onError,
  })
  const active = syncStatus.jobs.filter((job) => ['PENDING', 'RUNNING', 'RETRY'].includes(job.status)).length
  return (
    <section className="planning-section sync-job-section">
      <div className="planning-section-title"><div><h2>Đồng bộ theo từng Issue</h2></div><span>{active > 0 ? `${active} job đang xử lý` : `${syncStatus.jobs.length} job đã kết thúc`}</span></div>
      <div className="sync-job-grid">
        {syncStatus.jobs.map((job) => {
          const retryable = job.status === 'FAILED' && job.attempt < job.max_attempts
          return <article className={`sync-job-card sync-job-${job.status.toLowerCase()}`} key={job.id}>
            <div className="sync-job-head"><strong>GitLab #{job.gitlab_issue_external_id}</strong><span>{job.status}</span></div>
            <p>Lần thử {job.attempt}/{job.max_attempts}{job.next_attempt_at ? ` · tiếp theo ${formatDate(job.next_attempt_at)}` : ''}</p>
            {job.error_code && <code>{job.error_code}</code>}
            {retryable && <button className="button button-secondary button-small" onClick={() => retryMutation.mutate(job.id)} disabled={retryMutation.isPending}>{retryMutation.isPending ? 'Đang enqueue…' : 'Thử lại đồng bộ'}</button>}
          </article>
        })}
      </div>
    </section>
  )
}

const planningWarningLabels: Record<string, string> = {
  REPORT_MISSING: 'Chưa có báo cáo ngày hôm trước',
  REPORT_IDENTITY_UNMAPPED: 'Chưa khai báo email gửi báo cáo',
  REPORT_AI_UNREVIEWED: 'Báo cáo do AI đọc, chưa được xác nhận',
  REPORT_MALFORMED: 'Báo cáo sai mẫu',
  REPORT_LATE: 'Báo cáo gửi muộn',
  REPORT_BLOCKER: 'Báo cáo có việc bị chặn',
  GITLAB_REFERENCE_NOT_FOUND: 'Báo cáo nhắc Issue không có trong danh sách',
  EMAIL_DONE_GITLAB_OPEN: 'Báo cáo ghi xong nhưng Issue còn mở',
  EMAIL_ACTIVE_GITLAB_CLOSED: 'Báo cáo ghi đang làm nhưng Issue đã đóng',
  GITLAB_MILESTONE_MISSING: 'Issue chưa có milestone',
  GITLAB_DUE_DATE_MISSING: 'Issue chưa có hạn chót',
}
const planningWarningHints: Record<string, string> = {
  REPORT_MISSING: 'Kế hoạch vẫn lập được theo Issue; chỉ thiếu thông tin từ báo cáo của những người này.',
  REPORT_IDENTITY_UNMAPPED: 'Thêm email ở Cài đặt > Nhân sự để hệ thống nhận ra báo cáo của họ.',
  REPORT_AI_UNREVIEWED: 'Task trong các báo cáo này chưa được dùng. Xác nhận ở trang Báo cáo ngày.',
  REPORT_MALFORMED: 'Nội dung đọc được chỉ để tham khảo; Issue vẫn là nguồn chính.',
  EMAIL_DONE_GITLAB_OPEN: 'Trạng thái trên Issue được ưu tiên.',
  EMAIL_ACTIVE_GITLAB_CLOSED: 'Trạng thái trên Issue được ưu tiên.',
  GITLAB_MILESTONE_MISSING: 'Vẫn chốt được; khi ghi lên GitLab, Intake chỉ gửi trường có giá trị. Bổ sung trên Issue khi tiện.',
  GITLAB_DUE_DATE_MISSING: 'Vẫn chốt được; khi ghi lên GitLab, Intake chỉ gửi trường có giá trị. Bổ sung trên Issue khi tiện.',
}

// The planner raises one warning per person or Issue. Same-kind warnings are shown as one line with the names.
function PlanningWarnings({ warnings, members, editable, acknowledged, onChange }: { warnings: PlanningWarning[]; members: WorkforceMember[]; editable: boolean; acknowledged: string[]; onChange: (ids: string[]) => void }) {
  const groups = warnings.reduce<Record<string, PlanningWarning[]>>((all, warning) => ({ ...all, [warning.code]: [...(all[warning.code] || []), warning] }), {})
  const detail = (warning: PlanningWarning) => warning.message.match(/#[\w-]+/)?.[0] || warning.message.match(/'([^']+)'/)?.[1] || ''
  return (
    <section className="warning-stack">
      <div className="planning-section-title"><div><h2>Cảnh báo cần xem</h2></div><span>{Object.keys(groups).length} loại · {warnings.length} trường hợp</span></div>
      {Object.entries(groups).map(([code, items]) => {
        const open = items.filter((warning) => !warning.acknowledged_at)
        const checked = items.every((warning) => warning.acknowledged_at || acknowledged.includes(warning.id))
        const ids = open.map((warning) => warning.id)
        const who = Array.from(new Set(items.map((warning) => {
          const name = members.find((member) => member.id === warning.member_id)?.display_name
          const extra = detail(warning)
          return name && extra ? `${name} (${extra})` : name || extra
        }).filter(Boolean)))
        return (
          <label className={`planning-warning warning-${items.some((warning) => warning.severity !== 'WARNING') ? 'critical' : 'warning'}`} key={code} title={code}>
            <input type="checkbox" aria-label={`Đã xem: ${planningWarningLabels[code] || code}`} checked={checked} disabled={!editable || open.length === 0}
              onChange={(e) => onChange(e.target.checked ? Array.from(new Set([...acknowledged, ...ids])) : acknowledged.filter((id) => !ids.includes(id)))} />
            <span>
              <strong>{planningWarningLabels[code] || code}{items.length > 1 ? ` · ${items.length}` : ''}{planningWarningHints[code] && <InfoTip label={`Giải thích: ${planningWarningLabels[code] || code}`} text={planningWarningHints[code]} />}</strong>
              <span className="warning-who" title={who.length > 0 ? who.join(', ') : items[0].message}>{who.length > 0 ? who.join(', ') : items[0].message}</span>
            </span>
            <em>{checked ? 'Đã xem' : 'Chưa xem'}</em>
          </label>
        )
      })}
    </section>
  )
}

// The day's plan as plain text, one block per person, ready to paste into a chat.
function planAsText(run: PlanningRun, members: WorkforceMember[], projects: Project[]) {
  const scope = projects.filter((project) => run.project_ids.includes(project.id))
  const lines = [`Kế hoạch ngày ${formatDay(run.plan_date)}${scope.length === 1 ? ` · ${scope[0].name}` : ''}${['DRAFT', 'REVIEW_REQUIRED'].includes(run.status) ? ' (chưa chốt)' : ''}`]
  const people = Array.from(new Set(run.assignments.map((assignment) => assignment.member_id)))
    .map((id) => ({ id, name: members.find((member) => member.id === id)?.display_name || 'Chưa rõ tên' }))
    .sort((a, b) => a.name.localeCompare(b.name, 'vi'))
  for (const person of people) {
    const work = run.assignments.filter((assignment) => assignment.member_id === person.id).sort((a, b) => Number(a.slot !== 'MORNING') - Number(b.slot !== 'MORNING'))
    lines.push('', `${person.name} (${hoursText(work.reduce((sum, assignment) => sum + assignment.planned_hours, 0))})`)
    for (const assignment of work) {
      const title = assignment.title || run.candidates.find((candidate) => candidate.assignment_id === assignment.id)?.title || ''
      const project = scope.length > 1 ? projects.find((entry) => entry.id === assignment.project_id)?.name : ''
      lines.push(`- ${assignment.slot === 'MORNING' ? 'Sáng' : 'Chiều'} · ${hoursText(assignment.planned_hours)} · ${project ? `[${project}] ` : ''}#${assignment.gitlab_issue_external_id || '?'} ${title}`.trimEnd())
    }
  }
  return lines.join('\n')
}

const runStatusLabels: Record<string, string> = {
  DRAFT: 'Đang xếp', REVIEW_REQUIRED: 'Đang xếp', APPROVED: 'Đã chốt', SYNCING: 'Đã chốt, đang ghi lên Issue', SYNCED: 'Đã chốt và ghi lên Issue',
  PARTIAL: 'Đã chốt, ghi lên Issue chưa đủ', SYNC_FAILED: 'Đã chốt, ghi lên Issue lỗi', SUPERSEDED: 'Đã thay bằng bản mới',
}
// Short marks for warnings that are about one piece of work or one person; the full list sits next to "Chốt kế hoạch".
const warningMarks: Record<string, string> = {
  GITLAB_MILESTONE_MISSING: 'Thiếu milestone', GITLAB_DUE_DATE_MISSING: 'Thiếu hạn chót',
  REPORT_MISSING: 'Chưa có báo cáo', REPORT_AI_UNREVIEWED: 'Báo cáo chờ xác nhận', REPORT_MALFORMED: 'Báo cáo sai mẫu', REPORT_LATE: 'Báo cáo muộn',
  REPORT_BLOCKER: 'Có việc bị chặn', REPORT_IDENTITY_UNMAPPED: 'Chưa có email báo cáo',
}

type BoardMove = { dragging: string | null; target: string | null; pending: string | null; start: (id: string) => void; end: () => void; over: (cell: string | null) => void; move: (id: string, slot: PlanningSlot, memberId: string) => void; unassign: (id: string) => void }

type BoardMoveRequest = { id: string; slot: PlanningSlot; memberId: string; overrideReason?: string }

// The plan as a board: one row per person with the hours they have left, and their morning and afternoon side by side.
// Capacity is not a separate block; it is the first cell of each row.
const workStatusWords: Record<WorkStatus, string> = { PLANNED: 'Chưa bắt đầu', IN_PROGRESS: 'Đang làm', DONE: 'Xong', BLOCKED: 'Bị chặn' }

// Where a placed piece of work stands, set from the web (FR-PLAN-34). A closed plan still takes a status.
function WorkStatusPicker({ runId, assignmentId, value, note, onChanged }: { runId: string; assignmentId: string; value: WorkStatus; note: string | null; onChanged: () => void }) {
  const [said, setSaid] = useState<string | null>(null)
  const change = useMutation({
    mutationFn: (status: WorkStatus) => api<WorkStatusResult>(`/planning/runs/${runId}/assignments/${assignmentId}/work-status`, { method: 'PATCH', body: JSON.stringify({ status }) }),
    onSuccess: (result) => { setSaid(result.acceptance_queued ? 'Đã vào Nghiệm thu' : null); onChanged() },
    onError: (error) => setSaid(formatError(error)),
  })
  return (
    <span className={`work-status-pick work-${value.toLowerCase()}`} title={note || undefined}>
      <select aria-label="Trạng thái việc" value={value} disabled={change.isPending} onChange={(event) => change.mutate(event.target.value as WorkStatus)}>
        {(Object.keys(workStatusWords) as WorkStatus[]).map((key) => <option key={key} value={key}>{workStatusWords[key]}</option>)}
      </select>
      {said && <small>{said}</small>}
    </span>
  )
}

function planningIntakeCardId(publicId: string) {
  return `planning-intake-${publicId.replace(/[^a-zA-Z0-9_-]/g, '-')}`
}

function PlanBoard({ run, rows, members, editable, onEditHours, moving, onStatus, focusedIntake, onFocusIntake }: {
  run?: PlanningRun; rows: DailyCapacity[]; members: WorkforceMember[]; editable: boolean; onEditHours: (memberId: string) => void; moving: BoardMove; onStatus?: () => void
  focusedIntake: string | null; onFocusIntake: (publicId: string) => void
}) {
  const assignments = run?.assignments || []
  const warnings = run?.warnings || []
  // Someone with work in the plan but outside the scope's team still gets a row, so no work is hidden.
  const people = [
    ...rows.map((row) => ({ id: row.member_id, name: row.display_name, capacity: row as DailyCapacity | undefined })),
    ...Array.from(new Set(assignments.map((assignment) => assignment.member_id))).filter((id) => !rows.some((row) => row.member_id === id))
      .map((id) => ({ id, name: members.find((member) => member.id === id)?.display_name || 'Chưa rõ tên', capacity: undefined })),
  ]
  const slots: PlanningSlot[] = ['MORNING', 'AFTERNOON']
  const slotHours = (slot: PlanningSlot) => assignments.filter((assignment) => assignment.slot === slot).reduce((sum, assignment) => sum + assignment.planned_hours, 0)
  const dragged = assignments.find((assignment) => assignment.id === moving.dragging)
  return (
    <div className="panel plan-board" role="table" aria-label="Kế hoạch theo người">
      <div className="plan-board-head" role="row">
        <span role="columnheader">Người làm</span>
        {slots.map((slot) => <span role="columnheader" key={slot}>{slot === 'MORNING' ? <Sun size={15} aria-hidden="true" /> : <Moon size={15} aria-hidden="true" />}{slot === 'MORNING' ? 'Buổi sáng' : 'Buổi chiều'}<small>{hoursText(slotHours(slot))}</small></span>)}
      </div>
      {people.map((person) => {
        const mine = assignments.filter((assignment) => assignment.member_id === person.id)
        const used = mine.reduce((sum, assignment) => sum + assignment.planned_hours, 0) + (person.capacity?.planned_elsewhere_hours || 0)
        const total = person.capacity?.available_hours
        const left = total == null ? null : total - used
        const row = person.capacity
        const notes = row ? [
          row.override_hours == null ? (row.base_hours === 0 ? (row.is_cto ? '' : 'Ngày nghỉ') : '') : row.override_hours === 0 ? 'Nghỉ cả ngày' : row.override_hours > row.base_hours ? `Làm thêm: ${hoursText(row.override_hours)}` : `Làm ${hoursText(row.override_hours)} thay vì ${hoursText(row.base_hours)}`,
          busyHours(row) > 0 ? `bận ${hoursText(busyHours(row))}` : '',
          row.personal_hours > 0 ? `${hoursText(row.personal_hours)} việc riêng` : '',
          row.planned_elsewhere_hours > 0 ? (row.planned_elsewhere && row.planned_elsewhere.length > 0 ? row.planned_elsewhere.map((other) => `${other.project_name} ${hoursText(other.hours)}`).join(', ') : `${hoursText(row.planned_elsewhere_hours)} ở dự án khác`) : '',
        ].filter(Boolean) : ['ngoài đội của phạm vi này']
        const marks = Array.from(new Set(warnings.filter((warning) => !warning.assignment_id && warning.member_id === person.id).map((warning) => warningMarks[warning.code]).filter(Boolean)))
        return (
          <div className="plan-board-row" role="row" key={person.id}>
            <div className="plan-person" role="rowheader">
              <strong>{person.name}{row?.is_owner && <span className="capacity-owner">Project Owner</span>}{row?.is_cto && <span className="capacity-owner" title="Hồ sơ của chính CTO: đặt giờ cho ngày muốn nhận việc">CTO</span>}</strong>
              {total != null && left != null && (
                <span className={`plan-left${total === 0 ? ' is-off' : left < 0 ? ' is-over' : left === 0 ? ' is-full' : ''}`}>
                  {total === 0 ? (row?.is_cto ? 'Chưa đặt giờ' : 'Không làm hôm nay') : left < 0 ? `quá ${hoursText(-left)} / ${hoursText(total)}` : `còn ${hoursText(left)} / ${hoursText(total)}`}
                </span>
              )}
              {(notes.length > 0 || row?.override_reason) && <small>{[...notes, row?.override_reason ? `lý do: ${row.override_reason}` : ''].filter(Boolean).join(' · ')}</small>}
              {marks.length > 0 && <span className="plan-marks">{marks.map((mark) => <span key={mark}>{mark}</span>)}</span>}
              {row && <button type="button" className="text-button plan-hours-button" onClick={() => onEditHours(person.id)}>Sửa giờ</button>}
            </div>
            {slots.map((slot) => {
              const cell = `${person.id}:${slot}`
              const items = mine.filter((assignment) => assignment.slot === slot)
              const accepts = editable && dragged != null && (dragged.member_id !== person.id || dragged.slot !== slot)
              return (
                <div role="cell" key={slot} className={`plan-cell${accepts ? ' can-drop' : ''}${accepts && moving.target === cell ? ' drop-here' : ''}`} data-slot={slot === 'MORNING' ? 'Buổi sáng' : 'Buổi chiều'}
                  onDragOver={(event) => { if (accepts) { event.preventDefault(); moving.over(cell) } }}
                  onDragLeave={() => { if (moving.target === cell) moving.over(null) }}
                  onDrop={(event) => { event.preventDefault(); if (accepts && dragged) moving.move(dragged.id, slot, person.id); moving.end() }}>
                  {items.length === 0 ? <span className="plan-empty">{accepts ? 'Thả vào đây' : '—'}</span> : items.map((assignment) => {
                    const title = assignment.title || run?.candidates.find((candidate) => candidate.assignment_id === assignment.id)?.title || assignment.source_reference
                    const cardMarks = Array.from(new Set(warnings.filter((warning) => warning.assignment_id === assignment.id).map((warning) => warningMarks[warning.code] || warning.code)))
                    const accepted = assignment.approved_assignee_external_id != null
                    return (
                      <article key={assignment.id} id={assignment.intake_public_id ? planningIntakeCardId(assignment.intake_public_id) : undefined}
                        className={`${editable ? 'plan-card movable' : 'plan-card'}${assignment.accepted_at ? ' is-accepted' : ''}${assignment.intake_public_id === focusedIntake ? ' is-focused' : ''}`}
                        tabIndex={assignment.intake_public_id ? 0 : undefined} aria-current={assignment.intake_public_id === focusedIntake ? 'true' : undefined}
                        onClick={(event) => { if (assignment.intake_public_id && !(event.target as HTMLElement).closest('a, button, select, input')) onFocusIntake(assignment.intake_public_id) }}
                        onKeyDown={(event) => { if (assignment.intake_public_id && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onFocusIntake(assignment.intake_public_id) } }}
                        draggable={editable || undefined}
                        onDragStart={(event) => { event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', assignment.id); moving.start(assignment.id) }} onDragEnd={moving.end}>
                        <div className="plan-card-top"><PriorityBadge priority={assignment.approved_priority || assignment.proposed_priority} /><strong>{assignment.gitlab_issue_external_id ? (assignment.issue_url ? <a className="ref-link" href={assignment.issue_url} target="_blank" rel="noreferrer" title="Mở Issue trên tracker">#{assignment.gitlab_issue_external_id}</a> : `#${assignment.gitlab_issue_external_id}`) : null}{assignment.gitlab_issue_external_id ? ' ' : ''}{title}</strong><span>{hoursText(assignment.planned_hours)}</span></div>
                        <div className="plan-card-meta">
                          <span>{accepted ? 'Đã chấp nhận' : 'Đề xuất'}{assignment.is_primary ? '' : ' · việc phụ'}</span>
                          {assignment.accepted_at ? <span className="plan-mark work-accepted" title={`CTO nghiệm thu ${formatDate(assignment.accepted_at)}; giờ đã xếp giữ nguyên trong bản ghi của ngày`}>Đã nghiệm thu</span>
                            : onStatus && run ? <WorkStatusPicker runId={run.id} assignmentId={assignment.id} value={assignment.work_status || 'PLANNED'} note={assignment.work_status_note} onChanged={onStatus} />
                            : assignment.work_status && assignment.work_status !== 'PLANNED' && <span className={`plan-mark work-${assignment.work_status.toLowerCase()}`} title={assignment.work_status_note || undefined}>{assignment.work_status === 'IN_PROGRESS' ? 'Đang làm' : assignment.work_status === 'DONE' ? 'Báo xong' : 'Bị chặn'}</span>}
                          {cardMarks.map((mark) => <span className="plan-mark" key={mark}>{mark}</span>)}
                          {assignment.intake_id && <Link to={`/intakes/${assignment.intake_id}`}>Intake {assignment.intake_public_id} <ArrowUpRight size={11} /></Link>}
                          {editable && <button type="button" className="text-button plan-unassign" title="Đưa việc này về Việc chờ phân công; giờ và ưu tiên giữ nguyên, người làm được giải phóng" disabled={moving.pending === assignment.id} onClick={() => moving.unassign(assignment.id)}>↩ Về chờ phân công</button>}
                          {editable && <button type="button" className="text-button" disabled={moving.pending === assignment.id} onClick={() => moving.move(assignment.id, slot === 'MORNING' ? 'AFTERNOON' : 'MORNING', person.id)}>{moving.pending === assignment.id ? 'Đang chuyển…' : slot === 'MORNING' ? 'Sang chiều →' : '← Sang sáng'}</button>}
                        </div>
                      </article>
                    )
                  })}
                </div>
              )
            })}
          </div>
        )
      })}
    </div>
  )
}

// "Tất cả dự án": the day as it stands across projects, read-only (FR-PLAN-33). Each project is a block: its plan,
// the people with work, the people still free, and what waits to be placed; a button opens that project's plan.
function OffPlanWorkList({ items }: { items: DayPlanProject['off_plan'] }) {
  if (items.length === 0) return null
  return (
    <div className="day-plan-off-plan">
      <strong>Việc phát sinh ngoài kế hoạch · {items.length}</strong>
      <p className="field-help">Kết quả thực tế trong ngày; không cộng vào giờ đã lập kế hoạch và không sửa kế hoạch đã chốt.</p>
      <ul>
        {items.map((item) => (
          <li key={item.id} className={`off-plan-row${item.accepted_at || item.review_decision !== 'PENDING' ? ' is-decided' : ''}`}>
            <div>
              <strong>{item.issue_url ? <a href={item.issue_url} target="_blank" rel="noreferrer">#{item.issue}</a> : `#${item.issue}`} {item.title}</strong>
              <small>{item.executor}{item.actual_minutes != null ? ` · ${hoursText(item.actual_minutes / 60)} thực tế` : ''}{item.deployed === true ? ' · đã triển khai' : item.deployed === false ? ' · chưa triển khai' : ''}</small>
            </div>
            <span className="waiting-actions">
              <span className={`status decision-${item.review_decision.toLowerCase()}`}>{item.accepted_at ? 'Đã nghiệm thu' : item.review_decision === 'PENDING' ? 'Chờ nghiệm thu' : item.review_decision === 'RETURNED' ? 'Đã trả lại' : 'Đã xác nhận'}</span>
              <Link className="button button-secondary button-small" to={`/intakes/${item.intake_id}`}>Intake {item.intake_public_id} <ArrowUpRight size={12} /></Link>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ProjectOffPlanWork({ date, projectId }: { date: string; projectId: string }) {
  const plans = useQuery({ queryKey: ['planning-day-plans', date], queryFn: () => api<DayPlans>(`/planning/day-plans/${date}`), refetchInterval: 60_000 })
  const items = plans.data?.projects.find((block) => block.id === projectId)?.off_plan || []
  if (plans.error != null) return <ErrorNotice error={plans.error} onRetry={() => { void plans.refetch() }} />
  return <OffPlanWorkList items={items} />
}

type ProjectOrderingControls = {
  index: number
  total: number
  busy: boolean
  dragging: boolean
  onMove: (targetIndex: number) => void
  onDragStart: (event: DragEvent<HTMLButtonElement>) => void
  onDragEnd: () => void
  onDrop: () => void
}

function DayPlanProjectBlock({ block, onOpen, collapsed, onToggle, onChanged, ordering }: { block: DayPlanProject; onOpen: (projectId: string) => void; collapsed: boolean; onToggle: () => void; onChanged: () => void; ordering?: ProjectOrderingControls }) {
  const run = block.run
  const [cancelling, setCancelling] = useState<{ id: string; title: string } | null>(null)
  // Same three actions as the project's own plan page: place it, put it off until tomorrow, or note it was done already.
  const dismiss = useMutation({
    mutationFn: (candidateId: string) => api(`/planning/runs/${run?.id}/candidates/${candidateId}/dismiss`, { method: 'POST' }),
    onSuccess: () => onChanged(),
  })
  const status = !run ? 'Chưa có kế hoạch' : runStatusLabels[run.status] || run.status
  const tone = !run ? 'none' : run.open ? 'open' : 'closed'
  // Folded, the heading still says how the day stands: who has work, who is free, what waits.
  const folded = [
    block.people.length > 0 ? `${block.people.length} người có việc` : null,
    block.free.length > 0 ? `${block.free.length} còn trống` : null,
    block.waiting.length > 0 ? `${block.waiting.length} chờ phân công` : null,
    block.off_plan.length > 0 ? `${block.off_plan.length} ngoài kế hoạch` : null,
  ].filter(Boolean).join(' · ')
  return (
    <section className={`panel day-plan-project${collapsed ? ' is-collapsed' : ''}${ordering?.dragging ? ' is-dragging' : ''}`} aria-label={block.name}
      onDragOver={ordering ? (event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'move' } : undefined}
      onDrop={ordering ? (event) => { event.preventDefault(); ordering.onDrop() } : undefined}>
      <header className="day-plan-head" onClick={onToggle}>
        <button type="button" className="day-plan-fold" aria-expanded={!collapsed} aria-label={collapsed ? `Mở rộng ${block.name}` : `Thu gọn ${block.name}`} onClick={(event) => { event.stopPropagation(); onToggle() }}>{collapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}</button>
        <div>
          <h2>{block.name}</h2>
          <small>{block.owner_name ? `Project Owner: ${block.owner_name}` : 'Chưa có Project Owner'}{run ? ` · ${run.assignments} việc · ${hoursText(run.assigned_hours)}${run.revision > 1 ? ` · bản ${run.revision}` : ''}` : ''}{run && run.unseen_warnings > 0 ? ` · ${run.unseen_warnings} cảnh báo chưa xem` : ''}</small>
        </div>
        <div className="day-plan-tools" onClick={(event) => event.stopPropagation()}>
          {collapsed && folded && <small className="day-plan-folded">{folded}</small>}
          {ordering && <span className="day-plan-order-controls" aria-label="Sắp xếp dự án">
            <button type="button" className="text-button day-plan-drag" draggable={!ordering.busy} disabled={ordering.busy} aria-label={`Kéo để sắp xếp ${block.name}`} title="Kéo để đổi thứ tự" onDragStart={ordering.onDragStart} onDragEnd={ordering.onDragEnd}><GripVertical size={15} /></button>
            <button type="button" className="text-button" disabled={ordering.busy || ordering.index === 0} aria-label={`Đưa ${block.name} lên trên`} onClick={() => ordering.onMove(ordering.index - 1)}><ArrowUp size={14} /></button>
            <button type="button" className="text-button" disabled={ordering.busy || ordering.index === ordering.total - 1} aria-label={`Đưa ${block.name} xuống dưới`} onClick={() => ordering.onMove(ordering.index + 1)}><ArrowDown size={14} /></button>
          </span>}
          <span className={`run-status plan-tone-${tone}`}>{status}</span>
          <button type="button" className="button button-secondary button-small" onClick={() => onOpen(block.id)}>{run ? 'Mở kế hoạch' : 'Lập kế hoạch'} <ArrowUpRight size={13} /></button>
        </div>
      </header>
      {collapsed ? null : <>
      {block.people.length > 0 && (
        <ul className="day-plan-people">
          {block.people.map((person) => (
            <li key={person.member_id}>
              <div className="day-plan-person"><strong>{person.name}</strong><small>{hoursText(person.planned)} / {hoursText(person.hours)}{person.elsewhere.length > 0 ? ` · ${person.elsewhere.map((row) => `${row.project_name} ${hoursText(row.hours)}`).join(', ')}` : ''}</small></div>
              <div className="day-plan-cards">
                {person.assignments.map((item) => (
                  <article key={item.id} className={`plan-card is-compact${item.accepted_at ? ' is-accepted' : ''}`}>
                    <div className="plan-card-top"><PriorityBadge priority={item.priority} /><strong title={item.title}>{item.issue ? (item.issue_url ? <a className="ref-link" href={item.issue_url} target="_blank" rel="noreferrer" title="Mở Issue trên tracker">#{item.issue}</a> : `#${item.issue}`) : null}{item.issue ? ' ' : ''}{item.title}</strong><span className="plan-card-hours">{hoursText(item.hours)}</span></div>
                    <div className="plan-card-meta">
                      <span>{item.slot === 'MORNING' ? 'Sáng' : 'Chiều'}{item.accepted ? '' : ' · đề xuất'}</span>
                      {item.accepted_at ? <span className="plan-mark work-accepted" title={`CTO nghiệm thu ${formatDate(item.accepted_at)}`}>Đã nghiệm thu</span> : item.work_status !== 'PLANNED' && <span className={`plan-mark work-${item.work_status.toLowerCase()}`}>{item.work_status === 'IN_PROGRESS' ? 'Đang làm' : item.work_status === 'DONE' ? 'Báo xong' : 'Bị chặn'}</span>}
                      {item.intake_id && <Link to={`/intakes/${item.intake_id}`}>Intake {item.intake_public_id} <ArrowUpRight size={11} /></Link>}
                    </div>
                  </article>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
      {(block.free.length > 0 || block.off.length > 0) && (
        <p className="day-plan-free">
          {block.free.length > 0 && <span>Còn trống: {block.free.map((person) => `${person.name} ${hoursText(person.hours)}${person.elsewhere.length > 0 ? ` (${person.elsewhere.map((row) => `${row.project_name} ${hoursText(row.hours)}`).join(', ')})` : ''}`).join(', ')}</span>}
          {block.off.length > 0 && <span className="muted">Nghỉ: {block.off.join(', ')}</span>}
        </p>
      )}
      {block.people.length === 0 && block.free.length === 0 && block.off.length === 0 && <p className="day-plan-free muted">Dự án chưa có nhân sự.</p>}
      {block.waiting.length > 0 && (
        <div className="day-plan-waiting">
          <strong>Chờ phân công · {block.waiting.length}</strong>
          <ul>
            {block.waiting.map((item) => (
              <li key={item.id} className="waiting-row">
                <div>
                  <strong title={item.summary || undefined}>{item.title}</strong>
                  <WaitingMeta sourceType={item.source_type} intakeId={item.intake_id} intakePublicId={item.intake_public_id} priority={item.priority} issue={item.issue} issueUrl={item.issue_url} memberName={item.member_name} originAt={item.origin_at} />
                </div>
                <span className="waiting-actions">
                  <button type="button" className="button button-primary button-small" onClick={() => onOpen(block.id)}>Xếp việc</button>
                  <button type="button" className="button button-secondary button-small" title={run ? 'Hôm nay không xếp việc này; ngày mai nó hiện lại nếu Issue còn mở' : 'Lập kế hoạch ngày trước rồi mới hoãn được'} disabled={!run || dismiss.isPending} onClick={() => dismiss.mutate(item.id)}>Hoãn</button>
                  <button type="button" className="button button-secondary button-small" title={run ? 'Việc này đã làm xong ngoài kế hoạch: ghi ai làm, rồi bỏ khỏi danh sách chờ và đưa Issue vào Nghiệm thu' : 'Lập kế hoạch ngày trước rồi mới ghi được'} disabled={!run} onClick={() => setCancelling({ id: item.id, title: item.title })}>Đã làm rồi</button>
                </span>
              </li>
            ))}
          </ul>
          {dismiss.error != null && <ErrorNotice error={dismiss.error} />}
        </div>
      )}
      <OffPlanWorkList items={block.off_plan} />
      </>}
      {cancelling && run && <DoneElsewhereDialog runId={run.id} candidateId={cancelling.id} title={cancelling.title} onDone={() => { setCancelling(null); onChanged() }} onCancel={() => setCancelling(null)} />}
    </section>
  )
}

const FOLDED_KEY = 'intake-day-plans-folded'

// A waiting entry that was done already, outside the plan: a note, then off the list and into acceptance (FR-PLAN-34).
function DoneElsewhereDialog({ runId, candidateId, title, onDone, onCancel }: { runId: string; candidateId: string; title: string; onDone: () => void; onCancel: () => void }) {
  const [note, setNote] = useState('')
  const mark = useMutation({
    mutationFn: () => api<PlanningCandidate & { acceptance_queued: boolean }>(`/planning/runs/${runId}/candidates/${candidateId}/done`, { method: 'POST', body: JSON.stringify({ note: note.trim() }) }),
    onSuccess: onDone,
  })
  return (
    <ConfirmDialog title="Việc đã làm ngoài kế hoạch" confirmLabel="Ghi là đã làm" busyLabel="Đang ghi…" busy={mark.isPending} error={mark.error} plain onConfirm={() => { if (note.trim().length >= 3) mark.mutate() }} onCancel={onCancel}>
      <p><strong>{title}</strong></p>
      <p>Việc đã làm rồi nhưng chưa tổng hợp? Ghi ai làm, làm khi nào. Việc rời danh sách chờ; nếu có Issue thì vào Nghiệm thu, CTO xác nhận là Issue được đóng kèm đúng ghi chú này, nên ngày sau không hiện lại. Chỉ muốn hôm nay không xếp thì bấm "Hoãn" thay vì nút này.</p>
      <label className="done-note">Ghi chú<textarea rows={3} value={note} autoFocus onChange={(event) => setNote(event.target.value)} placeholder="vd. Nam đã làm hôm qua, chưa kịp báo" /></label>
      {note.trim().length > 0 && note.trim().length < 3 && <small className="field-help">Ghi chú cần ít nhất 3 ký tự.</small>}
    </ConfirmDialog>
  )
}

function DayPlansOverview({ date, onOpen }: { date: string; onOpen: (projectId: string) => void }) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [view, setView] = useState<'projects' | 'people'>('projects')
  const plans = useQuery({ queryKey: ['planning-day-plans', date], queryFn: () => api<DayPlans>(`/planning/day-plans/${date}`), refetchInterval: 60_000 })
  const [draggingProject, setDraggingProject] = useState<string | null>(null)
  const saveOrder = useMutation({
    mutationFn: (preference: PlanningProjectOrder) => api<PlanningProjectOrder>('/planning/project-order', { method: 'PUT', body: JSON.stringify(preference) }),
    onSuccess: (preference) => queryClient.setQueryData<DayPlans>(['planning-day-plans', date], (current) => current ? { ...current, project_order: preference } : current),
  })
  // Which projects this browser keeps folded; a project not listed is open.
  const [folded, setFolded] = useState<string[]>(() => { try { return JSON.parse(localStorage.getItem(FOLDED_KEY) || '[]') as string[] } catch { return [] } })
  const remember = (next: string[]) => { setFolded(next); try { localStorage.setItem(FOLDED_KEY, JSON.stringify(next)) } catch { /* private window */ } }
  const toggle = (projectId: string) => remember(folded.includes(projectId) ? folded.filter((id) => id !== projectId) : [...folded, projectId])
  if (plans.error != null) return <ErrorNotice error={plans.error} onRetry={() => { void plans.refetch() }} />
  if (plans.isLoading || !plans.data) return <LoadingBlock />
  const totals = plans.data.totals
  const preference = plans.data.project_order || { mode: 'PRIORITY' as const, project_ids: [] }
  const orderedProjects = orderPlanningProjects(plans.data.projects, preference, user?.role === 'CTO')
  const ids = orderedProjects.map((block) => block.id)
  const allFolded = ids.length > 0 && ids.every((id) => folded.includes(id))
  const changeMode = (mode: PlanningProjectOrder['mode']) => {
    const projectIds = mode === 'CUSTOM' ? orderPlanningProjects(plans.data.projects, { mode: 'PRIORITY', project_ids: [] }, user?.role === 'CTO').map((block) => block.id) : []
    saveOrder.mutate({ mode, project_ids: projectIds })
  }
  const reorder = (projectId: string, targetIndex: number) => {
    const next = movePlanningProject(ids, projectId, targetIndex)
    if (next !== ids) saveOrder.mutate({ mode: 'CUSTOM', project_ids: next })
  }
  return (
    <>
      <p className="day-plan-totals">
        <span><strong>{totals.unclosed}</strong>/{totals.projects} dự án chưa chốt</span><span><strong>{totals.free_people}</strong> người còn trống · {hoursText(totals.free_hours)}</span><span><strong>{totals.waiting}</strong> việc chờ phân công</span>{totals.off_plan > 0 && <span><strong>{totals.off_plan}</strong> ngoài kế hoạch{totals.off_plan_actual_minutes > 0 ? ` · ${hoursText(totals.off_plan_actual_minutes / 60)} thực tế` : ''}</span>}<span className="muted">Tổng quan chỉ đọc: xếp và chốt trong từng dự án.</span>
        <span className="day-plan-views"><button type="button" className={view === 'projects' ? 'active' : undefined} onClick={() => setView('projects')}>Theo dự án</button><button type="button" className={view === 'people' ? 'active' : undefined} onClick={() => setView('people')}>Theo người</button></span>
        {view === 'projects' && <span className="day-plan-sort"><label>Thứ tự <select value={preference.mode} disabled={saveOrder.isPending} onChange={(event) => changeMode(event.target.value as PlanningProjectOrder['mode'])}><option value="PRIORITY">Ưu tiên xử lý</option><option value="CUSTOM">Tùy chỉnh</option></select></label>{preference.mode === 'CUSTOM' && <button type="button" className="text-button" disabled={saveOrder.isPending} onClick={() => changeMode('PRIORITY')}><RotateCcw size={13} /> Khôi phục ưu tiên</button>}</span>}
        {view === 'projects' && ids.length > 1 && <button type="button" className="text-button day-plan-fold-all" onClick={() => remember(allFolded ? [] : ids)}>{allFolded ? 'Mở rộng tất cả' : 'Thu gọn tất cả'}</button>}
      </p>
      {saveOrder.error != null && <ErrorNotice error={saveOrder.error} />}
      {view === 'people' ? <div className="panel"><PeopleBoard day={date} /></div> : orderedProjects.length === 0 ? <div className="panel"><EmptyState icon={<CalendarDays size={20} />} title="Chưa có dự án phần mềm" text="Thêm dự án ở Cài đặt > Dự án." /></div> : orderedProjects.map((block, index) => <DayPlanProjectBlock key={block.id} block={block} onOpen={onOpen} collapsed={folded.includes(block.id)} onToggle={() => toggle(block.id)} onChanged={() => { void plans.refetch() }} ordering={preference.mode === 'CUSTOM' ? {
        index, total: orderedProjects.length, busy: saveOrder.isPending, dragging: draggingProject === block.id,
        onMove: (targetIndex) => reorder(block.id, targetIndex),
        onDragStart: (event) => { event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', block.id); setDraggingProject(block.id) },
        onDragEnd: () => setDraggingProject(null),
        onDrop: () => { if (draggingProject) reorder(draggingProject, index); setDraggingProject(null) },
      } : undefined} />)}
    </>
  )
}

function PlanningPage() {
  const { text } = useLocale()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const { user } = useAuth()
  const isCto = user?.role === 'CTO'
  const [copiedPlan, setCopiedPlan] = useState(false)
  const [planDate, setPlanDate] = useState(() => { const linked = searchParams.get('date'); return linked && /^\d{4}-\d{2}-\d{2}$/.test(linked) ? linked : todayInPlanningTimezone() })
  const [projectScope, setProjectScope] = useState(() => searchParams.get('project') || 'ALL')
  const focusedIntake = searchParams.get('intake')
  const [runId, setRunId] = useState('')
  const [actionError, setActionError] = useState<unknown>()
  const [acknowledged, setAcknowledged] = useState<string[]>([])
  const [panel, setPanel] = useState<{ kind: 'add' } | { kind: 'assign'; candidateId: string } | { kind: 'capacity'; memberId: string } | null>(null)
  const { setRightPanel } = useShell()
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const members = useQuery({ queryKey: ['planning-members'], queryFn: () => api<WorkforceMember[]>('/planning/members') })
  const capacities = useQuery({ queryKey: ['planning-capacities', planDate, projectScope], queryFn: () => api<DailyCapacity[]>(`/planning/capacities/${planDate}${projectScope === 'ALL' ? '' : `?project_id=${projectScope}`}`), enabled: projectScope !== 'ALL' })
  const runQuery = useQuery({
    queryKey: ['planning-run', runId],
    queryFn: () => api<PlanningRun>(`/planning/runs/${runId}`),
    enabled: Boolean(runId),
  })
  const syncQuery = useQuery({
    queryKey: ['planning-sync-jobs', runId],
    queryFn: () => api<PlanningRunSyncStatus>(`/planning/runs/${runId}/sync-jobs`),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const current = query.state.data as PlanningRunSyncStatus | undefined
      return current?.jobs.some((job) => ['PENDING', 'RUNNING', 'RETRY'].includes(job.status)) ? 5000 : false
    },
  })
  const run = runQuery.data

  const openMutation = useMutation({
    mutationFn: () => api<PlanningRun>('/planning/runs', {
      method: 'POST',
      body: JSON.stringify({ plan_date: planDate, project_ids: projectScope === 'ALL' ? [] : [projectScope], timezone: 'Asia/Ho_Chi_Minh' }),
    }),
    onMutate: () => setActionError(undefined),
    onSuccess: (opened) => {
      setRunId(opened.id)
      queryClient.setQueryData(['planning-run', opened.id], opened)
      setAcknowledged(opened.warnings.filter((warning) => warning.acknowledged_at).map((warning) => warning.id))
    },
    onError: setActionError,
  })
  const refreshRun = () => {
    if (runId) void queryClient.invalidateQueries({ queryKey: ['planning-run', runId] })
  }
  const refreshSync = () => {
    if (runId) void queryClient.invalidateQueries({ queryKey: ['planning-sync-jobs', runId] })
    refreshRun()
  }
  const acceptMutation = useMutation({
    mutationFn: () => api<PlanningRun>(`/planning/runs/${run?.id}/accept-proposals`, { method: 'POST', body: JSON.stringify({ expected_version: run?.version }) }),
    onMutate: () => setActionError(undefined), onSuccess: (updated) => queryClient.setQueryData(['planning-run', updated.id], updated), onError: setActionError,
  })
  const approveMutation = useMutation({
    mutationFn: (ids: string[]) => api(`/planning/runs/${run?.id}/approve`, { method: 'POST', body: JSON.stringify({ expected_version: run?.version, acknowledged_warning_ids: ids, override_reason: null }) }),
    onMutate: () => setActionError(undefined), onSuccess: refreshSync, onError: setActionError,
  })
  // A closed plan reopened as a new revision (FR-PLAN-18): the page moves to the new one, the old stays readable.
  const reopenMutation = useMutation({
    mutationFn: () => api<PlanningRun>(`/planning/runs/${run?.id}/reopen`, { method: 'POST', body: JSON.stringify({ expected_version: run?.version }) }),
    onMutate: () => setActionError(undefined),
    onSuccess: (opened) => {
      setRunId(opened.id)
      queryClient.setQueryData(['planning-run', opened.id], opened)
      setAcknowledged(opened.warnings.filter((warning) => warning.acknowledged_at).map((warning) => warning.id))
    },
    onError: setActionError,
  })
  const reopenPlan = () => {
    if (!run) return
    if (!window.confirm(`Mở lại kế hoạch ngày ${formatDay(run.plan_date)} thành bản ${run.revision + 1} để sửa? Bản đã chốt vẫn được giữ. Khi chốt lại, chỉ Issue có thay đổi mới được ghi lên GitLab.`)) return
    reopenMutation.mutate()
  }
  // A missing milestone or due date is something the person closing must have seen, not a reason to stop (ADR-0013):
  // closing asks once and marks those warnings seen, instead of sending people to find the checkbox.
  const closePlan = () => {
    const fieldIds = (run?.warnings || []).filter((warning) => ['GITLAB_MILESTONE_MISSING', 'GITLAB_DUE_DATE_MISSING'].includes(warning.code) && !warning.acknowledged_at).map((warning) => warning.id)
    const unseen = fieldIds.filter((id) => !acknowledged.includes(id))
    if (unseen.length > 0 && !window.confirm(`${unseen.length} việc có Issue thiếu milestone hoặc hạn chót. Vẫn chốt kế hoạch? Khi ghi lên GitLab, Intake chỉ gửi trường có giá trị.`)) return
    const ids = Array.from(new Set([...acknowledged, ...fieldIds]))
    setAcknowledged(ids)
    approveMutation.mutate(ids)
  }
  const mutable = Boolean(run && ['DRAFT', 'REVIEW_REQUIRED'].includes(run.status))
  // The CTO closes any plan; a Project Owner closes the plan of a project of theirs (FR-PLAN-25).
  const canClose = isCto || projectScope !== 'ALL'
  // Dragging can change the person, the half of the day, or both; the buttons keep the same person and change only the half.
  const [dragging, setDragging] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null)
  const [moveError, setMoveError] = useState<string>()
  const [overrideMove, setOverrideMove] = useState<(BoardMoveRequest & { code: string })>()
  const moveAssignment = useMutation({
    mutationFn: ({ id, slot, memberId, overrideReason }: BoardMoveRequest) => api<PlanningRun>(`/planning/runs/${run?.id}/assignments/${id}/move`, { method: 'POST', body: JSON.stringify({ expected_run_version: run?.version, slot, member_id: memberId, override_reason: overrideReason }) }),
    onMutate: () => setMoveError(undefined),
    onSuccess: (updated) => { setOverrideMove(undefined); queryClient.setQueryData(['planning-run', updated.id], updated) },
    onError: (error, variables) => {
      const code = error instanceof ApiError ? error.code : undefined
      if (!variables.overrideReason && code && ['OVER_CAPACITY', 'SLOT_OVER_CAPACITY', 'MULTIPLE_PRIMARY_DOING'].includes(code)) {
        setOverrideMove({ ...variables, code })
        return
      }
      setMoveError(code === 'SLOT_OVER_CAPACITY' ? 'Không chuyển được: buổi đó của người nhận sẽ quá 4 giờ.'
        : code === 'OVER_CAPACITY' ? 'Không chuyển được: người nhận không còn đủ giờ trong ngày.'
          : code === 'MULTIPLE_PRIMARY_DOING' ? 'Không chuyển được: người nhận đã có một việc phát triển chính khác.'
            : code === 'GITLAB_ASSIGNEE_REQUIRED' ? 'Không chuyển được: người nhận chưa được liên kết với tài khoản GitLab của dự án.'
              : code === 'MEMBER_NOT_IN_PROJECT' ? 'Không chuyển được: người nhận không còn thuộc dự án này.'
                : code === 'PLANNING_VERSION_CONFLICT' ? 'Kế hoạch vừa được người khác sửa. Tải lại trang rồi thử lại.' : formatError(error))
      refreshRun()
    },
  })
  // Something more urgent came up: the placed work goes back to the waiting list while the day is still open.
  const unassignAssignment = useMutation({
    mutationFn: (id: string) => api<PlanningRun>(`/planning/runs/${run?.id}/assignments/${id}/unassign`, { method: 'POST', body: JSON.stringify({ expected_run_version: run?.version }) }),
    onMutate: () => setMoveError(undefined),
    onSuccess: (updated) => queryClient.setQueryData(['planning-run', updated.id], updated),
    onError: (error) => {
      const code = error instanceof ApiError ? error.code : undefined
      setMoveError(code === 'PLANNING_VERSION_CONFLICT' ? 'Kế hoạch vừa được người khác sửa; đã tải lại.' : code === 'PLANNING_RUN_IMMUTABLE' ? 'Kế hoạch đã chốt, không đưa việc về chờ phân công được.' : formatError(error))
      refreshRun()
    },
  })
  const openRunId = run?.id
  const panelKind = panel?.kind
  const panelCandidate = panel?.kind === 'assign' ? panel.candidateId : undefined
  const panelMember = panel?.kind === 'capacity' ? panel.memberId : undefined
  useEffect(() => {
    if (!panelMember) return
    const close = () => setPanel(null)
    setRightPanel({ title: 'Giờ làm trong ngày', content: <CapacityEditPanel key={`${panelMember}-${planDate}`} workDate={planDate} scope={projectScope} memberId={panelMember} onDone={close} />, onClose: close })
    return () => setRightPanel(null)
  }, [panelMember, planDate, projectScope, setRightPanel])
  useEffect(() => {
    if (!panelKind || panelKind === 'capacity' || !openRunId || !mutable) return
    const close = () => setPanel(null)
    setRightPanel(panelKind === 'assign' && panelCandidate
      ? { title: 'Xếp việc vào kế hoạch', content: <AssignWorkPanel key={panelCandidate} runId={openRunId} candidateId={panelCandidate} canApprove onDone={close} />, onClose: close }
      : { title: 'Thêm việc vào kế hoạch', content: <AddWorkPanel key={openRunId} runId={openRunId} canApprove />, onClose: close })
    return () => setRightPanel(null)
  }, [panelKind, panelCandidate, openRunId, mutable, setRightPanel])
  const hasUnaccepted = Boolean(run?.assignments.some((assignment) => assignment.proposed_priority && !assignment.approved_priority))
  const projectList = projects.data || []
  const softwareIds = new Set(projectList.filter((project) => project.kind === 'SOFTWARE' && project.status === 'ACTIVE').map((project) => project.id))
  const unassignedCount = (members.data || []).filter((member) => !member.project_mappings.some((mapping) => mapping.active && softwareIds.has(mapping.project_id))).length
  const memberList = members.data || []
  const plannable = projectList.filter((project) => project.kind === 'SOFTWARE')
  // A Project Owner plans one of their own projects; "all projects" is the CTO's view.
  // "All projects" is a read-only overview (FR-PLAN-33) for the CTO and for a Project Owner alike; nothing is
  // opened or edited there, and a Project Owner's overview holds only their projects.
  const scopeMissing = false
  const overview = projectScope === 'ALL'
  const firstOwn = plannable[0]?.id
  void firstOwn
  const capacityRows = capacities.data || []
  const plannedHere = (run?.assignments || []).reduce<Record<string, number>>((hours, assignment) => ({ ...hours, [assignment.member_id]: (hours[assignment.member_id] || 0) + assignment.planned_hours }), {})
  const capacityTotal = capacityRows.reduce((sum, row) => sum + row.available_hours, 0)
  const capacityLeft = capacityRows.reduce((sum, row) => sum + Math.max(row.available_hours - row.planned_elsewhere_hours - (plannedHere[row.member_id] || 0), 0), 0)

  // The plan of the chosen day and scope opens by itself; choosing another day or scope opens that one.
  const wanted = `${planDate}|${projectScope}`
  const opened = useRef('')
  const openPlan = openMutation.mutate
  const waitingForProjects = projects.isLoading
  useEffect(() => {
    if (waitingForProjects || scopeMissing || overview || runId || opened.current === wanted) return
    opened.current = wanted
    openPlan()
  }, [wanted, waitingForProjects, scopeMissing, overview, runId, openPlan])
  const updatePlanningUrl = (date: string, project: string, intake: string | null) => {
    const next = new URLSearchParams()
    next.set('date', date)
    if (project !== 'ALL') next.set('project', project)
    if (intake) next.set('intake', intake)
    setSearchParams(next, { replace: true })
  }
  const openProject = (projectId: string) => { setProjectScope(projectId); setRunId(''); setPanel(null); updatePlanningUrl(planDate, projectId, null) }
  const goDay = (value: string) => { if (/^\d{4}-\d{2}-\d{2}$/.test(value)) { setPlanDate(value); setRunId(''); setPanel(null); updatePlanningUrl(value, projectScope, null) } }
  const focusIntake = (publicId: string) => updatePlanningUrl(planDate, projectScope, publicId)
  useEffect(() => {
    if (!focusedIntake || !run?.assignments.some((assignment) => assignment.intake_public_id === focusedIntake)) return
    const card = document.getElementById(planningIntakeCardId(focusedIntake))
    card?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    card?.focus({ preventScroll: true })
  }, [focusedIntake, run?.id, run?.assignments])
  const moving: BoardMove = {
    dragging, target: dropTarget, pending: moveAssignment.isPending ? moveAssignment.variables?.id || null : unassignAssignment.isPending ? unassignAssignment.variables || null : null,
    start: (id) => { setMoveError(undefined); setDragging(id) }, end: () => { setDragging(null); setDropTarget(null) }, over: setDropTarget,
    move: (id, slot, memberId) => moveAssignment.mutate({ id, slot, memberId }),
    unassign: (id) => unassignAssignment.mutate(id),
  }
  const overrideMember = overrideMove ? memberList.find((member) => member.id === overrideMove.memberId)?.display_name || 'người nhận' : ''
  const moveOverrideReason = overrideMove?.code === 'MULTIPLE_PRIMARY_DOING'
    ? 'Người xếp việc xác nhận giao thêm một việc phát triển chính'
    : overrideMove?.code === 'SLOT_OVER_CAPACITY'
      ? 'Người xếp việc xác nhận buổi làm của người nhận vượt 4 giờ'
      : 'Người xếp việc xác nhận đổi người dù vượt giới hạn giờ trong ngày'
  const warningKinds = new Set((run?.warnings || []).map((warning) => warning.code)).size
  const unseenWarnings = (run?.warnings || []).filter((warning) => !warning.acknowledged_at && !acknowledged.includes(warning.id)).length
  const approvalBar = useRef<HTMLElement>(null)
  usePinnedToPageColumn(approvalBar, Boolean(run))
  const copyPlan = () => { if (run) void navigator.clipboard.writeText(planAsText(run, memberList, projectList)).then(() => { setCopiedPlan(true); window.setTimeout(() => setCopiedPlan(false), 2500) }) }

  return (
    <>
      <AgentHint command="today" />
      <PageHeader title={text('Kế hoạch triển khai trong ngày', 'Daily Planning')} helper={[
        text('Mỗi người một hàng: giờ còn trống ở bên trái, việc buổi sáng và buổi chiều ở bên phải.', 'Each person has one row: available hours on the left, morning and afternoon work on the right.'),
        text('Kéo một việc sang ô của người khác để đổi người làm, hoặc sang ô còn lại để đổi buổi. Nút trên thẻ chỉ đổi buổi.', 'Drag work to another person or time slot to reassign it.'),
        text('"Tất cả dự án" là tổng quan chỉ đọc theo từng dự án; xếp và chốt trong kế hoạch của từng dự án.', '"All projects" is a read-only overview. Assign and close work inside one project plan.'),
        text('Issue trên GitLab/GitHub là nguồn chính; báo cáo ngày và Intake bổ sung ngữ cảnh.', 'GitLab or GitHub Issues are the source of truth; reports and Intake add context.'),
        text('CTO hoặc Project Owner của dự án chốt kế hoạch.', 'The CTO or Project Owner closes the plan.'),
      ]} action={mutable && !overview ? <button className="button button-primary" type="button" onClick={() => setPanel({ kind: 'add' })}><Plus size={16} /> {text('Thêm việc vào kế hoạch', 'Add work to plan')}</button> : undefined} />
      {overrideMove && (
        <ConfirmDialog plain title={`Vẫn giao việc cho ${overrideMember}?`} confirmLabel="Vẫn chuyển việc" busyLabel="Đang chuyển…" busy={moveAssignment.isPending} error={moveError} onConfirm={() => moveAssignment.mutate({ ...overrideMove, overrideReason: moveOverrideReason })} onCancel={() => { if (!moveAssignment.isPending) { setOverrideMove(undefined); setMoveError(undefined) } }}>
          <p>{overrideMove.code === 'MULTIPLE_PRIMARY_DOING' ? `${overrideMember} đã có một việc phát triển chính khác trong ngày.` : overrideMove.code === 'SLOT_OVER_CAPACITY' ? `Buổi nhận việc của ${overrideMember} sẽ vượt 4 giờ.` : `${overrideMember} không còn đủ giờ làm trong ngày.`}</p>
          <p className="field-help">Chỉ CTO hoặc Project Owner được xác nhận ngoại lệ này. Hệ thống sẽ lưu lý do vào lịch sử kế hoạch.</p>
        </ConfirmDialog>
      )}
      {/* A closed plan is past "Xếp việc": only the last step stays lit. */}
      <FlowGuide here={run && !mutable ? ['close'] : ['assign', 'close']} note={run && !mutable ? text('Kế hoạch ngày này đã chốt; người phụ trách được ghi lên từng Issue. Cần sửa thì bấm "Mở lại để sửa" ở thanh dưới: bản mới thay bản cũ, chốt lại chỉ ghi Issue có thay đổi.', 'This daily plan is closed and assignees were written to their Issues. Reopen it to create a new revision when changes are needed.') : text('Ở đây bạn giao việc đã có Issue cho từng người rồi chốt kế hoạch ngày. Chốt kế hoạch không phê duyệt yêu cầu nào; riêng việc thêm mới chưa có Issue thì được phê duyệt ngay tại khung thêm việc.', 'Assign work that already has an Issue, then close the daily plan. Closing a plan does not approve requests.')} />
      <div className="plan-bar">
        <button type="button" className="button button-secondary plan-day-step" title="Ngày trước" onClick={() => goDay(shiftDay(planDate, -1))}>← {shiftDay(planDate, -1) === todayInPlanningTimezone() ? 'Hôm nay' : planDate === todayInPlanningTimezone() ? 'Hôm qua' : shortDay(shiftDay(planDate, -1))}</button>
        <input type="date" aria-label={text('Ngày kế hoạch', 'Plan date')} value={planDate} onChange={(e) => goDay(e.target.value)} />
        <button type="button" className="button button-secondary plan-day-step" title="Ngày sau" onClick={() => goDay(shiftDay(planDate, 1))}>{shiftDay(planDate, 1) === todayInPlanningTimezone() ? 'Hôm nay' : planDate === todayInPlanningTimezone() ? 'Ngày mai' : shortDay(shiftDay(planDate, 1))} →</button>
        <select aria-label={text('Phạm vi', 'Scope')} title={text('Tất cả dự án là tổng quan chỉ đọc của cả đội; chọn một dự án để xếp và chốt kế hoạch của dự án đó.', 'All projects is a read-only team overview. Select one project to assign and close its plan.')} value={projectScope} onChange={(e) => { setProjectScope(e.target.value); setRunId(''); setPanel(null); updatePlanningUrl(planDate, e.target.value, null) }}><option value="ALL">{text('Tất cả dự án', 'All projects')}</option>{plannable.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select>
        {overview ? <span className="plan-bar-note">Tổng quan theo dự án</span> : run ? <span className={`run-status run-${run.status.toLowerCase()}`} title={`Danh sách Issue cập nhật lúc ${formatDate(run.source_snapshot_at)}`}>{runStatusLabels[run.status] || run.status}</span> : openMutation.isPending ? <span className="plan-bar-note">Đang mở kế hoạch…</span> : null}
        <span className="plan-bar-note plan-bar-right">{!overview && capacityRows.length > 0 ? `${capacityRows.length} người · còn ${hoursText(capacityLeft)} / ${hoursText(capacityTotal)}` : ''}</span>
        {run && !overview && run.warnings.length > 0 && <a className="plan-bar-warnings" href="#plan-warnings">{warningKinds} loại cảnh báo</a>}
        {run && !overview && run.assignments.length > 0 && <button className="button button-secondary" type="button" title="Chép kế hoạch theo từng người để dán vào chat" onClick={copyPlan}>{copiedPlan ? <><Check size={14} /> Đã chép</> : 'Chép kế hoạch'}</button>}
      </div>
      {actionError != null && <ErrorNotice error={actionError} onRetry={() => runId ? refreshRun() : openMutation.mutate()} />}
      {(projects.error || members.error || capacities.error || runQuery.error || syncQuery.error) && <ErrorNotice error={projects.error || members.error || capacities.error || runQuery.error || syncQuery.error} onRetry={() => { void projects.refetch(); void members.refetch(); void capacities.refetch(); if (runId) { void runQuery.refetch(); void syncQuery.refetch() } }} />}
      {moveError != null && <p className="notice notice-error" role="alert">{moveError}</p>}

      {overview ? <DayPlansOverview date={planDate} onOpen={openProject} /> : capacities.isLoading ? <LoadingBlock /> : capacityRows.length === 0 && !(run && run.assignments.length > 0) ? (
        <div className="panel"><EmptyState icon={<UserRound size={20} />} title={projectScope === 'ALL' ? 'Chưa có nhân sự nào thuộc dự án phần mềm' : 'Dự án này chưa có nhân sự'} text="Chọn Project Owner và Member ở Cài đặt > Dự án > Sửa > Nhân sự của dự án." /></div>
      ) : <PlanBoard run={run} rows={capacityRows} members={memberList} editable={mutable} onEditHours={(memberId) => setPanel({ kind: 'capacity', memberId })} moving={moving} onStatus={run ? refreshRun : undefined} focusedIntake={focusedIntake} onFocusIntake={focusIntake} />}
      {isCto && projectScope === 'ALL' && unassignedCount > 0 && <p className="field-help capacity-note">{unassignedCount} nhân sự chưa thuộc dự án phần mềm nào nên không hiện ở đây. <Link to="/settings/projects">Gán ở Cài đặt &gt; Dự án</Link>.</p>}
      {!overview && <ProjectOffPlanWork date={planDate} projectId={projectScope} />}

      {run && !overview && (
        <>
          {isCto && <VerificationList run={run} members={memberList} projects={projects.data || []} editable={mutable} onChanged={refreshRun} />}
          <WaitingList run={run} members={memberList} editable={mutable} onAssign={(candidateId) => setPanel({ kind: 'assign', candidateId })} onChanged={refreshRun} />
          {run.warnings.length > 0 && <div id="plan-warnings"><PlanningWarnings warnings={run.warnings} members={memberList} editable={mutable && canClose} acknowledged={acknowledged} onChange={setAcknowledged} /></div>}
          {syncQuery.data?.snapshot_id && <SyncJobPanel syncStatus={syncQuery.data} onChanged={refreshSync} onError={setActionError} />}
          <div className="pinned-bar-space" aria-hidden="true" />
          {canClose ? (
            <section className="panel planning-approval-bar" ref={approvalBar} aria-label="Chốt kế hoạch">
              <div className="approval-lead">
                <h2>{mutable ? text('Chốt kế hoạch', 'Close plan') : run.status === 'SUPERSEDED' ? text('Bản đã thay', 'Superseded revision') : text('Kế hoạch đã chốt', 'Plan closed')}</h2>
                <InfoTip label="Về chốt kế hoạch" text="Chấp nhận các đề xuất trước, rồi chốt. Với dự án dùng GitLab, người phụ trách, milestone và hạn chót được ghi lên từng Issue. Kế hoạch đã chốt mở lại được thành bản mới; chốt lại chỉ ghi Issue có thay đổi. Chốt kế hoạch không phê duyệt Intake nào." />
                <span className="approval-stats">{run.assignments.length} việc{run.revision > 1 ? ` · bản ${run.revision}` : ''}{mutable && unseenWarnings > 0 && <> · <a href="#plan-warnings">{unseenWarnings} cảnh báo chưa xem</a></>}</span>
              </div>
              <div>
                {!mutable && run.status !== 'SUPERSEDED' && <button className="button button-secondary" onClick={reopenPlan} disabled={reopenMutation.isPending}>{reopenMutation.isPending ? 'Đang mở lại…' : <><Pencil size={15} /> Mở lại để sửa</>}</button>}
                <button className="button button-secondary" onClick={() => acceptMutation.mutate()} disabled={!mutable || !hasUnaccepted || acceptMutation.isPending}>{acceptMutation.isPending ? text('Đang chấp nhận…', 'Accepting…') : <><Check size={15} /> {text('Chấp nhận đề xuất', 'Accept suggestions')}</>}</button><button className="button button-primary" onClick={closePlan} disabled={!mutable || hasUnaccepted || run.assignments.length === 0 || approveMutation.isPending}>{approveMutation.isPending ? text('Đang chốt…', 'Closing…') : <><ClipboardCheck size={15} /> {text('Chốt kế hoạch', 'Close plan')}</>}</button>
              </div>
            </section>
          ) : (
            <section className="panel planning-approval-bar" ref={approvalBar} aria-label="CTO chốt kế hoạch">
              <div className="approval-lead">
                <h2>{mutable ? 'CTO chốt kế hoạch' : 'Kế hoạch đã chốt'}</h2>
                <InfoTip label="Về chốt kế hoạch" text={mutable ? 'Bạn xếp việc cho đội mình; CTO xem lại và chốt. Khi xếp xong, hãy báo CTO.' : 'Kế hoạch này đã được chốt và không sửa được nữa.'} />
                <span className="approval-stats">{run.assignments.length} việc</span>
              </div>
            </section>
          )}
        </>
      )}
    </>
  )
}

const reportStatusLabels: Record<string, string> = { VALID: 'Hợp lệ', WARNING: 'Có cảnh báo', MALFORMED: 'Cần xem', NEW: 'Mới' }
const workStatusLabels: Record<string, string> = {
  PLANNED: 'Kế hoạch', IN_PROGRESS: 'Đang làm', PENDING_REVIEW: 'Chờ review', DONE: 'Xong', BLOCKED: 'Bị chặn', CANCELLED: 'Hủy',
}
const UNDATED = 'undated'
const linkSourceLabels: Record<string, string> = {
  RULE_PREVIOUS: 'máy gắn: cùng việc đã báo cáo trước', RULE_PLAN: 'máy gắn: từ kế hoạch ngày', RULE_ISSUE: 'gắn theo gợi ý Issue đang mở',
  RULE_INTAKE: 'gắn theo gợi ý từ yêu cầu đã duyệt', AI: 'gắn theo gợi ý AI', MANUAL: 'gắn tay',
}
const suggestionSourceLabels: Record<string, string> = {
  RULE_PREVIOUS: 'cùng việc đã báo cáo trước', RULE_PLAN: 'từ kế hoạch ngày', RULE_ISSUE: 'Issue đang mở', RULE_INTAKE: 'yêu cầu đã duyệt', AI: 'AI gợi ý',
}
const noIssueLabels: Record<NoIssueReason, string> = { MEETING: 'Họp', SUPPORT: 'Hỗ trợ', REVIEW: 'Review', LEARNING: 'Học', OTHER: 'Khác' }
const DELIVERY_STATUSES = ['DONE', 'IN_PROGRESS', 'PENDING_REVIEW', 'BLOCKED']
const issueLabels: Record<string, string> = {
  GITLAB_REFERENCE_MISSING: 'Task không ghi số Issue GitLab',
  DONE_PROGRESS_INVALID: 'Task Xong nhưng không ghi tiến độ 100%',
  PROJECT_SCOPE_MISMATCH: 'Mã dự án ở tiêu đề khác trong nội dung',
  TOTAL_HOURS_MISSING: 'Không ghi tổng số giờ',
  TOTAL_HOURS_MISMATCH: 'Tổng giờ các task khác tổng giờ báo cáo',
  INVALID_SUBJECT: 'Tiêu đề thư sai mẫu',
  INVALID_REPORT_DATE: 'Ngày báo cáo không hợp lệ',
  PROJECT_SECTION_MISSING: 'Không tìm thấy mục dự án theo mẫu',
  REPORT_ITEMS_MISSING: 'Bộ quy tắc không đọc được task nào',
  REPORT_MEMBER_UNMAPPED: 'Người gửi chưa có trong danh sách nhân sự',
  REPORT_PROJECT_UNMAPPED: 'Mã dự án chưa được ánh xạ',
  REPORT_AI_PARSED: 'Task do AI đọc, cần đối chiếu với thư gốc',
  REPORT_DATE_ASSUMED: 'Thư không ghi ngày báo cáo, dùng ngày nhận thư',
  REPORT_AI_RESCUE_FAILED: 'AI không đọc được thư này',
  REPORT_AI_RESCUE_RETRY: 'AI chưa đọc được, sẽ thử lại ở lượt sau',
}

function ReportItemRow({ item, reportId, projects, onUpdated, onError }: { item: DailyReportItem; reportId: string; projects: Project[]; onUpdated: (detail: DailyReportDetail) => void; onError: (error: unknown) => void }) {
  const [editing, setEditing] = useState(false)
  const planned = item.work_status === 'PLANNED'
  const initialDraft = () => ({
    work_status: item.work_status,
    title: item.title,
    project_code: projects.find((project) => project.name === item.project_name)?.code || '',
    hours: String((planned ? item.planned_hours : item.worked_hours) ?? ''),
    progress_percent: String(item.progress_percent ?? ''),
    gitlab_issue: item.gitlab_issue || '',
    blocker_detail: item.blocker_detail || '',
  })
  const [draft, setDraft] = useState(initialDraft)
  const base = `/reports/daily/${reportId}/items/${item.id}`
  const save = useMutation({
    mutationFn: () => {
      const hours = draft.hours.trim() === '' ? null : Number(draft.hours.replace(',', '.'))
      const draftPlanned = draft.work_status === 'PLANNED'
      return api<DailyReportDetail>(base, {
        method: 'PATCH',
        body: JSON.stringify({
          work_status: draft.work_status,
          title: draft.title.trim(),
          project_code: draft.project_code || null,
          worked_hours: draftPlanned ? null : hours,
          planned_hours: draftPlanned ? hours : null,
          progress_percent: draft.progress_percent.trim() === '' ? null : Number(draft.progress_percent),
          gitlab_issue: draft.gitlab_issue.trim().replace(/^#/, '') || null,
          blocker_detail: draft.blocker_detail.trim() || null,
        }),
      })
    },
    onSuccess: (detail) => { setEditing(false); onUpdated(detail) },
    onError,
  })
  const remove = useMutation({
    mutationFn: () => api<DailyReportDetail>(base, { method: 'DELETE' }),
    onSuccess: onUpdated,
    onError,
  })
  // One click decides where the work belongs: an Issue from the suggestions, a typed number, or no Issue at all.
  const [other, setOther] = useState<string | null>(null)
  const decide = useMutation({
    mutationFn: (body: { gitlab_issue?: string | null; no_issue_reason?: NoIssueReason | null }) => api<DailyReportDetail>(`${base}/issue`, { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: (detail) => { setOther(null); onUpdated(detail) },
    onError,
  })
  const unlinked = !item.gitlab_issue && !item.no_issue_reason && DELIVERY_STATUSES.includes(item.work_status)

  if (editing) {
    return (
      <li className="report-item-edit">
        <form onSubmit={(event) => { event.preventDefault(); if (draft.title.trim()) save.mutate() }}>
          <label><span className="req-label">Tên task<Req /></span><input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} required maxLength={512} /></label>
          <div className="report-edit-grid">
            <label>Trạng thái<select value={draft.work_status} onChange={(e) => setDraft({ ...draft, work_status: e.target.value })}>{Object.entries(workStatusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label>Dự án<select value={draft.project_code} onChange={(e) => setDraft({ ...draft, project_code: e.target.value })}><option value="">Chưa gắn dự án</option>{projects.map((project) => <option key={project.id} value={project.code}>{project.name}</option>)}</select></label>
            <label>{draft.work_status === 'PLANNED' ? 'Giờ dự kiến' : 'Giờ đã làm'}<input inputMode="decimal" value={draft.hours} onChange={(e) => setDraft({ ...draft, hours: e.target.value })} placeholder="0 - 24" /></label>
            <label>Tiến độ %<input inputMode="numeric" value={draft.progress_percent} onChange={(e) => setDraft({ ...draft, progress_percent: e.target.value })} placeholder="0 - 100" /></label>
            <label>Issue GitLab<input inputMode="numeric" value={draft.gitlab_issue} onChange={(e) => setDraft({ ...draft, gitlab_issue: e.target.value })} placeholder="Ví dụ: 412" /></label>
          </div>
          <label>Vướng mắc<input value={draft.blocker_detail} onChange={(e) => setDraft({ ...draft, blocker_detail: e.target.value })} placeholder="Bỏ trống nếu không có" /></label>
          <div className="report-edit-actions">
            <button className="button button-secondary button-small" type="button" onClick={() => { setDraft(initialDraft()); setEditing(false) }}>Hủy</button>
            <button className="button button-primary button-small" disabled={save.isPending}>{save.isPending ? 'Đang lưu…' : 'Lưu task'}</button>
          </div>
        </form>
      </li>
    )
  }

  return (
    <li className={unlinked ? 'is-unlinked' : undefined}>
      <div>
        <span className={`status work-${item.work_status.toLowerCase()}`}>{workStatusLabels[item.work_status] || item.work_status}</span>
        <strong>{item.title}</strong>
        <span className="report-item-actions">
          <button type="button" className="icon-button" aria-label={`Sửa task ${item.title}`} onClick={() => { setDraft(initialDraft()); setEditing(true) }}><Pencil size={15} /></button>
          <button type="button" className="icon-button" aria-label={`Xóa task ${item.title}`} disabled={remove.isPending} onClick={() => { if (window.confirm(`Xóa task "${item.title}" khỏi báo cáo này?`)) remove.mutate() }}><Trash2 size={15} /></button>
        </span>
      </div>
      <small>
        {[item.project_name ? `${item.project_name}${item.reported_project_code ? ` (${item.reported_project_code})` : ''}` : 'Chưa gắn dự án',
          item.worked_hours != null ? `${item.worked_hours} giờ` : item.planned_hours != null ? `dự kiến ${item.planned_hours} giờ` : null,
          item.progress_percent != null ? `${item.progress_percent}%` : null,
          item.gitlab_issue ? `GitLab #${item.gitlab_issue}${item.issue_link_source && item.issue_link_source !== 'TEXT' ? ` (${linkSourceLabels[item.issue_link_source] || item.issue_link_source})` : ''}` : item.no_issue_reason ? `không cần Issue: ${noIssueLabels[item.no_issue_reason]}` : 'không có Issue',
          item.edited ? 'CTO đã sửa' : null].filter(Boolean).join(' · ')}
      </small>
      {unlinked && (
        <div className="issue-suggest" role="group" aria-label={`Gắn Issue cho ${item.title}`}>
          <div className="issue-suggest-row">
            <span className="issue-suggest-label">Issue</span>
            {item.issue_suggestions.length === 0 ? <span className="muted">chưa thấy Issue nào giống</span> : item.issue_suggestions.map((hint) => (
              <button key={hint.issue} type="button" className={`issue-hint${hint.confidence >= 0.9 ? ' is-sure' : ''}`} disabled={decide.isPending} title={`${suggestionSourceLabels[hint.source] || hint.source} · ${Math.round(hint.confidence * 100)}%${hint.reason ? ` · ${hint.reason}` : ''}. Bấm để gắn.`} onClick={() => decide.mutate({ gitlab_issue: hint.issue })}>
                <Link2 size={13} aria-hidden="true" /><b>#{hint.issue}</b><span>{hint.title}</span><small>{Math.round(hint.confidence * 100)}%</small>
              </button>
            ))}
            {other === null ? (
              <button type="button" className="issue-reason" onClick={() => setOther('')}>Nhập số Issue…</button>
            ) : (
              <form className="issue-other" onSubmit={(event) => { event.preventDefault(); const issue = other.trim().replace(/^#/, ''); if (/^[0-9]{1,12}$/.test(issue)) decide.mutate({ gitlab_issue: issue }) }}>
                <input inputMode="numeric" value={other} onChange={(event) => setOther(event.target.value)} placeholder="số Issue" aria-label="Số Issue" autoFocus />
                <button type="submit" className="button button-secondary button-small" disabled={decide.isPending}>Gắn</button>
                <button type="button" className="text-button" onClick={() => setOther(null)}>Hủy</button>
              </form>
            )}
          </div>
          <div className="issue-suggest-row">
            <span className="issue-suggest-label">Không cần Issue</span>
            {(Object.keys(noIssueLabels) as NoIssueReason[]).map((reason) => (
              <button key={reason} type="button" className="issue-reason" disabled={decide.isPending} title={`Đánh dấu việc này là ${noIssueLabels[reason].toLowerCase()}, không đếm là thiếu Issue`} onClick={() => decide.mutate({ no_issue_reason: reason })}>{noIssueLabels[reason]}</button>
            ))}
          </div>
        </div>
      )}
      {item.no_issue_reason && <button type="button" className="text-button issue-undo" disabled={decide.isPending} onClick={() => decide.mutate({})}>Bỏ đánh dấu "không cần Issue"</button>}
      {item.blocker_detail && <p className="report-blocker">Vướng: {item.blocker_detail}</p>}
      {item.next_step && <p>Bước tiếp: {item.next_step}</p>}
    </li>
  )
}

const mailboxErrors: Record<string, string> = {
  error: 'máy chủ thư từ chối đăng nhập',
  TimeoutError: 'máy chủ thư không phản hồi',
  gaierror: 'không tìm thấy máy chủ thư',
  WORKER_UNAVAILABLE: 'tiến trình đọc thư không chạy',
}

// The API holds no mailbox password: the button leaves a request that the mail worker picks up within seconds.
function MailboxScanControl({ onNewMail }: { onNewMail: () => void }) {
  const queryClient = useQueryClient()
  const mailbox = useQuery({
    queryKey: ['report-mailbox'],
    queryFn: () => api<MailboxStatus>('/reports/mailbox'),
    refetchInterval: (query) => (query.state.data?.current ? 2000 : 60000),
  })
  const scan = useMutation({
    mutationFn: () => api<MailboxStatus>('/reports/mailbox/scan', { method: 'POST' }),
    onSuccess: (status) => queryClient.setQueryData(['report-mailbox'], status),
  })
  const data = mailbox.data
  const lastId = data?.last?.id
  const seen = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (lastId && seen.current && seen.current !== lastId) onNewMail()
    if (lastId) seen.current = lastId
  }, [lastId, onNewMail])
  if (!data) return null
  const last = data.last
  const busy = Boolean(data.current) || scan.isPending
  const note = !data.enabled ? 'Quét hộp thư đang tắt (REPORT_IMAP_ENABLED)'
    : busy ? `Đang quét ${data.mailbox}…`
    : scan.error ? 'Không gửi được yêu cầu quét'
    : !last ? `Tự quét ${data.poll_minutes} phút một lần`
    : last.status === 'FAILED' ? `Lần quét ${formatDate(last.completed_at || last.created_at)} lỗi: ${mailboxErrors[last.error_code || ''] || 'không đọc được hộp thư'}`
    : `Quét gần nhất ${formatDate(last.completed_at || last.created_at)} · ${last.ingested > 0 ? `${last.ingested} thư mới` : 'không có thư mới'}${last.failed > 0 ? ` · ${last.failed} thư lỗi` : ''}`
  return (
    <div className="mailbox-scan">
      <small className={last?.status === 'FAILED' && !busy ? 'mailbox-scan-failed' : undefined} title={data.enabled ? `Tự quét ${data.poll_minutes} phút một lần` : undefined}>{note}</small>
      <button className="button button-secondary" type="button" disabled={!data.enabled || busy} onClick={() => scan.mutate()}>
        <RefreshCw size={15} className={busy ? 'spin' : undefined} aria-hidden="true" /> Quét email ngay
      </button>
    </div>
  )
}

function ReportsPage() {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const reports = useQuery({ queryKey: ['daily-reports'], queryFn: () => api<DailyReport[]>('/reports/daily') })
  const asked = new URLSearchParams(window.location.search)
  const [dateKey, setDateKey] = useState<string | undefined>(() => asked.get('date') || undefined)
  const [selectedId, setSelectedId] = useState<string>()
  const [error, setError] = useState<unknown>()
  const [onlyUnlinked, setOnlyUnlinked] = useState(() => asked.get('unlinked') === '1')

  const dates = Array.from(new Set((reports.data || []).map((report) => report.report_date || UNDATED)))
    .sort((a, b) => (a === UNDATED ? 1 : b === UNDATED ? -1 : b.localeCompare(a)))
  const activeDate = dateKey && dates.includes(dateKey) ? dateKey : dates[0]
  const onDate = (reports.data || []).filter((report) => (report.report_date || UNDATED) === activeDate)
  // The menu badge counts every AI-read report still waiting in the window; the ones on other days are named here.
  const waitingElsewhere = reportsWaiting(reports.data).filter((report) => (report.report_date || UNDATED) !== activeDate)
  const visible = onlyUnlinked ? onDate.filter((report) => report.unlinked_items > 0) : onDate
  const unlinkedOnDate = onDate.reduce((sum, report) => sum + report.unlinked_items, 0)
  const activeId = visible.some((report) => report.id === selectedId) ? selectedId : visible[0]?.id

  const detail = useQuery({
    queryKey: ['daily-report', activeId],
    queryFn: () => api<DailyReportDetail>(`/reports/daily/${activeId}`),
    enabled: Boolean(activeId),
  })
  const source = useQuery({
    queryKey: ['daily-report-source', activeId],
    queryFn: () => api<DailyReportSource>(`/reports/daily/${activeId}/raw`),
    enabled: false,
  })
  const nextUnreviewed = visible.find((report) => report.id !== activeId && !report.review_decision)
  const review = useMutation({
    mutationFn: (decision: 'CONFIRMED' | 'REJECTED') => api<DailyReportDetail>(`/reports/daily/${activeId}/review`, { method: 'POST', body: JSON.stringify({ decision }) }),
    onSuccess: (updated) => {
      setError(undefined)
      queryClient.setQueryData(['daily-report', activeId], updated)
      void queryClient.invalidateQueries({ queryKey: ['daily-reports'] })
    },
    onError: setError,
  })

  const refreshReports = useCallback(() => { void queryClient.invalidateQueries({ queryKey: ['daily-reports'] }) }, [queryClient])
  const linkSure = useMutation({
    mutationFn: () => api<DailyReportDetail>(`/reports/daily/${activeId}/link-sure`, { method: 'POST' }),
    onSuccess: (updated) => { setError(undefined); queryClient.setQueryData(['daily-report', activeId], updated); void queryClient.invalidateQueries({ queryKey: ['daily-reports'] }) },
    onError: setError,
  })
  const suggestAgain = useMutation({
    mutationFn: () => api<{ items: number; linked: number; suggested: number }>(`/reports/daily/${activeId}/suggest-issues`, { method: 'POST' }),
    onSuccess: () => { setError(undefined); void queryClient.invalidateQueries({ queryKey: ['daily-report', activeId] }); void queryClient.invalidateQueries({ queryKey: ['daily-reports'] }) },
    onError: setError,
  })
  const formatDay = (value: string) => (value === UNDATED ? 'Không rõ ngày' : new Intl.DateTimeFormat('vi-VN', { dateStyle: 'full' }).format(new Date(`${value}T00:00:00`)))
  const current = detail.data
  const problems = Object.values((current?.issues || []).filter((issue) => issue.code !== 'REPORT_REVIEWED').reduce<Record<string, { code: string; severity: string; count: number }>>((groups, issue) => {
    const key = `${issue.code}:${issue.severity}`
    groups[key] = { code: issue.code, severity: issue.severity, count: (groups[key]?.count || 0) + 1 }
    return groups
  }, {})).sort((a, b) => Number(b.severity === 'ERROR') - Number(a.severity === 'ERROR'))

  return (
    <>
      <AgentHint command="end_day" />
      <PageHeader title="Báo cáo ngày" helper="Đối chiếu task đã trích với thư gốc trước khi dùng cho kế hoạch. Xem thư gốc được ghi audit." action={user?.role === 'CTO' ? <MailboxScanControl onNewMail={refreshReports} /> : undefined} />
      {reports.error && <ErrorNotice error={reports.error} onRetry={() => { void reports.refetch() }} />}
      {error != null && <ErrorNotice error={error} />}
      {reports.isLoading ? <LoadingBlock /> : dates.length === 0 ? (
        <section className="panel"><EmptyState icon={<Inbox size={20} />} title="Chưa có báo cáo nào" text="Báo cáo xuất hiện ở đây sau khi hộp thư report@ được quét." /></section>
      ) : (
        <>
          {/* What the menu badge still counts on other days, said where it is seen, not in a line at the far right. */}
          {waitingElsewhere.length > 0 && (
            <div className="notice report-waiting-elsewhere" role="status">
              <TriangleAlert size={15} aria-hidden="true" />
              <span>Còn {waitingElsewhere.length} báo cáo do AI đọc chưa xác nhận ở ngày khác (huy hiệu ở menu đếm cả những ngày này):</span>
              {waitingElsewhere.map((report) => <button key={report.id} type="button" className="text-button" onClick={() => { setDateKey(report.report_date || UNDATED); setSelectedId(report.id) }}>{report.member_name || 'ai đó'} · {changelogDay(report.report_date || report.received_at.slice(0, 10))}</button>)}
            </div>
          )}
          <div className="panel filter-bar report-toolbar">
            <select aria-label="Ngày báo cáo" value={activeDate} onChange={(e) => { setDateKey(e.target.value); setSelectedId(undefined) }}>
              {dates.map((value) => <option key={value} value={value}>{formatDay(value)}</option>)}
            </select>
            <span className="result-count">{onDate.length} báo cáo · {onDate.filter((report) => report.parsed_by === 'AI').length} do AI đọc · {onDate.filter((report) => report.review_decision).length} đã xem{unlinkedOnDate > 0 ? ` · ${unlinkedOnDate} việc chưa gắn Issue` : ''}</span>
            <label className="report-filter-unlinked"><input type="checkbox" checked={onlyUnlinked} onChange={(event) => { setOnlyUnlinked(event.target.checked); setSelectedId(undefined) }} /> Chỉ báo cáo còn việc chưa gắn Issue</label>
          </div>
          <div className="report-layout">
            <nav className="panel report-list" aria-label="Danh sách báo cáo">
              {visible.map((report) => (
                <button type="button" key={report.id} className={report.id === activeId ? 'report-row active' : 'report-row'} aria-current={report.id === activeId} onClick={() => setSelectedId(report.id)}>
                  <strong>{report.member_name || report.sender_address}</strong>
                  <small>{formatDate(report.received_at)} · {report.item_count} task</small>
                  <span className="report-tags">
                    <span className={`status report-${report.status.toLowerCase()}`}>{reportStatusLabels[report.status] || report.status}</span>
                    {report.parsed_by === 'AI' && <span className="ai-tag">AI đọc</span>}
                    {!report.usable_for_planning && <span className="status report-warning">Chưa dùng cho Planning</span>}
                    {report.review_decision && <span className={report.review_decision === 'CONFIRMED' ? 'status status-approved' : 'status status-needs_information'}>{report.review_decision === 'CONFIRMED' ? 'Đã xác nhận' : 'Đã loại'}</span>}
                  </span>
                </button>
              ))}
            </nav>
            <div className="report-detail">
              {detail.isLoading || !current ? <LoadingBlock /> : (
                <>
                  <section className="panel report-summary">
                    <div>
                      <h2>{current.member_name || current.sender_address}</h2>
                      <p>{current.sender_address} · nhận {formatDate(current.received_at)}{current.is_late ? ' · muộn' : ''} · bản {current.revision}</p>
                      {!current.review_decision && !current.usable_for_planning && <p className="report-gate">Báo cáo do AI đọc: chưa được dùng cho Planning cho tới khi bạn bấm "Xác nhận đúng".</p>}
                      {current.hidden_items > 0 && <p className="report-gate">{current.hidden_items} việc ở dự án khác đã ẩn; thư này chỉ hiện phần thuộc dự án của bạn.</p>}
                      {!current.can_review && <p className="report-gate">Thư có việc ở dự án khác nên CTO xác nhận hoặc loại cả thư; bạn vẫn sửa và gắn Issue cho việc của dự án mình.</p>}
                    </div>
                    {current.can_review && <div className="report-actions">
                      <button className="button button-danger" type="button" disabled={review.isPending || current.review_decision === 'REJECTED'} onClick={() => { if (window.confirm(`Loại báo cáo của ${current.member_name || current.sender_address}?

Các task của báo cáo này sẽ bị gỡ khỏi Planning và không khôi phục được. Nhân sự gửi lại thư thì bản mới sẽ thay thế.`)) review.mutate('REJECTED') }}><X size={15} /> {current.review_decision === 'REJECTED' ? 'Đã loại' : 'Loại báo cáo'}</button>
                      <button className="button button-primary" type="button" disabled={review.isPending || current.review_decision != null} onClick={() => review.mutate('CONFIRMED')}><Check size={15} /> {current.review_decision === 'CONFIRMED' ? 'Đã xác nhận' : 'Xác nhận đúng'}</button>
                    </div>}
                  </section>
                  {current.review_decision && (
                    <div className={`notice report-next ${current.review_decision === 'CONFIRMED' ? 'notice-success' : 'notice-warn'}`} role="status">
                      <span>{current.review_decision === 'CONFIRMED'
                        ? 'Đã xác nhận. Các task chưa xong của báo cáo này sẽ hiện ở mục "Yêu cầu cần phân loại" trong Daily Planning của ngày làm việc kế tiếp; task có số GitLab Issue được ưu tiên trong đề xuất.'
                        : 'Đã loại. Các task của báo cáo này đã bị gỡ khỏi Planning và không khôi phục được; nhân sự gửi lại thư thì bản mới sẽ thay thế.'}</span>
                      <span className="report-next-actions">
                        {nextUnreviewed
                          ? <button className="button button-secondary button-small" type="button" onClick={() => setSelectedId(nextUnreviewed.id)}>Báo cáo tiếp theo: {nextUnreviewed.member_name || nextUnreviewed.sender_address} <ArrowRight size={14} /></button>
                          : <span>Đã xem hết {visible.length} báo cáo của ngày này.</span>}
                        {current.review_decision === 'CONFIRMED' && <Link className="button button-secondary button-small" to="/planning">Mở Daily Planning</Link>}
                      </span>
                    </div>
                  )}
                  {problems.length > 0 && (
                    <section className={`report-issues${problems.some((issue) => issue.severity === 'ERROR') ? ' has-error' : ''}`} aria-label="Vấn đề cần xem">
                      <strong><TriangleAlert size={15} aria-hidden="true" /> {problems.length} điểm cần xem</strong>
                      <ul>
                        {problems.map((issue) => <li key={`${issue.code}-${issue.severity}`} className={`issue-${issue.severity.toLowerCase()}`} title={issue.code}>{issue.severity === 'ERROR' ? 'Lỗi: ' : ''}{issueLabels[issue.code] || issue.code}{issue.count > 1 ? ` (${issue.count} lần)` : ''}</li>)}
                      </ul>
                    </section>
                  )}
                  <div className="review-grid report-compare">
                    <section className="panel">
                      <div className="panel-heading"><div><h2>Thư gốc</h2></div><span className="restricted-tag">CTO only</span></div>
                      {source.data ? (
                        <div className="report-source"><strong>{source.data.subject}</strong><pre>{source.data.purged ? 'Nội dung đã bị xóa theo thời hạn lưu trữ.' : source.data.body}</pre>{!source.data.purged && source.data.signature && <details className="report-signature"><summary>Hiện chữ ký</summary><pre>{source.data.signature}</pre></details>}</div>
                      ) : (
                        <div className="raw-guard"><ShieldCheck size={22} aria-hidden="true" /><strong>Nội dung được bảo vệ</strong><p>Mỗi lần mở thư gốc được ghi vào audit.</p><button className="button button-secondary" type="button" disabled={source.isFetching} onClick={() => { void source.refetch() }}><Eye size={15} /> {source.isFetching ? 'Đang tải…' : 'Hiển thị thư gốc'}</button></div>
                      )}
                      {source.error && <ErrorNotice error={source.error} />}
                    </section>
                    <section className="panel">
                      <div className="panel-heading"><div><h2>Task đã trích</h2></div><span className="ai-tag">{current.parsed_by === 'AI' ? 'AI đọc' : 'Quy tắc'} · {current.items.length} task</span></div>
                      {current.unlinked_items > 0 && (
                        <div className="issue-bar">
                          <span><strong>{current.unlinked_items}</strong> việc chưa gắn Issue. {current.items.some((item) => item.issue_suggestions.some((hint) => hint.confidence >= 0.9) && !item.gitlab_issue && !item.no_issue_reason) ? 'Có gợi ý chắc, gắn một lần được.' : 'Bấm gợi ý dưới từng việc, hoặc đánh dấu không cần Issue.'}</span>
                          <span className="issue-bar-actions">
                            <button type="button" className="button button-secondary button-small" disabled={linkSure.isPending || !current.items.some((item) => item.issue_suggestions.some((hint) => hint.confidence >= 0.9) && !item.gitlab_issue && !item.no_issue_reason)} onClick={() => linkSure.mutate()}>{linkSure.isPending ? 'Đang gắn…' : 'Gắn mọi gợi ý chắc'}</button>
                            <button type="button" className="text-button" disabled={suggestAgain.isPending} title="Tìm lại theo kế hoạch, báo cáo trước và Issue đang mở; phần chưa rõ hỏi AI" onClick={() => suggestAgain.mutate()}>{suggestAgain.isPending ? 'Đang tìm…' : 'Gợi ý lại'}</button>
                          </span>
                        </div>
                      )}
                      {current.items.length === 0 ? <EmptyState icon={<CircleHelp size={20} />} title="Không có task nào" text={current.review_decision === 'REJECTED' ? 'Báo cáo đã bị loại nên các task không còn được dùng.' : 'Không trích được task nào từ thư này.'} /> : (
                        <ol className="report-items">
                          {current.items.filter((item) => !onlyUnlinked || (!item.gitlab_issue && !item.no_issue_reason && DELIVERY_STATUSES.includes(item.work_status))).map((item) => (
                            <ReportItemRow key={item.id} item={item} reportId={current.id} projects={projects.data || []} onError={setError}
                              onUpdated={(updated) => { setError(undefined); queryClient.setQueryData(['daily-report', activeId], updated); void queryClient.invalidateQueries({ queryKey: ['daily-reports'] }) }} />
                          ))}
                        </ol>
                      )}
                    </section>
                  </div>
                </>
              )}
            </div>
          </div>
        </>
      )}
    </>
  )
}

const noteKindLabels: Record<string, string> = {
  DECISION: 'Quyết định', REQUIREMENT: 'Yêu cầu', BUG: 'Bug', SCOPE_CHANGE: 'Thay đổi phạm vi', ACTION: 'Việc cần làm', QUESTION: 'Câu hỏi mở', RISK: 'Rủi ro',
}
const noteGroups: { title: string; kinds: string[] }[] = [
  { title: 'Quyết định', kinds: ['DECISION'] },
  { title: 'Yêu cầu, bug, thay đổi phạm vi', kinds: ['REQUIREMENT', 'BUG', 'SCOPE_CHANGE'] },
  { title: 'Việc cần làm', kinds: ['ACTION'] },
  { title: 'Câu hỏi mở và rủi ro', kinds: ['QUESTION', 'RISK'] },
]
const workLabels: Record<string, string> = { NONE: 'Chưa có', PENDING: 'Đang chờ', RUNNING: 'Đang xử lý', DONE: 'Xong', FAILED: 'Lỗi', SKIPPED: 'Bỏ qua' }
// Why a step failed, in words; the code stays in the tooltip for whoever reads the logs.
const meetingErrorLabels: Record<string, string> = {
  PROVIDER_NOT_CONFIGURED: 'chưa cấu hình dịch vụ chuyển chữ', PROVIDER_UNAVAILABLE: 'dịch vụ chuyển chữ không phản hồi',
  PROVIDER_TRANSIENT: 'dịch vụ chuyển chữ lỗi tạm thời', PROVIDER_REJECTED: 'dịch vụ chuyển chữ từ chối tệp này',
  UPLOAD_STALLED: 'tải lên bị ngắt giữa chừng', NOT_CONFIGURED: 'chưa cấu hình AI', AI_UNAVAILABLE: 'AI không phản hồi',
}
const workLabel = (status: string, error: string | null) => `${workLabels[status] || status}${error ? ` (${meetingErrorLabels[error] || error})` : ''}`

const noteKindShort: Record<string, string> = { DECISION: 'Chốt', REQUIREMENT: 'Yêu cầu', BUG: 'Bug', SCOPE_CHANGE: 'Phạm vi', ACTION: 'Việc', QUESTION: 'Hỏi', RISK: 'Rủi ro' }

// One line per point. The rest (detail, edit, delete) opens on click, so a long meeting stays readable.

// --- From the meeting note straight to the board (FR-REC-19) ---------------------------------------------------

type NoteDest = 'WORK' | 'INTAKE' | 'NONE'
type NoteChoice = { dest: NoteDest; member_id: string | null; due_date: string | null }
const noteWorkErrors: Record<string, string> = {
  NOTE_ITEM_HAS_INTAKE: 'Mục này đã được tạo rồi.',
  NOTE_ITEM_NOT_ACTIONABLE: 'Quyết định chỉ ghi nhận, không thành việc.',
  PROJECT_REQUIRED: 'Chọn dự án cho mục này trước.',
  PROJECT_NOT_ALLOWED: 'Mục này thuộc dự án anh/chị không quản.',
  MEMBER_NOT_IN_PROJECT: 'Người này không thuộc dự án của mục.',
}
function stripAccents(value: string) {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'D').toLowerCase()
}
// The person a note names, when exactly one member of the project answers to it; otherwise the row asks.
function suggestMember(owner: string | null, members: WorkforceMember[]): string | null {
  const name = stripAccents((owner || '').trim())
  if (!name || /^thanh vien \d/.test(name)) return null
  const tokens = name.split(/\s+/).filter((token) => token.length >= 2)
  if (tokens.length === 0) return null
  const last = tokens[tokens.length - 1]
  const hits = members.filter((member) => {
    const full = stripAccents(member.display_name)
    const parts = full.split(/\s+/)
    return full === name || full.includes(name) || parts[parts.length - 1] === last || (tokens.length > 1 && name.includes(parts[parts.length - 1]))
  })
  return hits.length === 1 ? hits[0].id : null
}
// "25/10", "hôm nay", "ngày mai", "thứ Sáu", "tuần sau", "cuối tháng": a date, or nothing when the note does not say.
function parseDueText(text: string | null, base: string): string | null {
  const raw = stripAccents((text || '').trim())
  if (!raw) return null
  const start = new Date(`${base || todayInPlanningTimezone()}T00:00:00`)
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  const plus = (days: number) => { const d = new Date(start); d.setDate(d.getDate() + days); return iso(d) }
  const dm = raw.match(/(\d{1,2})[\/.-](\d{1,2})(?:[\/.-](\d{2,4}))?/)
  if (dm) {
    const day = Number(dm[1]); const month = Number(dm[2]) - 1
    let year = dm[3] ? Number(dm[3].length === 2 ? `20${dm[3]}` : dm[3]) : start.getFullYear()
    let d = new Date(year, month, day)
    if (!dm[3] && d.getTime() < start.getTime() - 180 * 86400000) { year += 1; d = new Date(year, month, day) }
    return Number.isNaN(d.getTime()) ? null : iso(d)
  }
  if (/hom nay/.test(raw)) return plus(0)
  if (/ngay kia/.test(raw)) return plus(2)
  if (/\bmai\b/.test(raw)) return plus(1)
  if (/tuan sau|tuan toi/.test(raw)) return plus(7)
  if (/cuoi thang/.test(raw)) { const d = new Date(start.getFullYear(), start.getMonth() + 1, 0); return iso(d) }
  const weekdays: Record<string, number> = { 'chu nhat': 0, 'cn': 0, 'thu hai': 1, 'thu 2': 1, 'thu ba': 2, 'thu 3': 2, 'thu tu': 3, 'thu 4': 3, 'thu nam': 4, 'thu 5': 4, 'thu sau': 5, 'thu 6': 5, 'thu bay': 6, 'thu 7': 6 }
  const key = Object.keys(weekdays).find((name) => raw.includes(name))
  if (key !== undefined) { const target = weekdays[key]; let diff = (target - start.getDay() + 7) % 7; if (diff === 0) diff = 7; if (/cuoi tuan/.test(raw) && target === 0) diff = (5 - start.getDay() + 7) % 7 || 7; return plus(diff) }
  if (/cuoi tuan/.test(raw)) { const diff = (5 - start.getDay() + 7) % 7 || 7; return plus(diff) }
  return null
}
function defaultNoteChoice(item: MeetingNoteItem, members: WorkforceMember[], meetingDate: string): NoteChoice {
  const dest: NoteDest = item.kind === 'DECISION' ? 'NONE' : ['REQUIREMENT', 'BUG', 'SCOPE_CHANGE'].includes(item.kind) ? 'INTAKE' : 'WORK'
  return { dest, member_id: suggestMember(item.owner, members), due_date: parseDueText(item.due_text, meetingDate) }
}

function MeetingNoteRow({ item, meetingId, meetingProject, projects, onUpdated, onError, picked, onPick, members = [], meetingDate = '', choice, onChoice, postMode = false }: { item: MeetingNoteItem; meetingId: string; meetingProject: string | null; projects: Project[]; onUpdated: (detail: MeetingDetail) => void; onError: (error: unknown) => void; picked?: boolean; onPick?: (id: string, on: boolean) => void; members?: WorkforceMember[]; meetingDate?: string; choice?: NoteChoice; onChoice?: (id: string, choice: NoteChoice) => void; postMode?: boolean }) {
  const [editing, setEditing] = useState(false)
  const [open, setOpen] = useState(false)
  const initialDraft = () => ({ kind: item.kind, title: item.title || '', detail: item.detail || '', project_code: item.project_code || '', owner: item.owner || '', due_text: item.due_text || '' })
  const [draft, setDraft] = useState(initialDraft)
  const base = `/meetings/${meetingId}/note/items/${item.id}`
  const save = useMutation({
    mutationFn: () => api<MeetingDetail>(base, { method: 'PATCH', body: JSON.stringify({ kind: draft.kind, title: draft.title.trim(), detail: draft.detail.trim() || null, project_code: draft.project_code || null, owner: draft.owner.trim() || null, due_text: draft.due_text.trim() || null }) }),
    onSuccess: (detail) => { setEditing(false); onUpdated(detail) },
    onError,
  })
  const remove = useMutation({ mutationFn: () => api<MeetingDetail>(base, { method: 'DELETE' }), onSuccess: onUpdated, onError })
  const toIntake = useMutation({ mutationFn: (full: boolean) => api<MeetingDetail>(`${base}/intake${full ? '?full_transcript=true' : ''}`, { method: 'POST' }), onSuccess: onUpdated, onError })
  // Straight to the board (FR-REC-19): the Intake is made and approved from the meeting in one step, no AI pass.
  const toWork = useMutation({
    mutationFn: (spec: { member_id: string | null; due_date: string | null }) => api<MeetingNoteWorkOut>(`/meetings/${meetingId}/note/items/work`, { method: 'POST', body: JSON.stringify({ items: [{ item_id: item.id, ...spec }] }) }),
    onSuccess: (result) => { const row = result.results[0]; if (row?.error) onError(new Error(noteWorkErrors[row.error] || workErrorWords[row.error] || row.error)); onUpdated(result.meeting) },
    onError,
  })
  const [own, setOwn] = useState<NoteChoice>()
  const base_choice = choice ?? own ?? defaultNoteChoice(item, members, meetingDate)
  // On a marketing project every line but a decision goes to the board as a post (FR-MKT-07).
  const local: NoteChoice = postMode && base_choice.dest === 'INTAKE' ? { ...base_choice, dest: 'WORK' } : base_choice
  const setChoice = (next: NoteChoice) => { if (onChoice) onChoice(item.id, next); else setOwn(next) }
  // A question or a risk the team decided is really work: change its kind here, then it can become an Intake.
  const changeKind = useMutation({ mutationFn: (kind: string) => api<MeetingDetail>(base, { method: 'PATCH', body: JSON.stringify({ kind }) }), onSuccess: onUpdated, onError })

  if (editing) {
    return (
      <li className="report-item-edit">
        <form onSubmit={(event) => { event.preventDefault(); if (draft.title.trim()) save.mutate() }}>
          <label><span className="req-label">Nội dung<Req /></span><input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} required maxLength={500} /></label>
          <label>Chi tiết<textarea rows={3} value={draft.detail} onChange={(e) => setDraft({ ...draft, detail: e.target.value })} /></label>
          <div className="report-edit-grid">
            <label>Loại<select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>{Object.entries(noteKindLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label>Dự án<select value={draft.project_code} onChange={(e) => setDraft({ ...draft, project_code: e.target.value })}><option value="">Chưa gắn dự án</option>{projects.map((project) => <option key={project.id} value={project.code}>{project.name}</option>)}</select></label>
            <label>Người phụ trách<input value={draft.owner} onChange={(e) => setDraft({ ...draft, owner: e.target.value })} /></label>
            <label>Hạn<input value={draft.due_text} onChange={(e) => setDraft({ ...draft, due_text: e.target.value })} /></label>
          </div>
          <div className="report-edit-actions">
            <button className="button button-secondary button-small" type="button" onClick={() => { setDraft(initialDraft()); setEditing(false) }}>Hủy</button>
            <button className="button button-primary button-small" disabled={save.isPending}>{save.isPending ? 'Đang lưu…' : 'Lưu mục'}</button>
          </div>
        </form>
      </li>
    )
  }

  const who = [item.owner, item.due_text ? `hạn ${item.due_text}` : null].filter(Boolean).join(' · ')
  // The meeting's own project goes without saying; only a different one is worth a line.
  const otherProject = item.project_code && item.project_code !== meetingProject ? item.project_name : !item.project_code && item.can_become_intake ? 'Chưa gắn dự án' : null
  return (
    <li className={open ? 'note-row open' : 'note-row'}>
      <div className="note-row-line">
        {onPick && item.can_become_intake && item.project_code && <input type="checkbox" className="note-pick" aria-label={`Chọn mục "${item.title}"`} checked={Boolean(picked)} onChange={(event) => onPick(item.id, event.target.checked)} />}
        <button type="button" className="note-row-main" aria-expanded={open} onClick={() => setOpen(!open)}>
          <span className={`note-kind note-${item.kind.toLowerCase()}`} title={noteKindLabels[item.kind] || item.kind}>{noteKindShort[item.kind] || item.kind}</span>
          <span className="note-row-title">{item.title}{who && <small> · {who}</small>}</span>
        </button>
        {item.work_id ? <Link className="note-intake-link" to={`/viec?project=${item.project_code || ''}&work=${item.work_id}`}>{postMode ? 'Bài' : 'Việc'} {item.work_code} <ArrowUpRight size={13} /></Link>
          : item.intake_id && <Link className="note-intake-link" to={`/intakes/${item.intake_id}`}>Intake <ArrowUpRight size={13} /></Link>}
        {(item.can_become_work || item.can_become_intake) && (
          <span className="note-dest">
            {!postMode && <select aria-label="Đích" value={local.dest} onChange={(event) => setChoice({ ...local, dest: event.target.value as NoteDest })}>
              <option value="WORK">→ Việc</option>{item.can_become_intake && <option value="INTAKE">→ Intake</option>}<option value="NONE">Chỉ ghi nhận</option>
            </select>}
            {local.dest === 'WORK' && (
              <>
                <select aria-label="Người làm" value={local.member_id || ''} onChange={(event) => setChoice({ ...local, member_id: event.target.value || null })} title={item.owner && !local.member_id ? `Biên bản ghi "${item.owner}": chọn đúng người` : undefined} className={item.owner && !local.member_id ? 'is-asking' : undefined}>
                  <option value="">{item.owner ? `Ai là "${item.owner}"?` : 'Chưa giao'}</option>{members.map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}
                </select>
                <input type="date" aria-label="Hạn" value={local.due_date || ''} onChange={(event) => setChoice({ ...local, due_date: event.target.value || null })} title={item.due_text ? `Biên bản ghi hạn "${item.due_text}"` : undefined} />
              </>
            )}
            {local.dest !== 'NONE' && <button type="button" className="button button-secondary button-small" disabled={toWork.isPending || toIntake.isPending || !item.project_code} title={!item.project_code ? 'Chọn dự án cho mục này trước' : local.dest === 'WORK' ? 'Lên bảng Việc ngay: duyệt từ cuộc họp, không qua AI' : 'Tạo Intake để AI đọc, rồi duyệt ở Chờ phê duyệt'} onClick={() => (local.dest === 'WORK' ? toWork.mutate({ member_id: local.member_id || null, due_date: local.due_date || null }) : toIntake.mutate(false))}>{toWork.isPending || toIntake.isPending ? 'Đang tạo…' : postMode ? 'Đưa vào lịch' : 'Tạo'}</button>}
          </span>
        )}
      </div>
      {open && (
        <div className="note-row-more">
          {item.detail && <p>{item.detail}</p>}
          <div>
            <small>{[noteKindLabels[item.kind], otherProject, item.edited ? 'đã sửa tay' : null].filter(Boolean).join(' · ')}</small>
            <button type="button" className="text-button" onClick={() => { setDraft(initialDraft()); setEditing(true) }}><Pencil size={13} /> Sửa</button>
            {!item.intake_id && <label className="note-kind-change">Loại <select value={item.kind} disabled={changeKind.isPending} onChange={(event) => changeKind.mutate(event.target.value)}>{Object.entries(noteKindLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>}
            {item.can_become_intake && item.project_code && <button type="button" className="text-button" disabled={toIntake.isPending} title="Gửi cho AI toàn bộ bản chữ cuộc họp thay vì đoạn quanh chủ đề" onClick={() => toIntake.mutate(true)}><Plus size={13} /> Intake kèm cả bản chữ</button>}
            {!item.intake_id && <button type="button" className="text-button" disabled={remove.isPending} onClick={() => { if (window.confirm(`Xóa mục "${item.title}" khỏi meeting note?`)) remove.mutate() }}><Trash2 size={13} /> Xóa</button>}
          </div>
        </div>
      )}
    </li>
  )
}

// The note of another part of the same meeting, under the note of the part being looked at (FR-REC-17).
function PartNote({ part, projects, onError, onUpdated }: { part: MeetingPart; projects: Project[]; onError: (error: unknown) => void; onUpdated: (detail: MeetingDetail) => void }) {
  const detail = useQuery({ queryKey: ['meeting', part.id], queryFn: () => api<MeetingDetail>(`/meetings/${part.id}`), enabled: part.note_status === 'DONE' })
  if (part.note_status !== 'DONE') return <p className="muted note-empty">Phần {part.part_number}: note {workLabels[part.note_status] || part.note_status}.</p>
  if (!detail.data) return null
  return (
    <details className="note-topic note-part" open>
      <summary><span>Phần {part.part_number}</span><small>{detail.data.note_items.length} mục</small></summary>
      <ol>{detail.data.note_items.map((item) => <MeetingNoteRow key={item.id} item={item} meetingId={part.id} meetingProject={detail.data.project_code} projects={projects} onUpdated={onUpdated} onError={onError} />)}</ol>
    </details>
  )
}

function MeetingsPage() {
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [error, setError] = useState<unknown>()
  const [audioUrl, setAudioUrl] = useState<{ id: string; url: string }>()
  const [summaryDraft, setSummaryDraft] = useState<string>()
  const [names, setNames] = useState<Record<string, string>>({})
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const [withSpoken, setWithSpoken] = useState(false)
  const meetings = useQuery({ queryKey: ['meetings', withSpoken], queryFn: () => api<Meeting[]>(`/meetings${withSpoken ? '?include_dictation=true' : ''}`), refetchInterval: 15_000 })
  // A link may point at a spoken request, which the list leaves out by default: open what the link names.
  const activeId = searchParams.get('id') || meetings.data?.[0]?.id
  const detail = useQuery({
    queryKey: ['meeting', activeId],
    queryFn: () => api<MeetingDetail>(`/meetings/${activeId}`),
    enabled: Boolean(activeId),
    refetchInterval: (query) => {
      const data = query.state.data
      return data && (['PENDING', 'RUNNING'].includes(data.transcript_status) || data.note_status === 'PENDING' || data.status === 'RECORDING') ? 5000 : false
    },
  })
  const current = detail.data
  const updated = (next: MeetingDetail) => {
    setError(undefined)
    queryClient.setQueryData(['meeting', next.id], next)
    void queryClient.invalidateQueries({ queryKey: ['meetings'] })
    // Intakes made here show up in the request lists at once.
    void queryClient.invalidateQueries({ queryKey: ['intakes'] })
    void queryClient.invalidateQueries({ queryKey: ['approvals'] })
  }
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [bulkNote, setBulkNote] = useState<string>()
  // Who may take a note item on the meeting's project, and what each row settled on (FR-REC-19).
  const members = useQuery({ queryKey: ['planning-members'], queryFn: () => api<WorkforceMember[]>('/planning/members') })
  const [choices, setChoices] = useState<Record<string, NoteChoice>>({})
  const togglePick = (id: string, on: boolean) => setPicked((prev) => { const next = new Set(prev); if (on) next.add(id); else next.delete(id); return next })
  const bulk = useMutation({
    mutationFn: () => api<MeetingNoteBulkIntakeOut>(`/meetings/${activeId}/note/items/intakes`, { method: 'POST', body: JSON.stringify({ item_ids: Array.from(picked) }) }),
    onSuccess: (result) => {
      const made = result.results.filter((row) => row.intake_id).length
      const failed = result.results.filter((row) => row.error)
      setBulkNote(`Đã tạo ${made} Intake${failed.length > 0 ? `; ${failed.length} mục không tạo được (${failed.map((row) => row.error).join(', ')})` : ''}.`)
      setPicked(new Set())
      updated(result.meeting)
    },
    onError: setError,
  })
  const retryTranscript = useMutation({ mutationFn: () => api<MeetingDetail>(`/meetings/${activeId}/transcript/retry`, { method: 'POST' }), onSuccess: updated, onError: setError })

  useEffect(() => { setSummaryDraft(undefined); setNames({}); setTitleDraft(undefined); setPicked(new Set()); setBulkNote(undefined) }, [activeId])
  useEffect(() => () => { if (audioUrl) URL.revokeObjectURL(audioUrl.url) }, [audioUrl])

  const loadAudio = useMutation({
    mutationFn: async () => {
      const response = await fetch(`/api/v1/meetings/${activeId}/audio`, { credentials: 'include' })
      if (!response.ok) throw new Error('Không tải được bản ghi âm.')
      return { id: activeId!, url: URL.createObjectURL(await response.blob()) }
    },
    onSuccess: setAudioUrl,
    onError: setError,
  })
  const saveSummary = useMutation({
    mutationFn: () => api<MeetingDetail>(`/meetings/${activeId}/note`, { method: 'PATCH', body: JSON.stringify({ summary: (summaryDraft || '').trim() }) }),
    onSuccess: (next) => { setSummaryDraft(undefined); updated(next) },
    onError: setError,
  })
  const regenerate = useMutation({ mutationFn: () => api<MeetingDetail>(`/meetings/${activeId}/note/regenerate`, { method: 'POST' }), onSuccess: updated, onError: setError })
  // A meeting still "recording" that no browser is feeding (the tab was reloaded or closed): end it now from what reached the server.
  const recordingNow = useRecording()
  const finishStuck = useMutation({ mutationFn: () => api<MeetingDetail>(`/meetings/${activeId}/finish`, { method: 'POST', body: JSON.stringify({}) }), onSuccess: updated, onError: setError })
  const [titleDraft, setTitleDraft] = useState<string>()
  const renameMeeting = useMutation({
    mutationFn: () => api<MeetingDetail>(`/meetings/${activeId}`, { method: 'PATCH', body: JSON.stringify({ title: (titleDraft || '').trim() }) }),
    onSuccess: (next) => { setTitleDraft(undefined); updated(next) },
    onError: setError,
  })
  // The recording waiting for a yes in the confirmation popup.
  const [removing, setRemoving] = useState<MeetingDetail>()
  const removeMeeting = useMutation({
    mutationFn: (id: string) => api<{ deleted: boolean; intakes_kept: number }>(`/meetings/${id}`, { method: 'DELETE' }),
    onSuccess: (_, id) => {
      setRemoving(undefined)
      setError(undefined)
      // Leave the deleted recording first, so nothing asks the server for it again.
      setSearchParams({}, { replace: true })
      queryClient.setQueriesData<Meeting[]>({ queryKey: ['meetings'] }, (rows) => rows?.filter((row) => row.id !== id))
      queryClient.removeQueries({ queryKey: ['meeting', id] })
      void queryClient.invalidateQueries({ queryKey: ['meetings'] })
    },
  })
  const removeError = removeMeeting.error instanceof ApiError && removeMeeting.error.status === 409
    ? new Error('Chưa xóa được: bản ghi đang được ghi, đang chuyển chữ, hoặc bản sao phía dịch vụ chuyển chữ chưa xóa xong. Thử lại sau ít phút.')
    : removeMeeting.error
  const changeProject = useMutation({
    mutationFn: (code: string) => api<MeetingDetail>(`/meetings/${activeId}/project`, { method: 'PATCH', body: JSON.stringify({ project_id: code }) }),
    onSuccess: updated,
    onError: setError,
  })
  const rename = useMutation({
    mutationFn: () => api<MeetingDetail>(`/meetings/${activeId}/speakers`, { method: 'PATCH', body: JSON.stringify({ names }) }),
    onSuccess: (next) => { setNames({}); updated(next) },
    onError: setError,
  })

  const summaryLines = (current?.note_summary || '').split('\n').map((line) => line.trim()).filter(Boolean)
  const noteItems = current?.note_items || []
  const meetingProjectRow = (projects.data || []).find((project) => project.code === current?.project_code)
  const meetingProjectId = meetingProjectRow?.id
  const meetingPostMode = isPostProject(meetingProjectRow?.kind)
  const projectMembers = useMemo(() => (members.data || []).filter((member) => member.status === 'ACTIVE' && (!meetingProjectId || member.project_mappings.some((mapping) => mapping.project_id === meetingProjectId && mapping.active))), [members.data, meetingProjectId])
  const meetingDate = (current?.started_at || '').slice(0, 10)
  const choiceOf = (item: MeetingNoteItem) => choices[item.id] || defaultNoteChoice(item, projectMembers, meetingDate)
  const proposed = noteItems.filter((item) => !item.intake_id && item.project_code && (item.can_become_work || item.can_become_intake) && (meetingPostMode ? item.kind !== 'DECISION' : choiceOf(item).dest !== 'NONE'))
  const asProposed = useMutation({
    mutationFn: async () => {
      const work = proposed.filter((item) => meetingPostMode || choiceOf(item).dest === 'WORK').map((item) => ({ item_id: item.id, member_id: choiceOf(item).member_id, due_date: choiceOf(item).due_date }))
      const intakes = meetingPostMode ? [] : proposed.filter((item) => choiceOf(item).dest === 'INTAKE').map((item) => item.id)
      const made: string[] = []; const failed: string[] = []
      if (work.length > 0) { const result = await api<MeetingNoteWorkOut>(`/meetings/${activeId}/note/items/work`, { method: 'POST', body: JSON.stringify({ items: work }) }); for (const row of result.results) (row.error ? failed : made).push(row.error ? `${row.error}` : `Việc ${row.code}`) }
      if (intakes.length > 0) { const result = await api<MeetingNoteBulkIntakeOut>(`/meetings/${activeId}/note/items/intakes`, { method: 'POST', body: JSON.stringify({ item_ids: intakes }) }); for (const row of result.results) (row.error ? failed : made).push(row.error ? `${row.error}` : 'Intake') }
      return { made, failed }
    },
    onSuccess: ({ made, failed }) => { setBulkNote(`Đã tạo ${made.length} mục${failed.length > 0 ? `; ${failed.length} mục không tạo được (${failed.map((code) => noteWorkErrors[code] || code).join('; ')})` : ''}.`); setChoices({}); void queryClient.invalidateQueries({ queryKey: ['meeting', activeId] }); void queryClient.invalidateQueries({ queryKey: ['work'] }) },
    onError: setError,
  })
  // Notes written by subject are shown by subject; earlier notes keep their four groups by kind.
  const bySubject = noteItems.some((item) => item.topic)
  const noteSections = bySubject
    ? Array.from(new Set(noteItems.map((item) => item.topic || 'Khác'))).map((title) => ({ title, items: noteItems.filter((item) => (item.topic || 'Khác') === title) }))
    : noteGroups.map((group) => ({ title: group.title, items: noteItems.filter((item) => group.kinds.includes(item.kind)) })).filter((section) => section.items.length > 0)
  const duration = (seconds: number | null) => (seconds == null ? '—' : `${Math.floor(seconds / 60)} phút ${seconds % 60} giây`)
  const clock = (ms: number | null) => (ms == null ? '' : formatClock(Math.floor(ms / 1000)))
  // The transcript follows the player: the part being spoken is highlighted and kept in view.
  const player = useRef<HTMLAudioElement>(null)
  const transcriptList = useRef<HTMLOListElement>(null)
  const [playMs, setPlayMs] = useState<number>()
  const listening = audioUrl?.id === current?.id ? playMs : undefined
  const spokenId = listening == null ? undefined : (current?.segments || []).reduce<{ id?: string; at: number }>(
    (best, segment) => (segment.start_ms != null && segment.start_ms <= listening + 250 && segment.start_ms >= best.at ? { id: segment.id, at: segment.start_ms } : best),
    { at: -1 },
  ).id
  useEffect(() => { setPlayMs(undefined) }, [activeId])
  useEffect(() => {
    const list = transcriptList.current
    const row = spokenId ? list?.querySelector<HTMLElement>(`[data-segment="${spokenId}"]`) : null
    if (!list || !row) return
    // Scroll the transcript box only, never the page.
    const top = row.getBoundingClientRect().top - list.getBoundingClientRect().top + list.scrollTop
    if (top < list.scrollTop || top + row.offsetHeight > list.scrollTop + list.clientHeight) list.scrollTo({ top: Math.max(top - 12, 0), behavior: 'smooth' })
  }, [spokenId])
  const listenFrom = (ms: number) => {
    if (!player.current) return
    player.current.currentTime = ms / 1000
    setPlayMs(ms)
    void player.current.play()
  }
  const working = current && (['PENDING', 'RUNNING'].includes(current.transcript_status) || current.note_status === 'PENDING')

  return (
    <>
      {removing && (
        <ConfirmDialog title={removing.kind === 'DICTATION' ? 'Xóa bản ghi này?' : 'Xóa cuộc họp này?'} confirmLabel="Xóa hẳn" busy={removeMeeting.isPending} error={removeError ?? undefined}
          onConfirm={() => removeMeeting.mutate(removing.id)} onCancel={() => setRemoving(undefined)}>
          <p><strong>{removing.title}</strong><br />{formatDate(removing.started_at)} · {duration(removing.duration_seconds)}</p>
          <ul>
            <li>Bản ghi âm, bản chữ và meeting note bị xóa hẳn.</li>
            <li>Không khôi phục được.</li>
            {removing.note_items.some((item) => item.intake_id) && <li>{removing.note_items.filter((item) => item.intake_id).length} Intake đã tạo từ note này vẫn được giữ, nhưng không còn mở lại được cuộc họp nguồn.</li>}
          </ul>
        </ConfirmDialog>
      )}
      <PageHeader title="Cuộc họp" helper="Bản ghi âm, bản chữ theo người nói và meeting note do AI tổng hợp. Mỗi lần mở bản chữ hoặc nghe lại được ghi audit." action={<Link className="button button-primary" to="/intakes/new?panel=record"><Mic size={16} /> Ghi âm cuộc họp</Link>} />
      {meetings.error && <ErrorNotice error={meetings.error} onRetry={() => { void meetings.refetch() }} />}
      {error != null && <ErrorNotice error={error} />}
      <div className="segmented meetings-filter" role="group" aria-label="Loại bản ghi">
        <button type="button" aria-pressed={!withSpoken} className={withSpoken ? undefined : 'active'} onClick={() => setWithSpoken(false)}>Cuộc họp</button>
        <button type="button" aria-pressed={withSpoken} className={withSpoken ? 'active' : undefined} title="Gồm cả các lần bấm micro để nói khi tạo Intake" onClick={() => setWithSpoken(true)}>Cả "Nói để nhập"</button>
      </div>
      {meetings.isLoading ? <LoadingBlock /> : (meetings.data || []).length === 0 && !searchParams.get('id') ? (
        <section className="panel"><EmptyState icon={<Mic size={20} />} title="Chưa có cuộc họp nào" text="Bấm Ghi âm cuộc họp để bắt đầu; bản chữ và meeting note sẽ xuất hiện ở đây sau khi kết thúc." /></section>
      ) : (
        <div className="report-layout">
          <nav className="panel report-list" aria-label="Danh sách cuộc họp">
            {meetings.data!.map((meeting) => (
              <button type="button" key={meeting.id} className={meeting.id === activeId ? 'report-row active' : 'report-row'} aria-current={meeting.id === activeId} onClick={() => setSearchParams({ id: meeting.id }, { replace: true })}>
                <strong>{meeting.title}</strong>
                <small>{formatDate(meeting.started_at)} · {duration(meeting.duration_seconds)}</small>
                <span className="report-tags">
                  {meeting.project_name && <span className="status">{meeting.project_name}</span>}
                  {meeting.status === 'RECORDING' && <span className="status report-malformed">Đang ghi</span>}
                  {meeting.status === 'FAILED' && <span className="status status-rejected" title={meeting.transcript_error || undefined}>Lỗi tải lên</span>}
                  {(meeting.part_number || 1) > 1 && <span className="status">Phần {meeting.part_number}</span>}
                  {meeting.kind === 'DICTATION' && <span className="status">Nói để nhập</span>}
                  {meeting.status !== 'RECORDING' && meeting.kind !== 'DICTATION' && <span className={`status ${meeting.note_status === 'DONE' ? 'report-valid' : meeting.note_status === 'FAILED' ? 'report-malformed' : 'report-warning'}`}>Note: {workLabels[meeting.note_status] || meeting.note_status}</span>}
                </span>
              </button>
            ))}
          </nav>
          <div className="report-detail">
            {detail.isLoading || !current ? <LoadingBlock /> : (
              <>
                <section className="panel report-summary">
                  <div>
                    {titleDraft === undefined ? (
                      <h2 className="meeting-title">{current.title}<button type="button" className="icon-button" aria-label="Đổi tên" title="Đổi tên" onClick={() => setTitleDraft(current.title)}><Pencil size={14} /></button></h2>
                    ) : (
                      <form className="meeting-title-edit" onSubmit={(event) => { event.preventDefault(); if (titleDraft.trim()) renameMeeting.mutate() }}>
                        <input autoFocus value={titleDraft} maxLength={200} aria-label="Tên cuộc họp" onChange={(event) => setTitleDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') setTitleDraft(undefined) }} />
                        <button className="button button-primary button-small" disabled={!titleDraft.trim() || renameMeeting.isPending}>{renameMeeting.isPending ? 'Đang lưu…' : 'Lưu'}</button>
                        <button type="button" className="button button-secondary button-small" onClick={() => setTitleDraft(undefined)}>Hủy</button>
                      </form>
                    )}
                    <p>{[formatDate(current.started_at), duration(current.duration_seconds), `Bản chữ: ${workLabel(current.transcript_status, current.transcript_error)}`, `Note: ${workLabel(current.note_status, current.note_error)}`].join(' · ')}</p>
                    <label className="meeting-project">Dự án của cuộc họp
                      <select value={current.project_code || ''} disabled={changeProject.isPending} onChange={(e) => { const code = e.target.value; if (code && (current.note_items.length === 0 || window.confirm(`Chuyển cuộc họp và mọi mục note chưa thành Intake sang dự án "${projects.data?.find((project) => project.code === code)?.name || code}"?`))) changeProject.mutate(code) }}>
                        <option value="" disabled>Chưa chọn dự án…</option>
                        {projects.data?.map((project) => <option key={project.id} value={project.code}>{project.name}</option>)}
                      </select>
                    </label>
                    {current.parts.length > 1 && (
                      <p className="meeting-parts">Các phần: {current.parts.map((part: MeetingPart) => part.id === current.id
                        ? <strong key={part.id}>Phần {part.part_number}</strong>
                        : <Link key={part.id} to={`/meetings?id=${part.id}`} title={part.title}>Phần {part.part_number} · note {workLabels[part.note_status] || part.note_status}</Link>)}</p>
                    )}
                    {current.status === 'FAILED' && <p className="report-gate">Bản ghi này không hoàn tất ({meetingErrorLabels[current.transcript_error || ''] || 'tải lên bị ngắt'}) và không nhận được âm thanh hay chữ nào. Có thể xóa và tải lại tệp.</p>}
                    {current.status === 'FINISHED' && current.transcript_error === 'UPLOAD_STALLED' && <p className="report-gate">Tải lên bị ngắt giữa chừng (tab bị tải lại hoặc đóng): chữ và meeting note làm từ phần đã nhận được.</p>}
                    {current.status === 'RECORDING' && !(recordingNow.phase !== 'idle' && recordingNow.meetingId === current.id) && <p className="report-gate">Bản ghi còn "Đang ghi" nhưng không có trình duyệt nào đang gửi âm thanh (tab đã tải lại hoặc đóng). Nếu đúng vậy, kết thúc để chuyển chữ và tạo note từ phần đã nhận; không thì chờ máy đang ghi gửi tiếp. <button type="button" className="text-button" disabled={finishStuck.isPending} onClick={() => finishStuck.mutate()}>{finishStuck.isPending ? 'Đang kết thúc…' : 'Kết thúc bản ghi dở'}</button></p>}
                    {!current.project_code && <p className="report-gate">Cuộc họp chưa có dự án: chọn dự án để gán cho toàn bộ mục note.</p>}
                    {working && <p className="report-gate">Đang xử lý sau cuộc họp; trang tự cập nhật.</p>}
                    {!current.provider_data_deleted && <p className="report-gate">Bản sao phía ElevenLabs chưa xóa xong; hệ thống sẽ thử lại.</p>}
                  </div>
                  <div className="report-actions">
                    {current.status === 'FINISHED' && current.kind === 'MEETING' && current.audio_available && ['FAILED', 'SKIPPED'].includes(current.transcript_status) && <button className="button button-secondary" type="button" disabled={retryTranscript.isPending} title="Gửi lại tệp cho dịch vụ chuyển chữ" onClick={() => retryTranscript.mutate()}><RotateCcw size={15} /> {retryTranscript.isPending ? 'Đang gửi…' : 'Chuyển chữ lại'}</button>}
                    {current.audio_available && <a className="button button-secondary" href={`/api/v1/meetings/${current.id}/audio?download=true`} download><Download size={15} /> Tải xuống</a>}
                    <button className="icon-button meeting-delete" type="button" aria-label="Xóa cuộc họp" title="Xóa cuộc họp" disabled={removeMeeting.isPending || current.status === 'RECORDING'} onClick={() => { removeMeeting.reset(); setRemoving(current) }}><Trash2 size={16} /></button>
                    {current.audio_available && (audioUrl?.id === current.id
                      ? <audio ref={player} controls src={audioUrl.url} aria-label="Bản ghi âm cuộc họp" onTimeUpdate={(e) => setPlayMs(e.currentTarget.currentTime * 1000)} onSeeked={(e) => setPlayMs(e.currentTarget.currentTime * 1000)} />
                      : <button className="button button-secondary" type="button" disabled={loadAudio.isPending} onClick={() => loadAudio.mutate()}><Eye size={15} /> {loadAudio.isPending ? 'Đang tải…' : 'Nghe lại'}</button>)}
                  </div>
                </section>
                <div className="review-grid report-compare">
                  <section className="panel">
                    <div className="panel-heading"><div><h2>Meeting note</h2>{bulkNote && <small className="muted">{bulkNote}</small>}</div>{proposed.length > 0 && <button className="button button-primary button-small" type="button" disabled={asProposed.isPending || bulk.isPending} title="Việc cần làm, câu hỏi, rủi ro lên bảng Việc; yêu cầu và bug thành Intake để duyệt; quyết định chỉ ghi nhận. Đổi đích từng dòng trước khi bấm." onClick={() => asProposed.mutate()}><Plus size={14} /> {asProposed.isPending ? 'Đang tạo…' : meetingPostMode ? `Đưa tất cả vào lịch (${proposed.length})` : `Tạo theo đề xuất (${proposed.length})`}</button>}{picked.size > 0 && <button className="button button-secondary button-small" type="button" disabled={bulk.isPending} onClick={() => bulk.mutate()}><Plus size={14} /> {bulk.isPending ? 'Đang tạo…' : `Tạo Intake cho ${picked.size} mục`}</button>}<button className="button button-secondary button-small" type="button" disabled={regenerate.isPending || current.note_status === 'PENDING' || current.segments.length === 0} onClick={() => { if (window.confirm('Tạo lại meeting note? Các mục chưa thành Intake sẽ được thay bằng bản mới.')) regenerate.mutate() }}><RotateCcw size={14} /> Tạo lại</button></div>
                    {current.note_status === 'PENDING' || (current.note_status === 'NONE' && working) ? <LoadingBlock label="AI đang tổng hợp meeting note…" /> : current.note_status !== 'DONE' ? (
                      <EmptyState icon={<CircleHelp size={20} />} title={current.note_status === 'FAILED' ? 'AI chưa tạo được meeting note' : 'Chưa có meeting note'} text={current.note_status === 'FAILED' ? 'Bấm "Tạo lại" để thử lần nữa.' : 'Meeting note được tạo sau khi cuộc họp kết thúc và có bản chữ.'} />
                    ) : (
                      <div className="meeting-note">
                        <div className="note-summary">
                          <h3>Tóm tắt</h3>
                          {summaryDraft === undefined ? (
                            <>{summaryLines.length > 1 ? <ul>{summaryLines.map((line) => <li key={line}>{line}</li>)}</ul> : <p>{current.note_summary}</p>}<button type="button" className="text-button" onClick={() => setSummaryDraft(current.note_summary || '')}><Pencil size={13} /> Sửa tóm tắt</button></>
                          ) : (
                            <><textarea rows={5} aria-label="Tóm tắt cuộc họp" placeholder="Mỗi dòng một ý chính" value={summaryDraft} onChange={(e) => setSummaryDraft(e.target.value)} /><div className="report-edit-actions"><button type="button" className="button button-secondary button-small" onClick={() => setSummaryDraft(undefined)}>Hủy</button><button type="button" className="button button-primary button-small" disabled={!summaryDraft.trim() || saveSummary.isPending} onClick={() => saveSummary.mutate()}>Lưu tóm tắt</button></div></>
                          )}
                        </div>
                        {noteSections.length === 0 && <p className="muted note-empty">Không có mục nào được ghi lại.</p>}
                        {!bySubject && noteSections.length > 0 && <p className="note-old-format">Note này viết theo cách cũ (chia theo loại, hay lặp ý). Bấm "Tạo lại" để có bản gọn theo chủ đề.</p>}
                        {current.parts.filter((part: MeetingPart) => part.id !== current.id).map((part: MeetingPart) => <PartNote key={part.id} part={part} projects={projects.data || []} onError={setError} onUpdated={updated} />)}
                        {noteSections.map((section) => (
                          <details className="note-topic" key={section.title} open>
                            <summary><span>{section.title}</span><small>{section.items.length} mục</small></summary>
                            <ol>{section.items.map((item) => <MeetingNoteRow key={item.id} item={item} meetingId={current.id} meetingProject={current.project_code} projects={projects.data || []} onUpdated={updated} onError={setError} members={projectMembers} meetingDate={meetingDate} choice={choiceOf(item)} onChoice={(id, next) => setChoices((prev) => ({ ...prev, [id]: next }))} postMode={meetingPostMode} picked={picked.has(item.id)} onPick={togglePick} />)}</ol>
                          </details>
                        ))}
                      </div>
                    )}
                  </section>
                  <section className="panel">
                    <div className="panel-heading"><div><h2>Bản chữ</h2></div><span className="ai-tag">{current.transcript_source === 'BATCH' ? 'Đã tách người nói' : current.transcript_source === 'REALTIME' ? 'Bản thô realtime' : 'Chưa có'}</span></div>
                    {current.speakers.length > 0 && (
                      <form className="speaker-names" onSubmit={(event) => { event.preventDefault(); if (Object.keys(names).length > 0) rename.mutate() }}>
                        {current.speakers.map((speaker) => <label key={speaker.label}>{speaker.label}<input value={names[speaker.label] ?? speaker.name ?? ''} onChange={(e) => setNames({ ...names, [speaker.label]: e.target.value })} placeholder="Tên thật" maxLength={80} /></label>)}
                        <button className={Object.keys(names).length > 0 ? 'button button-primary' : 'button button-secondary'} disabled={Object.keys(names).length === 0 || rename.isPending} title="Tên được thay cho nhãn Thành viên trong bản chữ">{rename.isPending ? 'Đang lưu…' : rename.isSuccess && Object.keys(names).length === 0 ? <><Check size={15} /> Đã lưu</> : 'Lưu tên'}</button>
                      </form>
                    )}
                    {current.segments.length === 0 ? <EmptyState icon={<CircleHelp size={20} />} title="Chưa có bản chữ" text={current.audio_available ? 'Bản chữ sẽ có sau khi xử lý xong.' : 'Bản chữ và bản ghi đã bị xóa theo thời hạn lưu trữ hoặc cuộc họp không có âm thanh.'} /> : (
                      <ol className="report-items meeting-transcript" ref={transcriptList}>
                        {current.segments.map((segment) => {
                          const canJump = listening != null && segment.start_ms != null
                          return (
                            <li key={segment.id} data-segment={segment.id} className={segment.id === spokenId ? 'is-spoken' : undefined} aria-current={segment.id === spokenId ? 'true' : undefined}>
                              <small>
                                {segment.speaker_name || segment.speaker_label}
                                {(segment.speaker_name || segment.speaker_label) && segment.start_ms != null ? ' · ' : ''}
                                {canJump ? <button className="segment-time" type="button" title="Nghe từ đoạn này" onClick={() => listenFrom(segment.start_ms as number)}>{clock(segment.start_ms)}</button> : clock(segment.start_ms)}
                              </small>
                              <p>{segment.text}</p>
                            </li>
                          )
                        })}
                      </ol>
                    )}
                  </section>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  )
}

const projectKinds: { value: ProjectKind; label: string; hint: string; gitlab: boolean }[] = [
  { value: 'IDEA', label: 'Ý tưởng', hint: 'Mới ở mức ý tưởng. Gom yêu cầu trong Intake và theo dõi việc trên bảng Việc. Không vào Daily Planning.', gitlab: false },
  { value: 'NON_CODE', label: 'Marketing và nội dung', hint: 'Bài đăng, video, email, vận hành. Đội làm trên Tuần này, Bài và Chờ duyệt với từ của đội; không có Issue, GitLab hay Daily Planning.', gitlab: false },
  { value: 'SOFTWARE', label: 'Phần mềm', hint: 'Có code. Việc cần bàn trước nằm trên bảng Việc; giao việc trên GitLab của công ty hoặc GitHub của khách hàng; được lập kế hoạch trong Daily Planning.', gitlab: true },
]
const projectKindLabels: Record<string, string> = { IDEA: 'Ý tưởng', NON_CODE: 'Marketing và nội dung', SOFTWARE: 'Phần mềm' }
const probeErrors: Record<string, string> = {
  QUEUE_UNAVAILABLE: 'Hàng đợi đang không nhận việc. Thử lại sau ít phút.',
  GITLAB_NOT_CONFIGURED: 'GitLab chưa được cấu hình trên máy chủ.',
  GITLAB_AUTH_FAILED: 'Token GitLab không có quyền truy cập.',
  GITLAB_MAPPING_NOT_FOUND: 'Không tìm thấy dự án GitLab này, hoặc token không thấy nó.',
  GITHUB_MAPPING_NOT_FOUND: 'Không tìm thấy repository GitHub này, hoặc token không có quyền với nó.',
  GITHUB_AUTH_FAILED: 'Token GitHub không hợp lệ, đã hết hạn hoặc không đủ quyền.',
  GITHUB_TOKEN_NOT_FOUND: 'Máy chủ chưa có token này. Thêm vào .env.github rồi khởi động lại integration-worker.',
  GITHUB_RATE_LIMITED: 'GitHub đang giới hạn số lần gọi. Thử lại sau ít phút.',
  PROBE_TIMEOUT: 'Chưa có phản hồi sau 30 giây. Kiểm tra integration worker rồi thử lại.',
}

type LinkSystem = 'GITLAB' | 'GITHUB'
const linkTitles: Record<LinkSystem, string> = { GITLAB: 'GitLab', GITHUB: 'GitHub' }

async function runProbe(system: LinkSystem, action: 'LIST' | 'CHECK' | 'MEMBERS' | 'TOKENS', reference?: string, tokenRef?: string): Promise<IntegrationProbe> {
  let probe = await api<IntegrationProbe>('/projects/integration-probes', { method: 'POST', body: JSON.stringify({ system, action, reference: reference || null, token_ref: tokenRef || null }) })
  for (let attempt = 0; probe.status === 'PENDING' && attempt < 30; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 1000))
    probe = await api<IntegrationProbe>(`/projects/integration-probes/${probe.id}`)
  }
  if (probe.status === 'PENDING') throw new Error(probeErrors.PROBE_TIMEOUT)
  if (probe.status === 'FAILED') throw new Error(probeErrors[probe.error_code || ''] || `Không kết nối được (${probe.error_code}).`)
  return probe
}

interface VerifiedLink { reference: string; probeId: string; name: string; url: string | null; tokenRef?: string }

function LinkPicker({ system, required, value, onChange, initialToken }: { system: LinkSystem; required: boolean; value?: VerifiedLink; onChange: (link?: VerifiedLink) => void; initialToken?: string | null }) {
  const title = linkTitles[system]
  const [reference, setReference] = useState(value?.reference || '')
  const [tokenRef, setTokenRef] = useState(value?.tokenRef || initialToken || '')
  // GitHub: each customer repository has its own token; only the variable names are listed here.
  const tokens = useQuery({
    queryKey: ['github-token-names'], enabled: system === 'GITHUB', staleTime: 60_000, retry: false,
    queryFn: async () => { const probe = await runProbe('GITHUB', 'TOKENS'); return Array.isArray(probe.result) ? probe.result.map((row) => row.id) : [] },
  })
  const needsToken = system === 'GITHUB' && !tokenRef
  const [options, setOptions] = useState<RemoteProject[]>()
  const [error, setError] = useState<unknown>()
  const list = useMutation({
    mutationFn: () => runProbe(system, 'LIST', reference.includes('/') ? undefined : reference.trim(), tokenRef),
    onSuccess: (probe) => { setError(undefined); setOptions(Array.isArray(probe.result) ? probe.result : []) },
    onError: setError,
  })
  const check = useMutation({
    mutationFn: () => runProbe(system, 'CHECK', reference.trim(), tokenRef),
    onSuccess: (probe) => {
      setError(undefined)
      const found = probe.result as RemoteProject
      // A GitHub probe carries "TOKEN|owner/repository"; the link itself is just the repository.
      const cleaned = system === 'GITHUB' ? found.id : probe.reference || reference.trim()
      onChange({ reference: cleaned, probeId: probe.id, name: found.name, url: found.url, tokenRef: system === 'GITHUB' ? tokenRef : undefined })
    },
    onError: (checkError) => { onChange(undefined); setError(checkError) },
  })
  const busy = list.isPending || check.isPending

  return (
    <section className="link-picker">
      <header><h3>{title}</h3><span className={required ? 'status report-warning' : 'status'}>{required ? 'Bắt buộc' : 'Tùy chọn'}</span></header>
      {value ? (
        <div className="link-verified">
          <span><CircleCheck size={16} /> Đã kiểm tra kết nối: <strong>{value.name}</strong></span>
          <small>{value.reference}{value.tokenRef ? ` · token ${value.tokenRef}` : ''}</small>
          <button className="button button-secondary button-small" type="button" onClick={() => { onChange(undefined); setOptions(undefined) }}>Chọn dự án khác</button>
        </div>
      ) : (
        <>
          <p className="field-help">{system === 'GITLAB' ? 'Chọn repository đã có, hoặc dán đường dẫn dạng nhóm/dự-án hay URL của nó. Gõ vài chữ rồi bấm lấy danh sách để tìm.' : 'Repository thuộc GitHub của khách hàng. Chọn token dành riêng cho khách này, rồi chọn hoặc dán repository dạng chủ-sở-hữu/tên hay URL của nó.'}</p>
          {system === 'GITHUB' && (
            <label>Token của khách hàng
              <select value={tokenRef} onChange={(e) => { setTokenRef(e.target.value); setOptions(undefined) }}>
                <option value="" disabled>{tokens.isLoading ? 'Đang lấy danh sách token…' : 'Chọn token…'}</option>
                {tokenRef && !(tokens.data || []).includes(tokenRef) && <option value={tokenRef}>{tokenRef}</option>}
                {(tokens.data || []).map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
              <small className="field-help">{tokens.error ? 'Chưa lấy được danh sách token từ integration worker.' : tokens.data && tokens.data.length === 0 ? 'Máy chủ chưa có token GitHub nào. Thêm một biến GITHUB_TOKEN_<TÊN> vào file .env.github rồi khởi động lại integration-worker.' : 'Chỉ tên biến được hiển thị; giá trị token nằm trong .env.github trên máy chủ và không bao giờ đi qua màn hình này.'}</small>
            </label>
          )}
          <label>{system === 'GITLAB' ? 'Đường dẫn dự án GitLab' : 'Repository GitHub'}
            <input value={reference} onChange={(e) => setReference(e.target.value)} placeholder={system === 'GITLAB' ? '2026/ten-du-an' : 'ten-khach/ten-repository'} />
          </label>
          {options && (options.length === 0 ? <p className="field-help">Không có dự án nào khớp mà token nhìn thấy.</p> : (
            <label>Dự án tìm thấy
              <select value="" onChange={(e) => setReference(e.target.value)}>
                <option value="" disabled>Chọn trong {options.length} dự án…</option>
                {options.map((option) => <option key={option.id} value={option.id}>{option.name}{option.identifier ? ` (${option.identifier})` : ''}</option>)}
              </select>
            </label>
          ))}
          <div className="link-actions">
            <button className="button button-secondary button-small" type="button" disabled={busy || needsToken} onClick={() => list.mutate()}>{list.isPending ? 'Đang lấy…' : `Lấy danh sách từ ${title}`}</button>
            <button className="button button-primary button-small" type="button" disabled={busy || needsToken || !reference.trim()} onClick={() => check.mutate()}>{check.isPending ? 'Đang kiểm tra…' : 'Kiểm tra kết nối'}</button>
          </div>
          {error != null && <ErrorNotice error={error} />}
        </>
      )}
    </section>
  )
}

function slugify(value: string) {
  return value.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/gi, 'd').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').replace(/^[^a-z]+/, '').slice(0, 32)
}

function intakeKeyFrom(value: string) {
  const words = slugify(value).split('-').filter(Boolean)
  const key = words.length >= 3 ? words.map((word) => word[0]).join('') : words.join('')
  return key.replace(/[^a-z]/g, '').slice(0, 3).toUpperCase()
}

function DeliveryChoice({ value, onChange }: { value: 'GITLAB' | 'GITHUB'; onChange: (value: 'GITLAB' | 'GITHUB') => void }) {
  const options = [
    { value: 'GITLAB' as const, label: 'GitLab của công ty', hint: 'Issue được tạo đầy đủ; kế hoạch đã duyệt ghi người phụ trách, milestone và hạn chót lên GitLab.' },
    { value: 'GITHUB' as const, label: 'GitHub của khách hàng', hint: 'Issue chỉ gồm tiêu đề và mô tả vì khách hàng đọc được; kế hoạch đã duyệt chỉ lưu trong Intake, không ghi gì lên GitHub.' },
  ]
  return (
    <fieldset className="option-list">
      <legend>Nơi giao việc</legend>
      {options.map((entry) => (
        <label key={entry.value} className={value === entry.value ? 'option active' : 'option'}>
          <input type="radio" name="delivery-system" value={entry.value} checked={value === entry.value} onChange={() => onChange(entry.value)} />
          <span><strong>{entry.label}</strong><small>{entry.hint}</small></span>
        </label>
      ))}
    </fieldset>
  )
}

function ProjectWizardPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [step, setStep] = useState(1)
  const [name, setName] = useState('')
  const [code, setCode] = useState<string>()
  const [intakeKey, setIntakeKey] = useState<string>()
  const [kind, setKind] = useState<ProjectKind>('IDEA')
  const [gitlab, setGitlab] = useState<VerifiedLink>()
  const [github, setGithub] = useState<VerifiedLink>()
  const [delivery, setDelivery] = useState<'GITLAB' | 'GITHUB'>('GITLAB')
  const [error, setError] = useState<unknown>()
  const rule = projectKinds.find((entry) => entry.value === kind)!
  const deliveryLink = delivery === 'GITHUB' ? github : gitlab
  const finalCode = code ?? slugify(name)
  const finalKey = (intakeKey ?? intakeKeyFrom(name)).toUpperCase()
  const basicsValid = name.trim().length > 0 && /^[a-z][a-z0-9-]{1,31}$/.test(finalCode) && /^[A-Z]{2,8}$/.test(finalKey)
  const linksValid = !rule.gitlab || Boolean(deliveryLink)
  const steps = ['Thông tin', 'Loại dự án', 'Liên kết', 'Xác nhận']

  const create = useMutation({
    mutationFn: () => api<Project>('/projects', {
      method: 'POST',
      body: JSON.stringify({
        name: name.trim(), code: finalCode, intake_key: finalKey, kind,
        gitlab_project_path: rule.gitlab && delivery === 'GITLAB' ? gitlab?.reference || null : null,
        gitlab_probe_id: rule.gitlab && delivery === 'GITLAB' ? gitlab?.probeId || null : null,
        github_repository: rule.gitlab && delivery === 'GITHUB' ? github?.reference || null : null,
        github_token_ref: rule.gitlab && delivery === 'GITHUB' ? github?.tokenRef || null : null,
        github_probe_id: rule.gitlab && delivery === 'GITHUB' ? github?.probeId || null : null,
      }),
    }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['projects'] }); navigate('/settings/projects') },
    onError: setError,
  })

  return (
    <>
      <Link className="back-link" to="/settings/projects"><ArrowLeft size={15} /> Dự án</Link>
      <SectionHeader title="Tạo dự án" />
      <ol className="wizard-steps" aria-label="Các bước tạo dự án">
        {steps.map((label, index) => <li key={label} className={index + 1 === step ? 'active' : index + 1 < step ? 'done' : ''} aria-current={index + 1 === step ? 'step' : undefined}><span>{index + 1 < step ? <Check size={13} /> : index + 1}</span>{label}</li>)}
      </ol>
      <section className="panel wizard-panel">
        {step === 1 && (
          <div className="wizard-body">
            <label><span className="req-label">Tên dự án<Req /></span><input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ví dụ: Content Marketing" autoFocus /></label>
            <div className="wizard-row">
              <label><span className="req-label">Mã dự án<Req /></span><input value={finalCode} onChange={(e) => setCode(e.target.value.toLowerCase())} placeholder="content-marketing" /><small className="field-help">Chữ thường, số, gạch nối. Không đổi được sau khi tạo.</small></label>
              <label><span className="req-label">Mã Intake<Req /></span><input value={finalKey} onChange={(e) => setIntakeKey(e.target.value.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 8))} placeholder="CNT" /><small className="field-help">2 đến 8 chữ in hoa, đứng đầu mã Intake: {finalKey || 'CNT'}-26W41-001.</small></label>
            </div>
          </div>
        )}
        {step === 2 && (
          <fieldset className="option-list wizard-body">
            <legend>Dự án này thuộc loại nào?</legend>
            {projectKinds.map((entry) => (
              <label key={entry.value} className={kind === entry.value ? 'option active' : 'option'}>
                <input type="radio" name="project-kind" value={entry.value} checked={kind === entry.value} onChange={() => setKind(entry.value)} />
                <span><strong>{entry.label}</strong><small>{entry.hint}</small></span>
              </label>
            ))}
            <p className="field-help">Đổi loại được về sau, ví dụ khi một ý tưởng bắt đầu có code thì bổ sung GitLab.</p>
          </fieldset>
        )}
        {step === 3 && (
          <div className="wizard-body">
            {rule.gitlab ? (
              <>
                <DeliveryChoice value={delivery} onChange={setDelivery} />
                {delivery === 'GITLAB'
                  ? <LinkPicker key="gitlab" system="GITLAB" required value={gitlab} onChange={setGitlab} />
                  : <LinkPicker key="github" system="GITHUB" required value={github} onChange={setGithub} />}
              </>
            ) : <p className="notice notice-warn">Loại "{rule.label}" không có nơi giao việc (GitLab hay GitHub), nên dự án sẽ không xuất hiện trong Daily Planning.</p>}
          </div>
        )}
        {step === 4 && (
          <div className="wizard-body">
            <dl className="wizard-summary">
              <div><dt>Tên</dt><dd>{name.trim()}</dd></div>
              <div><dt>Mã dự án</dt><dd>{finalCode}</dd></div>
              <div><dt>Mã Intake</dt><dd>{finalKey}</dd></div>
              <div><dt>Loại</dt><dd>{rule.label}</dd></div>
              <div><dt>Nơi giao việc</dt><dd>{rule.gitlab && deliveryLink ? `${linkTitles[delivery]}: ${deliveryLink.name}` : 'Không liên kết'}</dd></div>
              {rule.gitlab && delivery === 'GITHUB' && <div><dt>Token</dt><dd>{github?.tokenRef}</dd></div>}
              <div><dt>Daily Planning</dt><dd>{rule.gitlab ? 'Có' : 'Không'}</dd></div>
            </dl>
            {error != null && <ErrorNotice error={error} />}
          </div>
        )}
        <footer className="wizard-foot">
          <button className="button button-secondary" type="button" disabled={step === 1 || create.isPending} onClick={() => { setError(undefined); setStep(step - 1) }}>Quay lại</button>
          {step < 4
            ? <button className="button button-primary" type="button" disabled={(step === 1 && !basicsValid) || (step === 3 && !linksValid)} onClick={() => setStep(step + 1)}>Tiếp tục</button>
            : <button className="button button-primary" type="button" disabled={create.isPending} onClick={() => create.mutate()}>{create.isPending ? 'Đang tạo…' : 'Tạo dự án'}</button>}
        </footer>
      </section>
    </>
  )
}

function ProjectEditPage() {
  const { code = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const project = projects.data?.find((entry) => entry.code === code)
  const [name, setName] = useState<string>()
  const [kind, setKind] = useState<ProjectKind>()
  const [status, setStatus] = useState<string>()
  const [gitlab, setGitlab] = useState<VerifiedLink>()
  const [github, setGithub] = useState<VerifiedLink>()
  const [chosenDelivery, setChosenDelivery] = useState<'GITLAB' | 'GITHUB'>('GITLAB')
  const [changing, setChanging] = useState<{ GITLAB?: boolean; GITHUB?: boolean }>({})
  const [error, setError] = useState<unknown>()

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<Project>(`/projects/${code}`, { method: 'PATCH', body: JSON.stringify(body) }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['projects'] }); navigate('/settings/projects') },
    onError: setError,
  })

  if (projects.isLoading) return <LoadingBlock />
  if (!project) return <><Link className="back-link" to="/settings/projects"><ArrowLeft size={15} /> Dự án</Link><section className="panel"><EmptyState icon={<Search size={20} />} title="Không tìm thấy dự án" text="Dự án này không tồn tại hoặc đã đổi mã." /></section></>

  const finalName = name ?? project.name
  const finalKind = kind ?? project.kind
  const finalStatus = status ?? project.status
  const rule = projectKinds.find((entry) => entry.value === finalKind)!
  // A project keeps the delivery system it already has; a project without one chooses here.
  const delivery = (project.delivery_system as 'GITLAB' | 'GITHUB' | null) ?? chosenDelivery
  const hasDelivery = delivery === 'GITHUB' ? Boolean(github || project.github_repository) : Boolean(gitlab || project.gitlab_project_id)
  const missing = [rule.gitlab && !hasDelivery ? linkTitles[delivery] : null].filter(Boolean)
  const body: Record<string, unknown> = {}
  if (finalName.trim() !== project.name) body.name = finalName.trim()
  if (finalKind !== project.kind) body.kind = finalKind
  if (finalStatus !== project.status) body.status = finalStatus
  if (gitlab && rule.gitlab && delivery === 'GITLAB') { body.gitlab_project_path = gitlab.reference; body.gitlab_probe_id = gitlab.probeId }
  if (github && rule.gitlab && delivery === 'GITHUB') { body.github_repository = github.reference; body.github_token_ref = github.tokenRef; body.github_probe_id = github.probeId }
  const dirty = Object.keys(body).length > 0
  const isCatchAll = project.code === 'other'

  const linkSection = (system: LinkSystem, allowed: boolean, required: boolean, currentId: string | null, currentUrl: string | null, enabled: boolean, value: VerifiedLink | undefined, onChange: (link?: VerifiedLink) => void) => {
    const title = linkTitles[system]
    if (!allowed) {
      return currentId
        ? <p className="notice notice-warn">Loại "{rule.label}" không dùng {title}. Liên kết {title} hiện có ({currentId}) được giữ lại nhưng dự án sẽ không được lập kế hoạch.</p>
        : null
    }
    if (currentId && !changing[system] && !value) {
      return (
        <section className="link-picker">
          <header><h3>{title}</h3><span className="status report-valid">Đang liên kết</span></header>
          <div className="link-verified">
            <small>{currentUrl ? <a href={currentUrl} target="_blank" rel="noreferrer">{currentId}</a> : currentId}{!enabled ? ' · chưa bật đồng bộ' : ''}{system === 'GITHUB' && project.github_token_ref ? ` · token ${project.github_token_ref}` : ''}</small>
            <button className="button button-secondary button-small" type="button" onClick={() => setChanging({ ...changing, [system]: true })}>Đổi liên kết</button>
          </div>
        </section>
      )
    }
    return <LinkPicker key={system} system={system} required={required} value={value} onChange={onChange} initialToken={system === 'GITHUB' ? project.github_token_ref : undefined} />
  }

  return (
    <>
      <Link className="back-link" to="/settings/projects"><ArrowLeft size={15} /> Dự án</Link>
      <SectionHeader title={`Sửa dự án ${project.name}`} />
      <section className="panel wizard-panel">
        <div className="wizard-body">
          <label>Tên dự án<input value={finalName} onChange={(e) => setName(e.target.value)} /></label>
          <div className="wizard-row">
            <label>Mã dự án<input value={project.code} disabled /><small className="field-help">Không đổi được sau khi tạo.</small></label>
            <label>Mã Intake<input value={project.intake_key} disabled /><small className="field-help">Đã nằm trong mã của các Intake hiện có.</small></label>
          </div>
          <fieldset className="option-list">
            <legend>Loại dự án</legend>
            {projectKinds.map((entry) => (
              <label key={entry.value} className={finalKind === entry.value ? 'option active' : 'option'}>
                <input type="radio" name="project-kind" value={entry.value} checked={finalKind === entry.value} disabled={isCatchAll} onChange={() => setKind(entry.value)} />
                <span><strong>{entry.label}</strong><small>{entry.hint}</small></span>
              </label>
            ))}
            {isCatchAll && <p className="field-help">"Dự án khác" là nơi gom việc ngoài các dự án đã khai báo, nên giữ loại Ý tưởng và luôn hoạt động.</p>}
          </fieldset>
          {rule.gitlab && !project.delivery_system && <DeliveryChoice value={chosenDelivery} onChange={setChosenDelivery} />}
          {delivery === 'GITHUB'
            ? linkSection('GITHUB', rule.gitlab, true, project.github_repository, project.github_project_url, project.github_enabled, github, setGithub)
            : linkSection('GITLAB', rule.gitlab, true, project.gitlab_project_id, project.gitlab_project_url, project.gitlab_enabled, gitlab, setGitlab)}
          {!isCatchAll && (
            <label>Trạng thái
              <select value={finalStatus} onChange={(e) => setStatus(e.target.value)}>
                <option value="ACTIVE">Đang hoạt động</option>
                <option value="INACTIVE">Ngừng hoạt động</option>
              </select>
              {finalStatus === 'INACTIVE' && <small className="field-help">Dự án ngừng hoạt động không nhận Intake, cuộc họp hay kế hoạch mới; dữ liệu cũ được giữ nguyên.</small>}
            </label>
          )}
          {missing.length > 0 && <p className="notice notice-warn">Loại "{rule.label}" cần liên kết {missing.join(' và ')}. Chọn dự án và kiểm tra kết nối trước khi lưu.</p>}
          {error != null && <ErrorNotice error={error} />}
        </div>
        <footer className="wizard-foot">
          <Link className="button button-secondary" to="/settings/projects">Hủy</Link>
          <button className="button button-primary" type="button" disabled={!dirty || missing.length > 0 || !finalName.trim() || save.isPending} onClick={() => { if (body.status === 'INACTIVE' && !window.confirm(`Ngừng hoạt động dự án "${project.name}"? Dự án sẽ không nhận Intake, cuộc họp hay kế hoạch mới.`)) return; setError(undefined); save.mutate(body) }}>{save.isPending ? 'Đang lưu…' : 'Lưu thay đổi'}</button>
        </footer>
      </section>
      <ProjectBriefPanel project={project} />
      <ProjectReportCodesPanel project={project} />
      <ProjectContextPanel project={project} />
      <ProjectTeamPanel project={project} />
    </>
  )
}

// What the product is, in the team's own words. AI reads it with every request of the project (ADR-0032), unless the
// approved context pack supplies sections 1 and 2 instead; then this field is the fallback (FR-CTX-05).
type ProjectBriefState = { brief: string; ai_source: 'PACK' | 'BRIEF'; pack_approved_at: string | null; pack_sections: string[] }
function ProjectBriefPanel({ project }: { project: Project }) {
  const queryClient = useQueryClient()
  const stored = useQuery({ queryKey: ['project-brief', project.id], queryFn: () => api<ProjectBriefState>(`/projects/${project.id}/brief`) })
  const [text, setText] = useState<string>()
  const [saved, setSaved] = useState(false)
  const value = text ?? stored.data?.brief ?? ''
  const usesPack = stored.data?.ai_source === 'PACK'
  const save = useMutation({
    mutationFn: () => api<ProjectBriefState>(`/projects/${project.id}/brief`, { method: 'PUT', body: JSON.stringify({ brief: value }) }),
    onSuccess: (next) => { queryClient.setQueryData(['project-brief', project.id], next); setText(undefined); setSaved(true); window.setTimeout(() => setSaved(false), 2500) },
  })
  const dirty = text !== undefined && text !== (stored.data?.brief ?? '')
  return (
    <section className="panel project-brief">
      <div className="panel-heading"><div><h2>Ngữ cảnh cho AI</h2></div><span className="muted">{usesPack ? 'Nguồn: hồ sơ ngữ cảnh' : `${value.length}/4000`}</span></div>
      <p className="field-help">AI đọc ngữ cảnh của dự án mỗi khi chuẩn hóa một yêu cầu, để gọi đúng tên module, màn hình và thuật ngữ của team. Nguồn theo thứ tự ưu tiên: mục 1 và 2 của hồ sơ ngữ cảnh trong repo khi hồ sơ đã được duyệt; nếu chưa, ô tự do bên dưới. Không viết mật khẩu, khóa hay dữ liệu khách hàng: nội dung được gửi tới nhà cung cấp AI.</p>
      {stored.error != null && <ErrorNotice error={stored.error} onRetry={() => { void stored.refetch() }} />}
      {save.error != null && <ErrorNotice error={save.error} />}
      {stored.data != null && (usesPack ? (
        <p className="ai-source-note ai-source-pack" role="status">
          <strong>AI đang đọc hồ sơ ngữ cảnh</strong> ({(stored.data.pack_sections ?? []).join(' và ') || 'mục 1 và 2'}; duyệt lúc {stored.data.pack_approved_at ? new Date(stored.data.pack_approved_at).toLocaleString('vi-VN') : 'chưa rõ'}). Ô tự do bên dưới không được gửi.
          Muốn AI gọi tên module hay thuật ngữ mới: sửa <code>docs/agent/CONTEXT.md</code> trong repo bằng merge request, bấm "Đọc lại từ repo" ở khối Hồ sơ ngữ cảnh rồi duyệt bản mới. Ô tự do chỉ được dùng lại khi bản mới nhất của hồ sơ chưa duyệt hoặc thiếu mục 1 và 2.
        </p>
      ) : (
        <p className="ai-source-note ai-source-brief" role="status">
          <strong>AI đang đọc ô tự do này</strong> vì dự án chưa có hồ sơ ngữ cảnh đã duyệt với mục 1 và 2. Khi hồ sơ trong repo được đọc và duyệt (khối Hồ sơ ngữ cảnh bên dưới), Intake tự chuyển sang hồ sơ và bỏ qua ô này; lúc đó không cần giữ hai bản giống nhau.
        </p>
      ))}
      <textarea rows={usesPack ? 5 : 9} aria-label="Ngữ cảnh cho AI" maxLength={4000} value={value} disabled={stored.isLoading} onChange={(event) => setText(event.target.value)}
        placeholder={'Sản phẩm là gì, cho ai dùng.\nCác module và màn hình chính, mỗi dòng một cái, kèm một câu nó làm gì.\nCác vai trò người dùng.\nTừ riêng của team và nghĩa của nó.\nNhững thứ dễ nhầm với nhau.'} />
      <div className="project-brief-foot">
        <span className="field-help">Ngoài ngữ cảnh này, AI còn nhận thuật ngữ của dự án (Cài đặt → Thuật ngữ) và tiêu đề các Issue đang mở.</span>
        <button type="button" className="button button-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>{save.isPending ? 'Đang lưu…' : saved ? 'Đã lưu' : 'Lưu ngữ cảnh'}</button>
      </div>
    </section>
  )
}

const contextBandWords: Record<string, string> = { FULL: 'Đủ', PARTIAL: 'Cần bổ sung', MISSING: 'Chưa đủ' }
const contextErrorWords: Record<string, string> = {
  NO_MAIN_REPO: 'dự án chưa có repo GitLab hoặc GitHub đang bật', CONTEXT_FILE_MISSING: 'repo chưa có tệp docs/agent/CONTEXT.md',
  GITLAB_READ_NOT_CONFIGURED: 'server chưa có token đọc GitLab (GITLAB_REPO_READ_TOKEN)', GITHUB_READ_NOT_CONFIGURED: 'server chưa có token đọc GitHub cho repo này',
  GITLAB_READ_FORBIDDEN: 'token đọc không được vào repo này', GITHUB_READ_FORBIDDEN: 'token đọc không được vào repo này',
  GITLAB_PROJECT_NOT_FOUND: 'không thấy repo trên GitLab', GITLAB_UNAVAILABLE: 'GitLab không trả lời', GITHUB_UNAVAILABLE: 'GitHub không trả lời',
}

// The project's context pack (ADR-0063): read from docs/agent/CONTEXT.md in the repository, scored, approved by the CTO.
function ProjectContextPanel({ project }: { project: Project }) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const pack = useQuery({ queryKey: ['project-context', project.id], queryFn: () => api<ProjectContext>(`/projects/${project.id}/context`), refetchInterval: (query) => query.state.data?.fetched_at ? false : 15_000 })
  const [pasting, setPasting] = useState(false)
  const [text, setText] = useState('')
  const [note, setNote] = useState<string | null>(null)
  const read = useMutation({ mutationFn: () => api<{ queued: boolean }>(`/projects/${project.id}/context/read`, { method: 'POST' }), onSuccess: (result) => { setNote(result.queued ? 'Đã gửi lệnh đọc; vài chục giây nữa tải lại.' : 'Không gửi được lệnh đọc (worker chưa chạy).'); window.setTimeout(() => { void pack.refetch() }, 8000) } })
  const paste = useMutation({ mutationFn: () => api<ProjectContext>(`/projects/${project.id}/context`, { method: 'PUT', body: JSON.stringify({ content: text }) }), onSuccess: (result) => { queryClient.setQueryData(['project-context', project.id], result); setPasting(false); setText(''); setNote('Đã lưu hồ sơ dán tay.') } })
  const approve = useMutation({ mutationFn: () => api<ProjectContext>(`/projects/${project.id}/context/approve`, { method: 'POST' }), onSuccess: (result) => { queryClient.setQueryData(['project-context', project.id], result); setNote('Đã duyệt bản này.') } })
  const suggestions = useQuery({ queryKey: ['project-context-suggestions', project.id], queryFn: () => api<ProjectContextSuggestion[]>(`/projects/${project.id}/context/suggestions`) })
  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: 'applied' | 'dismissed' }) => api<ProjectContextSuggestion>(`/projects/${project.id}/context/suggestions/${id}/${decision}`, { method: 'POST' }),
    onSuccess: () => { void suggestions.refetch(); void pack.refetch() },
  })
  const pendingSuggestions = (suggestions.data || []).filter((row) => row.status === 'PENDING')
  const decidedSuggestions = (suggestions.data || []).filter((row) => row.status !== 'PENDING').slice(0, 5)
  const data = pack.data
  const hasRepo = project.gitlab_enabled || project.github_enabled
  const sections = data ? Object.values(data.sections).sort((a, b) => a.number - b.number) : []
  return (
    <section className="panel project-brief project-context">
      <div className="panel-heading"><div><h2>Hồ sơ ngữ cảnh cho agent</h2></div>{data && <span className={`status context-band band-${data.band.toLowerCase()}`}>{contextBandWords[data.band] || data.band} · {data.score}/100</span>}</div>
      <p className="field-help">Tệp <code>docs/agent/CONTEXT.md</code> trong repo chính của dự án, tám mục theo <a href="/api/v1/agent-commands/files/context-template.md" target="_blank" rel="noreferrer">khuôn</a>; Intake đọc lúc 06:50 mỗi ngày và khi bấm "Đọc lại", chấm điểm theo quy tắc cố định. Mục 1 và 2 được gửi cho AI khi chuẩn hóa yêu cầu sau khi CTO duyệt bản hiện hành (thay ô "Ngữ cảnh cho AI" ở trên); các mục khác chỉ agent trong repo đọc. Thiếu mục bắt buộc thì agent dừng <code>/fix-issue</code>.</p>
      {pack.error != null && <ErrorNotice error={pack.error} onRetry={() => { void pack.refetch() }} />}
      {(read.error ?? paste.error ?? approve.error) != null && <ErrorNotice error={read.error ?? paste.error ?? approve.error} />}
      {data && (
        <>
          <ul className="context-sections">
            {sections.map((section) => (
              <li key={section.number} className={section.present ? 'is-present' : section.required ? 'is-missing' : 'is-optional'}>
                <span className="context-mark" aria-hidden="true">{section.present ? '✓' : section.required ? '✕' : '·'}</span>
                <span>{section.number}. {section.title}</span>
                <small>{section.present ? `${section.lines} dòng` : section.required ? 'thiếu, bắt buộc' : 'chưa có'}{section.to_ai ? ' · gửi AI' : ''}</small>
              </li>
            ))}
          </ul>
          <p className="field-help context-meta">
            {data.has_content ? `${data.source === 'PASTED' ? 'Dán tay' : 'Đọc từ repo'}${data.sha ? ` · bản ${data.sha.slice(0, 8)}` : ''}${data.fetched_at ? ` · đọc ${formatDate(data.fetched_at)}` : ''}${data.meta.updated ? ` · hồ sơ ghi ngày ${data.meta.updated}` : ''}${data.stale_days != null && data.stale_days > 30 ? ` · cũ ${data.stale_days} ngày (−10)` : ''}` : 'Chưa đọc được hồ sơ nào.'}
            {data.has_content ? (data.approved ? ` · CTO đã duyệt bản này${data.approved_at ? ` ${formatDate(data.approved_at)}` : ''}` : data.approved_sha ? ' · có bản mới hơn bản đã duyệt' : ' · chưa duyệt') : ''}
            {data.error ? ` · lần đọc gần nhất lỗi: ${contextErrorWords[data.error] || data.error}` : ''}
          </p>
          {note && <p className="field-help">{note}</p>}
          {decide.error != null && <ErrorNotice error={decide.error} />}
          {(suggestions.data || []).length > 0 && (
            <div className="context-suggestions">
              <h3>Gợi ý cho hồ sơ <small>{pendingSuggestions.length > 0 ? `${pendingSuggestions.length} chờ quyết` : 'không còn gợi ý chờ'}</small></h3>
              <ul>
                {pendingSuggestions.map((row) => (
                  <li key={row.id}>
                    <span>{row.text}</span>
                    <small>{row.agent_name ? `agent ${row.agent_name}` : row.suggested_by_name || 'không rõ'}{row.intake_public_id ? ` · ${row.intake_public_id}` : ''} · {formatDate(row.created_at)}</small>
                    {user?.role === 'CTO' && (
                      <span className="context-actions">
                        <button type="button" className="button button-secondary button-small" disabled={decide.isPending} title="Đã sửa tệp trong repo theo gợi ý này" onClick={() => decide.mutate({ id: row.id, decision: 'applied' })}>Đã đưa vào hồ sơ</button>
                        <button type="button" className="text-button" disabled={decide.isPending} onClick={() => decide.mutate({ id: row.id, decision: 'dismissed' })}>Bỏ qua</button>
                      </span>
                    )}
                  </li>
                ))}
                {decidedSuggestions.map((row) => (
                  <li key={row.id} className="is-decided">
                    <span>{row.text}</span>
                    <small>{row.status === 'APPLIED' ? 'đã đưa vào hồ sơ' : 'bỏ qua'}{row.decided_by_name ? ` · ${row.decided_by_name}` : ''}{row.decided_at ? ` · ${formatDate(row.decided_at)}` : ''}</small>
                  </li>
                ))}
              </ul>
              <p className="field-help">Agent và nhân sự ghi gợi ý khi làm việc (trường "Gợi ý cho hồ sơ" trong Lịch sử xử lý). "Đã đưa vào hồ sơ" là CTO đã sửa tệp trong repo rồi Đọc lại; Intake không tự sửa tệp.</p>
            </div>
          )}
          <div className="project-brief-foot">
            <span className="field-help">{hasRepo ? 'Sửa hồ sơ bằng merge request trong repo, rồi Đọc lại.' : 'Dự án chưa có repo đang bật: dán hồ sơ theo khuôn.'}</span>
            <span className="context-actions">
              {hasRepo && <button type="button" className="button button-secondary button-small" disabled={read.isPending} onClick={() => read.mutate()}>Đọc lại từ repo</button>}
              <button type="button" className="button button-secondary button-small" onClick={() => { setText(data.content || ''); setPasting((value) => !value) }}>{pasting ? 'Đóng ô dán' : 'Dán hồ sơ'}</button>
              {user?.role === 'CTO' && data.has_content && !data.approved && <button type="button" className="button button-primary button-small" disabled={approve.isPending} onClick={() => approve.mutate()}>Duyệt bản này</button>}
            </span>
          </div>
          {pasting && (
            <div className="context-paste">
              <textarea rows={14} aria-label="Hồ sơ ngữ cảnh" value={text} onChange={(event) => setText(event.target.value)} placeholder={'---\nproject: <mã dự án>\nowner: <tên>\nupdated: 2026-10-15\n---\n\n## 1. Sản phẩm và người dùng\n...'} />
              <div className="project-brief-foot"><span className="field-help">Dán nguyên tệp theo khuôn tám mục. Bản dán thay bản đọc từ repo cho tới lần đọc kế tiếp.</span><button type="button" className="button button-primary button-small" disabled={text.trim().length < 20 || paste.isPending} onClick={() => paste.mutate()}>Lưu hồ sơ dán</button></div>
            </div>
          )}
        </>
      )}
    </section>
  )
}

// The other codes staff write for this project in daily reports; with one, a report lands here, not in "Dự án khác" (FR-EML-12).
function ProjectReportCodesPanel({ project }: { project: Project }) {
  const queryClient = useQueryClient()
  const stored = useQuery({ queryKey: ['project-report-codes', project.id], queryFn: () => api<{ codes: string[] }>(`/projects/${project.id}/report-codes`) })
  const [text, setText] = useState<string>()
  const [saved, setSaved] = useState(false)
  const value = text ?? (stored.data?.codes || []).join(', ')
  const save = useMutation({
    mutationFn: () => api<{ codes: string[] }>(`/projects/${project.id}/report-codes`, { method: 'PUT', body: JSON.stringify({ codes: value.split(/[,;\n]+/).map((code) => code.trim()).filter(Boolean) }) }),
    onSuccess: (next) => { queryClient.setQueryData(['project-report-codes', project.id], next); setText(undefined); setSaved(true); window.setTimeout(() => setSaved(false), 2500) },
  })
  const dirty = text !== undefined && text !== (stored.data?.codes || []).join(', ')
  return (
    <section className="panel project-brief">
      <div className="panel-heading"><div><h2>Mã dự án trong báo cáo</h2></div><span className="muted">mã chính: {project.code.toUpperCase()}</span></div>
      <p className="field-help">Nhân sự ghi mã nào ở đầu mục dự án trong báo cáo ngày thì thư về đúng dự án này, thay vì rơi vào "Dự án khác" chỉ CTO thấy. Nhiều mã cách nhau bằng dấu phẩy, ví dụ AISE, AISE-CHATBOT.</p>
      {stored.error != null && <ErrorNotice error={stored.error} onRetry={() => { void stored.refetch() }} />}
      {save.error != null && <ErrorNotice error={save.error} />}
      <input aria-label="Mã dự án trong báo cáo" value={value} disabled={stored.isLoading} onChange={(event) => setText(event.target.value)} placeholder="AISE, AISE-CHATBOT" />
      <div className="project-brief-foot">
        <span className="field-help">Việc đã nằm ở "Dự án khác" không tự chuyển: CTO mở báo cáo, sửa từng việc và chọn dự án.</span>
        <button type="button" className="button button-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>{save.isPending ? 'Đang lưu…' : saved ? 'Đã lưu' : 'Lưu mã'}</button>
      </div>
    </section>
  )
}

// Tokens for agents: made here, shown once, revoked here. With one, Codex or Claude files requests and reports as you.
function AgentTokensSection() {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [issued, setIssued] = useState<ApiToken>()
  const [copied, setCopied] = useState('')
  const [removing, setRemoving] = useState<ApiToken>()
  const tokens = useQuery({ queryKey: ['api-tokens'], queryFn: () => api<ApiToken[]>('/auth/tokens') })
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['api-tokens'] }) }
  const create = useMutation({
    mutationFn: () => api<ApiToken>('/auth/tokens', { method: 'POST', body: JSON.stringify({ name: name.trim() }) }),
    onSuccess: (row) => { setIssued(row); setName(''); setCopied(''); refresh() },
  })
  const revoke = useMutation({
    mutationFn: (id: string) => api(`/auth/tokens/${id}`, { method: 'DELETE' }),
    onSuccess: () => { setRemoving(undefined); if (issued && removing && issued.id === removing.id) setIssued(undefined); refresh() },
  })
  const copy = (what: string, text: string) => { void navigator.clipboard.writeText(text).then(() => setCopied(what)) }
  const url = `${window.location.origin}/api/v1/mcp-server`
  const codexConfig = `[mcp_servers.intake]\nurl = "${url}"\nbearer_token_env_var = "INTAKE_MCP_TOKEN"`
  const claudeCommand = `claude mcp add --transport http intake ${url} --header "Authorization: Bearer <token>"`
  const list = tokens.data || []
  return (
    <section className="panel account-section" aria-label="Token cho Codex và Claude">
      {removing && (
        <ConfirmDialog title={`Thu hồi token "${removing.name}"?`} confirmLabel="Thu hồi" busyLabel="Đang thu hồi…" busy={revoke.isPending} error={revoke.error ?? undefined} onConfirm={() => revoke.mutate(removing.id)} onCancel={() => setRemoving(undefined)}>
          <ul><li>Agent đang dùng token này sẽ bị từ chối ngay.</li><li>Yêu cầu và báo cáo đã gửi không đổi.</li></ul>
        </ConfirmDialog>
      )}
      <header>
        <div><h3>Token cho Codex, Claude Code, Claude Desktop <Hint k="account.token" /></h3><p>Agent gọi Intake với đúng quyền của bạn: lấy việc của bạn trong ngày, báo việc đang làm hay xong, tạo yêu cầu, trả lời câu hỏi làm rõ, gửi báo cáo cuối ngày. Không duyệt, không chốt kế hoạch. Token hiện một lần; thu hồi được bất cứ lúc nào.</p></div>
      </header>
      {tokens.error != null && <ErrorNotice error={tokens.error} onRetry={() => { void tokens.refetch() }} />}
      {create.error != null && <ErrorNotice error={create.error} />}
      {issued?.token && (
        <div className="notice notice-success token-issued" role="status">
          <strong>Token "{issued.name}": chép ngay, sẽ không hiện lại.</strong>
          <code>{issued.token}</code>
          <div>
            <button type="button" className="button button-secondary button-small" onClick={() => copy('token', issued.token || '')}>{copied === 'token' ? 'Đã chép' : 'Chép token'}</button>
            <button type="button" className="text-button" onClick={() => setIssued(undefined)}>Đã lưu, ẩn đi</button>
          </div>
          <div className="agent-connect">
            <p><strong>Claude Code</strong>: dán một lệnh vào terminal; rồi gõ <code>/mcp__intake__today</code> lần đầu, agent sẽ tự cài các lệnh ngắn <code>/in-today</code>, <code>/in-end-day</code>, <code>/in-week</code> cho những lần sau (hoặc cài bằng dòng trong "Lệnh cho agent" ở menu tài khoản).</p>
            <pre>{`claude mcp add --transport http intake ${url} --header "Authorization: Bearer ${issued.token}"`}</pre>
            <button type="button" className="text-button" onClick={() => copy('claude-token', `claude mcp add --transport http intake ${url} --header "Authorization: Bearer ${issued.token}"`)}>{copied === 'claude-token' ? 'Đã chép' : 'Chép lệnh Claude Code'}</button>
            <p><strong>Codex</strong>: thêm khối dưới vào <code>~/.codex/config.toml</code>, rồi đặt biến môi trường trước khi mở Codex (dòng thứ hai cho PowerShell).</p>
            <pre>{`${codexConfig}\n\nexport INTAKE_MCP_TOKEN=${issued.token}\n$env:INTAKE_MCP_TOKEN="${issued.token}"`}</pre>
            <button type="button" className="text-button" onClick={() => copy('codex-token', `${codexConfig}\n\nexport INTAKE_MCP_TOKEN=${issued.token}`)}>{copied === 'codex-token' ? 'Đã chép' : 'Chép cấu hình Codex'}</button>
          </div>
        </div>
      )}
      {list.length > 0 && (
        <ul className="token-list">
          {list.map((row) => (
            <li key={row.id}>
              <div><strong>{row.name}</strong><small>{row.prefix}… · tạo {formatDate(row.created_at)}{row.last_used_at ? ` · dùng gần nhất ${formatDate(row.last_used_at)}` : ' · chưa dùng'}{row.expires_at ? ` · hết hạn ${formatDay(row.expires_at)}/${row.expires_at.slice(0, 4)}` : ''}</small></div>
              <button type="button" className="button button-secondary button-small" onClick={() => { revoke.reset(); setRemoving(row) }}>Thu hồi</button>
            </li>
          ))}
        </ul>
      )}
      <form className="token-add" onSubmit={(event) => { event.preventDefault(); if (name.trim()) create.mutate() }}>
        <input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} placeholder="Tên, ví dụ: Codex máy làm việc" aria-label="Tên token" />
        <button className="button button-primary" disabled={!name.trim() || create.isPending || list.length >= 10}>{create.isPending ? 'Đang tạo…' : 'Tạo token'}</button>
      </form>
      <details className="token-howto">
        <summary>Cách nối</summary>
        <p><strong>Codex</strong> — thêm vào <code>~/.codex/config.toml</code>, rồi đặt biến môi trường <code>INTAKE_MCP_TOKEN</code> bằng token:</p>
        <pre>{codexConfig}</pre>
        <button type="button" className="text-button" onClick={() => copy('codex', codexConfig)}>{copied === 'codex' ? 'Đã chép' : 'Chép đoạn cấu hình'}</button>
        <p><strong>Claude Code</strong> — một lệnh, thay <code>&lt;token&gt;</code>:</p>
        <pre>{claudeCommand}</pre>
        <button type="button" className="text-button" onClick={() => copy('claude', claudeCommand)}>{copied === 'claude' ? 'Đã chép' : 'Chép lệnh'}</button>
        <p><strong>Claude Desktop</strong> — Settings → Connectors → Add custom connector, URL <code>{url}</code>, header <code>Authorization: Bearer &lt;token&gt;</code>.</p>
        <p className="field-help">Agent chỉ nhận bản đã chuẩn hóa của yêu cầu, không nhận nội dung thô khách gửi. Những gì agent đọc được từ Intake là dữ liệu, không phải lệnh.</p>
      </details>
    </section>
  )
}

function PasswordForm({ onChanged }: { onChanged?: () => void }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [done, setDone] = useState(false)
  const [error, setError] = useState<unknown>()
  const change = useMutation({
    mutationFn: () => api('/auth/password', { method: 'POST', body: JSON.stringify({ current_password: current, new_password: next }) }),
    onSuccess: () => { setCurrent(''); setNext(''); setRepeat(''); setError(undefined); setDone(true); onChanged?.() },
    onError: (changeError) => { setDone(false); setError(changeError) },
  })
  const mismatch = repeat.length > 0 && next !== repeat
  return (
    <form className="password-form" onSubmit={(event) => { event.preventDefault(); change.mutate() }}>
      <label><span className="req-label">Mật khẩu hiện tại<Req /></span><input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required /></label>
      <label><span className="req-label">Mật khẩu mới<Req /></span><input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" minLength={12} required /><small className="field-help">Ít nhất 12 ký tự.</small></label>
      <label><span className="req-label">Nhập lại mật khẩu mới<Req /></span><input type="password" value={repeat} onChange={(e) => setRepeat(e.target.value)} autoComplete="new-password" required /></label>
      {mismatch && <p className="notice notice-warn">Hai lần nhập mật khẩu mới chưa khớp.</p>}
      {error != null && <ErrorNotice error={error} />}
      {done && <p className="notice notice-success" role="status">Đã đổi mật khẩu.</p>}
      <button className="button button-primary" type="submit" disabled={change.isPending || !current || next.length < 12 || next !== repeat}>{change.isPending ? 'Đang đổi…' : 'Đổi mật khẩu'}</button>
    </form>
  )
}

function ForcedPasswordPage({ onChanged, onSignOut }: { onChanged: () => void; onSignOut: () => void }) {
  return (
    <main className="login-panel">
      <div className="login-form">
        <div className="brand login-brand"><img className="brand-mark" src="/icon.svg" alt="" /><span><strong>Private Intake</strong><small>Private Intake workspace</small></span></div>
        <h1>Đặt mật khẩu của bạn</h1>
        <p>Bạn đang dùng mật khẩu tạm do CTO cấp. Hãy đặt mật khẩu riêng trước khi tiếp tục.</p>
        <PasswordForm onChanged={onChanged} />
        <button className="text-button" type="button" onClick={onSignOut}><LogOut size={15} /> Đăng xuất</button>
      </div>
    </main>
  )
}

// ---------------------------------------------------------------------------------------------------
// The private space (ADR-0031): the CTO's own ideas and post drafts, kept off the company's working screens.

const draftChannels: { value: VoiceChannel; label: string }[] = [
  { value: 'FACEBOOK', label: 'Facebook' }, { value: 'LINKEDIN', label: 'LinkedIn' }, { value: 'THREADS', label: 'Threads/X' },
]
// Two directions of one author's content, sharing one master brand document.
const draftTracks: DraftTrack[] = ['business', 'technical']
const trackDefaults: Record<DraftTrack, string> = { business: 'Kinh doanh', technical: 'Kỹ thuật' }
const otherTrack = (track: DraftTrack): DraftTrack => (track === 'business' ? 'technical' : 'business')
// What the idea behind a draft is, and whether money is behind the piece: the reader must be told both.
const draftContexts: { value: DraftContext; label: string }[] = [
  { value: 'REAL', label: 'Việc thật' }, { value: 'EXAMPLE', label: 'Ví dụ giả định' }, { value: 'SOURCE', label: 'Từ nguồn tham khảo' },
]
const draftCommercials: { value: DraftCommercial; label: string }[] = [
  { value: 'NONE', label: 'Không có' }, { value: 'SPONSORED', label: 'Tài trợ' }, { value: 'AFFILIATE', label: 'Affiliate' },
]
const trackName = (voices: Record<string, PrivateVoice> | undefined, track: string | null | undefined) => (track ? voices?.[track]?.name || trackDefaults[track as DraftTrack] || track : '')
// What the post is for decides how it ends; who it is for decides where it starts.
const draftGoals = [
  { value: 'AUTHORITY', label: 'Khẳng định quan điểm' }, { value: 'DISCUSSION', label: 'Mở thảo luận' },
  { value: 'REACH', label: 'Lan tỏa' }, { value: 'CONVERSATION', label: 'Mời trao đổi riêng' }, { value: 'FOLLOW', label: 'Theo dõi, đăng ký' },
]
const draftAudiences = [
  { value: 'SME', label: 'Chủ doanh nghiệp SME' }, { value: 'AGENCY', label: 'Agency' },
  { value: 'CONSULTANT', label: 'Nhà tư vấn' }, { value: 'DEVELOPER', label: 'Developer trên GitHub' }, { value: 'AI_USER', label: 'Người dùng AI' },
]
// Long pieces are written from an outline the author has read and kept.
const longChannels: { value: DraftChannel; label: string }[] = [{ value: 'BLOG', label: 'Bài blog' }, { value: 'VIDEO_SCRIPT', label: 'Kịch bản video' }]
const draftForms = [
  { value: 'SOCIAL', label: 'Bài mạng xã hội' }, { value: 'OUTLINE', label: 'Dàn ý' }, { value: 'BLOG', label: 'Bài blog' }, { value: 'VIDEO_SCRIPT', label: 'Kịch bản video' },
] as const
type DraftForm = typeof draftForms[number]['value']
const noteKinds: { value: TrackNote['kind']; label: string; hint: string }[] = [
  { value: 'FACT', label: 'Dữ kiện đã kiểm', hint: 'Điều có thật, AI được nêu nguyên văn. Ví dụ: đội có 6 người; sản phẩm chạy từ tháng 3.' },
  { value: 'PROOF', label: 'Bằng chứng được dùng', hint: 'Thứ được phép đưa ra làm ví dụ: một repo công khai, một màn hình, một tình huống đã ẩn tên.' },
  { value: 'DECISION', label: 'Điều đã quyết', hint: 'Quy tắc của mạch này. Ví dụ: không so sánh giá; chỉ nói về công cụ đã dùng trên hai tuần.' },
  { value: 'RESULT', label: 'Kết quả', hint: 'Bài nào đã hiệu quả, để AI nghiêng về hướng đó. Không được nêu như dữ kiện.' },
]
const draftGroups = [
  { value: 'FNB', label: 'F&B' }, { value: 'EDUCATION', label: 'Tuyển sinh, đào tạo' }, { value: 'RETAIL', label: 'Bán lẻ' },
  { value: 'SERVICE', label: 'Dịch vụ' }, { value: 'AGENCY', label: 'Agency' }, { value: 'CONSULTING', label: 'Tư vấn doanh nghiệp' },
]
const labelOf = (list: { value: string; label: string }[], value: string | null) => list.find((item) => item.value === value)?.label || value || ''
const channelName = (value: string) => (value === 'FACEBOOK_GROUP' ? 'Hội nhóm' : [...draftChannels, ...longChannels].find((channel) => channel.value === value)?.label || value)
const draftName = (draft: PostDraft) => (draft.kind === 'OUTLINE' ? `Dàn ý ${channelName(draft.channel).toLowerCase()}` : draft.group_context ? `Hội nhóm ${labelOf(draftGroups, draft.group_context)}` : channelName(draft.channel))
const weekdayShort = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']
const weekdayLong = ['Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ nhật']
const slotLabel = (slot: { weekday: number; day: string; time: string | null }) => `${weekdayShort[slot.weekday - 1]} ${formatDay(slot.day)}${slot.time ? ` · ${slot.time}` : ''}`
const formatMoment = (value: string) => new Intl.DateTimeFormat('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' }).format(new Date(value))
// The value a datetime-local input wants, in the browser's own time zone.
const localInput = (value: Date) => new Date(value.getTime() - value.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
const shiftWeek = (week: string, days: number) => { const next = new Date(`${week}T00:00:00Z`); next.setUTCDate(next.getUTCDate() + days); return next.toISOString().slice(0, 10) }
const slotStates: Record<PlanSlot['state'], string> = {
  EMPTY: 'Chưa có ý', PROPOSED: 'AI đề xuất', IDEA: 'Đã có ý', DRAFTED: 'Có nháp', APPROVED: 'Đã duyệt', POSTED: 'Đã đăng', SKIPPED: 'Bỏ qua',
}
type DraftAsk = {
  channel: DraftChannel; angle?: string | null; source_draft_id?: string
  track?: DraftTrack | null; goal?: string | null; audience?: string | null; pillar?: string | null; group_context?: string | null
  outline?: boolean; context?: DraftContext | null; commercial?: DraftCommercial | null
}
const choicesOf = (draft: PostDraft) => ({ track: draft.track, goal: draft.goal, audience: draft.audience, pillar: draft.pillar, context: draft.context, commercial: draft.commercial })
const wordCount = (text: string) => (text.trim() ? text.trim().split(/\s+/).length : 0)
const ideaStateLabels: Record<PrivateIdea['state'], string> = { NO_DRAFT: 'Chưa có nháp', DRAFTED: 'Có nháp', POSTED: 'Đã đăng', DROPPED: 'Đã bỏ' }

function usePrivateSpace() {
  return useQuery({ queryKey: ['private-space'], queryFn: () => api<PrivateSpace>('/private-space') })
}

// The first visit: nothing exists until the owner asks for it.
function OpenPrivateSpace() {
  const queryClient = useQueryClient()
  const open = useMutation({
    mutationFn: () => api<PrivateSpace>('/private-space', { method: 'POST' }),
    onSuccess: (space) => queryClient.setQueryData(['private-space'], space),
  })
  return (
    <section className="panel private-open">
      <span className="private-open-icon" aria-hidden="true"><Lock size={20} /></span>
      <h2>Không gian riêng của bạn</h2>
      <p>Nơi lưu ý tưởng cá nhân và soạn nháp bài đăng. Ý ở đây không hiện ở Chờ phê duyệt, Tất cả Intake, chuông hay bất kỳ màn hình nào của team.</p>
      <ul>
        <li>Chỉ tài khoản CTO mở được; Project Owner không thấy.</li>
        <li>Nội dung lưu mã hóa trên máy chủ công ty và nằm trong bản sao lưu.</li>
        <li>Khi AI đọc ý hoặc soạn nháp, nội dung được gửi tới nhà cung cấp AI.</li>
      </ul>
      {open.error != null && <ErrorNotice error={open.error} />}
      <button type="button" className="button button-primary" disabled={open.isPending} onClick={() => open.mutate()}>{open.isPending ? 'Đang tạo…' : 'Tạo không gian riêng'}</button>
    </section>
  )
}

const watchKinds: Record<WatchSource['kind'], string> = { WEB: 'Web', FACEBOOK: 'Facebook', X: 'X', YOUTUBE: 'YouTube', LINKEDIN: 'LinkedIn', OTHER: 'Khác' }

// What a scanning tool outside Intake found on the watched sources: one closed line until the owner wants to look.
function SignalBar({ track }: { track: DraftTrack }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<unknown>()
  const signals = useQuery({ queryKey: ['watch-signals', track], queryFn: () => api<WatchSignal[]>(`/private-space/watch/signals?track=${track}`) })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['watch-signals', track] })
    void queryClient.invalidateQueries({ queryKey: ['private-ideas'] })
    void queryClient.invalidateQueries({ queryKey: ['private-space'] })
  }
  const keep = useMutation({ mutationFn: (id: string) => api(`/private-space/watch/signals/${id}/idea`, { method: 'POST' }), onMutate: () => setError(undefined), onSuccess: refresh, onError: setError })
  const dismiss = useMutation({ mutationFn: (id: string) => api(`/private-space/watch/signals/${id}`, { method: 'DELETE' }), onMutate: () => setError(undefined), onSuccess: refresh, onError: setError })
  const list = signals.data || []
  if (list.length === 0) return null
  const busy = keep.isPending || dismiss.isPending
  return (
    <section className={open ? 'week-plan is-compact is-open signal-bar' : 'week-plan is-compact signal-bar'} aria-label="Tín hiệu từ nguồn theo dõi">
      <header className="week-bar">
        <button type="button" className="week-bar-toggle" aria-expanded={open} onClick={() => setOpen(!open)}><ChevronRight size={15} aria-hidden="true" /><strong>Tín hiệu</strong><small>{list.length} mới</small></button>
        <p className="week-bar-summary">Bài công cụ quét tìm thấy ở các nguồn bạn theo dõi. AI đọc tiêu đề khi đề xuất tuần; tự hết hạn sau 30 ngày.</p>
      </header>
      {open && (
        <div className="signal-list">
          {error != null && <ErrorNotice error={error} />}
          <ul>
            {list.map((signal) => (
              <li key={signal.id}>
                <div>
                  <a href={signal.url} target="_blank" rel="noreferrer noopener">{signal.title}</a>
                  <small>{[signal.source_label, signal.keyword && `từ khóa: ${signal.keyword}`, signal.pillar, formatDay(signal.published_at || signal.received_at)].filter(Boolean).join(' · ')}</small>
                </div>
                <button type="button" className="button button-secondary button-small" disabled={busy} onClick={() => keep.mutate(signal.id)}>Thành ý</button>
                <button type="button" className="text-button" disabled={busy} onClick={() => dismiss.mutate(signal.id)}>Bỏ</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

// One slot of the week: what is meant for that day, and how far it has come.
function PlanSlotRow({ slot, editable, ideas, onChange, onAccept, busy }: {
  slot: PlanSlot; editable: boolean; ideas: PrivateIdea[]; busy: boolean
  onChange: (body: { intake_id?: string | null; skipped?: boolean; dismiss?: boolean }) => void; onAccept: () => void
}) {
  const open = slot.state === 'EMPTY' || slot.state === 'PROPOSED'
  return (
    <li className={`plan-slot is-${slot.state.toLowerCase()}`}>
      <div className="plan-slot-when"><strong>{slotLabel(slot)}</strong><span>{channelName(slot.channel)}{slot.pillar ? ` · ${slot.pillar}` : ''}</span></div>
      <div className="plan-slot-body">
        {slot.idea ? (
          <Link to={`/rieng/y/${slot.idea.id}?o=${slot.id}`}>{slot.idea.title || 'Ý chưa có tiêu đề'}</Link>
        ) : slot.suggestion ? (
          <div className="plan-suggestion"><strong>{slot.suggestion.title}</strong><span>{slot.suggestion.from_store ? 'Ý trong kho' : 'Góc mới'}{slot.suggestion.pillar ? ` · ${slot.suggestion.pillar}` : ''}{slot.suggestion.reason ? ` · ${slot.suggestion.reason}` : ''}</span></div>
        ) : <span className="muted">{slot.state === 'SKIPPED' ? 'Bỏ qua tuần này' : 'Chưa có ý'}</span>}
        {slot.state === 'APPROVED' && slot.draft?.scheduled_for && <small>Đăng {formatMoment(slot.draft.scheduled_for)}</small>}
        {slot.state === 'POSTED' && slot.draft?.posted_at && <small>Đã lên {formatMoment(slot.draft.posted_at)}{slot.draft.posted_url ? <> · <a href={slot.draft.posted_url} target="_blank" rel="noreferrer">mở bài</a></> : ''}</small>}
      </div>
      <span className={`status plan-state plan-state-${slot.state.toLowerCase()}`}>{slotStates[slot.state]}</span>
      {editable && (
        <div className="plan-slot-actions">
          {slot.state === 'PROPOSED' && <button type="button" className="button button-primary button-small" disabled={busy} onClick={onAccept}>Chốt</button>}
          {slot.state === 'PROPOSED' && <button type="button" className="button button-secondary button-small" disabled={busy} onClick={() => onChange({ dismiss: true })}>Đổi ý khác</button>}
          {slot.state === 'EMPTY' && (
            <select aria-label={`Chọn ý cho ô ${slotLabel(slot)}`} value="" disabled={busy || ideas.length === 0} onChange={(event) => { if (event.target.value) onChange({ intake_id: event.target.value }) }}>
              <option value="">{ideas.length ? 'Chọn ý trong kho…' : 'Kho chưa có ý hợp'}</option>
              {ideas.map((idea) => <option key={idea.id} value={idea.id}>{(idea.title || 'Ý chưa có tiêu đề').slice(0, 70)}</option>)}
            </select>
          )}
          {open && <button type="button" className="text-button" disabled={busy} onClick={() => onChange({ skipped: true })}>Bỏ qua</button>}
          {(slot.state === 'IDEA' || slot.state === 'DRAFTED') && <button type="button" className="text-button" disabled={busy} onClick={() => onChange({ intake_id: null })}>Gỡ ý</button>}
          {slot.state === 'SKIPPED' && <button type="button" className="text-button" disabled={busy} onClick={() => onChange({ skipped: false })}>Khôi phục</button>}
        </div>
      )}
    </li>
  )
}

function PlanTrackColumn({ track, plan, week, editable, ideas, bare, onChanged }: {
  track: DraftTrack; plan: PlanTrack; week: string; editable: boolean; ideas: PrivateIdea[]; bare?: boolean; onChanged: () => void
}) {
  const [keywords, setKeywords] = useState('')
  const [error, setError] = useState<unknown>()
  const change = useMutation({
    mutationFn: (input: { id: string; body: object }) => api<PlanSlot>(`/private-space/plan/slots/${input.id}`, { method: 'PATCH', body: JSON.stringify(input.body) }),
    onMutate: () => setError(undefined), onSuccess: onChanged, onError: setError,
  })
  const accept = useMutation({
    mutationFn: (id: string) => api<{ slot: PlanSlot; created_idea_id: string | null }>(`/private-space/plan/slots/${id}/accept`, { method: 'POST' }),
    onMutate: () => setError(undefined), onSuccess: onChanged, onError: setError,
  })
  const propose = useMutation({
    mutationFn: () => api('/private-space/plan/propose', { method: 'POST', body: JSON.stringify({ track, week_start: week, keywords: keywords.trim() || null }) }),
    onMutate: () => setError(undefined), onSuccess: onChanged, onError: setError,
  })
  const stats = plan.stats
  const thinking = plan.request?.status === 'PENDING' || propose.isPending
  const busy = change.isPending || accept.isPending
  // Ideas of this line, or not filed yet, that no slot of this week already holds.
  const held = new Set(plan.slots.map((slot) => slot.idea?.id).filter(Boolean))
  const free = ideas.filter((idea) => (idea.track === track || idea.track === null) && !held.has(idea.id) && (idea.state === 'NO_DRAFT' || idea.state === 'DRAFTED'))
  return (
    <section className={bare ? 'plan-track is-bare' : 'plan-track'} aria-label={`Kế hoạch tuần của mạch ${plan.name}`}>
      {!bare && (
        <header>
          <h3>{plan.name}</h3>
          {stats.slots > 0 && <span className="plan-progress"><b>{stats.posted}/{stats.slots}</b> đã đăng{stats.approved > 0 ? ` · ${stats.approved} đã duyệt` : ''}</span>}
        </header>
      )}
      {plan.slots.length === 0 ? (
        <p className="plan-empty">{editable ? <>Mạch này chưa có nhịp tuần. Khai mỗi tuần mấy bài, ngày nào, kênh nào ở <Link to="/rieng/giong">Giọng của tôi</Link>.</> : 'Tuần này không có ô nào.'}</p>
      ) : (
        <ul className="plan-slots">
          {plan.slots.map((slot) => <PlanSlotRow key={slot.id} slot={slot} editable={editable} ideas={free} busy={busy} onChange={(body) => change.mutate({ id: slot.id, body })} onAccept={() => accept.mutate(slot.id)} />)}
        </ul>
      )}
      {!bare && <p className="plan-numbers">{stats.drafted_ideas} ý đã nháp · {stats.posted_total} bài đã đăng{stats.off_plan > 0 ? <> · <b>{stats.off_plan} ngoài kế hoạch</b></> : ''}</p>}
      {stats.pillars.length > 0 && <p className="plan-pillars"><span>Trụ, 4 tuần gần nhất:</span>{stats.pillars.map((row) => <span key={row.pillar || '-'} className={row.posted === 0 ? 'chip is-zero' : 'chip'}>{row.pillar || 'Chưa gắn trụ'} <b>{row.posted}</b></span>)}</p>}
      {error != null && <ErrorNotice error={error} />}
      {plan.request?.status === 'FAILED' && !thinking && <p className="plan-warning"><TriangleAlert size={14} aria-hidden="true" /> AI chưa đề xuất được lúc này{plan.request.error ? ` (${plan.request.error})` : ''}. Bạn thử lại hoặc tự chọn ý.</p>}
      {editable && stats.open > 0 && (
        <form className="plan-propose" onSubmit={(event) => { event.preventDefault(); if (!thinking) propose.mutate() }}>
          <input value={keywords} maxLength={2000} onChange={(event) => setKeywords(event.target.value)} placeholder="Từ khóa, tin đang nóng của tuần (không bắt buộc)" aria-label={`Từ khóa tuần này cho mạch ${plan.name}`} />
          <button className="button button-secondary" disabled={thinking}>{thinking ? <><span className="spinner" aria-hidden="true" /> AI đang đề xuất…</> : <><Sparkles size={15} aria-hidden="true" /> Đề xuất {stats.open} ô trống</>}</button>
        </form>
      )}
    </section>
  )
}

// The week first: what each line means to publish, and how far each post has come.
function WeekPlan({ ideas, only }: { ideas: PrivateIdea[]; only?: DraftTrack }) {
  const queryClient = useQueryClient()
  const [week, setWeek] = useState('')
  // Closed by default so the composer and the list stay in view; the choice is remembered on this browser.
  const [open, setOpen] = useState(() => { try { return window.localStorage.getItem('intake.rieng.week') === 'open' } catch { return false } })
  const toggle = () => { setOpen(!open); try { window.localStorage.setItem('intake.rieng.week', open ? 'closed' : 'open') } catch { /* not remembered */ } }
  // The weekly rhythm is set here, next to the plan it lays out.
  const [rhythmOpen, setRhythmOpen] = useState(false)
  const space = usePrivateSpace()
  const plan = useQuery({
    queryKey: ['plan-week', week],
    queryFn: () => api<PlanWeek>(`/private-space/plan${week ? `?week=${week}` : ''}`),
    // The AI worker fills the open slots; ask again until it has answered.
    refetchInterval: (query) => (Object.values((query.state.data as PlanWeek | undefined)?.tracks || {}).some((track) => track.request?.status === 'PENDING') ? 2000 : false),
  })
  const changed = () => {
    void queryClient.invalidateQueries({ queryKey: ['plan-week'] })
    void queryClient.invalidateQueries({ queryKey: ['private-ideas'] })
    void queryClient.invalidateQueries({ queryKey: ['private-space'] })
  }
  if (plan.isLoading) return <LoadingBlock />
  if (plan.error || !plan.data) return <ErrorNotice error={plan.error || new Error('Chưa tải được kế hoạch tuần.')} onRetry={() => { void plan.refetch() }} />
  const data = plan.data
  const current = data.week_start === data.this_week
  const title = current ? 'Tuần này' : data.week_start > data.this_week ? 'Tuần sau' : 'Tuần đã qua'
  const nav = (
    <div className="week-plan-nav">
      <button type="button" className="icon-button" aria-label="Tuần trước" title="Tuần trước" onClick={() => setWeek(shiftWeek(data.week_start, -7))}><ChevronLeft size={16} /></button>
      {!current && <button type="button" className="button button-secondary button-small" onClick={() => setWeek('')}>Về tuần này</button>}
      <button type="button" className="icon-button" aria-label="Tuần sau" title="Tuần sau" disabled={data.week_start > data.this_week} onClick={() => setWeek(shiftWeek(data.week_start, 7))}><ChevronRight size={16} /></button>
    </div>
  )
  const single = only ? data.tracks[only] : undefined
  if (only && single) {
    const stats = single.stats
    const waiting = single.slots.filter((slot) => slot.state === 'PROPOSED').length
    return (
      <section className={open ? 'week-plan is-compact is-open' : 'week-plan is-compact'} aria-label="Kế hoạch tuần">
        <header className="week-bar">
          <button type="button" className="week-bar-toggle" aria-expanded={open} onClick={toggle}>
            <ChevronRight size={15} aria-hidden="true" />
            <strong>{title}</strong><small>{formatDay(data.week_start)} – {formatDay(shiftWeek(data.week_start, 6))}</small>
          </button>
          <p className="week-bar-summary">
            {stats.slots > 0 ? <><b>{stats.posted}/{stats.slots}</b> đã đăng{stats.approved > 0 ? ` · ${stats.approved} đã duyệt` : ''}{stats.open > 0 ? ` · ${stats.open} ô chưa có ý` : ''}{waiting > 0 ? ` · ${waiting} đề xuất chờ chốt` : ''}</> : data.editable ? <>Chưa có nhịp tuần · <button type="button" className="text-button" onClick={() => setRhythmOpen(true)}>đặt nhịp</button></> : 'Không có ô nào'}
            {stats.off_plan > 0 && <span className="week-bar-off"> · {stats.off_plan} bài ngoài kế hoạch</span>}
          </p>
          {data.editable && <button type="button" className="button button-secondary button-small week-bar-rhythm" aria-pressed={rhythmOpen} onClick={() => setRhythmOpen(!rhythmOpen)}><Settings size={14} aria-hidden="true" /> Nhịp</button>}
          {nav}
        </header>
        {rhythmOpen && <TrackRhythm track={only} name={space.data?.voices?.[only]?.name || trackDefaults[only]} pillars={space.data?.voices?.[only]?.pillars || []} onClose={() => setRhythmOpen(false)} />}
        {open && <PlanTrackColumn track={only} plan={single} week={data.week_start} editable={data.editable} ideas={ideas} bare onChanged={changed} />}
      </section>
    )
  }
  return (
    <section className="week-plan" aria-label="Kế hoạch tuần">
      <header className="week-plan-head">
        <h2>{title} <small>{formatDay(data.week_start)} – {formatDay(shiftWeek(data.week_start, 6))}</small></h2>
        {nav}
      </header>
      <div className="week-plan-tracks">
        {draftTracks.filter((track) => data.tracks[track]).map((track) => <PlanTrackColumn key={track} track={track} plan={data.tracks[track]} week={data.week_start} editable={data.editable} ideas={ideas} onChanged={changed} />)}
      </div>
    </section>
  )
}

function PrivateIdeasPage() {
  const queryClient = useQueryClient()
  const space = usePrivateSpace()
  const recording = useRecording()
  const [state, setState] = useState<'ALL' | PrivateIdea['state']>('ALL')
  const [search, setSearch] = useState('')
  // One line of content at a time: its week, its ideas, its counts. The choice is remembered on this browser.
  const [tab, setTab] = useState<DraftTrack | 'none'>(() => { try { const kept = window.localStorage.getItem('intake.rieng.tab'); return kept === 'technical' || kept === 'personal' ? 'technical' : kept === 'none' ? 'none' : 'business' } catch { return 'business' } })
  const chooseTab = (next: DraftTrack | 'none') => { setTab(next); setState('ALL'); try { window.localStorage.setItem('intake.rieng.tab', next) } catch { /* the choice just is not remembered */ } }
  const track = tab === 'none' ? '' : tab
  const [note, setNote] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [error, setError] = useState<unknown>()
  const fileRef = useRef<HTMLInputElement>(null)
  const spokenRef = useRef<string | undefined>(undefined)
  const project = space.data?.project
  const ideas = useQuery({
    queryKey: ['private-ideas', state, search, track],
    queryFn: () => api<PrivateIdea[]>(`/private-space/ideas?state=${state}${track ? `&track=${track}` : ''}${search.trim() ? `&search=${encodeURIComponent(search.trim())}` : ''}`),
    enabled: Boolean(project),
    // An idea just saved is still being read by AI: look again until its title is there.
    refetchInterval: (query) => ((query.state.data as PrivateIdea[] | undefined)?.some((idea) => ['NEW', 'PROCESSING'].includes(idea.status)) ? 3000 : false),
  })
  // Every idea of the store, for choosing one into a slot of the week whatever the list below is filtered to.
  const store = useQuery({ queryKey: ['private-ideas', 'ALL', '', ''], queryFn: () => api<PrivateIdea[]>('/private-space/ideas?state=ALL'), enabled: Boolean(project) })
  const week = useQuery({ queryKey: ['plan-week', ''], queryFn: () => api<PlanWeek>('/private-space/plan'), enabled: Boolean(project) })
  useEffect(() => () => { void leaveRecording() }, [])

  const save = useMutation({
    mutationFn: async () => {
      const created = await api<Intake>('/intakes', {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ project_id: project!.code, channel: 'MANUAL', raw_text: note.trim() }),
      })
      for (const file of files) {
        const body = new FormData()
        body.append('file', file)
        await api(`/intakes/${created.id}/attachments`, { method: 'POST', body })
      }
      if (track) await api(`/private-space/ideas/${created.id}/track`, { method: 'PUT', body: JSON.stringify({ track }) })
      // The idea is kept whether or not AI can read it right now.
      try { await api(`/intakes/${created.id}/process`, { method: 'POST' }) } catch { /* shown as "AI chưa đọc" in the list */ }
      return created
    },
    onMutate: () => setError(undefined),
    onSuccess: () => {
      setNote(''); setFiles([]); spokenRef.current = undefined
      if (recording.kind === 'DICTATION') resetRecording()
      void queryClient.invalidateQueries({ queryKey: ['private-ideas'] })
      void queryClient.invalidateQueries({ queryKey: ['private-space'] })
    },
    onError: setError,
  })
  const addFiles = (next: File[]) => {
    const invalid = next.find((file) => file.size > 5 * 1024 * 1024 || !ACCEPTED_FILE_TYPES.includes(file.type))
    if (invalid) { setError(new Error(`File ${invalid.name} không hợp lệ. Chỉ nhận PDF/JPG/PNG/WebP, tối đa 5 MB.`)); return }
    setError(undefined)
    setFiles((current) => [...current, ...next])
  }
  const useSpoken = (text: string) => {
    const previous = spokenRef.current
    spokenRef.current = text
    setNote((current) => (previous && current.includes(previous) ? current.replace(previous, () => text) : current.trim() ? `${current.trim()}\n\n${text}` : text))
  }
  const recordingNow = recording.phase === 'starting' || recording.phase === 'recording' || recording.phase === 'stopping'
  // A meeting started elsewhere keeps running; this page neither shows it nor stops it.
  const meetingRunning = recordingNow && recording.kind === 'MEETING'
  const busy = recordingNow && !meetingRunning
  const toggleDictation = () => {
    if (meetingRunning) return
    if (busy) void stopRecording()
    else if (project) { spokenRef.current = undefined; void startRecording({ source: 'MIC', projectCode: project.code, kind: 'DICTATION' }) }
  }

  if (space.isLoading) return <><PageHeader title="Kho ý tưởng" /><LoadingBlock /></>
  if (space.error) return <><PageHeader title="Kho ý tưởng" /><ErrorNotice error={space.error} onRetry={() => { void space.refetch() }} /></>
  if (!project) return <><PageHeader title="Kho ý tưởng" /><OpenPrivateSpace /></>

  const counts = space.data!.counts
  const all = store.data || []
  const inTab = (idea: PrivateIdea, name: DraftTrack | 'none') => (name === 'none' ? idea.track === null : idea.track === name)
  const mine = all.filter((idea) => inTab(idea, tab))
  const unfiled = all.filter((idea) => idea.track === null).length
  const filters: { value: 'ALL' | PrivateIdea['state']; label: string; count?: number }[] = [
    { value: 'ALL', label: 'Tất cả', count: mine.length }, { value: 'NO_DRAFT', label: 'Chưa có nháp', count: mine.filter((idea) => idea.state === 'NO_DRAFT').length },
    { value: 'DRAFTED', label: 'Có nháp', count: mine.filter((idea) => idea.state === 'DRAFTED').length }, { value: 'POSTED', label: 'Đã đăng', count: mine.filter((idea) => idea.state === 'POSTED').length },
    ...(counts.dropped > 0 || state === 'DROPPED' ? [{ value: 'DROPPED' as const, label: 'Đã bỏ' }] : []),
  ]
  // The list is asked for by track; ideas not filed anywhere have no track to ask for, so they are picked out here.
  const shown = (ideas.data || []).filter((idea) => inTab(idea, tab))
  const voices = space.data!.voices || {}
  // A line with neither a brand document nor samples writes in nobody's voice.
  const unready = draftTracks.filter((name) => name === tab && !(space.data!.master_dna || '').trim() && (voices[name]?.samples.length || 0) < 3)
  const tabs: { value: DraftTrack | 'none'; label: string; note: string }[] = [
    ...draftTracks.map((name) => {
      const stats = week.data?.tracks[name]?.stats
      return { value: name, label: trackName(voices, name), note: stats && stats.slots > 0 ? `${stats.posted}/${stats.slots} tuần này` : `${all.filter((idea) => idea.track === name).length} ý` }
    }),
    ...(unfiled > 0 || tab === 'none' ? [{ value: 'none' as const, label: 'Chưa xếp hướng', note: `${unfiled} ý` }] : []),
  ]

  return (
    <>
      <PageHeader title="Kho ý tưởng" helper={[
        'Ý ở đây chỉ tài khoản CTO thấy; không hiện ở bất kỳ màn hình nào của team.',
        'Lưu nhanh: dán link, kéo ảnh, hoặc bấm micro nói một câu.',
        'Mở một ý để AI soạn nháp bài đăng theo giọng của bạn.',
        'Không có gì tự đăng đi đâu: bạn chép nháp sang nền tảng và hẹn giờ ở đó.',
      ]} action={<span className="private-tag"><Lock size={13} aria-hidden="true" /> Chỉ bạn thấy</span>} />
      <div className="track-tabs" role="tablist" aria-label="Mạch nội dung">
        {tabs.map((item) => <button type="button" role="tab" key={item.value} aria-selected={tab === item.value} className={tab === item.value ? 'active' : undefined} onClick={() => chooseTab(item.value)}>{item.label}<small>{item.note}</small></button>)}
      </div>
      {unready.length > 0 && <p className="notice notice-warn private-hint">Mạch {unready.map((name) => trackName(voices, name)).join(' và ')} chưa có Master DNA hoặc đủ 3 bài mẫu. Thêm ở <Link to="/rieng/giong">Giọng của tôi</Link> để nháp ra đúng giọng bạn.</p>}
      {tab === 'none'
        ? <p className="notice private-hint">Các ý ở đây chưa thuộc mạch nào. Mở một ý để xếp nó vào một mạch; ý chưa xếp vẫn chọn được cho một ô của tuần.</p>
        : <><WeekPlan ideas={all} only={tab} /><SignalBar track={tab} /></>}
      {error != null && <ErrorNotice error={error} />}
      {(recording.kind === 'DICTATION' || recording.phase === 'idle') && <LiveRecording onUse={useSpoken} />}
      <form className="private-capture" onSubmit={(event) => { event.preventDefault(); if (note.trim()) save.mutate() }}
        onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); addFiles(Array.from(event.dataTransfer.files)) }}>
        <textarea aria-label="Ý mới" rows={2} value={note} onChange={(event) => setNote(event.target.value)} placeholder={tab === 'none' ? 'Dán link, hoặc gõ một câu về ý này…' : `Ý mới cho mạch ${trackName(voices, tab)}: dán link, hoặc gõ một câu…`}
          onPaste={(event) => { const pasted = Array.from(event.clipboardData.files); if (pasted.length > 0) { event.preventDefault(); addFiles(pasted) } }}
          onKeyDown={(event) => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && note.trim()) save.mutate() }} />
        {files.length > 0 && <div className="composer-chips">{files.map((file, index) => <span className="chip" key={`${file.name}-${index}`}><FileText size={14} aria-hidden="true" /><span className="chip-label">{file.name}<small>{(file.size / 1024).toFixed(0)} KB</small></span><button type="button" aria-label={`Xóa ${file.name}`} onClick={() => setFiles(files.filter((_, fileIndex) => fileIndex !== index))}><X size={13} /></button></span>)}</div>}
        <div className="private-capture-bar">
          <button type="button" className="button button-secondary button-small" onClick={() => fileRef.current?.click()}><Paperclip size={14} aria-hidden="true" /> Ảnh</button>
          <span className="composer-spacer" />
          <button type="button" className={busy ? 'icon-button active is-recording' : 'icon-button'} aria-label={busy ? 'Nói xong' : 'Nói để nhập'} title={busy ? 'Nói xong' : 'Nói để nhập'} aria-pressed={busy} disabled={meetingRunning || recording.phase === 'starting' || recording.phase === 'stopping'} onClick={toggleDictation}><Mic size={18} /></button>
          <button className="button button-primary" disabled={!note.trim() || save.isPending}>{save.isPending ? 'Đang lưu…' : 'Lưu ý'}</button>
        </div>
        <input ref={fileRef} type="file" hidden multiple accept={ACCEPTED_FILE_TYPES.join(',')} onChange={(event) => { addFiles(Array.from(event.target.files ?? [])); event.target.value = '' }} />
      </form>
      <div className="private-filters">
        <div className="segmented" role="group" aria-label="Lọc ý">
          {filters.map((filter) => <button type="button" key={filter.value} aria-pressed={state === filter.value} className={state === filter.value ? 'active' : undefined} onClick={() => setState(filter.value)}>{filter.label}{filter.count != null && <> <small>{filter.count}</small></>}</button>)}
        </div>
        <div className="private-filters-side">
          <label className="search-field"><Search size={15} aria-hidden="true" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Tìm trong kho ý tưởng…" aria-label="Tìm trong kho ý tưởng" /></label>
        </div>
      </div>
      {ideas.isLoading ? <LoadingBlock /> : ideas.error ? <ErrorNotice error={ideas.error} onRetry={() => { void ideas.refetch() }} /> : shown.length === 0 ? (
        <section className="panel"><EmptyState icon={<Lightbulb size={20} />} title={search.trim() || state !== 'ALL' ? 'Không có ý nào khớp' : tab === 'none' ? 'Không còn ý nào chưa xếp' : 'Mạch này chưa có ý nào'} text={search.trim() || state !== 'ALL' ? 'Đổi bộ lọc hoặc từ khóa.' : 'Lưu ý đầu tiên ở ô phía trên: một link, một ảnh, hoặc một câu.'} /></section>
      ) : (
        <section className="panel private-list" aria-label="Danh sách ý">
          {shown.map((idea) => (
            <Link key={idea.id} to={`/rieng/y/${idea.id}`} className="private-row">
              <span className="private-row-main">
                <strong>{idea.analysed ? idea.title : idea.title || 'Ý chưa có tiêu đề'}</strong>
                <small>{formatDate(idea.created_at)}{!idea.analysed && ['NEW', 'PROCESSING'].includes(idea.status) ? ' · AI đang đọc…' : ''}{idea.note && idea.analysed ? ` · ${idea.note.slice(0, 90)}${idea.note.length > 90 ? '…' : ''}` : ''}</small>
              </span>
              <span className={`status private-state-${idea.state.toLowerCase()}`}>{ideaStateLabels[idea.state]}{idea.state === 'POSTED' && idea.posted_at ? ` ${formatDay(idea.posted_at)}` : idea.channels.length > 0 && idea.state === 'DRAFTED' ? ` · ${idea.channels.map(channelName).join(', ')}` : ''}</span>
              <ChevronRight size={16} aria-hidden="true" />
            </Link>
          ))}
        </section>
      )}
    </>
  )
}

// One written (or failed, or still being written) draft.
function DraftCard({ draft, intakeId, open, trackLabel, slot, adaptTo, onToggle, onChanged, onAsk }: {
  draft: PostDraft; intakeId: string; open: boolean; trackLabel: string; slot?: PlanSlot; onToggle: () => void; onChanged: () => void
  // The other direction of the master document, with its own default channel.
  adaptTo?: { track: DraftTrack; label: string; channel: DraftChannel }
  onAsk: (body: DraftAsk) => void
}) {
  const [text, setText] = useState(draft.text || '')
  const [copied, setCopied] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [posting, setPosting] = useState(false)
  const [postedAt, setPostedAt] = useState('')
  const [postedUrl, setPostedUrl] = useState('')
  const [error, setError] = useState<unknown>()
  const box = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { setText(draft.text || '') }, [draft.text])
  useEffect(() => { const element = box.current; if (element && open) { element.style.height = 'auto'; element.style.height = `${element.scrollHeight + 2}px` } }, [text, open])
  const update = useMutation({
    mutationFn: (body: { text?: string; posted?: boolean; posted_at?: string; posted_url?: string }) => api<PostDraft>(`/intakes/${intakeId}/drafts/${draft.id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    onMutate: () => setError(undefined), onSuccess: () => { setPosting(false); onChanged() }, onError: setError,
  })
  // Approving fixes the text; with a slot of the week plan in hand, the draft fills that slot.
  const approve = useMutation({
    mutationFn: (on: boolean) => api<PostDraft>(`/intakes/${intakeId}/drafts/${draft.id}/approve`, on ? { method: 'POST', body: JSON.stringify({ slot_id: slot?.id || null }) } : { method: 'DELETE' }),
    onMutate: () => setError(undefined), onSuccess: onChanged, onError: setError,
  })
  const approved = Boolean(draft.approved_at)
  const locked = approved || Boolean(draft.posted_at)
  const askPosted = () => { setPostedAt(localInput(draft.scheduled_for && new Date(draft.scheduled_for) < new Date() ? new Date(draft.scheduled_for) : new Date())); setPostedUrl(''); update.reset(); setPosting(true) }
  const remove = useMutation({
    mutationFn: () => api(`/intakes/${intakeId}/drafts/${draft.id}`, { method: 'DELETE' }),
    onSuccess: () => { setRemoving(false); onChanged() },
  })
  const dirty = draft.status === 'DONE' && text.trim() !== (draft.text || '').trim()
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setCopied(true); window.setTimeout(() => setCopied(false), 2000) }
    catch { box.current?.focus(); box.current?.select(); setError(new Error('Trình duyệt không cho chép tự động. Nội dung đã được chọn sẵn: bấm Ctrl+C.')) }
  }
  // Swapping the opening line: the first paragraph is the hook.
  const useHook = (hook: string) => { const parts = text.split(/\n\s*\n/); parts[0] = hook; setText(parts.join('\n\n')) }
  const outline = draft.kind === 'OUTLINE'
  // The first line of a long piece is its title; of a social post, its opening.
  const titled = outline || draft.channel === 'BLOG' || draft.channel === 'VIDEO_SCRIPT'
  const again: DraftAsk = { channel: draft.channel, angle: draft.angle, source_draft_id: draft.source_draft_id || undefined, ...choicesOf(draft), group_context: draft.group_context, outline }
  const chosen = [trackLabel, labelOf(draftGoals, draft.goal), labelOf(draftAudiences, draft.audience), draft.pillar, draft.context && draft.context !== 'REAL' ? labelOf(draftContexts, draft.context) : '', draft.commercial ? labelOf(draftCommercials, draft.commercial) : ''].filter(Boolean).join(' · ')
  const head = (
    <>
      <strong>{draftName(draft)}</strong>
      <span>{formatDate(draft.created_at)} · {draft.source_draft_id ? 'chỉnh từ nháp khác' : 'AI soạn'}{draft.edited_at ? ' · bạn đã sửa' : ''}{chosen ? ` · ${chosen}` : ''}</span>
      {draft.posted_at ? <span className="status report-valid">Đã đăng {formatMoment(draft.posted_at)}</span> : approved && <span className="status draft-approved">Đã duyệt{draft.scheduled_for ? ` · đăng ${formatMoment(draft.scheduled_for)}` : ''}</span>}
      {draft.status === 'DONE' && <span className="draft-words">{wordCount(open ? text : draft.text || '')} chữ</span>}
    </>
  )

  if (draft.status === 'PENDING') return <article className="draft-card is-pending" role="status"><header><span className="spinner" aria-hidden="true" /><strong>AI đang soạn nháp {draftName(draft)}…</strong><span>Bạn có thể rời trang; nháp vẫn được lưu.</span></header></article>
  if (draft.status === 'FAILED') return (
    <article className="draft-card is-failed">
      <header><strong>{draftName(draft)}</strong><span>AI chưa soạn được lúc này{draft.error ? ` (${draft.error})` : ''}.</span></header>
      <div className="draft-actions">
        <button type="button" className="button button-secondary button-small" onClick={() => { onAsk(again); remove.mutate() }}>Thử lại</button>
        <button type="button" className="button button-secondary button-small" onClick={() => remove.mutate()}>Bỏ qua</button>
      </div>
    </article>
  )
  if (!open) return <article className="draft-card is-closed"><button type="button" className="draft-toggle" aria-expanded={false} onClick={onToggle}>{head}<ChevronRight size={15} aria-hidden="true" /></button></article>

  return (
    <article className="draft-card">
      {removing && (
        <ConfirmDialog title="Xóa nháp này?" confirmLabel="Xóa nháp" busy={remove.isPending} error={remove.error ?? undefined} onConfirm={() => remove.mutate()} onCancel={() => setRemoving(false)}>
          <p><strong>Nháp {draftName(draft)}</strong><br />{formatDate(draft.created_at)} · {wordCount(draft.text || '')} chữ</p>
          <ul><li>Nháp bị xóa hẳn, không khôi phục được.</li><li>Ý gốc và các nháp khác vẫn còn.</li></ul>
        </ConfirmDialog>
      )}
      {posting && (
        <ConfirmDialog plain title="Bài này đã đăng?" confirmLabel="Ghi là đã đăng" busyLabel="Đang ghi…" busy={update.isPending} error={update.error ?? undefined}
          onConfirm={() => update.mutate({ posted: true, posted_at: postedAt ? new Date(postedAt).toISOString() : undefined, posted_url: postedUrl.trim() || undefined })} onCancel={() => setPosting(false)}>
          <p><strong>{draftName(draft)}</strong>{slot ? ` · ô ${slotLabel(slot)}` : ''}</p>
          <label className="confirm-field">Giờ bài lên<input type="datetime-local" value={postedAt} max={localInput(new Date())} onChange={(event) => setPostedAt(event.target.value)} /></label>
          <label className="confirm-field">Link bài (không bắt buộc)<input type="url" value={postedUrl} maxLength={500} placeholder="https://…" onChange={(event) => setPostedUrl(event.target.value)} /></label>
        </ConfirmDialog>
      )}
      <button type="button" className="draft-toggle" aria-expanded onClick={onToggle}>{head}</button>
      {error != null && <ErrorNotice error={error} />}
      {locked && <p className="draft-locked"><Lock size={13} aria-hidden="true" /> {draft.posted_at ? <>Bài đã đăng{draft.posted_url ? <> · <a href={draft.posted_url} target="_blank" rel="noreferrer">mở bài</a></> : ''}{draft.posted_via === 'WEBHOOK' ? ' · ghi bởi luồng đăng' : ''}. Nội dung giữ nguyên như lúc đăng.</> : 'Đã duyệt nên nội dung bị khóa. Bấm "Bỏ duyệt" để sửa.'}</p>}
      {draft.publish_error && !draft.posted_at && <p className="notice notice-warn draft-publish-error">Luồng đăng báo chưa đăng được: {draft.publish_error}. Bài vẫn ở trạng thái đã duyệt; luồng sẽ thử lại, hoặc bạn đăng tay rồi đánh dấu.</p>}
      <textarea ref={box} aria-label={`Nháp ${draftName(draft)}`} value={text} readOnly={locked} onChange={(event) => setText(event.target.value)} />
      {draft.hooks.length > 0 && (
        <div className="draft-hooks">
          <span>{titled ? 'Tiêu đề khác' : 'Câu mở khác'}</span>
          {draft.hooks.map((hook) => <div key={hook}><p>{hook}</p>{draft.channel !== 'VIDEO_SCRIPT' && !locked && <button type="button" className="text-button" onClick={() => useHook(hook)}>{titled ? 'Dùng tiêu đề này' : 'Dùng câu này'}</button>}</div>)}
        </div>
      )}
      {draft.gaps.length > 0 && <div className="draft-gaps"><TriangleAlert size={15} aria-hidden="true" /><div><strong>{outline ? 'Cần bạn chuẩn bị trước khi viết' : draft.channel === 'VIDEO_SCRIPT' ? 'Cần bạn chuẩn bị trước khi quay' : 'Cần bạn bổ sung trước khi đăng'}</strong><ul>{draft.gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul></div></div>}
      <div className="draft-actions">
        <button type="button" className="button button-primary button-small" onClick={() => { void copy() }}>{copied ? <><Check size={14} aria-hidden="true" /> Đã chép</> : <><Copy size={14} aria-hidden="true" /> Chép</>}</button>
        {!locked && <button type="button" className="button button-secondary button-small" disabled={!dirty || update.isPending} onClick={() => update.mutate({ text })}>{update.isPending && update.variables?.text != null ? 'Đang lưu…' : dirty ? 'Lưu sửa đổi' : 'Đã lưu'}</button>}
        {!outline && !draft.posted_at && (approved
          ? <button type="button" className="button button-secondary button-small" disabled={approve.isPending} onClick={() => approve.mutate(false)}>Bỏ duyệt</button>
          : <button type="button" className="button button-secondary button-small draft-approve" disabled={dirty || approve.isPending} title={dirty ? 'Lưu sửa đổi trước khi duyệt' : undefined} onClick={() => approve.mutate(true)}><CircleCheck size={14} aria-hidden="true" /> {slot ? `Duyệt cho ô ${slotLabel(slot)}` : 'Duyệt'}</button>)}
        {outline ? longChannels.map((target) => (
          <button type="button" key={target.value} className="button button-secondary button-small" disabled={dirty} title={dirty ? 'Lưu sửa đổi của dàn ý trước' : undefined} onClick={() => onAsk({ channel: target.value, source_draft_id: draft.id, ...choicesOf(draft) })}><Sparkles size={14} aria-hidden="true" /> Viết thành {target.label.toLowerCase()}</button>
        )) : (
        <select className="draft-adapt" aria-label="Chỉnh cho kênh khác" value="" onChange={(event) => {
          const value = event.target.value
          if (value.startsWith('GROUP:')) onAsk({ channel: 'FACEBOOK_GROUP', group_context: value.slice(6), source_draft_id: draft.id, ...choicesOf(draft) })
          // The other direction keeps the facts and changes the question, the depth and the call; its pillars and money are its own.
          else if (value === 'DIRECTION' && adaptTo) onAsk({ channel: adaptTo.channel, source_draft_id: draft.id, track: adaptTo.track, goal: null, audience: null, pillar: null, context: draft.context, commercial: null })
          else if (value) onAsk({ channel: value as DraftChannel, source_draft_id: draft.id, ...choicesOf(draft) })
        }}>
          <option value="">Chỉnh cho kênh khác…</option>
          {[...draftChannels, ...longChannels].filter((channel) => channel.value !== draft.channel).map((channel) => <option key={channel.value} value={channel.value}>{channel.label}</option>)}
          {adaptTo && <optgroup label="Chuyển thể sang hướng khác"><option value="DIRECTION">Hướng {adaptTo.label} · {channelName(adaptTo.channel)}</option></optgroup>}
          <optgroup label="Viết lại cho hội nhóm ngành">
            {draftGroups.filter((group) => group.value !== draft.group_context).map((group) => <option key={group.value} value={`GROUP:${group.value}`}>Hội nhóm {group.label}</option>)}
          </optgroup>
        </select>
        )}
        <button type="button" className="button button-secondary button-small" onClick={() => onAsk(again)}>Soạn lại</button>
        {!outline && (draft.posted_at
          ? <button type="button" className="button button-secondary button-small is-posted" disabled={update.isPending} aria-pressed onClick={() => update.mutate({ posted: false })} title="Bấm để bỏ đánh dấu"><Check size={14} aria-hidden="true" /> Đã đăng</button>
          : <button type="button" className="button button-secondary button-small" disabled={update.isPending} aria-pressed={false} onClick={askPosted}><Check size={14} aria-hidden="true" /> Đánh dấu đã đăng</button>)}
        {!(approved && !draft.posted_at) && <button type="button" className="icon-button draft-delete" aria-label="Xóa nháp" title="Xóa nháp" onClick={() => { remove.reset(); setRemoving(true) }}><Trash2 size={15} /></button>}
      </div>
    </article>
  )
}

function PostDrafts({ intakeId, ideaTrack, voices, masterDna, slot }: { intakeId: string; ideaTrack: DraftTrack; voices: Record<string, PrivateVoice>; masterDna: string; slot?: PlanSlot }) {
  const queryClient = useQueryClient()
  // Opened from a slot of the week plan: the slot says which line, which channel and which pillar.
  const [track, setTrack] = useState<DraftTrack>(slot?.track || ideaTrack)
  const voice = voices[track]
  const defaultSocial = (value: DraftChannel | undefined): VoiceChannel => (value && draftChannels.some((item) => item.value === value) ? value as VoiceChannel : 'FACEBOOK')
  const [channel, setChannel] = useState<VoiceChannel>(slot && draftChannels.some((item) => item.value === slot.channel) ? slot.channel as VoiceChannel : slot?.channel === 'FACEBOOK_GROUP' ? 'FACEBOOK' : defaultSocial(voice?.default_channel))
  const [context, setContext] = useState<DraftContext | ''>('')
  const [commercial, setCommercial] = useState<DraftCommercial | ''>('')
  const [goal, setGoal] = useState('')
  const [audience, setAudience] = useState('')
  const [pillar, setPillar] = useState(slot?.pillar || '')
  const [angle, setAngle] = useState('')
  const [form, setForm] = useState<DraftForm>(slot?.channel === 'BLOG' || slot?.channel === 'VIDEO_SCRIPT' ? slot.channel : !slot && (voice?.default_channel === 'BLOG' || voice?.default_channel === 'VIDEO_SCRIPT') ? voice.default_channel : 'SOCIAL')
  const [prompting, setPrompting] = useState(false)
  // Money behind a piece belongs to the technical direction only.
  useEffect(() => { if (track !== 'technical') setCommercial('') }, [track])
  const other = otherTrack(track)
  const adaptTo = { track: other, label: trackName(voices, other), channel: voices[other]?.default_channel || 'FACEBOOK' }
  // Filing the idea under another line moves the choice with it; a pillar belongs to one line.
  const lastTrack = useRef(track)
  useEffect(() => { if (!slot) setTrack(ideaTrack) }, [ideaTrack, slot])
  useEffect(() => { if (lastTrack.current !== track) { lastTrack.current = track; setPillar('') } }, [track])
  const pillars = [...(voice?.pillars || []), ...(pillar && !(voice?.pillars || []).includes(pillar) ? [pillar] : [])]
  const samples = voice?.samples.length || 0
  const [openId, setOpenId] = useState<string | null | undefined>(undefined)
  const [error, setError] = useState<unknown>()
  const drafts = useQuery({
    queryKey: ['drafts', intakeId],
    queryFn: () => api<PostDraft[]>(`/intakes/${intakeId}/drafts`),
    // The AI worker writes; ask again until nothing is pending.
    refetchInterval: (query) => ((query.state.data as PostDraft[] | undefined)?.some((draft) => draft.status === 'PENDING') ? 1500 : false),
  })
  const changed = () => {
    void queryClient.invalidateQueries({ queryKey: ['drafts', intakeId] })
    void queryClient.invalidateQueries({ queryKey: ['private-space'] })
    void queryClient.invalidateQueries({ queryKey: ['private-ideas'] })
    void queryClient.invalidateQueries({ queryKey: ['plan-week'] })
    void queryClient.invalidateQueries({ queryKey: ['plan-slot'] })
  }
  const ask = useMutation({
    mutationFn: (body: DraftAsk) => api<PostDraft>(`/intakes/${intakeId}/drafts`, { method: 'POST', body: JSON.stringify(body) }),
    onMutate: () => setError(undefined),
    onSuccess: () => { setOpenId(undefined); changed() },
    onError: setError,
  })
  const list = drafts.data || []
  const pending = list.some((draft) => draft.status === 'PENDING')
  // Nothing chosen yet means the newest written draft is open.
  const shownId = openId === undefined ? list.find((draft) => draft.status === 'DONE')?.id : openId

  return (
    <section className="panel post-drafts" aria-label="Nháp bài đăng">
      <div className="panel-heading"><div><h2>Nháp bài đăng</h2></div>{list.length > 0 && <span className="muted">{list.filter((draft) => draft.status === 'DONE').length} nháp</span>}</div>
      {slot && <p className="draft-slot"><CalendarDays size={15} aria-hidden="true" /><span>Đang viết cho ô <strong>{slotLabel(slot)}</strong> · {channelName(slot.channel)}{slot.pillar ? ` · trụ ${slot.pillar}` : ''}. Duyệt một nháp để ô này có bài.</span></p>}
      <div className="draft-choices">
        <div className="segmented" role="group" aria-label="Hướng nội dung">
          {draftTracks.map((name) => <button type="button" key={name} aria-pressed={track === name} className={track === name ? 'active' : undefined} onClick={() => setTrack(name)}>{trackName(voices, name)}</button>)}
        </div>
        <select aria-label="Mục tiêu bài" value={goal} onChange={(event) => setGoal(event.target.value)}>
          <option value="">Mục tiêu: AI tự chọn</option>
          {draftGoals.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
        <select aria-label="Đối tượng" value={audience} onChange={(event) => setAudience(event.target.value)}>
          <option value="">Đối tượng: theo giọng</option>
          {draftAudiences.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
        {pillars.length > 0 && (
          <select aria-label="Trụ nội dung" value={pillar} onChange={(event) => setPillar(event.target.value)}>
            <option value="">Trụ: không chọn</option>
            {pillars.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        )}
        <select aria-label="Bối cảnh" value={context} onChange={(event) => setContext(event.target.value as DraftContext | '')}>
          <option value="">Bối cảnh: theo ghi chú</option>
          {draftContexts.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
        {track === 'technical' && (
          <select aria-label="Quan hệ thương mại" value={commercial} onChange={(event) => setCommercial(event.target.value as DraftCommercial | '')}>
            <option value="">Thương mại: không có</option>
            {draftCommercials.filter((item) => item.value !== 'NONE').map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        )}
      </div>
      <div className="segmented draft-forms" role="group" aria-label="Kiểu nháp">
        {draftForms.map((item) => <button type="button" key={item.value} aria-pressed={form === item.value} className={form === item.value ? 'active' : undefined} onClick={() => setForm(item.value)}>{item.label}</button>)}
      </div>
      <div className={form === 'SOCIAL' ? 'draft-ask' : 'draft-ask is-long'}>
        {form === 'SOCIAL' && (
          <div className="segmented" role="group" aria-label="Kênh">
            {draftChannels.map((item) => <button type="button" key={item.value} aria-pressed={channel === item.value} className={channel === item.value ? 'active' : undefined} onClick={() => setChannel(item.value)}>{item.label}</button>)}
          </div>
        )}
        <input value={angle} onChange={(event) => setAngle(event.target.value)} maxLength={500} placeholder="Câu hỏi trung tâm hoặc góc nhìn muốn nhấn (không bắt buộc)" aria-label="Câu hỏi trung tâm" />
        <button type="button" className="button button-primary" disabled={ask.isPending || pending} onClick={() => ask.mutate({
          channel: form === 'SOCIAL' ? channel : form === 'OUTLINE' ? 'BLOG' : form, outline: form === 'OUTLINE',
          angle: angle.trim() || null, track, goal: goal || null, audience: audience || null, pillar: pillar || null,
          context: context || null, commercial: track === 'technical' && commercial ? commercial : null,
        })}><Sparkles size={15} aria-hidden="true" /> {pending ? 'Đang soạn…' : form === 'OUTLINE' ? 'Soạn dàn ý' : form === 'BLOG' ? 'Soạn bài blog' : form === 'VIDEO_SCRIPT' ? 'Soạn kịch bản' : 'Soạn nháp'}</button>
      </div>
      <p className="field-help">{masterDna.trim() ? `Theo Master DNA, hướng ${trackName(voices, track)}${samples > 0 ? ` · ${samples} bài mẫu` : ''} · khoảng 20 giây.` : samples > 0 ? `Theo giọng của hướng ${trackName(voices, track)} · ${samples} bài mẫu · khoảng 15 giây.` : <>Chưa có Master DNA và bài mẫu nên nháp sẽ ra giọng chung chung. Thêm ở <Link to="/rieng/giong">Giọng của tôi</Link>.</>} Nháp chỉ nằm ở đây, không tự đăng đi đâu.</p>
      <p className="field-help"><button type="button" className="text-button" onClick={() => setPrompting(true)}><Eye size={13} aria-hidden="true" /> Xem prompt sẽ gửi cho AI</button></p>
      <PromptAside open={prompting} drawer onClose={() => setPrompting(false)}>
        <p className="prompt-hint">Đúng những gì AI sẽ nhận nếu bạn bấm soạn ngay bây giờ, với các lựa chọn đang chọn. Không có gì được gửi tới AI khi xem.</p>
        <PromptPreviewBody body={{ track, intake_id: intakeId, channel: form === 'SOCIAL' ? channel : form === 'OUTLINE' ? 'BLOG' : form, outline: form === 'OUTLINE', goal: goal || null, audience: audience || null, pillar: pillar || null, angle: angle.trim() || null, context: context || null, commercial: track === 'technical' && commercial ? commercial : null }} />
      </PromptAside>
      {form === 'OUTLINE' && <p className="field-help">Dàn ý ngắn, bỏ đi không tiếc. Ưng thì bấm "Viết thành bài blog" hoặc "Viết thành kịch bản video" trên thẻ dàn ý; AI viết đúng theo dàn ý đó.</p>}
      {(form === 'BLOG' || form === 'VIDEO_SCRIPT') && <p className="field-help">Bài dài mất khoảng một phút. Nên soạn dàn ý trước rồi viết từ dàn ý, để không phải bỏ cả một bài.</p>}
      {error != null && <ErrorNotice error={error} />}
      {drafts.error != null && <ErrorNotice error={drafts.error} onRetry={() => { void drafts.refetch() }} />}
      {list.length > 0 && (
        <div className="draft-list">
          {list.map((draft) => <DraftCard key={draft.id} draft={draft} intakeId={intakeId} open={draft.id === shownId} trackLabel={trackName(voices, draft.track)} adaptTo={draft.kind === 'OUTLINE' ? undefined : { track: otherTrack((draft.track as DraftTrack) || track), label: trackName(voices, otherTrack((draft.track as DraftTrack) || track)), channel: voices[otherTrack((draft.track as DraftTrack) || track)]?.default_channel || 'FACEBOOK' }} slot={slot && slot.state !== 'POSTED' && slot.state !== 'SKIPPED' && (!slot.draft || slot.draft.id === draft.id) ? slot : undefined} onToggle={() => setOpenId(draft.id === shownId ? null : draft.id)} onChanged={changed} onAsk={(body) => ask.mutate(body)} />)}
        </div>
      )}
    </section>
  )
}

// Links in a note are the source of the idea: make them one click away.
function NoteText({ text }: { text: string }) {
  return <>{text.split(/(https?:\/\/[^\s]+)/g).map((part, index) => (/^https?:\/\//.test(part) ? <a key={index} href={part} target="_blank" rel="noreferrer">{part}</a> : part))}</>
}

function PrivateIdeaPage() {
  const { id = '' } = useParams()
  const [opened] = useSearchParams()
  const slotId = opened.get('o') || ''
  const slot = useQuery({ queryKey: ['plan-slot', slotId], queryFn: () => api<PlanSlot>(`/private-space/plan/slots/${slotId}`), enabled: Boolean(slotId), retry: false })
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const space = usePrivateSpace()
  const [dropping, setDropping] = useState(false)
  const idea = useQuery({
    queryKey: ['intake', id], queryFn: () => api<Intake>(`/intakes/${id}`),
    refetchInterval: (query) => (['NEW', 'PROCESSING'].includes(query.state.data?.status || '') ? 2500 : false),
  })
  // The note is the owner's own words, so it is shown straight away. Reading it is still audited.
  const raw = useQuery({ queryKey: ['raw', id], queryFn: () => api<{ raw_text: string | null }>(`/intakes/${id}/raw`), enabled: Boolean(idea.data) })
  const filed = useQuery({ queryKey: ['idea-track', id], queryFn: () => api<{ track: DraftTrack | null }>(`/private-space/ideas/${id}/track`), enabled: Boolean(idea.data), retry: false })
  const file = useMutation({
    mutationFn: (track: DraftTrack | null) => api<{ track: DraftTrack | null }>(`/private-space/ideas/${id}/track`, { method: 'PUT', body: JSON.stringify({ track }) }),
    onSuccess: (next) => { queryClient.setQueryData(['idea-track', id], next); void queryClient.invalidateQueries({ queryKey: ['private-ideas'] }) },
  })
  const drop = useMutation({
    mutationFn: () => api<Intake>(`/intakes/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason: 'Bỏ khỏi kho ý tưởng', expected_version: idea.data!.version }) }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['private-ideas'] })
      void queryClient.invalidateQueries({ queryKey: ['private-space'] })
      navigate('/rieng')
    },
  })

  if (idea.isLoading || space.isLoading) return <LoadingBlock />
  if (idea.error || !idea.data) return <ErrorNotice error={idea.error || new Error('Không tìm thấy ý này.')} onRetry={() => { void idea.refetch() }} />
  const item = idea.data
  if (space.data?.project && item.project_id !== space.data.project.id) return <Navigate to={`/intakes/${item.id}`} replace />
  const reading = ['NEW', 'PROCESSING'].includes(item.status)
  const dropped = item.status === 'REJECTED'
  const note = raw.data?.raw_text || ''
  const voices = space.data?.voices || {}

  return (
    <>
      {dropping && (
        <ConfirmDialog title="Bỏ ý này?" confirmLabel="Bỏ ý" busyLabel="Đang bỏ…" busy={drop.isPending} error={drop.error ?? undefined} onConfirm={() => drop.mutate()} onCancel={() => setDropping(false)}>
          <p><strong>{item.normalized_title || 'Ý chưa có tiêu đề'}</strong></p>
          <ul><li>Ý chuyển sang mục "Đã bỏ" và không còn trong kho.</li><li>Nội dung và các nháp vẫn được giữ; không khôi phục lại trạng thái cũ được từ màn hình này.</li></ul>
        </ConfirmDialog>
      )}
      <div className="detail-top">
        <Link className="back-link" to="/rieng"><ArrowLeft size={15} /> Kho ý tưởng</Link>
        <div className="detail-actions">{!dropped && !reading && <button type="button" className="button button-secondary" onClick={() => { drop.reset(); setDropping(true) }}>Bỏ ý này</button>}</div>
      </div>
      <header className="detail-header private-idea-head">
        <div><div className="detail-meta"><span className="private-tag"><Lock size={12} aria-hidden="true" /> Riêng</span>{dropped && <span className="status private-state-dropped">Đã bỏ</span>}
          <select className="idea-track" aria-label="Mạch nội dung của ý" value={filed.data?.track || ''} disabled={file.isPending || filed.isLoading} onChange={(event) => file.mutate((event.target.value || null) as DraftTrack | null)}>
            <option value="">Chưa xếp hướng</option>
            {draftTracks.map((name) => <option key={name} value={name}>Hướng {trackName(voices, name)}</option>)}
          </select></div>
          <h1>{reading ? 'AI đang đọc ý này…' : item.normalized_title || 'Ý chưa có tiêu đề'}</h1><p>Lưu {formatDate(item.created_at)} · {item.public_id}</p></div>
      </header>
      <div className="review-grid">
        <section className="panel"><div className="panel-heading"><div><h2>Ghi chú và nguồn của bạn</h2></div></div>
          {raw.isLoading ? <LoadingBlock /> : raw.error ? <ErrorNotice error={raw.error} onRetry={() => { void raw.refetch() }} /> : <div className="raw-content private-note">{note ? <NoteText text={note} /> : 'Ý này chỉ có tệp đính kèm, không có ghi chú.'}</div>}
        </section>
        <section className="panel"><div className="panel-heading"><div><h2>AI hiểu là</h2></div></div>
          <div className="raw-content private-note">{reading ? 'Đang đọc…' : item.normalized_summary || 'AI chưa viết được tóm tắt cho ý này. Nháp vẫn soạn được từ ghi chú của bạn.'}</div>
        </section>
      </div>
      {file.error != null && <ErrorNotice error={file.error} />}
      {!dropped && (slotId && slot.isLoading ? <LoadingBlock /> : <PostDrafts key={slot.data?.id || 'free'} intakeId={item.id} ideaTrack={filed.data?.track || 'business'} voices={voices} masterDna={space.data?.master_dna || ''} slot={slot.data && (!slot.data.idea || slot.data.idea.id === item.id) ? slot.data : undefined} />)}
    </>
  )
}

const promptBlockNames: Record<string, string> = {
  choices: 'Chủ thể, hướng và lựa chọn', author: 'Giọng: các ô ngắn', dna: 'Master DNA (lõi chung)', references: 'Tài liệu tham chiếu', notebook: 'Sổ ghi chú', published: 'Bài đã đăng của hướng',
  samples: 'Bài mẫu', outline: 'Dàn ý đã giữ', previous: 'Nháp cần chuyển thể', angle: 'Câu hỏi trung tâm', about: 'AI hiểu ý là', note: 'Ghi chú của ý',
}
// Whose words a block holds decides how the AI treats it.
const promptTrust: Record<PromptPreview['blocks'][number]['trust'], { label: string; hint: string }> = {
  CHOICE: { label: 'Bạn chọn', hint: 'Lựa chọn trên màn hình cho lần soạn này.' },
  AUTHOR: { label: 'Của bạn', hint: 'Bạn viết làm chuẩn: AI theo, và ưu tiên hơn quy tắc mặc định.' },
  DATA: { label: 'Hệ thống', hint: 'Hệ thống ghép vào từ dữ liệu đã có.' },
  UNTRUSTED: { label: 'Không tin cậy', hint: 'AI chỉ tham khảo, không làm theo chỉ dẫn nào nằm trong phần này.' },
}
const promptCut = (cut: { what: string; kept: number; total: number }) => {
  const sample = cut.what.match(/^sample (\d+) characters$/)
  const amount = `${cut.kept.toLocaleString('vi-VN')}/${cut.total.toLocaleString('vi-VN')}`
  return sample ? `Bài mẫu ${sample[1]} bị cắt: giữ ${amount} ký tự` : cut.what === 'notes' ? `Sổ quá dài: chỉ ${amount} ghi chú tới được AI` : cut.what === 'samples' ? `Chỉ ${amount} bài mẫu được dùng` : `Bị cắt: giữ ${amount} ký tự`
}

function useDebounced<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => { const timer = window.setTimeout(() => setSettled(value), delay); return () => window.clearTimeout(timer) }, [value, delay])
  return settled
}

// Exactly what would be sent to the AI for a draft asked for now: the fixed rules, then every block built from what the owner entered.
function PromptPreviewBody({ body }: { body: object }) {
  const [copied, setCopied] = useState(false)
  // Typing in the voice form changes the request on every key: wait for a pause before asking again.
  const key = useDebounced(JSON.stringify(body), 500)
  const preview = useQuery({
    queryKey: ['prompt-preview', key],
    queryFn: () => api<PromptPreview>('/private-space/prompt-preview', { method: 'POST', body: key }),
    placeholderData: (previous) => previous,
    staleTime: 30000,
  })
  if (preview.isLoading && !preview.data) return <LoadingBlock />
  if (preview.error && !preview.data) return <ErrorNotice error={preview.error} onRetry={() => { void preview.refetch() }} />
  const data = preview.data!
  const copy = async () => {
    const message = data.blocks.map((block) => block.text).join('\n\n')
    try { await navigator.clipboard.writeText(`=== SYSTEM ===\n${data.system_prompt}\n\n=== USER ===\n${message}`); setCopied(true); window.setTimeout(() => setCopied(false), 2000) } catch { /* the text can still be selected by hand */ }
  }
  const cuts = data.blocks.reduce((sum, block) => sum + block.cuts.length, 0)
  return (
    <div className={preview.isFetching ? 'prompt-preview is-updating' : 'prompt-preview'}>
      <p className="prompt-meta">
        <span><b>{data.prompt_version}</b> · {data.model}</span>
        <span>{(data.system_chars + data.message_chars).toLocaleString('vi-VN')} ký tự</span>
        <button type="button" className="text-button" onClick={() => { void copy() }}>{copied ? 'Đã chép' : 'Chép toàn bộ'}</button>
      </p>
      {preview.error != null && <ErrorNotice error={preview.error} />}
      {data.placeholder && <p className="prompt-note">Chưa chọn ý nào: chỗ của ý tưởng đang là chỗ giữ chỗ trong ngoặc vuông.</p>}
      {cuts > 0 && <p className="prompt-note is-warn"><TriangleAlert size={13} aria-hidden="true" /> {cuts} phần bị cắt trước khi gửi. Xem dòng cảnh báo trong từng khối.</p>}
      <details className="prompt-block trust-system" open>
        <summary><span>Quy tắc cố định</span><span className="status">Hệ thống</span><small>{data.system_chars.toLocaleString('vi-VN')} ký tự</small></summary>
        <p className="prompt-hint">Phần này giống nhau cho mọi lần soạn và không sửa được ở đây. Muốn AI viết khác đi, hãy sửa tài liệu DNA hoặc thêm "Điều đã quyết" vào sổ ghi chú: quy tắc ghi rõ tài liệu của bạn thắng mặc định.</p>
        <pre>{data.system_prompt}</pre>
      </details>
      {data.blocks.map((block) => (
        <details className={`prompt-block trust-${block.trust.toLowerCase()}`} key={block.key} open>
          <summary><span>{promptBlockNames[block.key] || block.key}</span><span className="status" title={promptTrust[block.trust].hint}>{promptTrust[block.trust].label}</span><small>{block.chars.toLocaleString('vi-VN')} ký tự</small></summary>
          {block.cuts.map((cut) => <p className="prompt-cut" key={cut.what}><TriangleAlert size={13} aria-hidden="true" /> {promptCut(cut)}</p>)}
          <pre>{block.text}</pre>
        </details>
      ))}
    </div>
  )
}

// The preview as a side panel: beside the page on a wide screen, a drawer over it otherwise or when asked.
function PromptAside({ open, drawer, onClose, children }: { open: boolean; drawer?: boolean; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    if (!open) return
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    document.addEventListener('keydown', escape)
    return () => document.removeEventListener('keydown', escape)
  }, [open, onClose])
  return (
    <>
      {open && <div className={drawer ? 'prompt-backdrop is-drawer' : 'prompt-backdrop'} role="presentation" onClick={onClose} />}
      <aside className={['prompt-aside', open ? 'is-open' : '', drawer ? 'is-drawer' : ''].filter(Boolean).join(' ')} aria-label="Xem trước prompt">
        <header><h2>Prompt gửi cho AI</h2><button type="button" className="icon-button prompt-close" aria-label="Đóng xem trước prompt" onClick={onClose}><X size={16} /></button></header>
        {(open || !drawer) && children}
      </aside>
    </>
  )
}

// On the voice page: the voice as it stands on the screen, with a kind of draft and, when wanted, a real idea.
function VoicePromptPreview({ track, voice, masterDna, open, onClose }: { track: DraftTrack; voice: PrivateVoice; masterDna: string; open: boolean; onClose: () => void }) {
  const [form, setForm] = useState<DraftForm>('SOCIAL')
  const [channel, setChannel] = useState<VoiceChannel>(draftChannels.some((item) => item.value === voice.default_channel) ? voice.default_channel as VoiceChannel : 'FACEBOOK')
  const [ideaId, setIdeaId] = useState('')
  const ideas = useQuery({ queryKey: ['private-ideas', 'ALL', '', ''], queryFn: () => api<PrivateIdea[]>('/private-space/ideas?state=ALL') })
  useEffect(() => { setIdeaId('') }, [track])
  const mine = (ideas.data || []).filter((idea) => idea.track === track || idea.track === null)
  return (
    <PromptAside open={open} onClose={onClose}>
      <div className="prompt-controls">
        <div className="segmented" role="group" aria-label="Kiểu nháp để xem trước">
          {draftForms.map((item) => <button type="button" key={item.value} aria-pressed={form === item.value} className={form === item.value ? 'active' : undefined} onClick={() => setForm(item.value)}>{item.label}</button>)}
        </div>
        {form === 'SOCIAL' && <select aria-label="Kênh để xem trước" value={channel} onChange={(event) => setChannel(event.target.value as VoiceChannel)}>{draftChannels.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>}
        <select aria-label="Ý để xem trước" value={ideaId} onChange={(event) => setIdeaId(event.target.value)}>
          <option value="">Ý tưởng: chỗ giữ chỗ</option>
          {mine.map((idea) => <option key={idea.id} value={idea.id}>{(idea.title || 'Ý chưa có tiêu đề').slice(0, 60)}</option>)}
        </select>
      </div>
      <p className="prompt-hint">Theo nội dung đang có trên trang, kể cả phần chưa lưu. Không có gì được gửi tới AI khi xem.</p>
      <PromptPreviewBody body={{ track, voice, master_dna: masterDna, intake_id: ideaId || null, channel: form === 'SOCIAL' ? channel : form === 'OUTLINE' ? 'BLOG' : form, outline: form === 'OUTLINE' }} />
    </PromptAside>
  )
}

// Keywords of each pillar: what the scanning tool searches for. AI offers, the owner keeps.
function PillarKeywordsPanel({ track, name, base = '/private-space/watch', byTrack = true }: { track: DraftTrack | 'content'; name: string; base?: string; byTrack?: boolean }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Record<string, string[]>>()
  const [typed, setTyped] = useState<Record<string, string>>({})
  const [saved, setSaved] = useState(false)
  const query = byTrack ? `?track=${track}` : ''
  const keywords = useQuery({
    queryKey: ['watch-keywords', base, track], queryFn: () => api<PillarKeywords>(`${base}/keywords${query}`),
    // The AI worker suggests; ask again until it has answered.
    refetchInterval: (query) => ((query.state.data as PillarKeywords | undefined)?.request?.status === 'PENDING' ? 2000 : false),
  })
  const stored = keywords.data ? Object.fromEntries(keywords.data.pillars.map((row) => [row.pillar, row.keywords])) : undefined
  useEffect(() => { setDraft(undefined); setTyped({}) }, [track])
  useEffect(() => { if (stored && !draft) setDraft(stored) }, [stored, draft])
  const suggest = useMutation({
    mutationFn: () => api(`${base}/keywords/suggest${query}`, { method: 'POST' }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['watch-keywords', base, track] }) },
  })
  const save = useMutation({
    mutationFn: (pillars: Record<string, string[]>) => api<PillarKeywords>(`${base}/keywords${query}`, { method: 'PUT', body: JSON.stringify({ pillars }) }),
    onSuccess: (next) => { queryClient.setQueryData(['watch-keywords', base, track], next); setDraft(Object.fromEntries(next.pillars.map((row) => [row.pillar, row.keywords]))); setSaved(true); window.setTimeout(() => setSaved(false), 2500) },
  })
  if (keywords.isLoading) return <LoadingBlock />
  if (keywords.error || !keywords.data) return <ErrorNotice error={keywords.error || new Error('Chưa tải được từ khóa.')} onRetry={() => { void keywords.refetch() }} />
  const data = keywords.data
  const list = draft || stored || {}
  const dirty = JSON.stringify(list) !== JSON.stringify(stored)
  const thinking = data.request?.status === 'PENDING' || suggest.isPending
  const add = (pillar: string, word: string) => {
    const value = word.trim().replace(/\s+/g, ' ')
    const held = list[pillar] || []
    if (!value || held.length >= 12 || held.some((item) => item.toLowerCase() === value.toLowerCase())) return
    setDraft({ ...list, [pillar]: [...held, value] })
  }
  if (data.pillars.length === 0) return <p className="plan-empty">Mạch {name} chưa có trụ nội dung. Khai trụ ở <Link to="/rieng/giong">Giọng của tôi</Link> rồi quay lại đặt từ khóa.</p>
  return (
    <div className="keyword-panel">
      {data.pillars.map(({ pillar }) => {
        const held = list[pillar] || []
        const offered = (data.suggested[pillar] || []).filter((word) => !held.some((item) => item.toLowerCase() === word.toLowerCase()))
        return (
          <div className="keyword-pillar" key={pillar}>
            <div className="keyword-pillar-head"><strong>{pillar}</strong><span className="muted">{held.length}/12</span></div>
            <div className="glossary-terms">
              {held.map((word) => <span className="chip" key={word}><span className="chip-label">{word}</span><button type="button" aria-label={`Bỏ từ khóa ${word}`} onClick={() => setDraft({ ...list, [pillar]: held.filter((item) => item !== word) })}><X size={13} /></button></span>)}
              {held.length === 0 && <span className="muted">Chưa có từ khóa: công cụ quét sẽ không tìm gì cho trụ này.</span>}
            </div>
            {offered.length > 0 && <div className="keyword-offered"><span>AI gợi ý, bấm để giữ:</span>{offered.map((word) => <button type="button" key={word} className="chip chip-offer" disabled={held.length >= 12} onClick={() => add(pillar, word)}><Plus size={12} aria-hidden="true" /> {word}</button>)}</div>}
            {held.length < 12 && (
              <form className="voice-add" onSubmit={(event) => { event.preventDefault(); add(pillar, typed[pillar] || ''); setTyped({ ...typed, [pillar]: '' }) }}>
                <input value={typed[pillar] || ''} maxLength={60} onChange={(event) => setTyped({ ...typed, [pillar]: event.target.value })} placeholder="Thêm một cụm 2–5 chữ người ta hay viết" aria-label={`Từ khóa mới cho trụ ${pillar}`} />
                <button className="button button-secondary button-small" disabled={!(typed[pillar] || '').trim()}>Thêm</button>
              </form>
            )}
          </div>
        )
      })}
      {data.request?.status === 'FAILED' && !thinking && <p className="plan-warning"><TriangleAlert size={14} aria-hidden="true" /> AI chưa gợi ý được lúc này{data.request.error ? ` (${data.request.error})` : ''}.</p>}
      {(suggest.error != null || save.error != null) && <ErrorNotice error={suggest.error ?? save.error} />}
      <div className="rhythm-actions">
        <button type="button" className="button button-secondary" disabled={thinking} onClick={() => suggest.mutate()}>{thinking ? <><span className="spinner" aria-hidden="true" /> AI đang gợi ý…</> : <><Sparkles size={15} aria-hidden="true" /> AI gợi ý từ khóa</>}</button>
        <button type="button" className="button button-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate(list)}>{save.isPending ? 'Đang lưu…' : saved && !dirty ? 'Đã lưu' : 'Lưu từ khóa'}</button>
      </div>
    </div>
  )
}

// What a track asks of the scanner: how many signals a week, and by when. The scanner reads this and paces itself.
function WatchDemandRow({ track, name }: { track: DraftTrack; name: string }) {
  const queryClient = useQueryClient()
  const demand = useQuery({ queryKey: ['watch-demand', track], queryFn: () => api<WatchDemand>(`/private-space/watch/demand?track=${track}`) })
  const [draft, setDraft] = useState<{ wanted: string; weekday: number; time: string; lookback: string }>()
  const [saved, setSaved] = useState(false)
  const stored = demand.data ? { wanted: String(demand.data.wanted_per_week), weekday: demand.data.weekday, time: demand.data.time, lookback: String(demand.data.lookback_days) } : undefined
  useEffect(() => { setDraft(undefined) }, [track])
  useEffect(() => { if (stored && !draft) setDraft(stored) }, [stored, draft])
  const save = useMutation({
    mutationFn: (next: NonNullable<typeof draft>) => api<WatchDemand>(`/private-space/watch/demand?track=${track}`, { method: 'PUT', body: JSON.stringify({ wanted_per_week: Number(next.wanted) || 0, weekday: next.weekday, time: next.time, lookback_days: Number(next.lookback) || 7 }) }),
    onSuccess: (next) => { queryClient.setQueryData(['watch-demand', track], next); setDraft({ wanted: String(next.wanted_per_week), weekday: next.weekday, time: next.time, lookback: String(next.lookback_days) }); setSaved(true); window.setTimeout(() => setSaved(false), 2500) },
  })
  if (!draft || !demand.data) return demand.error ? <ErrorNotice error={demand.error} onRetry={() => { void demand.refetch() }} /> : <LoadingBlock />
  const data = demand.data
  const dirty = JSON.stringify(draft) !== JSON.stringify(stored)
  return (
    <div className="watch-demand">
      <form onSubmit={(event) => { event.preventDefault(); if (dirty && draft.time) save.mutate(draft) }}>
        <label>Mỗi tuần cần<input type="number" min={0} max={50} value={draft.wanted} onChange={(event) => setDraft({ ...draft, wanted: event.target.value })} aria-label={`Số tín hiệu mỗi tuần của mạch ${name}`} /><span>tín hiệu</span></label>
        <label>có trước<select value={draft.weekday} onChange={(event) => setDraft({ ...draft, weekday: Number(event.target.value) })} aria-label="Ngày cần có dữ liệu">{weekdayLong.map((label, day) => <option key={label} value={day + 1}>{label}</option>)}</select>
          <input type="time" required value={draft.time} onChange={(event) => setDraft({ ...draft, time: event.target.value })} aria-label="Giờ cần có dữ liệu" /></label>
        <label>nhìn lại<input type="number" min={1} max={30} value={draft.lookback} onChange={(event) => setDraft({ ...draft, lookback: event.target.value })} aria-label="Số ngày nhìn lại" /><span>ngày</span></label>
        <button className="button button-secondary" disabled={!dirty || save.isPending}>{save.isPending ? 'Đang lưu…' : saved && !dirty ? 'Đã lưu' : 'Lưu nhu cầu'}</button>
      </form>
      <p className="field-help">
        {data.wanted_per_week > 0 && data.deadline
          ? <>Tuần này đã nhận <b>{data.received}/{data.wanted_per_week}</b>{data.remaining > 0 ? `, còn thiếu ${data.remaining}` : ', đã đủ'} · hạn {formatMoment(data.deadline)} (giờ Việt Nam). Công cụ quét đọc các số này để tự quyết lúc nào chạy; nhận tối đa {Math.ceil(data.wanted_per_week * 1.5)} mỗi tuần, phần gửi thừa bị từ chối.</>
          : 'Để 0 thì mạch này không đặt mục tiêu: công cụ quét không biết cần bao nhiêu và khi nào, và Intake không giới hạn số nhận mỗi tuần.'}
      </p>
      {save.error != null && <ErrorNotice error={save.error} />}
    </div>
  )
}

// Is the scanner outside alive: when it last called, and what the check every twelve hours found.
function WatchHealthPanel({ base = '/private-space/watch' }: { base?: string }) {
  const queryClient = useQueryClient()
  const health = useQuery({ queryKey: ['watch-health', base], queryFn: () => api<WatchHealth>(`${base}/health`), refetchInterval: 300000 })
  const check = useMutation({
    mutationFn: () => api<WatchHealth>(`${base}/health/check`, { method: 'POST' }),
    onSuccess: (next) => { queryClient.setQueryData(['watch-health', base], next) },
  })
  if (health.isLoading) return <LoadingBlock />
  if (health.error || !health.data) return <ErrorNotice error={health.error || new Error('Chưa tải được tình trạng công cụ quét.')} onRetry={() => { void health.refetch() }} />
  const data = health.data
  const asking = data.tracks.filter((track) => track.wanted_per_week > 0)
  return (
    <div className="watch-health">
      <p className="watch-health-line">
        <span>Công cụ đọc cấu hình lần cuối: <b>{data.last_config_at ? formatMoment(data.last_config_at) : 'chưa lần nào'}</b></span>
        <span>Gửi bài về lần cuối: <b>{data.last_signal_at ? formatMoment(data.last_signal_at) : 'chưa lần nào'}</b></span>
        <button type="button" className="button button-secondary button-small" disabled={check.isPending} onClick={() => check.mutate()}><RefreshCw size={13} aria-hidden="true" /> {check.isPending ? 'Đang kiểm…' : 'Kiểm tra ngay'}</button>
      </p>
      {asking.length === 0 ? <p className="field-help">Chưa mạch nào đặt số tín hiệu cần mỗi tuần, nên không có gì để kiểm. Đặt nhu cầu ở khối phía trên.</p> : (
        <ul className="watch-health-tracks">
          {asking.map((track) => (
            <li key={track.track} className={track.warning ? 'is-warning' : undefined}>
              <strong>{track.name}</strong>
              <span>{track.received}/{track.wanted_per_week} tuần này{track.deadline ? ` · hạn ${formatMoment(track.deadline)}` : ''}</span>
              {track.warning
                ? <span className="watch-health-warn"><TriangleAlert size={14} aria-hidden="true" /> {data.check_hours} giờ qua chưa có bài quét về. {watchReasons[track.reason || 'NOTHING_SENT']}</span>
                : <span className="muted">{track.checked_at ? `Kiểm lúc ${formatMoment(track.checked_at)}: ${track.remaining === 0 ? 'đã đủ' : track.received_in_check ? `nhận ${track.received_in_check} bài trong ${data.check_hours} giờ` : 'ổn'}` : 'Chưa tới lượt kiểm đầu tiên'}</span>}
            </li>
          ))}
        </ul>
      )}
      <p className="field-help">Intake tự kiểm lúc 07:30 và 19:30 mỗi ngày. Mạch nào còn thiếu tín hiệu mà {data.check_hours} giờ trước đó không nhận được bài nào thì có cảnh báo ở chuông, cho tới lượt kiểm sau hoặc tới khi có bài về. Intake không gửi email hay tin nhắn.</p>
      {check.error != null && <ErrorNotice error={check.error} />}
    </div>
  )
}

function PrivateWatchPage() {
  const queryClient = useQueryClient()
  const space = usePrivateSpace()
  const [track, setTrack] = useState<DraftTrack>('business')
  const [url, setUrl] = useState('')
  const [under, setUnder] = useState<WatchSource['track']>('business')
  const [removing, setRemoving] = useState<WatchSource>()
  const [error, setError] = useState<unknown>()
  const sources = useQuery({ queryKey: ['watch-sources'], queryFn: () => api<WatchSource[]>('/private-space/watch/sources'), enabled: Boolean(space.data?.project) })
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['watch-sources'] }) }
  const add = useMutation({
    mutationFn: () => api<WatchSource>('/private-space/watch/sources', { method: 'POST', body: JSON.stringify({ url: url.trim(), track: under }) }),
    onMutate: () => setError(undefined), onSuccess: () => { setUrl(''); refresh() }, onError: setError,
  })
  const change = useMutation({
    mutationFn: (input: { id: string; body: object }) => api<WatchSource>(`/private-space/watch/sources/${input.id}`, { method: 'PATCH', body: JSON.stringify(input.body) }),
    onMutate: () => setError(undefined), onSuccess: refresh, onError: setError,
  })
  const remove = useMutation({ mutationFn: (id: string) => api(`/private-space/watch/sources/${id}`, { method: 'DELETE' }), onSuccess: () => { setRemoving(undefined); refresh() } })

  if (space.isLoading) return <><PageHeader title="Nguồn theo dõi" /><LoadingBlock /></>
  if (space.error) return <><PageHeader title="Nguồn theo dõi" /><ErrorNotice error={space.error} onRetry={() => { void space.refetch() }} /></>
  if (!space.data?.project) return <><PageHeader title="Nguồn theo dõi" /><OpenPrivateSpace /></>
  const voices = space.data.voices || {}
  const list = sources.data || []
  const trackOptions: { value: WatchSource['track']; label: string }[] = [...draftTracks.map((name) => ({ value: name, label: trackName(voices, name) })), { value: 'both', label: 'Cả hai mạch' }]

  return (
    <>
      <PageHeader title="Nguồn theo dõi" helper={[
        'Khai các trang web, blog, kênh và tác giả bạn muốn theo dõi, và từ khóa cho từng trụ nội dung.',
        'Intake không tự mở các địa chỉ này. Một công cụ quét bên ngoài đọc danh sách qua API, đi quét, rồi gửi kết quả về thành "tín hiệu".',
        'Tín hiệu hiện ở Kho ý tưởng theo từng mạch, và AI đọc tiêu đề của chúng khi đề xuất kế hoạch tuần.',
        'Quét Facebook hay X bằng tài khoản cá nhân có thể làm tài khoản bị khóa: dùng một tài khoản khác cho công cụ quét.',
      ]} action={<span className="private-tag"><Lock size={13} aria-hidden="true" /> Chỉ bạn thấy</span>} />
      {removing && (
        <ConfirmDialog title="Bỏ nguồn này?" confirmLabel="Bỏ nguồn" busy={remove.isPending} error={remove.error ?? undefined} onConfirm={() => remove.mutate(removing.id)} onCancel={() => setRemoving(undefined)}>
          <p><strong>{removing.label}</strong><br />{removing.url}</p>
          <ul><li>Công cụ quét sẽ không còn nhận địa chỉ này.</li><li>Tín hiệu đã nhận từ nguồn này vẫn còn cho tới khi hết hạn.</li></ul>
        </ConfirmDialog>
      )}
      <section className="panel voice-form" aria-label="Nguồn">
        <div className="panel-heading"><div><h2>Nguồn</h2></div><span className="muted">{list.filter((row) => row.active).length} đang bật · {list.length}/80</span></div>
        <form className="source-add" onSubmit={(event) => { event.preventDefault(); if (url.trim()) add.mutate() }}>
          <input type="url" value={url} maxLength={500} onChange={(event) => setUrl(event.target.value)} placeholder="https://… địa chỉ trang web, trang Facebook, tài khoản X, kênh YouTube" aria-label="Địa chỉ nguồn mới" />
          <select aria-label="Mạch của nguồn mới" value={under} onChange={(event) => setUnder(event.target.value as WatchSource['track'])}>{trackOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
          <button className="button button-primary" disabled={!url.trim() || add.isPending}>{add.isPending ? 'Đang thêm…' : 'Thêm nguồn'}</button>
        </form>
        {error != null && <ErrorNotice error={error} />}
        {sources.error != null && <ErrorNotice error={sources.error} onRetry={() => { void sources.refetch() }} />}
        {list.length === 0 ? <p className="plan-empty">Chưa có nguồn nào. Dán một địa chỉ ở trên; loại nguồn được nhận ra từ địa chỉ.</p> : (
          <ul className="source-list">
            {list.map((row) => (
              <li key={row.id} className={row.active ? undefined : 'is-off'}>
                <span className="status source-kind">{watchKinds[row.kind]}</span>
                <div className="source-main"><strong>{row.label}</strong><a href={row.url} target="_blank" rel="noreferrer noopener">{row.url}</a></div>
                <select aria-label={`Mạch của nguồn ${row.label}`} value={row.track} disabled={change.isPending} onChange={(event) => change.mutate({ id: row.id, body: { track: event.target.value } })}>{trackOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
                <button type="button" className={row.active ? 'button button-secondary button-small is-posted' : 'button button-secondary button-small'} aria-pressed={row.active} disabled={change.isPending} onClick={() => change.mutate({ id: row.id, body: { active: !row.active } })}>{row.active ? 'Đang bật' : 'Đã tắt'}</button>
                <button type="button" className="icon-button" aria-label={`Bỏ nguồn ${row.label}`} title="Bỏ nguồn" onClick={() => { remove.reset(); setRemoving(row) }}><Trash2 size={14} /></button>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="panel voice-form" aria-label="Từ khóa theo trụ">
        <div className="panel-heading"><div><h2>Nhu cầu và từ khóa theo mạch</h2></div>
          <div className="segmented" role="group" aria-label="Mạch nội dung">{draftTracks.map((name) => <button type="button" key={name} aria-pressed={track === name} className={track === name ? 'active' : undefined} onClick={() => setTrack(name)}>{trackName(voices, name)}</button>)}</div>
        </div>
        <WatchDemandRow track={track} name={trackName(voices, track)} />
        <p className="field-help keyword-help">Tên trụ không phải là từ để tìm. Mỗi trụ cần vài cụm cụ thể người ta hay viết; công cụ quét tìm các cụm này ở những nguồn của mạch. AI gợi ý dựa trên tài liệu DNA, bạn quyết giữ cụm nào.</p>
        <PillarKeywordsPanel track={track} name={trackName(voices, track)} />
      </section>
      <section className="panel voice-form" aria-label="Kết nối công cụ quét">
        <div className="panel-heading"><div><h2>Kết nối công cụ quét</h2></div></div>
        <WatchHealthPanel />
        <ul className="watch-connect">
          <li><code>GET /api/v1/watch/config</code> trả nguồn đang bật, từ khóa theo trụ, và nhu cầu của từng mạch: cần bao nhiêu, đã nhận bao nhiêu, hạn kế tiếp.</li>
          <li><code>POST /api/v1/watch/signals</code> nhận kết quả quét, tối đa 50 mục mỗi lần gọi, có chữ ký.</li>
          <li>Hai đường này đóng cho tới khi <code>WATCH_API_KEY</code> và <code>WATCH_WEBHOOK_SECRET</code> được đặt trong <code>.env</code> của máy chủ. Định dạng và cách ký nằm ở <code>docs/stable/watch-flow.md</code>.</li>
        </ul>
      </section>
    </>
  )
}

// How many posts a line means to publish each week, on which day and where. The week plan is laid out from this.
function TrackRhythm({ track, name, pillars, onClose }: { track: DraftTrack; name: string; pillars: string[]; onClose?: () => void }) {
  const queryClient = useQueryClient()
  const plan = useQuery({ queryKey: ['plan-week', ''], queryFn: () => api<PlanWeek>('/private-space/plan') })
  const stored = plan.data?.rhythm[track]
  const [slots, setSlots] = useState<RhythmSlot[]>()
  const [saved, setSaved] = useState(false)
  useEffect(() => { setSlots(undefined) }, [track])
  useEffect(() => { if (stored && !slots) setSlots(stored) }, [stored, slots])
  const save = useMutation({
    mutationFn: (next: RhythmSlot[]) => api<PlanWeek>(`/private-space/plan/rhythm?track=${track}`, { method: 'PUT', body: JSON.stringify({ slots: next }) }),
    onSuccess: (next) => { queryClient.setQueryData(['plan-week', ''], next); void queryClient.invalidateQueries({ queryKey: ['plan-week'] }); setSlots(next.rhythm[track]); setSaved(true); window.setTimeout(() => setSaved(false), 2500) },
  })
  const list = slots || []
  const set = (index: number, patch: Partial<RhythmSlot>) => setSlots(list.map((slot, slotIndex) => (slotIndex === index ? { ...slot, ...patch } : slot)))
  const dirty = JSON.stringify(list) !== JSON.stringify(stored || [])
  return (
    <section className="panel voice-form track-rhythm" aria-label="Nhịp tuần">
      <div className="panel-heading"><div><h2>Nhịp tuần của hướng {name}</h2></div><div className="rhythm-head-right"><span className="muted">{list.length}/7 ô</span>{onClose && <button type="button" className="icon-button" aria-label="Đóng nhịp tuần" onClick={onClose}><X size={16} /></button>}</div></div>
      <p className="field-help">Mỗi ô là một bài bạn định đăng mỗi tuần. Kế hoạch tuần được dựng từ đây; đổi nhịp chỉ đổi các ô còn trống của tuần này và tuần sau.</p>
      {plan.error != null && <ErrorNotice error={plan.error} onRetry={() => { void plan.refetch() }} />}
      {list.length > 0 && (
        <ul className="rhythm-list">
          {list.map((slot, index) => (
            <li key={index}>
              <select aria-label={`Ngày của ô ${index + 1}`} value={slot.weekday} onChange={(event) => set(index, { weekday: Number(event.target.value) })}>{weekdayLong.map((label, day) => <option key={label} value={day + 1}>{label}</option>)}</select>
              <input type="time" aria-label={`Giờ của ô ${index + 1}`} value={slot.time || ''} onChange={(event) => set(index, { time: event.target.value || null })} />
              <select aria-label={`Kênh của ô ${index + 1}`} value={slot.channel} onChange={(event) => set(index, { channel: event.target.value as DraftChannel })}>
                {[...draftChannels, { value: 'FACEBOOK_GROUP' as DraftChannel, label: 'Hội nhóm' }, ...longChannels].map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
              <select aria-label={`Trụ của ô ${index + 1}`} value={slot.pillar || ''} onChange={(event) => set(index, { pillar: event.target.value || null })}>
                <option value="">Trụ: để AI chọn</option>
                {[...pillars, ...(slot.pillar && !pillars.includes(slot.pillar) ? [slot.pillar] : [])].map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
              <button type="button" className="icon-button" aria-label={`Bỏ ô ${index + 1}`} title="Bỏ ô này" onClick={() => setSlots(list.filter((_, slotIndex) => slotIndex !== index))}><X size={14} /></button>
            </li>
          ))}
        </ul>
      )}
      <div className="rhythm-actions">
        <button type="button" className="button button-secondary" disabled={list.length >= 7} onClick={() => setSlots([...list, { weekday: 2, time: '08:00', channel: 'FACEBOOK', pillar: null }])}><Plus size={15} aria-hidden="true" /> Thêm ô</button>
        <button type="button" className="button button-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate(list)}>{save.isPending ? 'Đang lưu…' : saved && !dirty ? 'Đã lưu' : 'Lưu nhịp tuần'}</button>
      </div>
      {save.error != null && <ErrorNotice error={save.error} />}
    </section>
  )
}

// What the author knows to be true, allows to be shown, has decided, and has seen work: read by AI before every draft.
function TrackNotes({ track, name }: { track: DraftTrack; name: string }) {
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<TrackNote['kind']>('FACT')
  const [text, setText] = useState('')
  const [removing, setRemoving] = useState<TrackNote>()
  const notes = useQuery({ queryKey: ['track-notes', track], queryFn: () => api<TrackNote[]>(`/private-space/notes?track=${track}`) })
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['track-notes', track] }) }
  const add = useMutation({
    mutationFn: () => api<TrackNote>('/private-space/notes', { method: 'POST', body: JSON.stringify({ track, kind, text: text.trim() }) }),
    onSuccess: () => { setText(''); refresh() },
  })
  const remove = useMutation({
    mutationFn: (id: string) => api(`/private-space/notes/${id}`, { method: 'DELETE' }),
    onSuccess: () => { setRemoving(undefined); refresh() },
  })
  const list = notes.data || []
  return (
    <section className="panel voice-form track-notes" aria-label="Sổ ghi chú">
      {removing && (
        <ConfirmDialog title="Xóa ghi chú này?" confirmLabel="Xóa ghi chú" busy={remove.isPending} error={remove.error ?? undefined} onConfirm={() => remove.mutate(removing.id)} onCancel={() => setRemoving(undefined)}>
          <p><strong>{labelOf(noteKinds, removing.kind)}</strong><br />{removing.text}</p>
          <ul><li>AI sẽ không còn đọc ghi chú này khi soạn nháp.</li><li>Nháp đã soạn không đổi.</li></ul>
        </ConfirmDialog>
      )}
      <div className="panel-heading"><div><h2>Sổ ghi chú của hướng {name}</h2></div><span className="muted">{list.length}/60{list.filter(noteIsStale).length > 0 ? ` · ${list.filter(noteIsStale).length} cần rà lại` : ''}</span></div>
      <p className="field-help">AI đọc sổ này trước mỗi lần soạn. Ghi chú lưu ngay khi thêm; nội dung lưu mã hóa và được gửi tới nhà cung cấp AI khi soạn nháp. Dữ kiện ghi hơn 6 tháng được nhắc rà lại: còn đúng thì xóa và ghi lại, hết đúng thì xóa.</p>
      {notes.error != null && <ErrorNotice error={notes.error} onRetry={() => { void notes.refetch() }} />}
      {list.length > 0 && (
        <ul className="note-list">
          {list.map((note) => (
            <li key={note.id} className={noteIsStale(note) ? 'is-stale' : undefined}>
              <span className="note-kind-cell"><span className={`status note-kind note-${note.kind.toLowerCase()}`}>{labelOf(noteKinds, note.kind)}</span><small className="note-when">{formatDay(note.created_at)}/{note.created_at.slice(0, 4)}</small></span>
              <p>{note.text}{noteIsStale(note) && <small className="note-stale"><TriangleAlert size={12} aria-hidden="true" /> cần rà lại: ghi hơn 6 tháng trước</small>}</p>
              <button type="button" className="icon-button" aria-label="Xóa ghi chú" title="Xóa ghi chú" onClick={() => { remove.reset(); setRemoving(note) }}><Trash2 size={14} /></button>
            </li>
          ))}
        </ul>
      )}
      <form className="note-add" onSubmit={(event) => { event.preventDefault(); if (text.trim().length >= 3) add.mutate() }}>
        <select aria-label="Loại ghi chú" value={kind} onChange={(event) => setKind(event.target.value as TrackNote['kind'])}>{noteKinds.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
        <input value={text} maxLength={1000} onChange={(event) => setText(event.target.value)} placeholder="Một ghi chú, một ý" aria-label="Ghi chú mới" />
        <button className="button button-secondary" disabled={text.trim().length < 3 || add.isPending || list.length >= 60}>{add.isPending ? 'Đang thêm…' : 'Thêm ghi chú'}</button>
      </form>
      <p className="field-help">{noteKinds.find((item) => item.value === kind)?.hint}</p>
      {add.error != null && <ErrorNotice error={add.error} />}
    </section>
  )
}

// Six months on, a fact may have moved: the author is asked to look at it again.
const NOTE_REVIEW_DAYS = 180
const noteIsStale = (note: TrackNote) => note.kind === 'FACT' && (Date.now() - new Date(note.created_at).getTime()) / 86400000 > NOTE_REVIEW_DAYS

// What the author changed on the open direction and has not saved yet, in the words of the screen.
function unsavedParts(draft: PrivateVoice, stored: PrivateVoice | undefined): string[] {
  if (!stored) return []
  const parts: string[] = []
  if (draft.samples.length !== stored.samples.length || JSON.stringify(draft.samples) !== JSON.stringify(stored.samples)) parts.push('bài mẫu')
  if (JSON.stringify(draft.pillars) !== JSON.stringify(stored.pillars)) parts.push('trụ nội dung')
  if (JSON.stringify(draft.references || []) !== JSON.stringify(stored.references || [])) parts.push('tài liệu tham chiếu')
  if ((['name', 'direction_note', 'positioning', 'audience', 'tone', 'avoid', 'default_channel'] as const).some((key) => draft[key] !== stored[key])) parts.push('các ô ngắn')
  return parts
}

// A short piece written now, in the voice as it stands on the screen: to hear it before saving. Nothing is kept.
function VoiceTrialPanel({ track, voice, masterDna, onClose }: { track: DraftTrack; voice: PrivateVoice; masterDna: string; onClose: () => void }) {
  const [idea, setIdea] = useState('')
  const [channel, setChannel] = useState<VoiceChannel>(draftChannels.some((item) => item.value === voice.default_channel) ? voice.default_channel as VoiceChannel : 'FACEBOOK')
  const trial = useMutation({
    mutationFn: () => api<VoiceTrial>('/private-space/voice-trial', { method: 'POST', body: JSON.stringify({ track, voice, master_dna: masterDna, channel, idea: idea.trim() }) }),
  })
  return (
    <section className="panel voice-form voice-trial" aria-label="Soạn thử">
      <div className="panel-heading"><div><h2>Soạn thử bằng giọng đang có trên màn hình</h2></div><button type="button" className="icon-button" aria-label="Đóng soạn thử" onClick={onClose}><X size={16} /></button></div>
      <p className="field-help">AI viết 80–120 chữ theo Master DNA, hướng {voice.name || trackDefaults[track]}, sổ ghi chú và bài mẫu như đang hiện, kể cả phần chưa lưu. Đoạn thử không được lưu; chỉ để nghe giọng, không phải nháp.</p>
      <form className="voice-trial-form" onSubmit={(event) => { event.preventDefault(); trial.mutate() }}>
        <input value={idea} maxLength={500} onChange={(event) => setIdea(event.target.value)} placeholder="Một dòng ý để viết thử, ví dụ: khách hỏi vì sao báo giá có hai mức" aria-label="Ý để soạn thử" />
        <select aria-label="Kênh để soạn thử" value={channel} onChange={(event) => setChannel(event.target.value as VoiceChannel)}>{draftChannels.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
        <button className="button button-primary" disabled={trial.isPending}><Sparkles size={15} aria-hidden="true" /> {trial.isPending ? 'Đang viết…' : trial.data ? 'Viết lại' : 'Soạn thử'}</button>
      </form>
      {trial.error != null && <ErrorNotice error={trial.error} />}
      {trial.data && (
        <article className="voice-trial-result">
          <p>{trial.data.text}</p>
          <small>{trial.data.model} · {trial.data.prompt_version} · {trial.data.message_chars.toLocaleString('vi-VN')} ký tự đã gửi · không lưu</small>
        </article>
      )}
    </section>
  )
}

function PrivateVoicePage() {
  const queryClient = useQueryClient()
  const space = usePrivateSpace()
  const [track, setTrack] = useState<DraftTrack>('business')
  const [drafts, setDrafts] = useState<Record<string, PrivateVoice>>()
  const [pillar, setPillar] = useState('')
  const [sample, setSample] = useState('')
  const [sampleChannel, setSampleChannel] = useState<VoiceChannel>('FACEBOOK')
  const [saved, setSaved] = useState(false)
  const [prompting, setPrompting] = useState(false)
  const [trying, setTrying] = useState(false)
  // Samples are shown as one line each; one at a time opens to its full text.
  const [openSample, setOpenSample] = useState<number | null>(null)
  const [master, setMaster] = useState<string>()
  const [masterSaved, setMasterSaved] = useState(false)
  const [refTitle, setRefTitle] = useState('')
  const [refText, setRefText] = useState('')
  const voices = space.data?.voices
  const storedMaster = space.data?.master_dna
  // The notebook of the open direction, for the status line; the notebook block reads the same query.
  const notes = useQuery({ queryKey: ['track-notes', track], queryFn: () => api<TrackNote[]>(`/private-space/notes?track=${track}`), enabled: Boolean(space.data?.project) })
  useEffect(() => { if (voices && Object.keys(voices).length > 0 && !drafts) setDrafts(voices) }, [voices, drafts])
  useEffect(() => { if (storedMaster !== undefined && master === undefined) setMaster(storedMaster) }, [storedMaster, master])
  // The shared core is saved on its own: it belongs to every track.
  const saveMaster = useMutation({
    mutationFn: (text: string) => api<PrivateSpace>('/private-space/master-dna', { method: 'PUT', body: JSON.stringify({ text }) }),
    onSuccess: (next) => { queryClient.setQueryData(['private-space'], next); setMaster(next.master_dna); setMasterSaved(true); window.setTimeout(() => setMasterSaved(false), 2500) },
  })
  const save = useMutation({
    mutationFn: (input: { track: DraftTrack; voice: PrivateVoice }) => api<PrivateSpace>(`/private-space/voice?track=${input.track}`, { method: 'PUT', body: JSON.stringify(input.voice) }),
    // Only the line that was saved is taken back: the other may hold changes not saved yet.
    onSuccess: (next, input) => { queryClient.setQueryData(['private-space'], next); setDrafts((current) => ({ ...(current || {}), [input.track]: next.voices[input.track] })); setSaved(true); window.setTimeout(() => setSaved(false), 2500) },
  })

  if (space.isLoading) return <><PageHeader title="Giọng của tôi" /><LoadingBlock /></>
  if (space.error) return <><PageHeader title="Giọng của tôi" /><ErrorNotice error={space.error} onRetry={() => { void space.refetch() }} /></>
  if (!space.data?.project) return <><PageHeader title="Giọng của tôi" /><OpenPrivateSpace /></>
  const draft = drafts?.[track]
  if (!draft) return <LoadingBlock />

  const set = (patch: Partial<PrivateVoice>) => setDrafts({ ...(drafts || {}), [track]: { ...draft, ...patch } })
  const changed = (name: DraftTrack) => JSON.stringify(drafts?.[name]) !== JSON.stringify(voices?.[name])
  const dirty = changed(track)
  const parts = unsavedParts(draft, voices?.[track])
  const addPillar = () => { const value = pillar.trim(); if (value && draft.pillars.length < 5 && !draft.pillars.includes(value)) { set({ pillars: [...draft.pillars, value] }); setPillar('') } }
  const addSample = () => { const value = sample.trim(); if (value.length >= 20 && draft.samples.length < 8) { set({ samples: [...draft.samples, { text: value, channel: sampleChannel }] }); setSample('') } }
  const addReference = () => { const text = refText.trim(); if (text && (draft.references || []).length < 2) { set({ references: [...(draft.references || []), { title: refTitle.trim() || 'Tài liệu tham chiếu', text }] }); setRefTitle(''); setRefText('') } }
  const masterText = master ?? storedMaster ?? ''
  const masterDirty = masterText !== (storedMaster ?? '')
  const name = draft.name || trackDefaults[track]
  const stale = (notes.data || []).filter(noteIsStale).length
  const references = draft.references || []
  const switchTrack = (next: DraftTrack) => { setTrack(next); setPillar(''); setSample(''); setOpenSample(null) }
  // The weekly read of one direction: what is there, what is short, and where to go.
  const status: { key: string; label: string; ok: boolean; href: string; hint?: string }[] = [
    { key: 'master', label: masterText.trim() ? `Master DNA ${masterText.length.toLocaleString('vi-VN')} ký tự` : 'Chưa có Master DNA', ok: Boolean(masterText.trim()), href: '#voice-master' },
    { key: 'pillars', label: `${draft.pillars.length}/5 trụ`, ok: draft.pillars.length > 0, href: '#voice-setup' },
    { key: 'references', label: `${references.length}/2 tài liệu tham chiếu`, ok: true, href: '#voice-setup' },
    { key: 'samples', label: `${draft.samples.length}/8 bài mẫu`, ok: draft.samples.length >= 3, href: '#voice-samples', hint: draft.samples.length < 3 ? 'cần 3' : undefined },
    { key: 'notes', label: `${(notes.data || []).length} ghi chú`, ok: stale === 0, href: '#voice-notes', hint: stale > 0 ? `${stale} cần rà lại` : undefined },
  ]

  return (
    <>
      <PageHeader title="Giọng của tôi" helper={[
        'Một lõi, hai hướng: Master DNA là tài liệu chung; mỗi hướng (Kinh doanh, Kỹ thuật) là một phần của tài liệu đó, với người đọc, cách xưng hô và lời kêu gọi riêng.',
        'Việc hằng tuần ở trên: ghi vào sổ điều vừa biết, vừa quyết, vừa thấy hiệu quả; dán bài vừa đăng mà thấy ưng. Thiết lập một lần nằm thu gọn phía dưới.',
        'AI đọc Master DNA cộng hướng được chọn mỗi lần soạn, và bỏ qua phần của hướng kia. "Soạn thử" cho nghe giọng ngay với nội dung đang có trên màn hình, không lưu gì.',
        'Ghi chú lưu ngay khi thêm. Các phần khác của hướng lưu bằng thanh ở đáy trang; Master DNA lưu bằng nút riêng trong khối của nó.',
      ]} />
      {save.error != null && <ErrorNotice error={save.error} />}
      <div className="voice-layout">
      <div className="voice-main">
      <div className="voice-tracks-row">
      <div className="segmented voice-tracks" role="group" aria-label="Hướng nội dung">
        {draftTracks.map((item) => <button type="button" key={item} aria-pressed={track === item} className={track === item ? 'active' : undefined} onClick={() => switchTrack(item)}>{drafts?.[item]?.name || trackDefaults[item]}{changed(item) && <span className="voice-dirty" title="Có thay đổi chưa lưu" aria-label="Có thay đổi chưa lưu">●</span>}</button>)}
      </div>
      <div className="voice-tools">
        <button type="button" className="button button-secondary button-small prompt-open voice-try" aria-pressed={trying} onClick={() => setTrying(!trying)}><Sparkles size={14} aria-hidden="true" /> Soạn thử</button>
        <button type="button" className="button button-secondary button-small prompt-open" onClick={() => setPrompting(true)}><Eye size={14} aria-hidden="true" /> Xem prompt</button>
      </div>
      </div>
      <nav className="voice-status" aria-label={`Tình trạng hướng ${name}`}>
        {status.map((item) => <a key={item.key} href={item.href} className={item.ok ? 'is-ok' : 'is-short'}>{item.ok ? <Check size={13} aria-hidden="true" /> : <TriangleAlert size={13} aria-hidden="true" />}{item.label}{item.hint && <small>{item.hint}</small>}</a>)}
        <Link to="/rieng" className="is-link">Nhịp tuần ở Kho ý tưởng <ChevronRight size={13} aria-hidden="true" /></Link>
      </nav>
      {trying && <VoiceTrialPanel track={track} voice={draft} masterDna={masterText} onClose={() => setTrying(false)} />}
      <div id="voice-notes"><TrackNotes track={track} name={name} /></div>
      <section className="panel voice-form" id="voice-samples" aria-label="Bài mẫu">
        <div className="panel-heading"><div><h2>Bài mẫu của bạn ({draft.samples.length}/8)</h2></div></div>
        {draft.samples.length < 3 && <p className="notice notice-warn">{masterText.trim() ? 'Đã có Master DNA; thêm 3 bài mẫu để AI bắt được nhịp câu của bạn.' : 'Chưa đủ 3 bài mẫu và chưa có Master DNA: AI mới chỉ có các ô ngắn để dựa vào.'}</p>}
        <div className="voice-samples">
          {draft.samples.map((item, index) => (
            <article key={index}>
              <header><strong>Bài {index + 1}</strong><span>{channelName(item.channel)} · {wordCount(item.text)} chữ</span><button type="button" className="text-button" onClick={() => set({ samples: draft.samples.filter((_, sampleIndex) => sampleIndex !== index) })}>Bỏ</button></header>
              {openSample === index
                ? <p>{item.text}</p>
                : <p className="is-clamped">{item.text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).join(' · ')}</p>}
              <button type="button" className="text-button sample-toggle" onClick={() => setOpenSample(openSample === index ? null : index)}>{openSample === index ? 'Thu gọn' : 'Xem đủ'}</button>
            </article>
          ))}
        </div>
        {draft.samples.length < 8 && (
          <div className="voice-sample-add">
            <textarea rows={5} value={sample} maxLength={4000} onChange={(event) => setSample(event.target.value)} placeholder="Dán nguyên một bài bạn đã đăng và thấy ưng…" aria-label="Bài mẫu mới" />
            <div><select aria-label="Kênh của bài mẫu" value={sampleChannel} onChange={(event) => setSampleChannel(event.target.value as VoiceChannel)}>{draftChannels.map((channel) => <option key={channel.value} value={channel.value}>{channel.label}</option>)}</select><button type="button" className="button button-secondary" disabled={sample.trim().length < 20} onClick={addSample}>Thêm bài mẫu</button></div>
          </div>
        )}
        <p className="field-help">Chỉ dán bài đã đăng công khai và thấy ưng. AI học nhịp và cách mở bài, không lấy nội dung; bài mẫu được gửi tới nhà cung cấp AI mỗi lần soạn nháp.</p>
      </section>
      <details className="panel voice-setup" id="voice-setup">
        <summary><span>Thiết lập một lần: hướng {name}</span><small>{draft.pillars.length}/5 trụ · {references.length}/2 tài liệu tham chiếu · kênh mặc định {channelName(draft.default_channel)}</small></summary>
        <div className="voice-form">
        <div className="voice-two">
          <label>Tên hướng<input value={draft.name} maxLength={60} onChange={(event) => set({ name: event.target.value })} placeholder={trackDefaults[track]} /></label>
          <label>Hướng nào trong Master DNA<input value={draft.direction_note} maxLength={300} onChange={(event) => set({ direction_note: event.target.value })} placeholder="Ví dụ: Hướng Kinh doanh trong Master DNA" /></label>
        </div>
        <p className="field-help">Các ô dưới đây không bắt buộc khi Master DNA đã có; nếu điền, giữ đúng với tài liệu để không va nhau.</p>
        <label>Định vị (một câu)<input value={draft.positioning} maxLength={300} onChange={(event) => set({ positioning: event.target.value })} placeholder="Bạn muốn được biết đến vì điều gì" /></label>
        <div className="voice-two">
          <label>Viết cho ai<input value={draft.audience} maxLength={300} onChange={(event) => set({ audience: event.target.value })} placeholder="Ví dụ: chủ doanh nghiệp nhỏ, quản lý IT" /></label>
          <label>Kênh mặc định<select value={draft.default_channel} onChange={(event) => set({ default_channel: event.target.value as DraftChannel })}>{[...draftChannels, ...longChannels].map((channel) => <option key={channel.value} value={channel.value}>{channel.label}</option>)}</select></label>
        </div>
        <div className="voice-field">
          <span className="voice-label">Trụ nội dung ({draft.pillars.length}/5)</span>
          <div className="glossary-terms">
            {draft.pillars.map((item) => <span className="chip" key={item}><span className="chip-label">{item}</span><button type="button" aria-label={`Xóa trụ ${item}`} onClick={() => set({ pillars: draft.pillars.filter((pillarItem) => pillarItem !== item) })}><X size={12} /></button></span>)}
          </div>
          {draft.pillars.length < 5 && <form className="voice-add" onSubmit={(event) => { event.preventDefault(); addPillar() }}><input value={pillar} maxLength={80} onChange={(event) => setPillar(event.target.value)} placeholder="Thêm một trụ" aria-label="Trụ nội dung mới" /><button className="button button-secondary" disabled={!pillar.trim()}>Thêm</button></form>}
        </div>
        <div className="voice-two">
          <label>Giọng<input value={draft.tone} maxLength={300} onChange={(event) => set({ tone: event.target.value })} placeholder="Ví dụ: thẳng, có ví dụ thật, câu ngắn" /></label>
          <label>Không viết<input value={draft.avoid} maxLength={300} onChange={(event) => set({ avoid: event.target.value })} placeholder="Ví dụ: chính trị, chê đối thủ đích danh" /></label>
        </div>
        <div className="voice-field" aria-label="Tài liệu tham chiếu">
          <span className="voice-label">Tài liệu tham chiếu ({references.length}/2)</span>
          <p className="field-help">Tài liệu về một tổ chức hay sản phẩm mà hướng này hay nhắc tới (ví dụ DNA Acme cho hướng Kinh doanh). AI chỉ dùng để đối chiếu dữ kiện, không viết bằng giọng của tài liệu.</p>
          {references.length > 0 && (
            <ul className="reference-list">
              {references.map((item, index) => (
                <li key={index}><div><strong>{item.title}</strong><small>{item.text.length.toLocaleString('vi-VN')} ký tự · {item.text.slice(0, 120).replace(/\s+/g, ' ')}…</small></div><button type="button" className="text-button" onClick={() => set({ references: references.filter((_, referenceIndex) => referenceIndex !== index) })}>Bỏ</button></li>
              ))}
            </ul>
          )}
          {references.length < 2 && (
            <div className="voice-sample-add">
              <input value={refTitle} maxLength={120} onChange={(event) => setRefTitle(event.target.value)} placeholder="Tên tài liệu, ví dụ: DNA Acme 2.2" aria-label="Tên tài liệu tham chiếu" />
              <textarea rows={4} value={refText} maxLength={20000} onChange={(event) => setRefText(event.target.value)} placeholder="Dán nguyên tài liệu…" aria-label="Nội dung tài liệu tham chiếu" />
              <div><button type="button" className="button button-secondary" disabled={!refText.trim()} onClick={addReference}>Thêm tài liệu</button></div>
            </div>
          )}
        </div>
        </div>
      </details>
      <details className="panel voice-setup voice-dna" id="voice-master">
        <summary><span>Lõi: Master DNA (dùng chung cho mọi hướng)</span><small>{masterText.trim() ? `${masterText.length.toLocaleString('vi-VN')}/40.000 ký tự` : 'chưa có'}{masterDirty ? ' · chưa lưu' : ''}</small></summary>
        <div className="voice-form">
        <textarea rows={12} value={masterText} maxLength={40000} onChange={(event) => setMaster(event.target.value)} aria-label="Master DNA" placeholder="Dán nguyên Master DNA: lõi (định vị, dữ kiện, giới hạn) và các hướng nội dung." />
        <div className="rhythm-actions">
          <p className="field-help">AI coi đây là chuẩn và ưu tiên nó hơn các ô ngắn. Điều tài liệu ghi là mục tiêu hoặc chưa kiểm chứng thì AI không được kể như đã làm.</p>
          <button type="button" className="button button-primary" disabled={!masterDirty || saveMaster.isPending} onClick={() => saveMaster.mutate(masterText)}>{saveMaster.isPending ? 'Đang lưu…' : masterSaved && !masterDirty ? 'Đã lưu' : 'Lưu Master DNA'}</button>
        </div>
        {saveMaster.error != null && <ErrorNotice error={saveMaster.error} />}
        </div>
      </details>
      {(dirty || masterDirty || saved) && (
        <div className="decision-bar voice-save-bar" role="region" aria-label="Lưu hướng đang mở">
          <div className="decision-bar-row">
            <span className="decision-bar-title">{name}</span>
            <p className="voice-save-note">{dirty ? `Chưa lưu: ${parts.join(', ') || 'thay đổi'}.` : saved ? 'Đã lưu.' : ''}{masterDirty ? ' Master DNA còn thay đổi chưa lưu (nút riêng trong khối Lõi).' : ''}</p>
            <div className="decision-bar-actions">
              {dirty && <button type="button" className="button button-secondary" onClick={() => { if (voices?.[track]) setDrafts({ ...(drafts || {}), [track]: voices[track] }) }}>Bỏ thay đổi</button>}
              <button type="button" className="button button-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate({ track, voice: draft })}>{save.isPending ? 'Đang lưu…' : saved && !dirty ? 'Đã lưu' : `Lưu hướng ${name}`}</button>
            </div>
          </div>
        </div>
      )}
      </div>
      <VoicePromptPreview track={track} voice={draft} masterDna={masterText} open={prompting} onClose={() => setPrompting(false)} />
      </div>
    </>
  )
}

// On the home page: one line apart from the steps of the working day, so the day can be "done" while ideas wait.
function PrivateSpaceLine() {
  const space = usePrivateSpace()
  const plan = useQuery({ queryKey: ['plan-week', ''], queryFn: () => api<PlanWeek>('/private-space/plan'), enabled: Boolean(space.data?.project) })
  if (!space.data?.project) return null
  const counts = space.data.counts
  const tracks = Object.values(plan.data?.tracks || {})
  const slots = tracks.reduce((sum, track) => sum + track.stats.slots, 0)
  const posted = tracks.reduce((sum, track) => sum + track.stats.posted, 0)
  const open = tracks.reduce((sum, track) => sum + track.stats.open, 0)
  return (
    <Link className="today-private" to="/rieng">
      <Lock size={15} aria-hidden="true" />
      <span><strong>Riêng</strong> {slots > 0 ? `Tuần này: ${posted}/${slots} bài đã đăng${open > 0 ? ` · ${open} ô chưa có ý` : ''}` : `Kho ý tưởng: ${counts.no_draft} ý chưa có nháp`}{counts.unposted_drafts > 0 ? ` · ${counts.unposted_drafts} nháp chưa đăng` : ''}</span>
      <span className="today-private-go">Mở kho ý tưởng <ArrowRight size={14} aria-hidden="true" /></span>
    </Link>
  )
}

function WelcomePage() {
  const { refresh } = useAuth()
  const navigate = useNavigate()
  const status = useQuery({ queryKey: ['setup-status'], queryFn: () => api<{ needs_bootstrap: boolean }>('/setup/status'), retry: false })
  const [cto, setCto] = useState({ email: '', display_name: '', password: '', confirm: '' })
  const [withOwner, setWithOwner] = useState(true)
  const [owner, setOwner] = useState({ email: '', display_name: '', password: '', confirm: '' })
  const [error, setError] = useState<unknown>()
  const [submitting, setSubmitting] = useState(false)

  if (status.isLoading) return <main className="login-page"><LoadingBlock /></main>
  if (!status.data?.needs_bootstrap) return <Navigate to="/login" replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(undefined)
    if (cto.password.length < 12 || (withOwner && owner.password.length < 12)) { setError(new Error('Mật khẩu phải có ít nhất 12 ký tự.')); return }
    if (cto.password !== cto.confirm || (withOwner && owner.password !== owner.confirm)) { setError(new Error('Hai lần nhập mật khẩu chưa khớp.')); return }
    setSubmitting(true)
    try {
      const account = ({ email, display_name, password }: typeof cto) => ({ email: email.trim(), display_name: display_name.trim(), password })
      await api('/setup/bootstrap', { method: 'POST', body: JSON.stringify({ cto: account(cto), owner: withOwner ? account(owner) : null }) })
      await refresh()
      navigate('/setup', { replace: true })
    } catch (requestError) {
      setError(requestError)
    } finally {
      setSubmitting(false)
    }
  }

  const fields = (value: typeof cto, set: (next: typeof cto) => void, prefix: string) => (
    <>
      <label>Email<input type="email" value={value.email} onChange={(event) => set({ ...value, email: event.target.value })} autoComplete={`${prefix} email`} required /></label>
      <label>Tên hiển thị<input value={value.display_name} onChange={(event) => set({ ...value, display_name: event.target.value })} required /></label>
      <label>Mật khẩu (ít nhất 12 ký tự)<input type="password" value={value.password} onChange={(event) => set({ ...value, password: event.target.value })} autoComplete="new-password" minLength={12} required /></label>
      <label>Nhập lại mật khẩu<input type="password" value={value.confirm} onChange={(event) => set({ ...value, confirm: event.target.value })} autoComplete="new-password" minLength={12} required /></label>
    </>
  )

  return (
    <main className="login-page">
      <section className="login-panel">
        <form className="login-form welcome-form" onSubmit={submit}>
          <div className="brand login-brand"><img className="brand-mark" src="/icon.svg" alt="" /><span><strong>Private Intake</strong><small>Cài đặt lần đầu</small></span></div>
          <h1>Chào mừng đến với Intake</h1>
          <p>Tạo tài khoản đầu tiên. Người tạo trước sẽ là CTO của hệ thống này, nên hãy làm ngay trên máy của bạn.</p>
          {error != null && <ErrorNotice error={error} />}
          <h3>CTO (quản trị)</h3>
          {fields(cto, setCto, 'section-cto')}
          <label className="checkbox-row"><input type="checkbox" checked={withOwner} onChange={(event) => setWithOwner(event.target.checked)} /> Tạo luôn tài khoản Project Owner</label>
          {withOwner && (<><h3>Project Owner</h3>{fields(owner, setOwner, 'section-owner')}</>)}
          <button className="button button-primary button-wide" disabled={submitting}>{submitting ? 'Đang tạo…' : 'Tạo tài khoản và tiếp tục'}</button>
        </form>
      </section>
    </main>
  )
}

function SetupPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [error, setError] = useState<unknown>()
  const state = useQuery({ queryKey: ['setup'], queryFn: () => api<SetupState>('/setup') })
  const refresh = (next: SetupState) => { queryClient.setQueryData(['setup'], next); void queryClient.invalidateQueries({ queryKey: ['projects'] }) }
  const sample = useMutation({ mutationFn: () => api<SetupState>('/setup/private-sample', { method: 'POST' }), onSuccess: refresh, onError: setError })
  const finish = useMutation({ mutationFn: () => api<SetupState>('/setup/complete', { method: 'POST' }), onSuccess: (next) => { refresh(next); navigate('/') }, onError: setError })
  const data = state.data
  return (
    <>
      <SectionHeader title="Thiết lập lần đầu" />
      <section className="panel wizard-panel">
        <div className="wizard-body">
          <p>Chào mừng đến với Intake. Hai bước dưới đây giúp bạn có thứ để thử ngay. Bạn có thể bỏ qua và làm sau trong Cài đặt.</p>
          {state.error && <ErrorNotice error={state.error} onRetry={() => { void state.refetch() }} />}
          {error != null && <ErrorNotice error={error} onRetry={() => setError(undefined)} />}
          <h3>1. Dự án đầu tiên {data?.has_project && <Check size={15} aria-label="Đã xong" />}</h3>
          <p>Kết nối repo GitLab hoặc GitHub của bạn, hoặc tạo một dự án trống (loại Ý tưởng) để làm quen trước.</p>
          <p><Link className="button button-primary" to="/settings/projects/new">Tạo dự án</Link></p>
          {data?.wizard ? (
            <>
              <h3>2. Khóa AI (bắt buộc) {data.ai_ready && <Check size={15} aria-label="Đã xong" />}</h3>
              <p>Thêm khóa LLM, rồi chọn nhà cung cấp và model cho tác vụ "Mặc định". Hệ thống cần bước này để chuẩn hóa yêu cầu.</p>
              <AiSettings />
            </>
          ) : (
            <>
              <h3>2. Khóa AI (không bắt buộc)</h3>
              <p>Thêm khóa LLM của bạn và chọn model cho từng tác vụ. Chưa có khóa thì hệ thống vẫn chạy, chỉ không tự chuẩn hóa bằng AI.</p>
              <p><Link className="button button-secondary" to="/settings/ai">Cấu hình AI</Link></p>
            </>
          )}
          <h3>3. Giọng viết mẫu (không bắt buộc) {data?.has_private_space && <Check size={15} aria-label="Đã xong" />}</h3>
          <p>Nạp một bộ DNA thương hiệu hư cấu (Nova Labs) vào Không gian riêng để thử viết bài. Thay bằng thương hiệu của bạn sau.</p>
          <p><button className="button button-secondary" disabled={!data?.sample_available || sample.isPending} onClick={() => sample.mutate()}>{sample.isPending ? 'Đang nạp…' : 'Nạp giọng viết mẫu'}</button></p>
          <p><button className="button button-primary" disabled={finish.isPending || (data?.wizard === true && !data.ai_ready)} onClick={() => finish.mutate()}>Hoàn tất thiết lập</button>{data?.wizard && !data.ai_ready && <span className="field-help"> Cần thêm khóa AI trước.</span>}</p>
        </div>
      </section>
    </>
  )
}

function CtoOnly() {
  const { user } = useAuth()
  // Pass the shell context through, or pages below lose access to the right sidebar.
  const shell = useOutletContext<ShellContext>()
  return user?.role === 'CTO' ? <Outlet context={shell} /> : <Navigate to="/" replace />
}

function ProjectManagerOnly() {
  const { user } = useAuth()
  const shell = useOutletContext<ShellContext>()
  return user?.role === 'CTO' || user?.role === 'PROJECT_OWNER' ? <Outlet context={shell} /> : <Navigate to="/" replace />
}

function SettingsIndex() {
  const { user } = useAuth()
  return <Navigate to={user?.role === 'CTO' ? '/settings/projects' : '/settings/account'} replace />
}

function IssuedPassword({ issued, onClose }: { issued: { subject: string; password: string; name?: string }; onClose: () => void }) {
  return (
    <div className="notice notice-success issued-password" role="status">
      <span>Mật khẩu tạm của <strong>{issued.name ? `${issued.name} (${issued.subject})` : issued.subject}</strong>: <code>{issued.password}</code></span>
      <small>Mật khẩu này chỉ hiện một lần. Hãy chuyển cho người dùng qua kênh an toàn; họ phải đặt mật khẩu riêng ở lần đăng nhập đầu.</small>
      <button className="button button-secondary button-small" type="button" onClick={onClose}>Đã ghi lại</button>
    </div>
  )
}

function ProjectTeamPanel({ project }: { project: Project }) {
  const queryClient = useQueryClient()
  const team = useQuery({ queryKey: ['project-team', project.code], queryFn: () => api<ProjectTeam>(`/projects/${project.code}/team`) })
  const staff = useQuery({ queryKey: ['settings-members'], queryFn: () => api<WorkforceMember[]>('/planning/members?include_inactive=true') })
  const [ownerId, setOwnerId] = useState<string>()
  const [memberIds, setMemberIds] = useState<string[]>()
  const [issued, setIssued] = useState<{ subject: string; password: string; name?: string }>()
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<unknown>()
  const save = useMutation({
    mutationFn: (body: { owner_member_id: string | null; member_ids: string[] }) => api<ProjectTeam>(`/projects/${project.code}/team`, { method: 'PUT', body: JSON.stringify(body) }),
    onSuccess: (next) => {
      setError(undefined); setOwnerId(undefined); setMemberIds(undefined); setSaved(true)
      setIssued(next.issued ? { subject: next.issued.subject, password: next.issued.temporary_password, name: next.issued.display_name } : undefined)
      queryClient.setQueryData(['project-team', project.code], next)
      for (const key of ['projects', 'settings-members', 'planning-members', 'accounts']) void queryClient.invalidateQueries({ queryKey: [key] })
    },
    onError: (saveError) => { setSaved(false); setError(saveError) },
  })
  if (team.isLoading || staff.isLoading) return <section className="panel wizard-panel team-panel"><LoadingBlock /></section>
  if (team.error || staff.error) return <section className="panel wizard-panel team-panel"><ErrorNotice error={team.error || staff.error} onRetry={() => { void team.refetch(); void staff.refetch() }} /></section>

  const savedOwner = team.data?.owner_member_id || ''
  const savedMembers = (team.data?.members || []).map((row) => row.member_id)
  const owner = ownerId ?? savedOwner
  const chosen = memberIds ?? savedMembers
  // The owner also works on the project, so they are always part of the member list.
  const members = owner && !chosen.includes(owner) ? [owner, ...chosen] : chosen
  const people = (staff.data || []).filter((member) => member.status === 'ACTIVE' || savedMembers.includes(member.id))
  const dirty = owner !== savedOwner || members.length !== savedMembers.length || members.some((id) => !savedMembers.includes(id))
  const ownerChanged = owner !== savedOwner
  const previousOwner = people.find((member) => member.id === savedOwner)
  const toggle = (id: string) => { setSaved(false); setMemberIds(members.includes(id) ? members.filter((value) => value !== id) : [...members, id]) }
  const submit = () => {
    if (ownerChanged && previousOwner && !window.confirm(`Đổi Project Owner của ${project.name}? ${previousOwner.display_name} sẽ mất quyền ở dự án này ngay, và tài khoản sẽ bị khóa nếu không còn là Owner của dự án nào.`)) return
    save.mutate({ owner_member_id: owner || null, member_ids: members })
  }

  return (
    <section className="panel wizard-panel team-panel">
      <div className="wizard-body">
        <div className="settings-head"><div><h2>Nhân sự của dự án</h2><p>Mỗi dự án có một Project Owner và nhiều Member, đều chọn từ danh sách nhân sự. Chỉ Project Owner đăng nhập và duyệt được trong dự án; Member được phân công việc và gửi báo cáo, không đăng nhập.</p></div></div>
        {issued && <IssuedPassword issued={issued} onClose={() => setIssued(undefined)} />}
        <label>Project Owner
          <select value={owner} onChange={(e) => { setSaved(false); setOwnerId(e.target.value) }}>
            <option value="">Chưa có: chỉ CTO quyết định trong dự án này</option>
            {people.map((member) => <option key={member.id} value={member.id} disabled={!member.email_reference}>{member.display_name}{member.is_cto ? ' (CTO)' : ''}{member.email_reference ? '' : ' · cần có email'}</option>)}
          </select>
          <small className="field-help">{!owner ? 'Chọn một nhân sự để giao quyền xem nội dung gốc, phê duyệt và đồng bộ trong dự án này.' : ownerChanged ? (people.find((member) => member.id === owner)?.is_cto ? 'Anh tự quản dự án này: không tạo tài khoản, tên anh hiện là Project Owner trên tổng quan và trong nhắc Telegram.' : 'Khi lưu, người này được cấp quyền ngay. Nếu chưa có tài khoản, hệ thống tạo tài khoản và hiện mật khẩu tạm một lần.') : 'Người này đang là Project Owner của dự án.'}</small>
        </label>
        <fieldset className="member-projects">
          <legend>Member <small>{members.length} người</small></legend>
          {people.length === 0 && <p className="field-help">Chưa có nhân sự nào. Thêm nhân sự ở tab Nhân sự trước.</p>}
          <div className="team-grid">
            {people.map((member) => {
              const isOwner = member.id === owner
              return (
                <label className={`member-project-toggle team-member ${members.includes(member.id) ? 'active' : ''}`} key={member.id}>
                  <input type="checkbox" checked={members.includes(member.id)} disabled={isOwner} onChange={() => toggle(member.id)} />
                  <span><strong>{member.display_name}{isOwner ? ' · Project Owner' : ''}</strong><small>{member.email_reference || 'Chưa có email'}</small></span>
                </label>
              )
            })}
          </div>
          {project.kind === 'SOFTWARE' && <p className="field-help">Để phân công được trong Daily Planning, mỗi người còn cần người dùng {project.delivery_system === 'GITHUB' ? 'GitHub' : 'GitLab'} tương ứng; gán ở tab Nhân sự.</p>}
        </fieldset>
        {error != null && <ErrorNotice error={error} />}
        {saved && !dirty && <p className="notice notice-success" role="status">Đã lưu nhân sự của dự án.</p>}
      </div>
      <footer className="wizard-foot">
        <span />
        <button className="button button-primary" type="button" disabled={!dirty || save.isPending} onClick={submit}>{save.isPending ? 'Đang lưu…' : 'Lưu nhân sự dự án'}</button>
      </footer>
    </section>
  )
}

function ManagedProjectsPage() {
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  return (
    <>
      <PageHeader title="Dự án" helper="Mở một dự án để xem đội ngũ và thêm nhân sự. Bạn chỉ thấy các dự án mình được phép quản lý." />
      {projects.error != null && <ErrorNotice error={projects.error} onRetry={() => { void projects.refetch() }} />}
      {projects.isLoading ? <LoadingBlock /> : (projects.data || []).length === 0 ? (
        <section className="panel"><EmptyState icon={<UserRound size={20} />} title="Chưa có dự án" text="Tài khoản này chưa được giao quản lý dự án nào." /></section>
      ) : (
        <section className="panel settings-panel member-list">
          {(projects.data || []).map((project) => (
            <div className="member-row" key={project.id}>
              <div><strong>{project.name}</strong><small>{project.code} · {project.owner_name ? `Project Owner: ${project.owner_name}` : 'Chưa có Project Owner'}</small></div>
              <span className="project-actions"><Link className="button button-secondary button-small" to={`/projects/${project.code}`}>Chi tiết <ArrowRight size={14} /></Link></span>
            </div>
          ))}
        </section>
      )}
    </>
  )
}

function ProjectMembersPanel({ project, projects }: { project: Project; projects: Project[] }) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const teamKey = ['project-team', project.code]
  const candidatesKey = ['project-member-candidates', project.code]
  const team = useQuery({ queryKey: teamKey, queryFn: () => api<ProjectTeam>(`/projects/${project.code}/team`) })
  const candidates = useQuery({ queryKey: candidatesKey, queryFn: () => api<ProjectMemberCandidate[]>(`/projects/${project.code}/team/candidates`) })
  const staff = useQuery({ queryKey: ['settings-members'], queryFn: () => api<WorkforceMember[]>('/planning/members?include_inactive=true'), enabled: user?.role === 'CTO' })
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<string>()
  const [search, setSearch] = useState('')
  const [memberId, setMemberId] = useState('')
  const [notice, setNotice] = useState('')
  const choices = (candidates.data || []).filter((member) => `${member.display_name} ${member.email || ''}`.toLowerCase().includes(search.trim().toLowerCase()))
  useEffect(() => {
    if (adding && !memberId && choices.length > 0) setMemberId(choices[0].member_id)
  }, [adding, memberId, choices])
  const add = useMutation({
    mutationFn: () => api<ProjectMemberAdded>(`/projects/${project.code}/team/members`, { method: 'POST', body: JSON.stringify({ member_id: memberId }) }),
    onSuccess: (result) => {
      queryClient.setQueryData(teamKey, result.team)
      void queryClient.invalidateQueries({ queryKey: candidatesKey })
      for (const key of ['planning-members', 'settings-members']) void queryClient.invalidateQueries({ queryKey: [key] })
      setNotice(result.added ? 'Đã thêm nhân sự vào dự án.' : 'Nhân sự này đã thuộc dự án, không tạo bản ghi trùng.')
      setAdding(false); setSearch(''); setMemberId('')
    },
  })
  const remove = useMutation({
    mutationFn: (memberId: string) => api<ProjectMemberRemoved>(`/projects/${project.code}/team/members/${memberId}`, { method: 'DELETE' }),
    onSuccess: (result) => {
      queryClient.setQueryData(teamKey, result.team)
      void queryClient.invalidateQueries({ queryKey: candidatesKey })
      for (const key of ['planning-members', 'settings-members']) void queryClient.invalidateQueries({ queryKey: [key] })
      setNotice(result.removed ? 'Đã gỡ nhân sự khỏi dự án. Hồ sơ và tài khoản vẫn được giữ.' : 'Nhân sự này không còn thuộc dự án.')
      setEditing(undefined)
    },
  })
  const finishEditing = () => {
    setEditing(undefined)
    void queryClient.invalidateQueries({ queryKey: teamKey })
    void queryClient.invalidateQueries({ queryKey: candidatesKey })
  }
  if (team.isLoading) return <section className="panel settings-panel"><LoadingBlock /></section>
  if (team.error || !team.data) return <section className="panel settings-panel"><ErrorNotice error={team.error || new Error('Chưa tải được nhân sự dự án.')} onRetry={() => { void team.refetch() }} /></section>
  return (
    <>
      {adding && (
        <ConfirmDialog plain title="Thêm nhân sự" confirmLabel="Thêm vào dự án" busyLabel="Đang thêm…" busy={add.isPending} confirmDisabled={!memberId} error={add.error} onConfirm={() => { if (memberId) add.mutate() }} onCancel={() => { if (!add.isPending) { setAdding(false); setSearch(''); setMemberId(''); add.reset() } }}>
          {candidates.isLoading ? <LoadingBlock /> : candidates.error ? <ErrorNotice error={candidates.error} onRetry={() => { void candidates.refetch() }} /> : (candidates.data || []).length === 0 ? <p>Tất cả nhân sự đang hoạt động đã thuộc dự án này.</p> : (
            <div className="member-picker">
              <label>Tìm nhân sự<input value={search} onChange={(event) => { setSearch(event.target.value); setMemberId('') }} placeholder="Nhập tên hoặc email" autoFocus /></label>
              <label>Nhân sự<select value={memberId} onChange={(event) => setMemberId(event.target.value)}><option value="">Chọn nhân sự</option>{choices.map((member) => <option key={member.member_id} value={member.member_id}>{member.display_name}{member.email ? ` · ${member.email}` : ''}</option>)}</select></label>
              {choices.length === 0 && <p className="field-help">Không tìm thấy nhân sự phù hợp.</p>}
            </div>
          )}
        </ConfirmDialog>
      )}
      <section className="panel settings-panel member-list">
        <div className="panel-heading"><div><h2>Nhân sự dự án</h2><p>Project Owner và CTO có thể thêm nhân sự đang hoạt động. Việc đổi Owner hoặc loại nhân sự vẫn chỉ do CTO thực hiện.</p></div><button type="button" className="button button-primary" onClick={() => { setNotice(''); setAdding(true) }}><Plus size={16} /> Thêm nhân sự</button></div>
        {notice && <p className="notice notice-success" role="status">{notice}</p>}
        {(remove.error || staff.error) && <ErrorNotice error={remove.error || staff.error} />}
        {team.data.members.length === 0 ? <EmptyState icon={<UserRound size={20} />} title="Chưa có nhân sự" text="Thêm người đầu tiên vào dự án." /> : team.data.members.map((member) => {
          const fullMember = staff.data?.find((row) => row.id === member.member_id)
          if (editing === member.member_id && fullMember) return <MemberEditor key={member.member_id} member={fullMember} projects={projects} onDone={finishEditing} />
          return (
            <div className="member-row" key={member.member_id}>
              <div><strong>{member.display_name}{member.is_owner && <span className="capacity-owner">Project Owner</span>}</strong><small>{member.email || 'Chưa có email'} · {member.account_subject ? `tài khoản ${member.account_subject}` : 'Chưa có tài khoản'}</small></div>
              <span className="status">{member.is_owner ? 'Quản lý dự án' : 'Thành viên'}</span>
              {user?.role === 'CTO' && <span className="project-actions">
                <button className="button button-secondary button-small" type="button" disabled={!fullMember || staff.isLoading} onClick={() => { setNotice(''); setEditing(member.member_id) }}><Pencil size={14} /> Sửa</button>
                <button className="icon-button" type="button" aria-label={`Gỡ ${member.display_name} khỏi dự án`} title={member.is_owner ? 'Đổi Project Owner trước khi gỡ người này' : 'Gỡ khỏi dự án, không xóa hồ sơ hoặc tài khoản'} disabled={member.is_owner || remove.isPending} onClick={() => { if (window.confirm(`Gỡ ${member.display_name} khỏi dự án ${project.name}?\n\nHồ sơ nhân sự, tài khoản, lịch sử và các dự án khác vẫn được giữ.`)) remove.mutate(member.member_id) }}><Trash2 size={15} /></button>
              </span>}
            </div>
          )
        })}
      </section>
    </>
  )
}

function ProjectDetailsPage() {
  const { code = '' } = useParams()
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const project = projects.data?.find((row) => row.code === code)
  if (projects.isLoading) return <LoadingBlock />
  if (projects.error) return <ErrorNotice error={projects.error} onRetry={() => { void projects.refetch() }} />
  if (!project) return <><Link className="back-link" to="/projects"><ArrowLeft size={15} /> Dự án</Link><section className="panel"><EmptyState icon={<Search size={20} />} title="Không tìm thấy dự án" text="Dự án không tồn tại hoặc nằm ngoài phạm vi của bạn." /></section></>
  return (
    <>
      <Link className="back-link" to="/projects"><ArrowLeft size={15} /> Dự án</Link>
      <PageHeader title={project.name} helper={`Mã dự án ${project.code} · ${project.owner_name ? `Project Owner: ${project.owner_name}` : 'chưa có Project Owner'}`} />
      <ProjectMembersPanel project={project} projects={(projects.data || []).filter((row) => row.status === 'ACTIVE')} />
    </>
  )
}

function AccountEditor({ account, accounts, onDone }: { account: Account; accounts: Account[]; onDone: () => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(account.display_name)
  const [active, setActive] = useState(account.is_active)
  const [memberId, setMemberId] = useState(account.member_id || '')
  const [error, setError] = useState<unknown>()
  const members = useQuery({ queryKey: ['settings-members'], queryFn: () => api<WorkforceMember[]>('/planning/members?include_inactive=true') })
  // A staff member already behind another login shows greyed with that login's name, so the CTO knows where to free it.
  const holder = new Map(accounts.filter((row) => row.id !== account.id && row.member_id).map((row) => [row.member_id as string, row.display_name || row.subject]))
  const choices = (members.data || []).filter((member) => member.status === 'ACTIVE')
  const save = useMutation({
    mutationFn: () => api<Account>(`/users/${account.id}`, { method: 'PATCH', body: JSON.stringify({ display_name: name.trim(), is_active: active, ...(memberId !== (account.member_id || '') ? { member_id: memberId } : {}) }) }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['accounts'] }); onDone() },
    onError: setError,
  })
  return (
    <form className="member-editor" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
      <div className="wizard-row">
        <label><span className="req-label">Họ tên<Req /></span><input value={name} onChange={(e) => setName(e.target.value)} required autoFocus /></label>
        {account.role === 'CTO' ? <span /> : <label>Trạng thái<select value={active ? 'ACTIVE' : 'INACTIVE'} onChange={(e) => setActive(e.target.value === 'ACTIVE')}><option value="ACTIVE">Đang hoạt động</option><option value="INACTIVE">Đã khóa</option></select></label>}
        <label>Là nhân sự<select value={memberId} onChange={(e) => setMemberId(e.target.value)} disabled={account.role === 'DEVELOPER'}>
          <option value="">Không gắn</option>
          {choices.map((member) => <option key={member.id} value={member.id} disabled={holder.has(member.id)}>{member.display_name}{member.email_reference ? ` · ${member.email_reference}` : ''}{holder.has(member.id) ? ` · đã gắn tài khoản ${holder.get(member.id)}` : ''}</option>)}
        </select></label>
      </div>
      <p className="field-help">Gắn tài khoản với nhân sự để giờ việc riêng trừ vào giờ trống của người đó, bot Telegram nhắc đúng người, và agent lấy được việc của họ. Tài khoản CTO gắn với chính mình.</p>
      <p className="field-help">Dự án của một tài khoản được quyết định ở trang từng dự án (Cài đặt &gt; Dự án &gt; Sửa &gt; Nhân sự của dự án), nơi mỗi dự án có đúng một Project Owner.</p>
      {error != null && <ErrorNotice error={error} />}
      <div className="report-edit-actions">
        <button className="button button-secondary button-small" type="button" onClick={onDone}>Hủy</button>
        <button className="button button-primary button-small" type="submit" disabled={!name.trim() || save.isPending}>{save.isPending ? 'Đang lưu…' : 'Lưu tài khoản'}</button>
      </div>
    </form>
  )
}

// A login for a staff member who works through an agent: it carries a personal token and nothing to decide (FR-MCP-05).
function DeveloperAccountForm({ accounts, onIssued }: { accounts: Account[]; onIssued: (issued: { subject: string; password: string; name?: string }) => void }) {
  const queryClient = useQueryClient()
  const members = useQuery({ queryKey: ['settings-members'], queryFn: () => api<WorkforceMember[]>('/planning/members?include_inactive=true') })
  const taken = new Set(accounts.map((account) => account.member_id).filter(Boolean))
  const free = (members.data || []).filter((member) => member.status === 'ACTIVE' && !taken.has(member.id))
  const [memberId, setMemberId] = useState('')
  const [subject, setSubject] = useState('')
  const [error, setError] = useState<unknown>()
  const create = useMutation({
    mutationFn: () => api<{ account: Account; temporary_password: string }>('/users', { method: 'POST', body: JSON.stringify({ subject: subject.trim(), role: 'DEVELOPER', member_id: memberId }) }),
    onSuccess: (result) => { setError(undefined); setMemberId(''); setSubject(''); onIssued({ subject: result.account.subject, password: result.temporary_password, name: result.account.display_name }); void queryClient.invalidateQueries({ queryKey: ['accounts'] }) },
    onError: setError,
  })
  const chosen = free.find((member) => member.id === memberId)
  return (
    <form className="settings-inline-form developer-form" onSubmit={(event) => { event.preventDefault(); if (memberId && subject.trim()) create.mutate() }}>
      <label>Nhân sự
        <select value={memberId} onChange={(event) => { setMemberId(event.target.value); const picked = free.find((member) => member.id === event.target.value); if (picked && !subject) setSubject((picked.email_reference || '').split('@')[0].toLowerCase().replace(/[^a-z0-9._-]/g, '')) }}>
          <option value="">Chọn người chưa có tài khoản</option>
          {free.map((member) => <option key={member.id} value={member.id} disabled={!member.email_reference}>{member.display_name}{member.email_reference ? '' : ' (chưa có email)'}</option>)}
        </select>
      </label>
      <label>Tên đăng nhập<input value={subject} onChange={(event) => setSubject(event.target.value)} placeholder="vd. minh.tuong" minLength={3} maxLength={64} /></label>
      <button className="button button-primary" type="submit" disabled={!memberId || subject.trim().length < 3 || create.isPending || !chosen?.email_reference}>{create.isPending ? 'Đang tạo…' : 'Tạo tài khoản Developer'}</button>
      {error != null && <ErrorNotice error={error} />}
      <p className="field-help">Developer đăng nhập web chỉ để đặt mật khẩu và tạo token cho Codex hay Claude Code; dự án của họ là các dự án họ có mặt ở Cài đặt &gt; Nhân sự. Agent của họ lấy việc trong ngày, báo đang làm hay xong, gửi báo cáo cuối ngày; không duyệt, không chốt.</p>
    </form>
  )
}

function UsersSettings() {
  const queryClient = useQueryClient()
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api<Account[]>('/users') })
  const [editing, setEditing] = useState<string>()
  const [issued, setIssued] = useState<{ subject: string; password: string; name?: string }>()
  const [error, setError] = useState<unknown>()
  const reset = useMutation({
    mutationFn: (account: Account) => api<{ account: Account; temporary_password: string }>(`/users/${account.id}/reset-password`, { method: 'POST' }),
    onSuccess: (result) => { setError(undefined); setIssued({ subject: result.account.subject, password: result.temporary_password }); void queryClient.invalidateQueries({ queryKey: ['accounts'] }) },
    onError: setError,
  })
  return (
    <>
      <SectionHeader title="Người dùng" helper="Các tài khoản đăng nhập. Tài khoản Project Owner được tạo tự động khi bạn chọn một nhân sự làm Project Owner ở trang dự án, và bị khóa khi người đó không còn là Owner của dự án nào. Ở đây bạn khóa tài khoản hoặc cấp lại mật khẩu tạm." />
      {issued && <IssuedPassword issued={issued} onClose={() => setIssued(undefined)} />}
      {(accounts.error || error != null) && <ErrorNotice error={accounts.error || error} />}
      {accounts.data && <section className="panel settings-panel developer-panel"><div className="panel-heading"><div><h2>Tài khoản Developer</h2></div></div><DeveloperAccountForm accounts={accounts.data} onIssued={setIssued} /></section>}
      {accounts.isLoading ? <LoadingBlock /> : (
        <section className="panel settings-panel member-list">
          {(accounts.data || []).map((account) => editing === account.id ? <AccountEditor key={account.id} account={account} accounts={accounts.data || []} onDone={() => setEditing(undefined)} /> : (
            <div className="member-row" key={account.id}>
              <div><strong>{account.display_name}</strong><small>{account.subject} · {account.email}{account.member_name ? ` · nhân sự: ${account.member_name}` : account.role === 'CTO' ? ' · chưa gắn nhân sự' : ''}{account.agent_last_used_at ? ` · agent dùng ${formatDate(account.agent_last_used_at)}` : ' · chưa dùng agent'}{!account.is_active ? ' · đã khóa' : ''}{account.must_change_password ? ' · chưa đổi mật khẩu tạm' : ''}{account.mfa_enabled ? ' · có MFA' : ' · chưa bật MFA'}</small></div>
              <div className="report-tags">
                {account.role === 'CTO' ? <span className="status report-valid">CTO · mọi dự án</span> : account.role === 'DEVELOPER' ? (account.projects.length === 0 ? <span className="status report-warning">Developer · chưa có dự án ở Nhân sự</span> : account.projects.map((project) => <span className="status" key={project.id}>Developer · {project.name}</span>)) : account.projects.length === 0 ? <span className="status report-warning">Không là Owner của dự án nào</span> : account.projects.map((project) => <span className="status" key={project.id}>Owner · {project.name}</span>)}
              </div>
              {account.role === 'CTO' ? (
                <span className="project-actions"><button className="button button-secondary button-small" type="button" onClick={() => setEditing(account.id)}><Pencil size={15} /> Sửa</button></span>
              ) : (
                <span className="project-actions">
                  <button className="button button-secondary button-small" type="button" disabled={reset.isPending} onClick={() => { if (window.confirm(`Cấp mật khẩu tạm mới cho ${account.subject}? Mật khẩu hiện tại sẽ hết hiệu lực.`)) reset.mutate(account) }}>Cấp lại mật khẩu</button>{' '}
                  <button className="button button-secondary button-small" type="button" onClick={() => setEditing(account.id)}><Pencil size={15} /> Sửa</button>
                </span>
              )}
            </div>
          ))}
        </section>
      )}
    </>
  )
}

const settingsTabs = [
  { to: '/settings/projects', label: 'Dự án', ctoOnly: true },
  { to: '/settings/members', label: 'Nhân sự', ctoOnly: true },
  { to: '/settings/users', label: 'Người dùng', ctoOnly: true },
  { to: '/settings/glossary', label: 'Thuật ngữ', ctoOnly: false },
  { to: '/settings/ai', label: 'AI', ctoOnly: true },
  { to: '/settings/system', label: 'Hệ thống', ctoOnly: true },
  { to: '/settings/channels', label: 'Kênh đăng', ctoOnly: true },
  { to: '/settings/watch', label: 'Nguồn quét', ctoOnly: true },
  { to: '/settings/account', label: 'Tài khoản & bảo mật', ctoOnly: false },
]

function SettingsLayout() {
  const { pathname } = useLocation()
  const { user } = useAuth()
  return (
    <>
      <PageHeader title="Cài đặt" />
      <nav className="settings-tabs" aria-label="Các mục cài đặt">
        {settingsTabs.filter((tab) => (user?.beta_features_enabled !== false || (tab.to !== '/settings/channels' && tab.to !== '/settings/watch')) && (!tab.ctoOnly || user?.role === 'CTO') && (user?.role !== 'DEVELOPER' || tab.to === '/settings/account')).map((tab) => <Link key={tab.to} to={tab.to} className={pathname.startsWith(tab.to) ? 'active' : undefined} aria-current={pathname.startsWith(tab.to) ? 'page' : undefined}>{tab.label}</Link>)}
      </nav>
      <Outlet context={useOutletContext<ShellContext>()} />
    </>
  )
}

function SectionHeader({ title, helper, action }: { title: string; helper?: string; action?: ReactNode }) {
  return <div className="settings-head"><div><h2>{title}</h2>{helper && <p>{helper}</p>}</div>{action}</div>
}

const backupErrors: Record<string, string> = {
  PASSPHRASE_MISSING: 'chưa đặt BACKUP_PASSPHRASE (từ 16 ký tự) trong .env',
  TARGET_FOLDER_MISSING: 'không thấy thư mục BACKUP_DIR',
  VERIFY_FAILED: 'file sao lưu không đọc lại được',
  VERIFY_INCOMPLETE: 'file sao lưu thiếu nội dung',
  ARCHIVE_FAILED: 'không ghi được file sao lưu',
}

function backupSummary(detail: BackupDetail) {
  const failed = detail.last_error_code ? ` · lần gần nhất lỗi: ${backupErrors[detail.last_error_code] || detail.last_error_code}` : ''
  if (!detail.last_ok_at) return `Chưa có bản sao lưu nào${failed}`
  const size = detail.last_ok_size_bytes == null ? '' : ` · ${(detail.last_ok_size_bytes / 1_000_000).toFixed(1)} MB`
  return `${detail.state === 'overdue' ? 'Quá hạn · bản' : 'Bản'} gần nhất ${formatDate(detail.last_ok_at)}${size}${failed}`
}

// Reminders over Telegram: the bot, who is linked, the holidays, what went out (FR-NTF-01..05).
function TelegramPanel() {
  const queryClient = useQueryClient()
  const status = useQuery({ queryKey: ['telegram-status'], queryFn: () => api<TelegramStatus>('/notify/telegram') })
  const log = useQuery({ queryKey: ['telegram-messages'], queryFn: () => api<TelegramMessageRow[]>('/notify/telegram/messages?days=7') })
  const [holidayText, setHolidayText] = useState<string>()
  const [error, setError] = useState<unknown>()
  const save = useMutation({
    mutationFn: (days: { day: string; note: string | null }[]) => api('/notify/holidays', { method: 'PUT', body: JSON.stringify({ days }) }),
    onMutate: () => setError(undefined), onSuccess: () => { setHolidayText(undefined); void queryClient.invalidateQueries({ queryKey: ['telegram-status'] }) }, onError: setError,
  })
  const data = status.data
  const text = holidayText ?? (data?.holidays || []).map((row) => `${row.day}${row.note ? ` ${row.note}` : ''}`).join('\n')
  const parse = (value: string) => value.split('\n').map((line) => line.trim()).filter(Boolean).map((line) => { const [day, ...rest] = line.split(/\s+/); return { day, note: rest.join(' ') || null } }).filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.day))
  const sent = (log.data || []).filter((row) => row.status === 'SENT').length
  const failed = (log.data || []).filter((row) => row.status === 'FAILED')
  return (
    <section className="panel system-panel">
      <div className="panel-heading"><div><h2>Nhắc việc qua Telegram</h2></div><span className={`health-dot ${data?.bot_seen_at ? 'healthy' : ''}`} /></div>
      {status.error != null && <ErrorNotice error={status.error} onRetry={() => { void status.refetch() }} />}
      {error != null && <ErrorNotice error={error} />}
      {status.isLoading || !data ? <LoadingBlock /> : (
        <div className="telegram-panel">
          <div className="health-list">
            <HealthLine label="Bot" value={data.bot_username ? (data.bot_seen_at ? 'ok' : 'chưa thấy chạy') : 'chưa cấu hình'} />
            <div className="health-line"><span>Nhóm dự án đã gắn</span><strong>{data.projects.filter((row) => row.linked).length}/{data.projects.length}</strong></div>
            <div className="health-line"><span>Người đã gắn</span><strong>{data.members.filter((row) => row.linked).length}/{data.members.length}</strong></div>
            <div className="health-line"><span>Bảy ngày qua</span><strong className={failed.length > 0 ? 'text-warn' : 'text-good'}>{sent} tin đã gửi{failed.length > 0 ? ` · ${failed.length} lỗi` : ''}</strong></div>
          </div>
          <p className="field-help">{data.bot_username ? <>Bot <strong>@{data.bot_username}</strong>. Thêm bot vào nhóm Telegram của dự án, hoặc vào nhóm chung đã bật Chủ đề, rồi gõ <code>/lien-ket &lt;mã dự án&gt;</code> trong nhóm hay trong chủ đề của dự án; mỗi người bấm link mời ở Cài đặt &gt; Nhân sự. Nhắc kế hoạch ngày mai 17:30, nhắc lại 08:30 và 09:30; nhắc báo cáo 17:30 và 08:00; kế hoạch từng người 08:00; việc quá hạn tới CTO 09:30. Chỉ thứ Hai đến thứ Sáu, trừ ngày nghỉ bên dưới.</> : <>Đặt <code>TELEGRAM_BOT_TOKEN</code> và <code>TELEGRAM_BOT_USERNAME</code> trong <code>.env</code> trên server rồi khởi động dịch vụ <code>telegram-bot</code>.</>}</p>
          <label className="telegram-holidays">Ngày nghỉ (mỗi dòng một ngày, dạng 2026-01-01, ghi chú tùy ý phía sau)
            <textarea rows={4} value={text} onChange={(event) => setHolidayText(event.target.value)} placeholder="2026-12-25 Giáng sinh" />
          </label>
          <div className="report-edit-actions">
            <button type="button" className="button button-primary button-small" disabled={save.isPending || holidayText === undefined} onClick={() => save.mutate(parse(text))}>{save.isPending ? 'Đang lưu…' : 'Lưu ngày nghỉ'}</button>
          </div>
          {failed.length > 0 && <ul className="telegram-failed">{failed.slice(0, 5).map((row) => <li key={row.id}>{row.for_date} {row.slot} · {row.project_name || row.member_name || row.kind}: {row.error}</li>)}</ul>}
        </div>
      )}
    </section>
  )
}

const aiPresets: { label: string; name: string; base_url: string; extra_body: Record<string, unknown> | null; models: string[] }[] = [
  { label: 'UModelVerse', name: 'umodelverse', base_url: 'https://api-sg.umodelverse.ai/v1', extra_body: null, models: [] },
  { label: 'OpenRouter (không lưu dữ liệu)', name: 'openrouter', base_url: 'https://openrouter.ai/api/v1', extra_body: { provider: { zdr: true, data_collection: 'deny', allow_fallbacks: false } }, models: [] },
  { label: 'OpenAI', name: 'openai', base_url: 'https://api.openai.com/v1', extra_body: null, models: ['gpt-4o-mini', 'gpt-4o'] },
  { label: 'DeepSeek', name: 'deepseek', base_url: 'https://api.deepseek.com/v1', extra_body: null, models: ['deepseek-chat'] },
  { label: 'Ollama trên máy chủ', name: 'ollama', base_url: 'http://host.docker.internal:11434/v1', extra_body: null, models: [] },
  { label: 'Tùy chỉnh', name: '', base_url: '', extra_body: null, models: [] },
]

const aiTaskLabels: Record<string, string> = {
  default: 'Mặc định (tác vụ chưa đặt riêng)',
  normalize: 'Chuẩn hóa yêu cầu',
  report: 'Báo cáo cuối ngày',
  meeting: 'Biên bản họp',
  vision: 'Đọc ảnh đính kèm',
  content: 'Bài viết và nội dung',
}

const aiSourceLabels: Record<string, string> = { route: 'đặt riêng', default: 'theo Mặc định', env: 'theo .env', none: 'chưa cấu hình' }

const aiTestErrors: Record<string, string> = {
  AUTH: 'khóa bị từ chối',
  TIMEOUT: 'quá thời gian chờ',
  NETWORK: 'không kết nối được tới địa chỉ này',
  KEY_UNREADABLE: 'không đọc được khóa đã lưu, hãy nhập lại',
}

function AiSettings() {
  const queryClient = useQueryClient()
  const [error, setError] = useState<unknown>()
  const [preset, setPreset] = useState(0)
  const [form, setForm] = useState({ name: aiPresets[0].name, base_url: aiPresets[0].base_url, api_key: '' })
  const [models, setModels] = useState<Record<string, string[]>>({})
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [draft, setDraft] = useState<Record<string, { provider_id: string; model: string }>>({})
  const providers = useQuery({ queryKey: ['ai-providers'], queryFn: () => api<AiProvider[]>('/ai/providers') })
  const routes = useQuery({ queryKey: ['ai-routes'], queryFn: () => api<AiRoute[]>('/ai/routes') })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['ai-providers'] })
    void queryClient.invalidateQueries({ queryKey: ['ai-routes'] })
    void queryClient.invalidateQueries({ queryKey: ['operations'] })
    void queryClient.invalidateQueries({ queryKey: ['setup'] })
  }
  const choose = (index: number) => {
    setPreset(index)
    setForm({ name: aiPresets[index].name, base_url: aiPresets[index].base_url, api_key: '' })
  }
  const add = useMutation({
    mutationFn: () => api<AiProvider>('/ai/providers', { method: 'POST', body: JSON.stringify({ ...form, extra_body: aiPresets[preset].extra_body }) }),
    onSuccess: () => { setForm({ ...form, api_key: '' }); setError(undefined); refresh() },
    onError: setError,
  })
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api<AiProvider>(`/ai/providers/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    onSuccess: () => { setError(undefined); refresh() },
    onError: setError,
  })
  const remove = useMutation({
    mutationFn: (id: string) => api<unknown>(`/ai/providers/${id}`, { method: 'DELETE' }),
    onSuccess: () => { setError(undefined); refresh() },
    onError: setError,
  })
  const test = useMutation({
    mutationFn: (id: string) => api<AiProviderTest>(`/ai/providers/${id}/test`, { method: 'POST' }).then((result) => ({ id, result })),
    onSuccess: ({ id, result }) => {
      setModels((current) => ({ ...current, [id]: result.models }))
      setNotes((current) => ({ ...current, [id]: result.ok ? `Kết nối được, thấy ${result.models.length} model.` : `Không kết nối được: ${aiTestErrors[result.error || ''] || result.error}` }))
      refresh()
    },
    onError: setError,
  })
  const save = useMutation({
    mutationFn: ({ task, provider_id, model }: { task: string; provider_id: string | null; model: string | null }) =>
      api<AiRoute[]>(`/ai/routes/${task}`, { method: 'PUT', body: JSON.stringify({ provider_id, model }) }),
    onSuccess: (_data, variables) => {
      setDraft((current) => { const next = { ...current }; delete next[variables.task]; return next })
      setError(undefined)
      refresh()
    },
    onError: setError,
  })
  const rows = providers.data || []
  const suggestions = (providerId: string): string[] => {
    const row = rows.find((item) => item.id === providerId)
    const known = aiPresets.find((item) => row && item.base_url === row.base_url)?.models || []
    return Array.from(new Set([...(models[providerId] || []), ...known]))
  }
  return (
    <>
      <SectionHeader title="AI" helper="Khóa LLM và model cho từng tác vụ. Chỉ nhận API tương thích OpenAI. Khóa được mã hóa và không hiển thị lại." />
      {error != null && <ErrorNotice error={error} onRetry={() => setError(undefined)} />}
      <section className="panel ai-panel">
        <div className="panel-heading"><div><h2>Nhà cung cấp</h2></div></div>
        {providers.isLoading ? <LoadingBlock /> : providers.error ? <ErrorNotice error={providers.error} onRetry={() => { void providers.refetch() }} /> : (
          <div className="ai-list">
            {rows.length === 0 && <p className="field-help">Chưa có nhà cung cấp nào. Nếu máy chủ còn khóa trong .env thì hệ thống vẫn dùng khóa đó.</p>}
            {rows.map((row) => (
              <div className="ai-provider" key={row.id}>
                <div>
                  <strong>{row.name}</strong> <span className="field-help">{row.base_url}</span>
                  <div className="field-help">
                    {row.key_ok ? `Khóa …${row.key_hint}` : 'Không đọc được khóa đã lưu, hãy nhập lại'}
                    {row.last_test_at && ` · lần thử gần nhất: ${row.last_test_ok ? 'đạt' : aiTestErrors[row.last_test_error || ''] || row.last_test_error}`}
                    {!row.enabled && ' · đang tắt'}
                  </div>
                  {notes[row.id] && <div className="field-help" role="status">{notes[row.id]}</div>}
                </div>
                <div className="ai-actions">
                  <button className="button button-secondary" disabled={test.isPending} onClick={() => test.mutate(row.id)}>Thử kết nối</button>
                  <button className="button button-secondary" onClick={() => patch.mutate({ id: row.id, body: { enabled: !row.enabled } })}>{row.enabled ? 'Tắt' : 'Bật'}</button>
                  <button className="button button-secondary" onClick={() => { const key = window.prompt('Nhập khóa mới'); if (key) patch.mutate({ id: row.id, body: { api_key: key } }) }}>Đổi khóa</button>
                  <button className="button button-secondary" onClick={() => { if (window.confirm(`Xóa nhà cung cấp ${row.name}?`)) remove.mutate(row.id) }}>Xóa</button>
                </div>
              </div>
            ))}
          </div>
        )}
        <h3>Thêm nhà cung cấp</h3>
        <div className="form-grid two-col">
          <label>Loại
            <select value={preset} onChange={(event) => choose(Number(event.target.value))}>
              {aiPresets.map((item, index) => <option key={item.label} value={index}>{item.label}</option>)}
            </select>
          </label>
          <label>Tên (tối đa 32 ký tự)
            <input value={form.name} maxLength={32} onChange={(event) => setForm({ ...form, name: event.target.value })} />
          </label>
          <label>Địa chỉ API (base URL)
            <input value={form.base_url} placeholder="https://…/v1" onChange={(event) => setForm({ ...form, base_url: event.target.value })} />
          </label>
          <label>Khóa API
            <input type="password" autoComplete="off" value={form.api_key} onChange={(event) => setForm({ ...form, api_key: event.target.value })} />
          </label>
        </div>
        <p><button className="button button-primary" disabled={add.isPending || !form.name.trim() || !form.base_url.trim() || !form.api_key.trim()} onClick={() => add.mutate()}>Thêm</button></p>
      </section>
      <section className="panel ai-panel">
        <div className="panel-heading"><div><h2>Model theo tác vụ</h2></div></div>
        {routes.isLoading ? <LoadingBlock /> : routes.error ? <ErrorNotice error={routes.error} onRetry={() => { void routes.refetch() }} /> : (
          <div className="ai-list">
            {(routes.data || []).map((route) => {
              const value = draft[route.task] || { provider_id: route.provider_id || '', model: route.model || '' }
              const dirty = value.provider_id !== (route.provider_id || '') || value.model !== (route.model || '')
              const listId = `ai-models-${route.task}`
              return (
                <div className="ai-route" key={route.task}>
                  <div>
                    <strong>{aiTaskLabels[route.task] || route.task}</strong>
                    <div className="field-help">Đang dùng: {route.effective_provider ? `${route.effective_provider} · ${route.effective_model}` : 'chưa có'} ({aiSourceLabels[route.source] || route.source})</div>
                  </div>
                  <div className="ai-actions">
                    <select aria-label={`Nhà cung cấp cho ${aiTaskLabels[route.task]}`} value={value.provider_id} onChange={(event) => setDraft({ ...draft, [route.task]: { ...value, provider_id: event.target.value } })}>
                      <option value="">Không đặt riêng</option>
                      {rows.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
                    </select>
                    <input aria-label={`Model cho ${aiTaskLabels[route.task]}`} list={listId} value={value.model} maxLength={128} placeholder="tên model" disabled={!value.provider_id} onChange={(event) => setDraft({ ...draft, [route.task]: { ...value, model: event.target.value } })} />
                    <datalist id={listId}>{suggestions(value.provider_id).map((name) => <option key={name} value={name} />)}</datalist>
                    <button className="button button-primary" disabled={!dirty || save.isPending || (Boolean(value.provider_id) && !value.model.trim())} onClick={() => save.mutate({ task: route.task, provider_id: value.provider_id || null, model: value.provider_id ? value.model.trim() : null })}>Lưu</button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
        <p className="field-help">Tác vụ chưa đặt riêng dùng dòng Mặc định; chưa có cả hai thì dùng khóa trong .env nếu có. Tác vụ đã đặt ở đây chỉ gọi một lần, không chuyển sang model khác khi lỗi.</p>
      </section>
    </>
  )
}

function SystemSettings() {
  const operationsQuery = useQuery({ queryKey: ['operations'], queryFn: () => api<OperationsStatus>('/operations/status') })
  return (
    <>
      <SectionHeader title="Hệ thống" helper="Tình trạng các thành phần mà ứng dụng phụ thuộc." />
      <TelegramPanel />
      <section className="panel system-panel">
        <div className="panel-heading"><div><h2>Trạng thái</h2></div><span className={`health-dot ${operationsQuery.data?.status === 'ok' ? 'healthy' : ''}`} /></div>
        {operationsQuery.isLoading ? <LoadingBlock /> : operationsQuery.error ? <ErrorNotice error={operationsQuery.error} onRetry={() => { void operationsQuery.refetch() }} /> : (
          <div className="health-list">
            <HealthLine label="API & giao diện" value={operationsQuery.data?.web} />
            <HealthLine label="AI processing" value={operationsQuery.data?.worker_ai} />
            <HealthLine label="AI" value={operationsQuery.data ? (operationsQuery.data.ai_configured ? `sẵn sàng (${({ route: 'đặt trên màn hình AI', default: 'theo dòng Mặc định', env: 'theo .env' } as Record<string, string>)[operationsQuery.data.ai_source] || operationsQuery.data.ai_source})` : 'chưa có API key') : undefined} />
            <HealthLine label="SeaweedFS" value={operationsQuery.data?.storage} />
            <div className="health-line"><span>Sao lưu hằng ngày</span><strong className={operationsQuery.data?.backup === 'healthy' ? 'text-good' : 'text-warn'}>{operationsQuery.data ? backupSummary(operationsQuery.data.backup_detail) : 'Chưa rõ'}</strong></div>
          </div>
        )}
        <div className="privacy-card"><ShieldCheck size={20} aria-hidden="true" /><div><strong>Ranh giới riêng tư</strong><p>Raw chat chỉ được tải ở trang chi tiết và chỉ CTO có quyền truy cập.</p></div></div>
      </section>
    </>
  )
}

function GlossarySettings() {
  const queryClient = useQueryClient()
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const [scope, setScope] = useState('')
  const [term, setTerm] = useState('')
  const [error, setError] = useState<unknown>()
  const glossary = useQuery({ queryKey: ['meeting-glossary', scope], queryFn: () => api<GlossaryTerm[]>(`/meetings/glossary${scope ? `?project_id=${scope}` : ''}`) })
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['meeting-glossary'] }) }
  const add = useMutation({
    mutationFn: () => api<GlossaryTerm>('/meetings/glossary', { method: 'POST', body: JSON.stringify({ term: term.trim(), project_id: scope || null }) }),
    onSuccess: () => { setTerm(''); setError(undefined); refresh() },
    onError: setError,
  })
  const remove = useMutation({ mutationFn: (id: string) => api(`/meetings/glossary/${id}`, { method: 'DELETE' }), onSuccess: refresh, onError: setError })
  const { user } = useAuth()
  const sharedLocked = user?.role !== 'CTO'
  const scopeName = projects.data?.find((project) => project.code === scope)?.name
  const groups = [
    { title: 'Thuật ngữ chung', hint: 'Dùng cho mọi cuộc họp.', items: (glossary.data || []).filter((item) => !item.project_code) },
    ...(scope ? [{ title: `Thuật ngữ của ${scopeName || scope}`, hint: 'Chỉ nạp khi cuộc họp thuộc dự án này.', items: (glossary.data || []).filter((item) => item.project_code) }] : []),
  ]
  return (
    <>
      <SectionHeader title="Thuật ngữ" helper="Tên riêng và từ chuyên ngành được nạp cho bước chuyển chữ để nhận đúng, ví dụ tên sản phẩm. Thuật ngữ dài hơn 20 ký tự chỉ dùng cho bản chữ sau cuộc họp." />
      <section className="panel settings-panel">
        <label className="settings-scope">Phạm vi
          <select value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="">Chỉ thuật ngữ chung</option>
            {projects.data?.filter((project) => project.status === 'ACTIVE').map((project) => <option key={project.id} value={project.code}>{project.name}</option>)}
          </select>
        </label>
        {glossary.isLoading ? <LoadingBlock /> : groups.map((group) => (
          <div className="glossary-group" key={group.title}>
            <h3>{group.title} <small>{group.items.length}</small></h3>
            <p className="field-help">{group.hint}</p>
            <div className="glossary-terms">
              {group.items.length === 0 && <small className="muted">Chưa có thuật ngữ nào.</small>}
              {group.items.map((item) => <span className="chip" key={item.id} title={item.usable_in_realtime ? undefined : 'Dài hơn 20 ký tự: chỉ dùng cho bản chữ sau cuộc họp'}>{item.term}{!(sharedLocked && !item.project_code) && <button type="button" aria-label={`Xóa thuật ngữ ${item.term}`} onClick={() => remove.mutate(item.id)}><X size={12} /></button>}</span>)}
            </div>
          </div>
        ))}
        {sharedLocked && !scope && <p className="field-help">Thuật ngữ chung do CTO quản lý. Chọn một dự án của bạn để thêm thuật ngữ riêng.</p>}
        <form className="settings-inline-form" onSubmit={(event) => { event.preventDefault(); if (term.trim()) add.mutate() }}>
          <label>Thêm vào {scope ? `dự án ${scopeName || scope}` : 'thuật ngữ chung'}<input value={term} onChange={(e) => setTerm(e.target.value)} maxLength={50} placeholder="Ví dụ: Orbit" /></label>
          <button className="button button-primary" type="submit" disabled={!term.trim() || add.isPending || (sharedLocked && !scope)}>Thêm</button>
        </form>
        {error != null && <ErrorNotice error={error} />}
      </section>
    </>
  )
}

interface MembershipDraft { enabled: boolean; gitlabUser: string }

function MemberEditor({ member, projects, onDone }: { member?: WorkforceMember; projects: Project[]; onDone: () => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(member?.display_name || '')
  const [email, setEmail] = useState(member?.email_reference || '')
  const [hours, setHours] = useState(String(member?.default_weekday_hours ?? 8))
  const [status, setStatus] = useState(member?.status || 'ACTIVE')
  const [draft, setDraft] = useState<Record<string, MembershipDraft>>(() => Object.fromEntries(projects.map((project) => {
    const current = member?.project_mappings.find((mapping) => mapping.project_id === project.id && mapping.active)
    return [project.id, { enabled: Boolean(current), gitlabUser: current?.gitlab_user_external_id || '' }]
  })))
  const [users, setUsers] = useState<Record<string, GitLabUser[]>>({})
  const [error, setError] = useState<unknown>()
  const loadUsers = useMutation({
    mutationFn: async (project: Project) => ({
      id: project.id,
      probe: project.delivery_system === 'GITHUB'
        ? await runProbe('GITHUB', 'MEMBERS', project.github_repository || '', project.github_token_ref || '')
        : await runProbe('GITLAB', 'MEMBERS', project.gitlab_project_id || ''),
    }),
    onSuccess: ({ id, probe }) => { setError(undefined); setUsers((current) => ({ ...current, [id]: Array.isArray(probe.result) ? probe.result as unknown as GitLabUser[] : [] })) },
    onError: setError,
  })
  const save = useMutation({
    mutationFn: async () => {
      const body = {
        display_name: name.trim(), email_reference: email.trim() || null, default_weekday_hours: Number(hours) || 0, status,
        project_mappings: projects.filter((project) => draft[project.id]?.enabled).map((project) => ({
          project_id: project.id, gitlab_user_external_id: project.kind === 'SOFTWARE' ? draft[project.id].gitlabUser.trim() || null : null,
        })),
      }
      const target = member ?? await api<WorkforceMember>('/planning/members', { method: 'POST', body: JSON.stringify({ display_name: body.display_name, email_reference: body.email_reference, default_weekday_hours: body.default_weekday_hours }) })
      return api<WorkforceMember>(`/planning/members/${target.id}`, { method: 'PUT', body: JSON.stringify(body) })
    },
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['planning-members'] }); void queryClient.invalidateQueries({ queryKey: ['settings-members'] }); onDone() },
    onError: setError,
  })
  const update = (projectId: string, change: Partial<MembershipDraft>) => setDraft((current) => ({ ...current, [projectId]: { ...current[projectId], ...change } }))

  return (
    <form className="member-editor" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
      <div className="wizard-row">
        <label><span className="req-label">Họ tên<Req /></span><input value={name} onChange={(e) => setName(e.target.value)} required autoFocus /></label>
        <label>Email gửi báo cáo ngày<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="ten@example.com" /><small className="field-help">Dùng để nhận ra thư Daily Report của người này.</small></label>
      </div>
      <div className="wizard-row">
        <label>Số giờ mỗi ngày thường<input type="number" min={0} max={24} step={0.5} value={hours} onChange={(e) => setHours(e.target.value)} /></label>
        <label>Trạng thái<select value={status} onChange={(e) => setStatus(e.target.value)}><option value="ACTIVE">Đang làm việc</option><option value="INACTIVE">Ngừng</option></select></label>
      </div>
      <fieldset className="member-projects">
        <legend>Dự án tham gia</legend>
        {projects.map((project) => {
          const row = draft[project.id]
          const needsUser = project.kind === 'SOFTWARE'
          const deliveryName = project.delivery_system === 'GITHUB' ? 'GitHub' : 'GitLab'
          return (
            <div className="member-project" key={project.id}>
              <label className="member-project-toggle"><input type="checkbox" checked={row.enabled} onChange={(e) => update(project.id, { enabled: e.target.checked })} /><span><strong>{project.name}</strong><small>{projectKindLabels[project.kind]}</small></span></label>
              {row.enabled && needsUser && (
                <div className="member-gitlab">
                  {users[project.id] ? (
                    <select aria-label={`Người dùng ${deliveryName} ở ${project.name}`} value={row.gitlabUser} onChange={(e) => update(project.id, { gitlabUser: e.target.value })}>
                      <option value="">Chưa chọn</option>
                      {row.gitlabUser && !users[project.id].some((user) => user.id === row.gitlabUser) && <option value={row.gitlabUser}>ID {row.gitlabUser}</option>}
                      {users[project.id].map((user) => <option key={user.id} value={user.id}>{user.name}{user.username ? ` (@${user.username})` : ''}</option>)}
                    </select>
                  ) : <input aria-label={`ID người dùng ${deliveryName} ở ${project.name}`} value={row.gitlabUser} onChange={(e) => update(project.id, { gitlabUser: e.target.value })} placeholder={`ID người dùng ${deliveryName}`} />}
                  {project.delivery_system && !users[project.id] && <button className="button button-secondary button-small" type="button" disabled={loadUsers.isPending} onClick={() => loadUsers.mutate(project)}>{loadUsers.isPending && loadUsers.variables?.id === project.id ? 'Đang lấy…' : `Chọn từ ${deliveryName}`}</button>}
                  {!row.gitlabUser && <small className="report-gate">Chưa có người dùng {deliveryName}: chưa phân công được trong Daily Planning.</small>}
                </div>
              )}
            </div>
          )
        })}
      </fieldset>
      {error != null && <ErrorNotice error={error} />}
      <div className="report-edit-actions">
        <button className="button button-secondary button-small" type="button" onClick={onDone}>Hủy</button>
        <button className="button button-primary button-small" type="submit" disabled={!name.trim() || save.isPending}>{save.isPending ? 'Đang lưu…' : member ? 'Lưu nhân sự' : 'Thêm nhân sự'}</button>
      </div>
    </form>
  )
}

// The person's Telegram: linked, or an invite link to copy and send them (FR-NTF-03).
function TelegramInvite({ member }: { member: WorkforceMember }) {
  const queryClient = useQueryClient()
  const [link, setLink] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const invite = useMutation({
    mutationFn: () => api<{ code: string; link: string | null }>(`/notify/telegram/members/${member.id}/invite`, { method: 'POST' }),
    onSuccess: (made) => { setLink(made.link || `/start ${made.code}`); void queryClient.invalidateQueries({ queryKey: ['settings-members'] }) },
  })
  const unlink = useMutation({
    mutationFn: () => api(`/notify/telegram/members/${member.id}/link`, { method: 'DELETE' }),
    onSuccess: () => { setLink(null); void queryClient.invalidateQueries({ queryKey: ['settings-members'] }) },
  })
  if (member.telegram_linked) {
    return <span className="status status-approved" title="Nhận kế hoạch và nhắc báo cáo qua Telegram">Telegram{member.telegram_username ? ` @${member.telegram_username}` : ''} <button type="button" className="text-button" disabled={unlink.isPending} onClick={() => { if (window.confirm(`Bỏ gắn Telegram của ${member.display_name}?`)) unlink.mutate() }}>bỏ</button></span>
  }
  return (
    <span className="telegram-invite">
      {link ? (
        <button type="button" className="button button-secondary button-small" onClick={() => { void navigator.clipboard.writeText(link).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 2000) }) }}><Copy size={13} aria-hidden="true" /> {copied ? 'Đã chép link mời' : 'Chép link mời'}</button>
      ) : (
        <button type="button" className="text-button" disabled={invite.isPending} title="Tạo link mời; người đó bấm link là bot biết họ" onClick={() => invite.mutate()}>{member.telegram_invite_pending ? 'Tạo lại link mời Telegram' : 'Link mời Telegram'}</button>
      )}
      {invite.error != null && <small className="text-warn">{formatError(invite.error)}</small>}
    </span>
  )
}

function MembersSettings() {
  const { user, refresh } = useAuth()
  const queryClient = useQueryClient()
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const members = useQuery({ queryKey: ['settings-members'], queryFn: () => api<WorkforceMember[]>('/planning/members?include_inactive=true') })
  const [editing, setEditing] = useState<string>()
  // The CTO's own staff record in one click (FR-PLAN-37): then they can be planned like anyone else.
  const addMe = useMutation({
    mutationFn: () => api<WorkforceMember>('/planning/members/me', { method: 'POST' }),
    onSuccess: async () => { for (const key of ['settings-members', 'planning-members']) void queryClient.invalidateQueries({ queryKey: [key] }); await refresh() },
  })
  const activeProjects = (projects.data || []).filter((project) => project.status === 'ACTIVE')
  const projectById = new Map((projects.data || []).map((project) => [project.id, project]))
  return (
    <>
      <SectionHeader title="Nhân sự" helper="Gán nhân sự vào dự án. Dự án phần mềm cần thêm người dùng tương ứng ở nơi giao việc (GitLab hoặc GitHub) thì mới phân công được trong Daily Planning." action={editing === 'new' ? undefined : <span className="settings-actions">{user?.role === 'CTO' && !user.member_id && <button className="button button-secondary" type="button" disabled={addMe.isPending} title="Tạo hồ sơ nhân sự cho chính anh: 0 giờ mặc định, không đòi báo cáo ngày. Gán vào dự án kèm người dùng GitLab hoặc GitHub để nhận việc trong Daily Planning." onClick={() => addMe.mutate()}><UserRound size={16} /> {addMe.isPending ? 'Đang thêm…' : 'Thêm tôi vào nhân sự'}</button>}<button className="button button-primary" type="button" onClick={() => setEditing('new')}><Plus size={16} /> Thêm nhân sự</button></span>} />
      {addMe.error != null && <p className="field-help text-warn">{formatError(addMe.error)}</p>}
      {(members.error || projects.error) && <ErrorNotice error={members.error || projects.error} onRetry={() => { void members.refetch(); void projects.refetch() }} />}
      {members.isLoading || projects.isLoading ? <LoadingBlock /> : (
        <section className="panel settings-panel member-list">
          {editing === 'new' && <MemberEditor projects={activeProjects} onDone={() => setEditing(undefined)} />}
          {(members.data || []).length === 0 && editing !== 'new' && <EmptyState icon={<UserRound size={20} />} title="Chưa có nhân sự" text="Thêm nhân sự để nhận báo cáo ngày và lập kế hoạch." />}
          {(members.data || []).map((member) => editing === member.id ? <MemberEditor key={member.id} member={member} projects={activeProjects} onDone={() => setEditing(undefined)} /> : (
            <div className="member-row" key={member.id}>
              <div><strong>{member.display_name}{member.is_cto && <span className="capacity-owner" title="Hồ sơ nhân sự của chính CTO: không đòi báo cáo ngày; đặt giờ theo ngày ở Daily Planning khi nhận việc">CTO</span>}</strong><small>{member.email_reference || 'Chưa có email báo cáo'} · {member.default_weekday_hours} giờ/ngày{member.is_cto ? ' · không cần báo cáo ngày' : ''}{member.status !== 'ACTIVE' ? ' · đã ngừng' : ''}</small></div>
              <div className="report-tags">
                {member.project_mappings.filter((mapping) => mapping.active).length === 0 && <span className="status report-warning">Chưa gán dự án</span>}
                {member.project_mappings.filter((mapping) => mapping.active).map((mapping) => {
                  const project = projectById.get(mapping.project_id)
                  const missingUser = project?.kind === 'SOFTWARE' && !mapping.gitlab_user_external_id
                  return <span key={mapping.project_id} className={missingUser ? 'status report-warning' : 'status'} title={missingUser ? 'Chưa có người dùng ở nơi giao việc' : undefined}>{project?.name || 'Dự án'}{missingUser ? ` · thiếu ${project?.delivery_system === 'GITHUB' ? 'GitHub' : 'GitLab'}` : ''}</span>
                })}
              </div>
              {member.status === 'ACTIVE' && <TelegramInvite member={member} />}
              <button className="button button-secondary button-small" type="button" onClick={() => setEditing(member.id)}><Pencil size={15} /> Sửa</button>
            </div>
          ))}
        </section>
      )}
    </>
  )
}

function ProjectsPage() {
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const link = (label: string, id: string | null, url: string | null, enabled: boolean) => (
    id ? <span className="project-link">{url ? <a href={url} target="_blank" rel="noreferrer">{label} <ArrowUpRight size={12} /></a> : label}{!enabled && <small>chưa bật đồng bộ</small>}</span> : <span className="muted">Không liên kết</span>
  )
  return (
    <>
      <SectionHeader title="Dự án" helper="Loại dự án quyết định liên kết: Ý tưởng và Không code chỉ dùng Intake (việc trên bảng Việc), Phần mềm dùng thêm một nơi giao việc (GitLab của công ty hoặc GitHub của khách hàng) và được lập kế hoạch hằng ngày." action={<Link className="button button-primary" to="/settings/projects/new"><Plus size={16} /> Tạo dự án</Link>} />
      {projects.error && <ErrorNotice error={projects.error} onRetry={() => { void projects.refetch() }} />}
      {projects.isLoading ? <LoadingBlock /> : (
        <section className="panel">
          <table className="project-table">
            <thead><tr><th>Dự án</th><th>Loại</th><th>Project Owner</th><th>Nơi giao việc</th><th>Nhóm Telegram</th><th>Daily Planning</th><th><span className="sr-only">Thao tác</span></th></tr></thead>
            <tbody>
              {(projects.data || []).map((project) => (
                <tr key={project.id}>
                  <td><strong>{project.name}</strong><small>{project.code} · {project.intake_key}{project.status !== 'ACTIVE' ? ' · ngừng hoạt động' : ''}</small></td>
                  <td><span className="status">{projectKindLabels[project.kind] || project.kind}</span></td>
                  <td>{project.owner_name || <span className="muted">Chưa có</span>}</td>
                  <td>{project.delivery_system === 'GITHUB' ? link('GitHub của khách', project.github_repository, project.github_project_url, project.github_enabled) : link('GitLab', project.gitlab_project_id, project.gitlab_project_url, project.gitlab_enabled)}</td>
                  <td>{project.kind !== 'SOFTWARE' ? <span className="muted">Không nhắc</span> : project.telegram_linked ? <span className="status status-approved" title="Nhóm nhận nhắc kế hoạch và báo cáo">{project.telegram_chat_title || 'Đã gắn'}</span> : <span className="muted" title={`Thêm bot vào nhóm Telegram của dự án (hoặc mở chủ đề của dự án trong nhóm chung) rồi gõ /lien-ket ${project.code}`}>Chưa gắn · /lien-ket {project.code}</span>}</td>
                  <td>{project.kind === 'SOFTWARE' ? 'Có' : <span className="muted">Không</span>}</td>
                  <td className="project-actions"><Link className="button button-secondary button-small" to={`/settings/projects/${project.code}`}><Pencil size={15} /> Sửa</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  )
}

function AccountPage() {
  const { user, refresh } = useAuth()
  const [open, setOpen] = useState<'password' | 'mfa' | null>(null)
  const [passwordChanged, setPasswordChanged] = useState(false)
  const [secret, setSecret] = useState('')
  const [otp, setOtp] = useState('')
  const [stepUpPassword, setStepUpPassword] = useState('')
  const [stepUpOtp, setStepUpOtp] = useState('')
  const [codePassword, setCodePassword] = useState('')
  const [codeOtp, setCodeOtp] = useState('')
  const [codes, setCodes] = useState<string[]>([])
  const [copied, setCopied] = useState('')
  const [mfaJustEnabled, setMfaJustEnabled] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<{ at: 'mfa' | 'codes'; error: unknown }>()

  const run = async (at: 'mfa' | 'codes', action: () => Promise<void>) => {
    setError(undefined)
    setBusy(true)
    try { await action() } catch (requestError) { setError({ at, error: requestError }) } finally { setBusy(false) }
  }
  const setup = (event: FormEvent) => {
    event.preventDefault()
    void run('mfa', async () => {
      const result = await api<{ secret: string }>('/auth/mfa/setup', {
        method: 'POST', body: JSON.stringify({ current_password: stepUpPassword, otp: stepUpOtp || null }),
      })
      setSecret(result.secret)
      setStepUpPassword('')
      setStepUpOtp('')
      setMfaJustEnabled(false)
    })
  }
  const confirm = (event: FormEvent) => {
    event.preventDefault()
    void run('mfa', async () => {
      await api('/auth/mfa/confirm', { method: 'POST', body: JSON.stringify({ code: otp }) })
      setOtp('')
      setSecret('')
      setOpen(null)
      setMfaJustEnabled(true)
      await refresh()
    })
  }
  const generateCodes = (event: FormEvent) => {
    event.preventDefault()
    void run('codes', async () => {
      const result = await api<{ recovery_codes: string[] }>('/auth/mfa/recovery-codes', {
        method: 'POST', body: JSON.stringify({ current_password: codePassword, otp: codeOtp || null }),
      })
      setCodes(result.recovery_codes)
      setCodePassword('')
      setCodeOtp('')
    })
  }
  const copy = (what: string, text: string) => { void navigator.clipboard.writeText(text).then(() => setCopied(what)) }

  const name = user?.display_name || user?.email || ''
  const initials = name.split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('')
  const mfaOn = Boolean(user?.mfa_enabled)
  return (
    <div className="account-page">
      <section className="panel account-identity">
        <div className="account-avatar" aria-hidden="true">{initials}</div>
        <div><strong>{name}</strong><small>{user?.display_name ? `${user.email} · ` : ''}{user?.role === 'CTO' ? 'CTO' : user?.role === 'DEVELOPER' ? 'Developer' : 'Project Owner'}</small></div>
        <span className={`status ${mfaOn ? 'report-valid' : 'report-warning'}`}>{mfaOn ? 'Xác thực hai lớp đang bật' : 'Chưa bật xác thực hai lớp'}</span>
      </section>

      <section className="panel account-section">
        <header>
          <div><h3>Mật khẩu</h3><p>Dùng để đăng nhập. Tối thiểu 12 ký tự.</p></div>
          {open !== 'password' && <button className="button button-secondary" type="button" onClick={() => { setOpen('password'); setPasswordChanged(false) }}>Đổi mật khẩu</button>}
        </header>
        {passwordChanged && open !== 'password' && <p className="notice notice-success" role="status">Đã đổi mật khẩu.</p>}
        {open === 'password' && (
          <div className="account-body">
            <PasswordForm onChanged={() => { setPasswordChanged(true); setOpen(null) }} />
            <button className="text-button" type="button" onClick={() => setOpen(null)}>Hủy</button>
          </div>
        )}
      </section>

      <PageIntro k="account" />
      <AgentTokensSection />

      <section className="panel account-section">
        <header>
          <div><h3>Xác thực hai lớp</h3><p>Khi đăng nhập, ngoài mật khẩu bạn nhập thêm mã 6 số từ ứng dụng xác thực trên điện thoại (Google Authenticator, Microsoft Authenticator, 1Password…).</p></div>
          {!secret && open !== 'mfa' && <button className={mfaOn ? 'button button-secondary' : 'button button-primary'} type="button" disabled={busy} onClick={() => { setOpen('mfa'); setError(undefined) }}>{mfaOn ? 'Thiết lập lại' : 'Bật xác thực hai lớp'}</button>}
        </header>
        {mfaJustEnabled && <p className="notice notice-success" role="status">Đã bật xác thực hai lớp. Hãy tạo mã khôi phục ở mục bên dưới để không bị khóa ngoài khi mất điện thoại.</p>}
        {error?.at === 'mfa' && <ErrorNotice error={error.error} />}
        {open === 'mfa' && !secret && (
          <form className="account-body account-confirm" onSubmit={setup}>
            <input aria-label="Mật khẩu hiện tại" type="password" value={stepUpPassword} onChange={(e) => setStepUpPassword(e.target.value)} placeholder="Mật khẩu hiện tại" autoComplete="current-password" required />
            {mfaOn && <input aria-label="Mã MFA hiện tại" value={stepUpOtp} onChange={(e) => setStepUpOtp(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="Mã MFA hiện tại" inputMode="numeric" autoComplete="one-time-code" required />}
            <button className="button button-primary" type="submit" disabled={busy || !stepUpPassword || (mfaOn && stepUpOtp.length !== 6)}>Tiếp tục</button>
            <button className="text-button" type="button" onClick={() => { setOpen(null); setStepUpPassword(''); setStepUpOtp(''); setError(undefined) }}>Hủy</button>
          </form>
        )}
        {secret && (
          <ol className="account-body account-steps">
            <li>
              <strong>Thêm tài khoản trong ứng dụng xác thực</strong>
              <p>Chọn "nhập mã thiết lập" rồi nhập mã dưới đây. Không gửi mã này qua chat hoặc email.</p>
              <div className="account-secret"><code>{secret}</code><button className="button button-secondary button-small" type="button" onClick={() => copy('secret', secret)}>{copied === 'secret' ? 'Đã chép' : 'Chép mã'}</button></div>
            </li>
            <li>
              <strong>Nhập mã 6 số ứng dụng đang hiện</strong>
              <form className="account-confirm" onSubmit={confirm}>
                <input aria-label="Mã 6 chữ số" value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="000000" inputMode="numeric" autoComplete="one-time-code" required />
                <button className="button button-primary" type="submit" disabled={busy || otp.length !== 6}>Xác nhận và bật</button>
                <button className="text-button" type="button" onClick={() => { setSecret(''); setOtp(''); setError(undefined) }}>Hủy</button>
              </form>
            </li>
          </ol>
        )}
      </section>

      <section className="panel account-section">
        <header>
          <div><h3>Mã khôi phục</h3><p>{mfaOn ? 'Dùng thay mã 6 số khi bạn mất điện thoại. Mỗi mã dùng một lần; tạo bộ mới thì bộ cũ hết hiệu lực.' : 'Dùng thay mã 6 số khi bạn mất điện thoại. Cần bật xác thực hai lớp trước.'}</p></div>
        </header>
        {error?.at === 'codes' && <ErrorNotice error={error.error} />}
        {mfaOn && codes.length === 0 && (
          <form className="account-body account-confirm" onSubmit={generateCodes}>
            <input aria-label="Mật khẩu hiện tại để tạo mã khôi phục" type="password" value={codePassword} onChange={(e) => setCodePassword(e.target.value)} placeholder="Mật khẩu hiện tại" autoComplete="current-password" required />
            <input aria-label="Mã MFA hiện tại để tạo mã khôi phục" value={codeOtp} onChange={(e) => setCodeOtp(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="Mã MFA hiện tại" inputMode="numeric" autoComplete="one-time-code" required />
            <button className="button button-secondary" type="submit" disabled={busy || !codePassword || codeOtp.length !== 6}>Tạo bộ mã mới</button>
          </form>
        )}
        {codes.length > 0 && (
          <div className="account-body">
            <p className="notice notice-warn">Các mã này chỉ hiện một lần. Hãy lưu vào nơi an toàn trước khi rời trang.</p>
            <div className="account-codes">{codes.map((code) => <code key={code}>{code}</code>)}</div>
            <button className="button button-secondary button-small" type="button" onClick={() => copy('codes', codes.join('\n'))}>{copied === 'codes' ? 'Đã chép' : 'Chép tất cả'}</button>
          </div>
        )}
      </section>
    </div>
  )
}

const feedbackStatusWords: Record<string, string> = { PENDING: 'chờ Project Owner', ACCEPTED: 'đã nhận', REJECTED: 'chưa nhận' }
const feedbackTransportWords: Record<string, string> = { WEB: 'web', TELEGRAM: 'Telegram', AGENT: 'agent' }

function FeedbackFiles({ item }: { item: FeedbackItem }) {
  if (item.files.length === 0) return null
  return (
    <ul className="feedback-files">
      {item.files.map((file) => {
        const href = `/api/v1/feedback/${item.id}/files/${file.id}`
        const image = file.mime_type.startsWith('image/')
        return <li key={file.id}><a href={href} target="_blank" rel="noreferrer" title={file.name || file.mime_type}>{image ? <img src={href} alt={file.name || 'ảnh góp ý'} loading="lazy" /> : <span className="feedback-file-doc"><FileText size={14} /> {file.name || 'PDF'}</span>}</a></li>
      })}
    </ul>
  )
}

// Accept or reject one suggestion, from the approvals block or the Góp ý page (FR-FBK-03).
function FeedbackDecide({ row, onDone }: { row: FeedbackItem; onDone: () => void }) {
  const [rejecting, setRejecting] = useState(false)
  const [note, setNote] = useState('')
  const [error, setError] = useState<unknown>()
  const accept = useMutation({ mutationFn: () => api<FeedbackItem>(`/feedback/${row.id}/accept`, { method: 'POST', body: JSON.stringify({}) }), onMutate: () => setError(undefined), onSuccess: onDone, onError: setError })
  const reject = useMutation({ mutationFn: (why: string) => api<FeedbackItem>(`/feedback/${row.id}/reject`, { method: 'POST', body: JSON.stringify({ note: why }) }), onMutate: () => setError(undefined), onSuccess: onDone, onError: setError })
  const busy = accept.isPending || reject.isPending
  return (
    <>
      {error != null && <ErrorNotice error={error} />}
      {rejecting ? (
        <div className="feedback-reject">
          <textarea rows={2} aria-label="Lý do chưa nhận" value={note} onChange={(event) => setNote(event.target.value)} placeholder="Một dòng cho người góp ý: vì sao chưa làm, hoặc cần gì thêm" />
          <span className="waiting-actions">
            <button type="button" className="button button-primary button-small" disabled={note.trim().length < 3 || busy} onClick={() => reject.mutate(note.trim())}>Gửi lý do</button>
            <button type="button" className="text-button" onClick={() => { setRejecting(false); setNote('') }}>Thôi</button>
          </span>
        </div>
      ) : (
        <span className="waiting-actions">
          <button type="button" className="button button-primary button-small" disabled={busy} onClick={() => accept.mutate()}>Nhận thành Intake</button>
          <button type="button" className="button button-secondary button-small" disabled={busy} onClick={() => { setRejecting(true); setNote('') }}>Chưa nhận</button>
        </span>
      )}
    </>
  )
}

function FeedbackCard({ row, decide, onDone, linkIntake }: { row: FeedbackItem; decide: boolean; onDone: () => void; linkIntake: boolean }) {
  return (
    <li className={`feedback-card is-${row.status.toLowerCase()}`}>
      <div className="feedback-head"><strong>{row.member_name || 'nhân sự'}</strong><small>{row.project_name} · qua {feedbackTransportWords[row.transport] || row.transport} · {formatDate(row.created_at)} · <span className={`status feedback-status-${row.status.toLowerCase()}`}>{feedbackStatusWords[row.status] || row.status}</span></small></div>
      <p className="feedback-text">{row.text}</p>
      <FeedbackFiles item={row} />
      {row.status === 'ACCEPTED' && <p className="field-help">Đã thành yêu cầu {linkIntake && row.intake_id ? <Link to={`/intakes/${row.intake_id}`}>{row.intake_public_id}</Link> : row.intake_public_id || ''}{row.decided_by_name ? ` · ${row.decided_by_name}` : ''}{row.decided_at ? ` · ${formatDate(row.decided_at)}` : ''}{row.decision_note ? ` · ${row.decision_note}` : ''}</p>}
      {row.status === 'REJECTED' && <p className="field-help">Chưa nhận{row.decided_by_name ? ` (${row.decided_by_name})` : ''}: {row.decision_note}</p>}
      {decide && row.status === 'PENDING' && <FeedbackDecide row={row} onDone={onDone} />}
    </li>
  )
}

// The owner's part on the approvals page: suggestions waiting, read and decided before anything becomes a request (FR-FBK-02, FR-FBK-03).
function FeedbackQueue({ projectFilter }: { projectFilter: string }) {
  const queryClient = useQueryClient()
  const pending = useQuery({ queryKey: ['feedback', 'PENDING'], queryFn: () => api<FeedbackItem[]>('/feedback?status=PENDING&limit=100'), refetchInterval: 60_000 })
  const done = () => { void queryClient.invalidateQueries({ queryKey: ['feedback'] }); void queryClient.invalidateQueries({ queryKey: ['intakes'] }); void queryClient.invalidateQueries({ queryKey: ['alert-intakes'] }) }
  const rows = (pending.data || []).filter((row) => projectFilter === 'ALL' || row.project_id === projectFilter)
  if (pending.isLoading || rows.length === 0) return null
  return (
    <section className="panel feedback-queue" aria-label="Góp ý chờ nhận">
      <div className="panel-heading"><div><h2>Góp ý từ nhân sự <span className="status">{rows.length}</span></h2><p>Chưa phải yêu cầu: nhận thì thành Intake kênh "Góp ý" và AI đọc; chưa nhận thì ghi một dòng để người góp ý biết. Toàn bộ góp ý, kể cả đã quyết, ở trang <Link to="/gop-y">Góp ý</Link>.</p></div></div>
      <ul className="feedback-list">{rows.map((row) => <FeedbackCard key={row.id} row={row} decide onDone={done} linkIntake />)}</ul>
    </section>
  )
}

// --- Help inside the app (FR-UI-17): a hint next to a label, a page introduction read once, a one-screen guide ---

let hintSeq = 0

// ⓘ next to a label: opens on hover, keyboard focus, or a tap (tap again to close). The first open on a page is
// counted, so the week shows which hints people reach for.
function Hint({ k }: { k: HintKey }) {
  const hint = ALL_HINTS[k]
  const [open, setOpen] = useState(false)
  const [id] = useState(() => `hint-${++hintSeq}`)
  const counted = useRef(false)
  const anchor = useRef<HTMLButtonElement>(null)
  // The tip is placed on the viewport, so a column that scrolls or a narrow panel cannot cut it off.
  const [pos, setPos] = useState<{ top: number; left: number; width: number; above: boolean }>({ top: 0, left: 0, width: 300, above: true })
  const place = () => {
    const rect = anchor.current?.getBoundingClientRect()
    if (!rect) return
    const width = Math.min(300, window.innerWidth - 24)
    const left = Math.min(Math.max(12, rect.left + rect.width / 2 - width / 2), window.innerWidth - width - 12)
    const above = rect.top > 180
    setPos({ top: above ? rect.top - 8 : rect.bottom + 8, left, width, above })
  }
  const count = () => {
    place()
    if (counted.current) return
    counted.current = true
    void api(`/hints/${k}/opened`, { method: 'POST' }).catch(() => undefined)
  }
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    const onDown = (event: MouseEvent) => { if (!(event.target as HTMLElement).closest?.(`[data-hint="${id}"]`)) setOpen(false) }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('mousedown', onDown) }
  }, [open, id])
  return (
    <span className={open ? 'hint is-open' : 'hint'} data-hint={id} onMouseEnter={count}>
      <button ref={anchor} type="button" aria-label={`Giải thích: ${hint.label}`} aria-describedby={id} aria-expanded={open} onFocus={count} onClick={(event) => { event.preventDefault(); event.stopPropagation(); count(); setOpen((value) => !value) }}><Info size={13} aria-hidden="true" /></button>
      <span role="tooltip" id={id} className={pos.above ? 'hint-tip is-above' : 'hint-tip'} style={{ top: pos.top, left: pos.left, width: pos.width }}><strong>{hint.what}</strong><span>{hint.do}</span><Link to={`/huong-dan#${k}`} onClick={() => setOpen(false)}>Hướng dẫn nhanh</Link></span>
    </span>
  )
}

// Three lines at the top of a page the first time a person opens it; "Đã hiểu" is remembered on the server.
function PageIntro({ k }: { k: PageIntroKey }) {
  const queryClient = useQueryClient()
  const intro = ALL_INTROS[k]
  const read = useQuery({ queryKey: ['hints'], queryFn: () => api<{ dismissed: string[] }>('/hints'), staleTime: 300_000 })
  const dismiss = useMutation({
    mutationFn: () => api<{ dismissed: string[] }>(`/hints/page.${k}/dismiss`, { method: 'POST' }),
    onSuccess: (data) => queryClient.setQueryData(['hints'], data),
  })
  if (!read.data || read.data.dismissed.includes(`page.${k}`)) return null
  return (
    <aside className="page-intro" aria-label={intro.title}>
      <div>
        <strong>{intro.title}</strong>
        <ul>{intro.lines.map((line) => <li key={line}>{line}</li>)}</ul>
      </div>
      <div className="page-intro-actions">
        <Link to="/huong-dan" className="text-button">Hướng dẫn nhanh</Link>
        <button type="button" className="button button-secondary button-small" disabled={dismiss.isPending} onClick={() => dismiss.mutate()}>Đã hiểu</button>
      </div>
    </aside>
  )
}

// One screen for a new person: every page introduction and every hint, by page; the CTO also sees the week's counts.
function GuidePage() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const isCto = user?.role === 'CTO'
  const stats = useQuery({ queryKey: ['hint-stats'], queryFn: () => api<{ days: number; opened: { key: string; opens: number; people: number }[]; dismissed: { key: string; people: number }[] }>('/hints/stats?days=7'), enabled: isCto })
  const read = useQuery({ queryKey: ['hints'], queryFn: () => api<{ dismissed: string[] }>('/hints') })
  const reopen = useMutation({ mutationFn: (key: string) => api<void>(`/hints/${key}/dismiss`, { method: 'DELETE' }), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['hints'] }) } })
  const opens = new Map((stats.data?.opened || []).map((row) => [row.key, row]))
  const marketing = user?.mode === 'MARKETING'
  const pages = marketing ? [...Object.keys(POST_HINT_PAGES), 'account'] : [...Object.keys(HINT_PAGES), ...Object.keys(POST_HINT_PAGES)]
  const pageNames: Record<string, string> = { ...HINT_PAGES, ...POST_HINT_PAGES }
  useEffect(() => {
    const target = window.location.hash.slice(1)
    if (target) document.getElementById(`guide-${target}`)?.scrollIntoView({ block: 'center' })
  }, [])
  return (
    <>
      <PageHeader title="Hướng dẫn nhanh" description="Mỗi trang để làm gì, mỗi nút nghĩa là gì. Dấu ⓘ cạnh một nhãn trong app mở đúng lời giải thích ở đây." />
      {pages.map((page) => {
        const intro = ALL_INTROS[page]
        const rows = (Object.keys(ALL_HINTS) as HintKey[]).filter((key) => ALL_HINTS[key].page === page)
        const dismissed = read.data?.dismissed.includes(`page.${page}`)
        return (
          <section className="panel guide-page" key={page} id={`guide-page-${page}`}>
            <div className="panel-heading"><div><h2>{pageNames[page]}</h2><p>{intro.title}</p></div>
              {dismissed && <button type="button" className="text-button" disabled={reopen.isPending} onClick={() => reopen.mutate(`page.${page}`)}>Hiện lại lời giới thiệu trên trang</button>}</div>
            <ul className="guide-intro">{intro.lines.map((line) => <li key={line}>{line}</li>)}</ul>
            <dl className="guide-hints">
              {rows.map((key) => (
                <div key={key} id={`guide-${key}`}>
                  <dt>{ALL_HINTS[key].label}{isCto && opens.has(key) && <small> · mở {opens.get(key)!.opens} lần, {opens.get(key)!.people} người, 7 ngày</small>}</dt>
                  <dd><strong>{ALL_HINTS[key].what}</strong> {ALL_HINTS[key].do}</dd>
                </div>
              ))}
            </dl>
          </section>
        )
      })}
      {isCto && stats.data && <p className="field-help">Số lượt mở tính trong {stats.data.days} ngày, từ lịch sử "hint.opened". Hint không ai mở sau vài tuần là hint có thể bỏ; hint mở nhiều là chỗ giao diện chưa tự nói được.</p>}
    </>
  )
}

// --- Work tracked inside Intake: the board, a card's detail and discussion, the way to an Issue (FR-WRK-01..05, ADR-0066) ---

const workColumns: { value: WorkItemStatus; label: string; hint: string }[] = [
  { value: 'DISCUSS', label: 'Cần bàn', hint: 'Chưa quyết làm hay không: bàn ở phần thảo luận của thẻ.' },
  { value: 'READY', label: 'Sẵn sàng', hint: 'Đã rõ việc, chờ người nhận.' },
  { value: 'IN_PROGRESS', label: 'Đang làm', hint: 'Người được giao đang làm.' },
  { value: 'ACCEPTANCE', label: 'Chờ nghiệm thu', hint: 'Người làm báo xong, chờ Project Owner xem.' },
  { value: 'DONE', label: 'Xong', hint: 'Đã nghiệm thu, hoặc đã thành Issue.' },
  { value: 'CANCELLED', label: 'Bỏ', hint: 'Không làm nữa; phải ghi lý do.' },
]
const workColumnLabels = Object.fromEntries(workColumns.map((column) => [column.value, column.label])) as Record<WorkItemStatus, string>
const workEventWords: Record<string, string> = {
  'work.created': 'Tạo việc', 'work.moved': 'Chuyển cột', 'work.updated': 'Sửa', 'work.commented': 'Bình luận', 'work.cancelled': 'Bỏ',
  'work.issue_requested': 'Yêu cầu tạo Issue', 'work.issue_created': 'Đã thành Issue',
}
const workErrorWords: Record<string, string> = {
  STALE_VERSION: 'Việc này vừa được người khác đổi. Bảng đã tải lại, hãy thử lại.',
  NOTE_REQUIRED: 'Bỏ một việc thì phải ghi lý do.',
  WORK_LOCKED_BY_ISSUE: 'Việc này đã thành Issue, theo dõi tiếp ở GitLab/GitHub.',
  WORK_CLOSED: 'Việc đã Xong hoặc đã Bỏ; đưa về cột mở trước khi sửa.',
  MOVE_NOT_ALLOWED: 'Người làm chỉ chuyển việc của mình giữa Ý tưởng, Sẵn sàng, Đang làm và Chờ duyệt.',
  NOT_YOUR_WORK: 'Chỉ người được giao việc này mới chuyển được nó.',
  MEMBER_NOT_IN_PROJECT: 'Người này không thuộc dự án.',
  PROJECT_NOT_SOFTWARE: 'Chỉ dự án phần mềm mới có nơi giao việc để tạo Issue.',
  DELIVERY_SYNC_DISABLED: 'Dự án chưa bật đồng bộ sang GitLab/GitHub nên chưa tạo Issue được.',
  URL_INVALID: 'Dán địa chỉ http(s) đầy đủ.',
  TOO_MANY_LINKS: 'Một việc giữ tối đa 40 link.',
  CHANNEL_TEXT_TOO_LONG: 'Một bản kênh dài hơn kênh cho phép; cắt bớt rồi gửi duyệt lại.',
  TOPICS_LIMIT: 'Làm mới tối đa ba lần mỗi ngày; lượt tự động vẫn chạy theo lịch.',
  TOPIC_CLOSED: 'Chủ đề này đã bỏ.',
  NETWORK_NOT_OPEN: 'CTO chưa mở kênh này cho công cụ quét.',
  SCHEDULE_INVALID: 'Giờ hoặc ngày không hợp lệ, hoặc nhiều mốc hơn trần CTO đặt.',
  TARGET_INVALID: 'Dán địa chỉ http(s) đầy đủ của trang đích.',
  PILLARS_TOO_MANY: 'Tối đa sáu trụ.',
  PILLAR_DUPLICATE: 'Hai trụ trùng tên.',
  WATCH_NOT_FOR_PROJECT: 'Chỉ dự án marketing mới có phần này.',
  EVIDENCE_REQUIRED: 'Bước này cần một link (bản cắt, bài đã đăng) hoặc lý do vì sao không có.',
  STEPS_OPEN: 'Còn bước chưa xong; đóng các bước trước.',
  TEMPLATE_UNKNOWN: 'Mẫu quy trình không có.',
}
function workErrorText(error: unknown) {
  const code = error instanceof ApiError ? error.code : undefined
  return (code && workErrorWords[code]) || formatError(error)
}
function workEventText(row: WorkHistory) {
  const details = row.details || {}
  const column = (value: unknown) => (typeof value === 'string' && workColumnLabels[value as WorkItemStatus]) || String(value ?? '')
  if (row.event_type === 'work.moved' || row.event_type === 'work.cancelled') return `${column(details.from)} → ${column(details.to)}${details.note ? ` · ${details.note}` : ''}`
  if (row.event_type === 'work.issue_created') return `Issue #${String(details.external_id ?? '')}`
  if (row.event_type === 'work.updated') return Object.keys(details).map((key) => ({ title: 'tiêu đề', description: 'mô tả', priority: 'ưu tiên', member_id: 'người làm', due_date: 'hạn' })[key] || key).join(', ')
  if (row.event_type === 'work.created') return `${column(details.status)} · ${String(details.priority ?? '')}`
  return ''
}

function WorkSteps({ row, steps, onOpenStep }: { row: WorkItem; steps: WorkItem[]; onOpenStep: (id: string) => void }) {
  if (!row.template || steps.length === 0) return null
  return (
    <div className="work-steps" aria-label="Các bước">
      {steps.map((step) => <button type="button" key={step.id} className={`work-step-chip step-${step.status.toLowerCase()}`} title={`${step.step_label}: ${workColumnLabels[step.status]}${step.member_name ? ` · ${step.member_name}` : ''}`} onClick={() => onOpenStep(step.id)}>{step.step_label}</button>)}
      <span>{row.steps_done}/{row.steps_total}</span>
    </div>
  )
}

function WorkCard({ row, steps = [], onOpen, onOpenStep, onMove, canDrag, busy, postMode = false }: { row: WorkItem; steps?: WorkItem[]; onOpen: () => void; onOpenStep?: (id: string) => void; onMove: (status: WorkItemStatus) => void; canDrag: boolean; busy: boolean; postMode?: boolean }) {
  const overdue = row.due_date != null && row.status !== 'DONE' && row.status !== 'CANCELLED' && row.due_date < todayInPlanningTimezone()
  return (
    <article className={canDrag ? 'work-card movable' : 'work-card'} draggable={canDrag || undefined}
      onDragStart={(event) => { event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', row.id) }}>
      <div className="work-card-top">
        <button type="button" className="work-card-code" onClick={onOpen}>{row.code}</button>
        {postMode ? (row.urgent && <span className="post-urgent">Gấp</span>) : <PriorityBadge priority={row.priority} />}
        {row.link_count > 0 && <span className="work-card-comments" title={`${row.link_count} link`}><Link2 size={12} aria-hidden="true" />{row.link_count}</span>}
        {row.comment_count > 0 && <span className="work-card-comments" title={`${row.comment_count} bình luận`}><MessagesSquare size={12} aria-hidden="true" />{row.comment_count}</span>}
      </div>
      <button type="button" className="work-card-title" onClick={onOpen}>{row.title}</button>
      <div className="work-card-meta">
        {row.member_name ? <span>{row.member_name}</span> : <span className="muted">Chưa giao</span>}
        {postMode && <ChannelChips row={row} />}
        {postMode && row.campaign && <span className="post-campaign">{row.campaign}</span>}
        {!postMode && row.due_date && <span className={overdue ? 'work-due is-overdue' : 'work-due'}>{overdue ? 'Quá hạn ' : 'Hạn '}{formatDay(row.due_date)}</span>}
        {row.outcome === 'ISSUE' && row.issue_external_id && (row.issue_url
          ? <a className="ref-link" href={row.issue_url} target="_blank" rel="noreferrer">Issue #{row.issue_external_id}</a>
          : <span>Issue #{row.issue_external_id}</span>)}
        {row.issue_pending && <span className="work-pending">Đang tạo Issue</span>}
        {!postMode && row.intake_public_id && <Link to={`/intakes/${row.intake_id}`}>Intake {row.intake_public_id}</Link>}
      </div>
      {onOpenStep && <WorkSteps row={row} steps={steps} onOpenStep={onOpenStep} />}
      {row.outcome !== 'ISSUE' && (
        <select className="work-column-pick" aria-label={`Chuyển cột cho ${row.code}`} title="Chuyển cột" value={postMode ? postColumnOf(row.status) : row.status} disabled={busy} onChange={(event) => onMove(event.target.value as WorkItemStatus)}>
          {(postMode ? POST_COLUMNS : workColumns).map((column) => <option key={column.value} value={column.value}>{column.label}</option>)}
        </select>
      )}
    </article>
  )
}

// The six columns of one project. Cards move by drag or by the column picker on each card; dropping on Bỏ asks why.
// --- Posts for a marketing project (FR-MKT-01..06, ADR-0067): the words, the week grid, the review page, the rules ---

function useMode(): UiMode {
  const { user } = useAuth()
  return user?.mode === 'MARKETING' ? 'MARKETING' : 'FULL'
}
// The CTO sees everything, but a marketing project is still dressed as posts wherever it is opened.
function isPostProject(kind: string | null | undefined): boolean {
  return kind === 'NON_CODE'
}
const channelRulesQuery = { queryKey: ['channel-rules'], queryFn: () => api<ChannelRule[]>('/channel-rules'), staleTime: 300_000 }
const CHANNELS_KEY = 'intake.post.channels.'

function ChannelChips({ row }: { row: WorkItem }) {
  if (!row.channels || row.channels.length === 0) return row.channel ? <span className="chip-channel">{CHANNEL_SHORT[row.channel] || row.channel}</span> : null
  return (
    <span className="chip-channels">
      {row.channels.map((v) => {
        const day = dayOfStamp(v.publish_at)
        const late = v.status !== 'PUBLISHED' && day != null && day < todayInPlanningTimezone()
        return <span key={v.id} className={`chip-channel is-${v.status.toLowerCase()}${late ? ' is-late' : ''}`} title={`${CHANNEL_NAMES[v.channel] || v.channel}: ${CHANNEL_VERSION_LABELS[v.status]}${day ? `, ${formatDay(day)}` : ''}`}>{CHANNEL_SHORT[v.channel] || v.channel}{day ? ` ${day.slice(8, 10)}/${day.slice(5, 7)}` : ''}</span>
      })}
    </span>
  )
}

function bestHour(rules: ChannelRule[] | undefined, channel: string): string {
  const rule = (rules || []).find((r) => r.code === channel)
  return rule?.best_hours?.[0] || '09:00'
}

// Four moves to a post: a name, the channels, the day, the person. Everything else folds under "Thêm chi tiết".
function PostFormPanel({ projectId, members, campaigns, preset, onDone }: { projectId: string; members: WorkforceMember[]; campaigns: string[]; preset?: { channel?: string; day?: string }; onDone: () => void }) {
  const rules = useQuery(channelRulesQuery)
  const remembered = (() => { try { return JSON.parse(localStorage.getItem(CHANNELS_KEY + projectId) || '[]') as string[] } catch { return [] } })()
  const [title, setTitle] = useState('')
  const [channels, setChannels] = useState<string[]>(preset?.channel ? [preset.channel] : remembered.length > 0 ? remembered : ['FACEBOOK_PAGE'])
  const [day, setDay] = useState(preset?.day || todayInPlanningTimezone())
  const [memberId, setMemberId] = useState('')
  const [more, setMore] = useState(false)
  const [description, setDescription] = useState('')
  const [campaign, setCampaign] = useState('')
  const [format, setFormat] = useState('')
  const [urgent, setUrgent] = useState(false)
  const [videoSteps, setVideoSteps] = useState(false)
  const enabled = (rules.data || []).filter((r) => r.enabled)
  const toggle = (code: string) => setChannels((prev) => (prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]))
  const isVideo = format === 'VIDEO' || (!format && channels.some((c) => ['TIKTOK', 'YOUTUBE', 'REELS'].includes(c)))
  const create = useMutation({
    mutationFn: () => api<WorkItem>('/work', { method: 'POST', body: JSON.stringify({
      project: projectId, title: title.trim(), description: description.trim() || null, status: 'DISCUSS', member_id: memberId || null, campaign: campaign.trim() || null,
      urgent, format: format || null, template: isVideo && videoSteps ? 'VIDEO' : null,
      channels: channels.map((c) => ({ channel: c, publish_at: stampOf(day, bestHour(rules.data, c)) })),
    }) }),
    onSuccess: () => { try { localStorage.setItem(CHANNELS_KEY + projectId, JSON.stringify(channels)) } catch { /* no storage */ } onDone() },
  })
  return (
    <form className="panel-form post-form" onSubmit={(event) => { event.preventDefault(); if (title.trim() && channels.length > 0) create.mutate() }}>
      <label>Tên bài<input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={255} autoFocus required placeholder="Ví dụ: Ba điều đội nhỏ cần trước khi dùng AI" /></label>
      <div className="post-channels-pick" role="group" aria-label="Kênh">
        <span className="field-label">Kênh</span>
        <div className="chip-row">{(enabled.length > 0 ? enabled.map((r) => r.code) : CHANNEL_ORDER).map((code) => <button type="button" key={code} className={channels.includes(code) ? 'chip-pick is-on' : 'chip-pick'} aria-pressed={channels.includes(code)} onClick={() => toggle(code)}>{CHANNEL_SHORT[code] || code}</button>)}</div>
        {channels.length === 0 && <span className="field-help">Chọn ít nhất một kênh.</span>}
      </div>
      <div className="panel-form-row">
        <label>Ngày đăng<input type="date" value={day} onChange={(event) => setDay(event.target.value)} required /></label>
        <label>Người làm<select value={memberId} onChange={(event) => setMemberId(event.target.value)}><option value="">Chưa giao</option>{members.map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>
      </div>
      {channels.length > 1 && <p className="field-help">Mỗi kênh một bản với giờ tốt của kênh đó; đổi ngày từng kênh trong thẻ sau khi tạo.</p>}
      <button type="button" className="text-button" onClick={() => setMore(!more)}>{more ? 'Bớt chi tiết' : 'Thêm chi tiết'}</button>
      {more && (
        <>
          <label>Brief<textarea rows={4} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Nói gì, cho ai, muốn người đọc làm gì. Không dán tên hay tin nhắn khách." /></label>
          <div className="panel-form-row">
            <label>Chiến dịch<input list="post-campaigns" value={campaign} onChange={(event) => setCampaign(event.target.value)} maxLength={80} placeholder="Ví dụ: Ra mắt bản 5.0" /><datalist id="post-campaigns">{campaigns.map((name) => <option key={name} value={name} />)}</datalist></label>
            <label>Định dạng<select value={format} onChange={(event) => setFormat(event.target.value)}><option value="">Theo kênh</option>{Object.entries(FORMAT_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          </div>
          <label className="check-line"><input type="checkbox" checked={urgent} onChange={(event) => setUrgent(event.target.checked)} /> Gấp <Hint k="post.urgent" /></label>
          {isVideo && <label className="check-line"><input type="checkbox" checked={videoSteps} onChange={(event) => setVideoSteps(event.target.checked)} /> Theo sáu bước video (Brief, Kịch bản, Quay, Dựng, Duyệt, Đăng)</label>}
        </>
      )}
      {create.error != null && <ErrorNotice error={new Error(workErrorText(create.error))} />}
      <div className="panel-form-actions"><button type="submit" className="button button-primary" disabled={create.isPending || !title.trim() || channels.length === 0}>{create.isPending ? 'Đang lưu…' : POST_WORDS.add}</button></div>
    </form>
  )
}

// Many posts at once: one line each, one channel, spread across the week from a start day.
function BulkPostsPanel({ projectId, members, onDone }: { projectId: string; members: WorkforceMember[]; onDone: () => void }) {
  const rules = useQuery(channelRulesQuery)
  const [text, setText] = useState('')
  const [channel, setChannel] = useState('FACEBOOK_PAGE')
  const [start, setStart] = useState(todayInPlanningTimezone())
  const [memberId, setMemberId] = useState('')
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean).slice(0, 50)
  const rows = lines.map((line, index) => {
    // "Tên bài | X | 25/10" lets a line name its own channel or day; the rest follows the shared choices.
    const parts = line.split('|').map((part) => part.trim())
    const own = parts.slice(1).find((part) => CHANNEL_ORDER.includes(part.toUpperCase()))
    const dateText = parts.slice(1).find((part) => /^\d{1,2}\/\d{1,2}/.test(part))
    const day = dateText ? (parseDueText(dateText, start) || addDays(start, Math.floor(index * 7 / Math.max(lines.length, 1)))) : addDays(start, Math.floor(index * 7 / Math.max(lines.length, 1)))
    const code = own ? own.toUpperCase() : channel
    return { title: parts[0], channel: code, day, publish_at: stampOf(day, bestHour(rules.data, code)), member_id: memberId || null }
  })
  const create = useMutation({
    mutationFn: () => api<{ title: string; id?: string; code?: string; error?: string }[]>('/work/bulk', { method: 'POST', body: JSON.stringify({ project: projectId, rows: rows.map((row) => ({ title: row.title, channel: row.channel, publish_at: row.publish_at, member_id: row.member_id })) }) }),
    onSuccess: onDone,
  })
  return (
    <form className="panel-form" onSubmit={(event) => { event.preventDefault(); if (rows.length > 0) create.mutate() }}>
      <label><span>Mỗi dòng một bài <Hint k="post.add_many" /></span><textarea rows={8} value={text} onChange={(event) => setText(event.target.value)} placeholder={'Ba điều đội nhỏ cần trước khi dùng AI\nMột tuần của PO marketing | LinkedIn\nVideo giới thiệu bản 5.0 | TikTok | 24/10'} autoFocus /></label>
      <div className="panel-form-row">
        <label>Kênh chung<select value={channel} onChange={(event) => setChannel(event.target.value)}>{CHANNEL_ORDER.map((code) => <option key={code} value={code}>{CHANNEL_NAMES[code]}</option>)}</select></label>
        <label>Từ ngày<input type="date" value={start} onChange={(event) => setStart(event.target.value)} /></label>
      </div>
      <label>Người làm<select value={memberId} onChange={(event) => setMemberId(event.target.value)}><option value="">Chưa giao</option>{members.map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>
      {rows.length > 0 && (
        <ul className="bulk-preview">{rows.map((row, index) => <li key={index}><strong>{row.title}</strong><small>{CHANNEL_SHORT[row.channel] || row.channel} · {formatDay(row.day)}</small></li>)}</ul>
      )}
      {create.error != null && <ErrorNotice error={new Error(workErrorText(create.error))} />}
      <div className="panel-form-actions"><button type="submit" className="button button-primary" disabled={create.isPending || rows.length === 0}>{create.isPending ? 'Đang tạo…' : `Tạo ${rows.length} bài`}</button></div>
    </form>
  )
}

// The channels a post goes out on: a date each, "Đã đăng" with the link, one more channel, one fewer.
// How long a version is for its channel, the way the server counts it (FR-MKT-11): a link as the rule says.
function countChars(text: string, rule: ChannelRule | undefined): number {
  if (!rule || !text) return text.length
  if (rule.link_counts_chars && rule.link_chars > 0) return text.replace(/https?:\/\/\S+/g, 'x'.repeat(rule.link_chars)).length
  if (!rule.link_counts_chars) return text.replace(/https?:\/\/\S+/g, '').length
  return text.length
}

function PostChannelsBlock({ row, decides, mine, onChanged, onError }: { row: WorkDetail; decides: boolean; mine: boolean; onChanged: () => void; onError: (error: unknown) => void }) {
  const rules = useQuery(channelRulesQuery)
  const [publishing, setPublishing] = useState<string | null>(null)
  const [url, setUrl] = useState('')
  const [adding, setAdding] = useState(false)
  const [newChannel, setNewChannel] = useState('')
  const [newDay, setNewDay] = useState(todayInPlanningTimezone())
  // The words of one version, and the short link of one version (FR-MKT-11, FR-MKT-12).
  const [textFor, setTextFor] = useState<string | null>(null)
  const [textDraft, setTextDraft] = useState('')
  const [linkFor, setLinkFor] = useState<string | null>(null)
  const [target, setTarget] = useState('')
  const [copied, setCopied] = useState<string | null>(null)
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api<WorkDetail>(`/work/${row.id}/channels/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    onSuccess: () => { setPublishing(null); setUrl(''); setTextFor(null); onChanged() }, onError,
  })
  const issue = useMutation({
    mutationFn: ({ id, target_url }: { id: string; target_url: string }) => api<{ code: string; url: string }>(`/work/${row.id}/channels/${id}/link`, { method: 'POST', body: JSON.stringify({ target_url }) }),
    onSuccess: () => { setLinkFor(null); setTarget(''); onChanged() }, onError,
  })
  const copy = (id: string, text: string) => {
    const absolute = text.startsWith('/') ? `${window.location.origin}${text}` : text
    navigator.clipboard?.writeText(absolute).then(() => { setCopied(id); window.setTimeout(() => setCopied(null), 2000) }).catch(() => undefined)
  }
  const add = useMutation({
    mutationFn: () => api<WorkDetail>(`/work/${row.id}/channels`, { method: 'POST', body: JSON.stringify({ channel: newChannel, publish_at: stampOf(newDay, bestHour(rules.data, newChannel)) }) }),
    onSuccess: () => { setAdding(false); setNewChannel(''); onChanged() }, onError,
  })
  const remove = useMutation({ mutationFn: (id: string) => api<WorkDetail>(`/work/${row.id}/channels/${id}`, { method: 'DELETE' }), onSuccess: onChanged, onError })
  const canPublish = decides || mine
  const free = CHANNEL_ORDER.filter((code) => !row.channels.some((v) => v.channel === code))
  return (
    <section className="post-channels">
      <h3>Kênh và ngày đăng <Hint k="post.channels" /></h3>
      {row.channels.length === 0 && <p className="field-help">Chưa chọn kênh nào.</p>}
      <ul className="post-channel-list">
        {row.channels.map((v) => {
          const day = dayOfStamp(v.publish_at)
          const late = v.status !== 'PUBLISHED' && day != null && day < todayInPlanningTimezone()
          return (
            <li key={v.id} className={`is-${v.status.toLowerCase()}${late ? ' is-late' : ''}`}>
              <strong>{CHANNEL_NAMES[v.channel] || v.channel}</strong>
              {decides ? <input type="date" aria-label={`Ngày đăng ${CHANNEL_NAMES[v.channel]}`} value={day || ''} disabled={v.status === 'PUBLISHED' || patch.isPending} onChange={(event) => patch.mutate({ id: v.id, body: event.target.value ? { publish_at: stampOf(event.target.value, timeOfStamp(v.publish_at) || bestHour(rules.data, v.channel)) } : { clear_publish: true } })} />
                : <span>{day ? formatDay(day) : 'chưa có ngày'}</span>}
              {v.status === 'PUBLISHED'
                ? (v.published_url ? <a href={v.published_url} target="_blank" rel="noreferrer">Đã đăng <ArrowUpRight size={12} /></a> : <span className="muted">Đã đăng, không có link</span>)
                : <span className={late ? 'work-due is-overdue' : 'muted'}>{late ? 'Trễ' : CHANNEL_VERSION_LABELS[v.status]}{rules.data?.find((r) => r.code === v.channel)?.auto_publish ? ' · tự đăng khi đã duyệt' : ''}</span>}
              {v.status !== 'PUBLISHED' && canPublish && publishing !== v.id && <button type="button" className="button button-secondary button-small" onClick={() => { setPublishing(v.id); setUrl('') }}>{POST_WORDS.publish}</button>}
              {canPublish && textFor !== v.id && <button type="button" className="text-button" onClick={() => { setTextFor(v.id); setTextDraft(v.text || '') }}>{v.text ? `Chữ (${countChars(v.text, rules.data?.find((r) => r.code === v.channel)).toLocaleString('vi-VN')})` : 'Viết chữ'}</button>}
              {v.status !== 'PUBLISHED' && decides && <button type="button" className="icon-button" aria-label="Bỏ kênh" title="Bỏ kênh này" disabled={remove.isPending} onClick={() => remove.mutate(v.id)}><Trash2 size={13} /></button>}
              {publishing === v.id && (
                <form className="post-publish" onSubmit={(event) => { event.preventDefault(); patch.mutate({ id: v.id, body: { status: 'PUBLISHED', published_url: url.trim() || null } }) }}>
                  <input type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="Dán link bài đã đăng" aria-label="Link bài đã đăng" autoFocus />
                  <button type="submit" className="button button-primary button-small" disabled={patch.isPending}>{url.trim() ? 'Đã đăng' : POST_WORDS.noLinkQuestion}</button>
                  <button type="button" className="text-button" onClick={() => setPublishing(null)}>Thôi</button>
                </form>
              )}
              {textFor === v.id && (() => {
                const rule = rules.data?.find((r) => r.code === v.channel)
                const count = countChars(textDraft, rule)
                const hard = rule ? (rule.long_max_chars || rule.max_chars) : 0
                const over = rule ? count > hard : false
                const long = rule ? count > rule.max_chars && !over : false
                return (
                  <form className="post-text" onSubmit={(event) => { event.preventDefault(); if (!over) patch.mutate({ id: v.id, body: textDraft.trim() ? { text: textDraft } : { clear_text: true } }) }}>
                    <textarea rows={5} value={textDraft} onChange={(event) => setTextDraft(event.target.value)} placeholder={`Chữ đăng lên ${CHANNEL_NAMES[v.channel] || v.channel}`} aria-label={`Chữ của bản ${CHANNEL_NAMES[v.channel]}`} autoFocus />
                    <div className="post-text-foot">
                      <span className={`char-count${over ? ' is-over' : long ? ' is-long' : ''}`}>{rule ? POST_WORDS.charCount(count, rule.max_chars) : `${count} ký tự`}{long && rule?.long_max_chars ? ` · bài dài, tới ${rule.long_max_chars.toLocaleString('vi-VN')}` : ''}{over ? ' · vượt mức, không gửi duyệt được' : ''} <Hint k="post.text" /></span>
                      <span><button type="submit" className="button button-primary button-small" disabled={patch.isPending || over}>Lưu chữ</button><button type="button" className="text-button" onClick={() => setTextFor(null)}>Thôi</button></span>
                    </div>
                  </form>
                )
              })()}
              {v.short_link ? (
                <span className="post-short-link"><a href={v.short_link.url} target="_blank" rel="noreferrer">{v.short_link.url.replace(/^https?:\/\//, '')}</a> · {v.short_link.clicks} bấm <button type="button" className="text-button" onClick={() => copy(v.id, v.short_link!.url)}><Copy size={12} aria-hidden="true" /> {copied === v.id ? POST_WORDS.copied : POST_WORDS.copyLink}</button> <Hint k="post.short_link" /></span>
              ) : decides && linkFor !== v.id ? <button type="button" className="text-button" onClick={() => { setLinkFor(v.id); setTarget(row.links[0]?.url || '') }}><Link2 size={12} aria-hidden="true" /> {POST_WORDS.getLink}</button> : null}
              {linkFor === v.id && (
                <form className="post-publish" onSubmit={(event) => { event.preventDefault(); if (/^https?:\/\//i.test(target.trim())) issue.mutate({ id: v.id, target_url: target.trim() }) }}>
                  <input type="url" value={target} onChange={(event) => setTarget(event.target.value)} placeholder="Trang đích bài này dẫn tới (https://…)" aria-label="Trang đích" autoFocus />
                  <button type="submit" className="button button-primary button-small" disabled={issue.isPending || !/^https?:\/\//i.test(target.trim())}>{POST_WORDS.getLink}</button>
                  <button type="button" className="text-button" onClick={() => setLinkFor(null)}>Thôi</button>
                </form>
              )}
            </li>
          )
        })}
      </ul>
      {decides && free.length > 0 && (adding ? (
        <form className="post-add-channel" onSubmit={(event) => { event.preventDefault(); if (newChannel) add.mutate() }}>
          <select value={newChannel} onChange={(event) => setNewChannel(event.target.value)} aria-label="Kênh thêm"><option value="">Chọn kênh</option>{free.map((code) => <option key={code} value={code}>{CHANNEL_NAMES[code]}</option>)}</select>
          <input type="date" value={newDay} onChange={(event) => setNewDay(event.target.value)} aria-label="Ngày đăng kênh thêm" />
          <button type="submit" className="button button-secondary button-small" disabled={!newChannel || add.isPending}>Thêm</button>
          <button type="button" className="text-button" onClick={() => setAdding(false)}>Thôi</button>
        </form>
      ) : <button type="button" className="text-button" onClick={() => setAdding(true)}><Plus size={13} /> Thêm kênh</button>)}
    </section>
  )
}

// The one or two buttons a post needs next, in the team's words.
function PostActions({ row, decides, mine, onMove }: { row: WorkDetail; decides: boolean; mine: boolean; onMove: (status: WorkItemStatus) => void }) {
  const status = postColumnOf(row.status)
  return (
    <div className="post-actions">
      {status === 'DISCUSS' && (decides || mine) && <button type="button" className="button button-primary button-small" onClick={() => onMove('IN_PROGRESS')}>{POST_WORDS.start}</button>}
      {status === 'IN_PROGRESS' && (decides || mine) && <button type="button" className="button button-primary button-small" onClick={() => onMove('ACCEPTANCE')}>{POST_WORDS.submit}</button>}
      {status === 'ACCEPTANCE' && decides && <><button type="button" className="button button-primary button-small" onClick={() => onMove('APPROVED')}>{POST_WORDS.approve}</button><button type="button" className="button button-secondary button-small" onClick={() => onMove('IN_PROGRESS')}>{POST_WORDS.sendBack}</button></>}
      {status === 'ACCEPTANCE' && !decides && <span className="muted">Đang chờ Project Owner duyệt</span>}
      {status === 'APPROVED' && <span className="muted">Đã duyệt: bấm "Đã đăng" ở từng kênh khi bài đã lên</span>}
      {status === 'APPROVED' && decides && <button type="button" className="text-button" onClick={() => onMove('IN_PROGRESS')}>Về Đang làm</button>}
      {status === 'CANCELLED' && decides && <button type="button" className="button button-secondary button-small" onClick={() => onMove('DISCUSS')}>{POST_WORDS.undrop}</button>}
      {status !== 'DONE' && status !== 'CANCELLED' && decides && <button type="button" className="text-button post-drop" onClick={() => onMove('CANCELLED')}>{POST_WORDS.drop}</button>}
    </div>
  )
}

// --- Listening for a marketing project (FR-MKT-08..12, ADR-0068): hot topics on Tuần này, the sources page, the CTO's networks ---

const topicsQuery = (projectId: string) => ({ queryKey: ['watch-topics', projectId], queryFn: () => api<WatchTopics>(`/watch-topics?project=${projectId}`) })
const letterOf = (index: number) => String.fromCharCode(65 + index)

// The block above the week: what the watched sources are talking about, scored by rule and summed up by AI; the owner picks.
function HotTopicsBlock({ projectId, decides, onOpenTopic, onOpenWork }: { projectId: string; decides: boolean; onOpenTopic: (id: string) => void; onOpenWork: (id: string) => void }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(() => { try { return localStorage.getItem('hot-topics-open') !== '0' } catch { return true } })
  // After "Làm mới" the list is asked again every few seconds until a new build lands.
  const [waitingSince, setWaitingSince] = useState<string | null | undefined>(undefined)
  const [error, setError] = useState<unknown>()
  const topics = useQuery({
    ...topicsQuery(projectId), enabled: Boolean(projectId),
    refetchInterval: (query) => { const data = query.state.data as WatchTopics | undefined; return waitingSince !== undefined && data?.built_at === waitingSince ? 3000 : 120_000 },
  })
  useEffect(() => { if (waitingSince !== undefined && topics.data && topics.data.built_at !== waitingSince) setWaitingSince(undefined) }, [topics.data, waitingSince])
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['watch-topics', projectId] }); void queryClient.invalidateQueries({ queryKey: ['work'] }) }
  const rebuild = useMutation({
    mutationFn: () => api<{ status: string; refresh_left: number }>(`/watch-topics/refresh?project=${projectId}`, { method: 'POST' }),
    onMutate: () => { setError(undefined); setWaitingSince(topics.data?.built_at ?? null) }, onSuccess: refresh, onError: (err) => { setWaitingSince(undefined); setError(err) },
  })
  const toPost = useMutation({
    mutationFn: (id: string) => api<WorkDetail>(`/watch-topics/${id}/post?project=${projectId}`, { method: 'POST', body: JSON.stringify({ mode: 'post' }) }),
    onMutate: () => setError(undefined), onSuccess: (made) => { refresh(); onOpenWork(made.id) }, onError: setError,
  })
  const drop = useMutation({ mutationFn: (id: string) => api<void>(`/watch-topics/${id}?project=${projectId}`, { method: 'DELETE' }), onMutate: () => setError(undefined), onSuccess: refresh, onError: setError })
  const toggle = () => { try { localStorage.setItem('hot-topics-open', open ? '0' : '1') } catch { /* no memory in a private window */ } setOpen(!open) }
  const data = topics.data
  if (!data) return null
  if (!data.has_sources) return decides ? <p className="hot-topics-nudge"><Sparkles size={14} aria-hidden="true" /> Chưa có nguồn theo dõi, nên chưa có {POST_WORDS.hotTopics.toLowerCase()}. <Link to={`/nguon?project=${projectId}`}>Khai nguồn và trụ</Link> để công cụ quét bắt đầu.</p> : null
  const fresh = data.topics.filter((row) => row.state === 'NEW')
  const used = data.topics.filter((row) => row.state === 'USED')
  const waiting = waitingSince !== undefined
  return (
    <section className="panel hot-topics" aria-label={POST_WORDS.hotTopics}>
      <div className="hot-topics-head">
        <div><h2>{POST_WORDS.hotTopics} <Hint k="week.hot_topics" /></h2><p className="muted">{POST_WORDS.keptThisWeek(data.kept_this_week)}{data.built_at ? ` · cập nhật ${formatMoment(data.built_at)}` : ' · chưa chạy lần nào'} · AI chạy lúc {data.schedule.times.join(', ')}</p></div>
        <div className="hot-topics-actions">
          {decides && <span className="with-hint"><button type="button" className="button button-secondary button-small" disabled={waiting || data.refresh_left === 0 || rebuild.isPending} onClick={() => rebuild.mutate()}>{waiting ? <><span className="spinner" aria-hidden="true" /> AI đang tóm…</> : <><RefreshCw size={13} aria-hidden="true" /> {POST_WORDS.refreshTopics} (còn {data.refresh_left})</>}</button><Hint k="week.refresh_topics" /></span>}
          <button type="button" className="text-button" onClick={toggle}>{open ? 'Thu gọn' : `Mở (${fresh.length})`}</button>
        </div>
      </div>
      {error != null && <ErrorNotice error={new Error(workErrorText(error))} />}
      {open && (fresh.length === 0 ? <p className="hot-topics-empty">{POST_WORDS.topicsEmpty} {decides && <Link to={`/nguon?project=${projectId}`}>{POST_WORDS.sourcesPage}</Link>}</p> : (
        <ul className="hot-topic-list">
          {fresh.map((topic) => (
            <li key={topic.id} className="hot-topic">
              <div className="hot-topic-main">
                <button type="button" className="hot-topic-title" onClick={() => onOpenTopic(topic.id)}>{topic.title}</button>
                <span className="hot-topic-meta">{topic.pillar && <span className="chip-pillar">{topic.pillar}</span>}<span className="hot-topic-score">điểm {topic.score} · {topic.sources} nguồn{topic.ai_written ? '' : ' · AI chưa tóm'}</span></span>
                {topic.why && <p>{topic.why}</p>}
                <span className="hot-topic-links">{topic.signals.slice(0, 3).map((signal) => <a key={signal.id} href={signal.url} target="_blank" rel="noopener noreferrer">{signal.host}</a>)}</span>
              </div>
              {decides && <div className="hot-topic-actions"><button type="button" className="button button-primary button-small" disabled={toPost.isPending} onClick={() => toPost.mutate(topic.id)}>{POST_WORDS.toPost}</button><button type="button" className="text-button" disabled={drop.isPending} onClick={() => drop.mutate(topic.id)}>{POST_WORDS.dropTopic}</button></div>}
            </li>
          ))}
        </ul>
      ))}
      {open && used.length > 0 && <p className="hot-topics-used">Đã thành bài: {used.map((topic, index) => <span key={topic.id}>{index > 0 ? ' · ' : ''}<button type="button" className="text-button" onClick={() => topic.work_id && onOpenWork(topic.work_id)}>{topic.title}</button></span>)}</p>}
    </section>
  )
}

// The analysis of one topic, and the owner's decision: a post, a series across the pillar's channels, or nothing.
function TopicPanel({ projectId, topicId, decides, members, week, onOpenWork, onDone }: { projectId: string; topicId: string; decides: boolean; members: WorkforceMember[]; week: string; onOpenWork: (id: string) => void; onDone: () => void }) {
  const queryClient = useQueryClient()
  const topics = useQuery(topicsQuery(projectId))
  const [angle, setAngle] = useState<number | null>(null)
  const [memberId, setMemberId] = useState('')
  const [error, setError] = useState<unknown>()
  const invalidate = () => { void queryClient.invalidateQueries({ queryKey: ['watch-topics', projectId] }); void queryClient.invalidateQueries({ queryKey: ['work'] }) }
  const make = useMutation({
    mutationFn: (mode: 'post' | 'series') => api<WorkDetail>(`/watch-topics/${topicId}/post?project=${projectId}`, { method: 'POST', body: JSON.stringify({ mode, angle, member_id: memberId || null, week }) }),
    onMutate: () => setError(undefined), onSuccess: (made) => { invalidate(); onOpenWork(made.id) }, onError: setError,
  })
  const drop = useMutation({ mutationFn: () => api<void>(`/watch-topics/${topicId}?project=${projectId}`, { method: 'DELETE' }), onMutate: () => setError(undefined), onSuccess: () => { invalidate(); onDone() }, onError: setError })
  const topic = topics.data?.topics.find((row) => row.id === topicId)
  if (topics.isLoading) return <LoadingBlock />
  if (!topic) return <ErrorNotice error={new Error('Chủ đề này không còn trong tuần.')} />
  return (
    <div className="topic-panel">
      <h2 className="work-detail-title">{topic.title}</h2>
      <p className="hot-topic-meta">{topic.pillar && <span className="chip-pillar">{topic.pillar}</span>}<span className="hot-topic-score">điểm {topic.score} · {topic.sources} nguồn · {topic.ai_written ? 'AI đã tóm' : 'theo luật, AI chưa tóm'}</span> <Hint k="week.topic_panel" /></p>
      <section className="topic-ai"><h3>Vì sao đáng nói</h3><p>{topic.why || 'Chưa có.'}</p></section>
      {topic.angles.length > 0 && (
        <section className="topic-ai"><h3>Góc đề xuất <small>chọn một, hoặc giữ tiêu đề</small></h3>
          <div className="topic-angles">{topic.angles.map((text, index) => <button key={text} type="button" className={angle === index ? 'button button-secondary button-small is-posted' : 'button button-secondary button-small'} aria-pressed={angle === index} onClick={() => setAngle(angle === index ? null : index)}>{letterOf(index)} · {text}</button>)}</div>
        </section>
      )}
      {(topic.channels.length > 0 || topic.caution) && (
        <section className="topic-ai"><h3>Kênh gợi ý và lưu ý</h3>
          {topic.channels.length > 0 && <p>{topic.channels.map((code) => CHANNEL_NAMES[code] || code).join(', ')}</p>}
          {topic.caution && <p className="plan-warning"><TriangleAlert size={14} aria-hidden="true" /> {topic.caution}</p>}
        </section>
      )}
      <section><h3>Nguồn <small>{topic.signals.length}</small></h3>
        <ul className="topic-sources">{topic.signals.map((signal) => <li key={signal.id}><a href={signal.url} target="_blank" rel="noopener noreferrer">{signal.title}</a><small>{signal.host}{signal.published_at ? ` · ${formatDay(signal.published_at.slice(0, 10))}` : ''}{signal.via === 'scrape' ? ' · qua dịch vụ cào' : ''}</small></li>)}</ul>
      </section>
      {decides && topic.state === 'NEW' && (
        <section className="topic-decide">
          <h3>Quyết định</h3>
          <label>Giao cho<select value={memberId} onChange={(event) => setMemberId(event.target.value)}><option value="">Chưa giao</option>{members.map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>
          <div className="topic-decide-actions">
            <button type="button" className="button button-primary button-small" disabled={make.isPending} onClick={() => make.mutate('post')}>{POST_WORDS.toPost}{angle != null ? ` (góc ${letterOf(angle)})` : ''}</button>
            <button type="button" className="button button-secondary button-small" disabled={make.isPending} onClick={() => make.mutate('series')}>{POST_WORDS.toSeries}</button>
            <button type="button" className="text-button" disabled={drop.isPending} onClick={() => drop.mutate()}>{POST_WORDS.dropTopic}</button>
          </div>
          <p className="field-help">Thành chuỗi tạo một bài gốc kèm bản cho từng kênh ưu tiên của trụ, ngày theo giờ tốt của kênh trong tuần đang xem; bản tiếng Anh lệch một ngày.</p>
        </section>
      )}
      {topic.state === 'USED' && topic.work_id && <p className="notice notice-info">Đã thành bài. <button type="button" className="text-button" onClick={() => onOpenWork(topic.work_id!)}>Mở bài</button></p>}
      {error != null && <ErrorNotice error={new Error(workErrorText(error))} />}
    </div>
  )
}

const EMPTY_PILLAR: Pillar = { name: '', description: '', audience: '', channels: [], share_pct: 0, keywords: [], samples: [], avoid: '' }

// The pillars as the owner writes them: the frame every AI run reads (FR-MKT-08).
function PillarsEditor({ code, decides }: { code: string; decides: boolean }) {
  const queryClient = useQueryClient()
  const base = `/projects/${code}/watch`
  const pillars = useQuery({ queryKey: ['watch-pillars', code], queryFn: () => api<Pillar[]>(`${base}/pillars`) })
  const keywords = useQuery({
    queryKey: ['watch-keywords', base, 'content'], queryFn: () => api<PillarKeywords>(`${base}/keywords`),
    refetchInterval: (query) => ((query.state.data as PillarKeywords | undefined)?.request?.status === 'PENDING' ? 2000 : false),
  })
  const [draft, setDraft] = useState<Pillar[]>()
  const [openRow, setOpenRow] = useState<number | null>(null)
  const [typed, setTyped] = useState<Record<number, string>>({})
  const [error, setError] = useState<unknown>()
  const [saved, setSaved] = useState(false)
  useEffect(() => { setDraft(undefined) }, [code])
  useEffect(() => { if (pillars.data && !draft) setDraft(pillars.data) }, [pillars.data, draft])
  const save = useMutation({
    mutationFn: (rows: Pillar[]) => api<Pillar[]>(`${base}/pillars`, { method: 'PUT', body: JSON.stringify({ pillars: rows }) }),
    onMutate: () => setError(undefined),
    onSuccess: (rows) => { queryClient.setQueryData(['watch-pillars', code], rows); setDraft(rows); setSaved(true); window.setTimeout(() => setSaved(false), 2500); void queryClient.invalidateQueries({ queryKey: ['watch-keywords', base, 'content'] }); void queryClient.invalidateQueries({ queryKey: ['watch-topics'] }) },
    onError: setError,
  })
  const suggest = useMutation({ mutationFn: () => api(`${base}/keywords/suggest`, { method: 'POST' }), onMutate: () => setError(undefined), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['watch-keywords', base, 'content'] }) }, onError: setError })
  if (pillars.error != null) return <section className="panel voice-form"><ErrorNotice error={pillars.error} onRetry={() => { void pillars.refetch() }} /></section>
  if (!draft) return <section className="panel voice-form"><LoadingBlock /></section>
  const list = draft
  const dirty = JSON.stringify(list) !== JSON.stringify(pillars.data)
  const total = list.reduce((sum, row) => sum + (row.share_pct || 0), 0)
  const thinking = keywords.data?.request?.status === 'PENDING' || suggest.isPending
  const update = (index: number, patch: Partial<Pillar>) => setDraft(list.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  const addTerm = (index: number, raw: string) => {
    const text = raw.trim().replace(/\s+/g, ' ')
    const row = list[index]
    if (!text || row.keywords.length >= 12 || row.keywords.some((term) => term.text.toLowerCase() === text.toLowerCase())) return
    update(index, { keywords: [...row.keywords, { text, kind: text.startsWith('#') ? 'hashtag' : 'keyword', priority: 'normal' }] })
  }
  return (
    <section className="panel voice-form" aria-label={POST_WORDS.pillars}>
      <div className="panel-heading">
        <div><h2>{POST_WORDS.pillars} <Hint k="sources.pillars" /></h2><p className="muted">{list.length}/6 trụ · tổng tỉ lệ {total}%</p></div>
        {decides && <div className="rhythm-actions">
          <button type="button" className="button button-secondary button-small" disabled={thinking || list.length === 0 || dirty} title={dirty ? 'Lưu trụ trước' : undefined} onClick={() => suggest.mutate()}>{thinking ? <><span className="spinner" aria-hidden="true" /> AI đang gợi ý…</> : <><Sparkles size={14} aria-hidden="true" /> AI gợi ý từ khóa</>}</button>
          <button type="button" className="button button-primary button-small" disabled={!dirty || save.isPending} onClick={() => save.mutate(list)}>{save.isPending ? 'Đang lưu…' : saved && !dirty ? 'Đã lưu' : 'Lưu trụ'}</button>
        </div>}
      </div>
      {error != null && <ErrorNotice error={new Error(workErrorText(error))} />}
      {list.length === 0 && <p className="field-help">Chưa có trụ nào. Thêm trụ đầu tiên: tên, người đọc, kênh, tỉ lệ, vài từ khóa. AI không tóm gì khi chưa có trụ.</p>}
      <div className="pillar-list">
        {list.map((row, index) => {
          const offered = (keywords.data?.suggested[row.name] || []).filter((word) => !row.keywords.some((term) => term.text.toLowerCase() === word.toLowerCase()))
          return (
            <div className="pillar-row" key={index}>
              <div className="pillar-head">
                <input value={row.name} maxLength={60} placeholder="Tên trụ" aria-label="Tên trụ" disabled={!decides} onChange={(event) => update(index, { name: event.target.value })} />
                <input value={row.audience} maxLength={120} placeholder="Người đọc" aria-label="Người đọc" disabled={!decides} onChange={(event) => update(index, { audience: event.target.value })} />
                <label className="pillar-share">Tỉ lệ<input type="number" min={0} max={100} value={row.share_pct} aria-label="Tỉ lệ tuần" disabled={!decides} onChange={(event) => update(index, { share_pct: Number(event.target.value) || 0 })} />%</label>
                <button type="button" className="text-button" onClick={() => setOpenRow(openRow === index ? null : index)}>{openRow === index ? 'Thu gọn' : 'Chi tiết'}</button>
                {decides && <button type="button" className="icon-button" aria-label="Bỏ trụ" title="Bỏ trụ" onClick={() => setDraft(list.filter((_, i) => i !== index))}><Trash2 size={14} /></button>}
              </div>
              <div className="pillar-channels" aria-label="Kênh ưu tiên">{CHANNEL_ORDER.map((channel) => <button key={channel} type="button" className={row.channels.includes(channel) ? 'pillar-channel is-on' : 'pillar-channel'} aria-pressed={row.channels.includes(channel)} disabled={!decides} onClick={() => update(index, { channels: row.channels.includes(channel) ? row.channels.filter((c) => c !== channel) : [...row.channels, channel] })}>{CHANNEL_SHORT[channel]}</button>)}</div>
              <div className="glossary-terms">
                {row.keywords.map((term) => (
                  <span className={term.priority === 'high' ? 'chip is-high' : 'chip'} key={term.text}>
                    <button type="button" className="chip-label" title={term.priority === 'high' ? 'Ưu tiên quét trước; bấm để bỏ ưu tiên' : 'Bấm để ưu tiên quét trước'} disabled={!decides} onClick={() => update(index, { keywords: row.keywords.map((item) => (item === term ? { ...item, priority: item.priority === 'high' ? 'normal' : 'high' } : item)) })}>{term.priority === 'high' && <Star size={12} aria-hidden="true" />}{term.text}</button>
                    {decides && <button type="button" aria-label={`Bỏ ${term.text}`} onClick={() => update(index, { keywords: row.keywords.filter((item) => item !== term) })}><X size={13} /></button>}
                  </span>
                ))}
                {row.keywords.length === 0 && <span className="muted">Chưa có từ khóa: công cụ quét không tìm gì cho trụ này.</span>}
              </div>
              {offered.length > 0 && decides && <div className="keyword-offered"><span>AI gợi ý, bấm để giữ:</span>{offered.map((word) => <button type="button" key={word} className="chip chip-offer" disabled={row.keywords.length >= 12} onClick={() => addTerm(index, word)}><Plus size={12} aria-hidden="true" /> {word}</button>)}</div>}
              {decides && row.keywords.length < 12 && (
                <form className="voice-add" onSubmit={(event) => { event.preventDefault(); addTerm(index, typed[index] || ''); setTyped({ ...typed, [index]: '' }) }}>
                  <input value={typed[index] || ''} maxLength={60} placeholder="Từ khóa, hoặc #hashtag" aria-label="Từ khóa mới" onChange={(event) => setTyped({ ...typed, [index]: event.target.value })} />
                  <button className="button button-secondary button-small" disabled={!(typed[index] || '').trim()}>Thêm</button>
                </form>
              )}
              {openRow === index && (
                <div className="pillar-more">
                  <label>Một câu mô tả<input value={row.description} maxLength={200} disabled={!decides} placeholder="Trụ này nói về gì, cho ai" onChange={(event) => update(index, { description: event.target.value })} /></label>
                  <label>Điều tránh<input value={row.avoid} maxLength={300} disabled={!decides} placeholder="Không hứa kết quả, không nêu tên đối thủ…" onChange={(event) => update(index, { avoid: event.target.value })} /></label>
                  <label>Bài mẫu (tối đa 2 link, cách nhau bằng dấu cách)<input value={row.samples.map((sample) => sample.url).join(' ')} disabled={!decides} placeholder="https://… https://…" onChange={(event) => update(index, { samples: event.target.value.split(/\s+/).filter(Boolean).slice(0, 2).map((url) => ({ title: null, url })) })} /></label>
                </div>
              )}
            </div>
          )
        })}
      </div>
      {decides && list.length < 6 && <button type="button" className="text-button" onClick={() => { setDraft([...list, { ...EMPTY_PILLAR }]); setOpenRow(list.length) }}><Plus size={13} /> Thêm trụ</button>}
      {keywords.data?.request?.status === 'FAILED' && !thinking && <p className="plan-warning"><TriangleAlert size={14} aria-hidden="true" /> AI chưa gợi ý được lúc này.</p>}
    </section>
  )
}

// The addresses a marketing project watches: one list, no tracks to choose.
function ProjectSourcesPanel({ code, decides }: { code: string; decides: boolean }) {
  const queryClient = useQueryClient()
  const base = `/projects/${code}/watch`
  const [url, setUrl] = useState('')
  const [removing, setRemoving] = useState<WatchSource>()
  const [error, setError] = useState<unknown>()
  const sources = useQuery({ queryKey: ['watch-sources', code], queryFn: () => api<WatchSource[]>(`${base}/sources`) })
  const demand = useQuery({ queryKey: ['watch-demand', code], queryFn: () => api<WatchDemand>(`${base}/demand`) })
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['watch-sources', code] }); void queryClient.invalidateQueries({ queryKey: ['watch-topics'] }) }
  const add = useMutation({ mutationFn: () => api<WatchSource>(`${base}/sources`, { method: 'POST', body: JSON.stringify({ url: url.trim(), track: 'content' }) }), onMutate: () => setError(undefined), onSuccess: () => { setUrl(''); refresh() }, onError: setError })
  const change = useMutation({ mutationFn: (input: { id: string; body: object }) => api<WatchSource>(`${base}/sources/${input.id}`, { method: 'PATCH', body: JSON.stringify(input.body) }), onMutate: () => setError(undefined), onSuccess: refresh, onError: setError })
  const remove = useMutation({ mutationFn: (id: string) => api(`${base}/sources/${id}`, { method: 'DELETE' }), onSuccess: () => { setRemoving(undefined); refresh() } })
  const list = sources.data || []
  return (
    <section className="panel voice-form" aria-label="Nguồn theo dõi">
      {removing && (
        <ConfirmDialog title="Bỏ nguồn này?" confirmLabel="Bỏ nguồn" busy={remove.isPending} error={remove.error ?? undefined} onConfirm={() => remove.mutate(removing.id)} onCancel={() => setRemoving(undefined)}>
          <p><strong>{removing.label}</strong><br />{removing.url}</p>
        </ConfirmDialog>
      )}
      <div className="panel-heading"><div><h2>Nguồn theo dõi</h2><p className="muted">{list.filter((row) => row.active).length} đang bật · {list.length}/80{demand.data && demand.data.wanted_per_week > 0 ? ` · tuần này đã nhận ${demand.data.received}/${demand.data.wanted_per_week}` : ''}</p></div></div>
      {decides && (
        <form className="source-add" onSubmit={(event) => { event.preventDefault(); if (url.trim()) add.mutate() }}>
          <input type="url" value={url} maxLength={500} onChange={(event) => setUrl(event.target.value)} placeholder="https://… trang web, RSS, trang Facebook, kênh YouTube" aria-label="Địa chỉ nguồn mới" />
          <button className="button button-primary" disabled={!url.trim() || add.isPending}>{add.isPending ? 'Đang thêm…' : 'Thêm nguồn'}</button>
        </form>
      )}
      {error != null && <ErrorNotice error={new Error(workErrorText(error))} />}
      {sources.error != null && <ErrorNotice error={sources.error} onRetry={() => { void sources.refetch() }} />}
      {list.length === 0 ? <p className="field-help">Chưa có nguồn nào. Dán một địa chỉ ở trên; loại nguồn được nhận ra từ địa chỉ. Google Trends: https://trends.google.com/trending/rss?geo=VN</p> : (
        <ul className="source-list source-list-plain">
          {list.map((row) => (
            <li key={row.id} className={row.active ? undefined : 'is-off'}>
              <span className="status source-kind">{watchKinds[row.kind]}</span>
              <div className="source-main"><strong>{row.label}</strong><a href={row.url} target="_blank" rel="noreferrer noopener">{row.url}</a></div>
              {decides && <button type="button" className={row.active ? 'button button-secondary button-small is-posted' : 'button button-secondary button-small'} aria-pressed={row.active} disabled={change.isPending} onClick={() => change.mutate({ id: row.id, body: { active: !row.active } })}>{row.active ? 'Đang bật' : 'Đã tắt'}</button>}
              {decides && <button type="button" className="icon-button" aria-label={`Bỏ nguồn ${row.label}`} title="Bỏ nguồn" onClick={() => { remove.reset(); setRemoving(row) }}><Trash2 size={14} /></button>}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

const networkWords: Record<string, string> = { api: 'quét được', scrape: 'qua dịch vụ cào', none: 'chưa có cách' }

// Which networks this project listens on, among those the CTO opened.
function NetworksPanel({ code, decides }: { code: string; decides: boolean }) {
  const queryClient = useQueryClient()
  const base = `/projects/${code}/watch`
  const platforms = useQuery({ queryKey: ['watch-platforms'], queryFn: () => api<WatchPlatform[]>('/settings/watch-platforms'), staleTime: 300_000 })
  const settings = useQuery({ queryKey: ['watch-settings', code], queryFn: () => api<WatchSettings>(`${base}/settings`) })
  const [error, setError] = useState<unknown>()
  const save = useMutation({ mutationFn: (networks: string[]) => api<WatchSettings>(`${base}/settings`, { method: 'PUT', body: JSON.stringify({ networks }) }), onMutate: () => setError(undefined), onSuccess: (next) => queryClient.setQueryData(['watch-settings', code], next), onError: setError })
  if (!platforms.data || !settings.data) return <section className="panel voice-form"><LoadingBlock /></section>
  const on = settings.data.networks
  return (
    <section className="panel voice-form" aria-label={POST_WORDS.networks}>
      <div className="panel-heading"><div><h2>{POST_WORDS.networks} <Hint k="sources.networks" /></h2><p className="muted">{on.length} đang bật</p></div></div>
      {error != null && <ErrorNotice error={new Error(workErrorText(error))} />}
      <ul className="network-list">
        {platforms.data.map((platform) => {
          const open = platform.enabled && platform.via !== 'none'
          const state = platform.via === 'none' ? 'chưa có cách' : !platform.enabled ? 'cần CTO bật' : networkWords[platform.via]
          return (
            <li key={platform.code} className={open ? undefined : 'is-off'}>
              <label className="check-line"><input type="checkbox" checked={on.includes(platform.code)} disabled={!decides || !open || save.isPending} onChange={(event) => save.mutate(event.target.checked ? [...on, platform.code] : on.filter((c) => c !== platform.code))} /> <strong>{platform.label}</strong></label>
              <span className={`network-state is-${open ? platform.via : 'closed'}`}>{state}</span>
              <small>{platform.note}</small>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

// How often the flow scans and when the AI sums up, within the CTO's cap; and how many signals a week are enough.
function RhythmPanel({ code, decides }: { code: string; decides: boolean }) {
  const queryClient = useQueryClient()
  const base = `/projects/${code}/watch`
  const settings = useQuery({ queryKey: ['watch-settings', code], queryFn: () => api<WatchSettings>(`${base}/settings`) })
  const demand = useQuery({ queryKey: ['watch-demand', code], queryFn: () => api<WatchDemand>(`${base}/demand`) })
  const [draft, setDraft] = useState<{ times: string[]; weekdays: number[]; scan: number; wanted: string }>()
  const [newTime, setNewTime] = useState('')
  const [error, setError] = useState<unknown>()
  const [saved, setSaved] = useState(false)
  const stored = settings.data && demand.data ? { times: settings.data.schedule.times, weekdays: settings.data.schedule.weekdays, scan: settings.data.scan_every_hours, wanted: String(demand.data.wanted_per_week) } : undefined
  useEffect(() => { setDraft(undefined) }, [code])
  useEffect(() => { if (stored && !draft) setDraft(stored) }, [stored, draft])
  const save = useMutation({
    mutationFn: async (next: NonNullable<typeof draft>) => {
      const one = await api<WatchSettings>(`${base}/settings`, { method: 'PUT', body: JSON.stringify({ times: next.times, weekdays: next.weekdays, scan_every_hours: next.scan }) })
      const two = await api<WatchDemand>(`${base}/demand`, { method: 'PUT', body: JSON.stringify({ wanted_per_week: Number(next.wanted) || 0, weekday: demand.data?.weekday || 1, time: demand.data?.time || '06:00', lookback_days: demand.data?.lookback_days || 7 }) })
      return { one, two }
    },
    onMutate: () => setError(undefined),
    onSuccess: ({ one, two }) => { queryClient.setQueryData(['watch-settings', code], one); queryClient.setQueryData(['watch-demand', code], two); setDraft({ times: one.schedule.times, weekdays: one.schedule.weekdays, scan: one.scan_every_hours, wanted: String(two.wanted_per_week) }); setSaved(true); window.setTimeout(() => setSaved(false), 2500) },
    onError: setError,
  })
  if (!draft || !settings.data) return <section className="panel voice-form"><LoadingBlock /></section>
  const cap = settings.data.max_ai_runs_per_day
  const dirty = JSON.stringify(draft) !== JSON.stringify(stored)
  const runs = draft.times.length * draft.weekdays.length
  return (
    <section className="panel voice-form" aria-label={POST_WORDS.rhythm}>
      <div className="panel-heading"><div><h2>{POST_WORDS.rhythm} <Hint k="sources.rhythm" /></h2><p className="muted">ước chừng {runs} lượt AI mỗi tuần · trần {cap} lượt mỗi ngày</p></div>
        {decides && <button type="button" className="button button-primary button-small" disabled={!dirty || save.isPending || draft.times.length === 0 || draft.weekdays.length === 0} onClick={() => save.mutate(draft)}>{save.isPending ? 'Đang lưu…' : saved && !dirty ? 'Đã lưu' : 'Lưu nhịp'}</button>}
      </div>
      {error != null && <ErrorNotice error={new Error(workErrorText(error))} />}
      <div className="rhythm-grid">
        <label>Công cụ quét mỗi<select value={draft.scan} disabled={!decides} onChange={(event) => setDraft({ ...draft, scan: Number(event.target.value) })}>{settings.data.scan_hours.map((hours) => <option key={hours} value={hours}>{hours} giờ</option>)}</select></label>
        <div className="rhythm-times"><span>AI tóm chủ đề lúc</span>
          {draft.times.map((stamp) => <span className="chip" key={stamp}><span className="chip-label">{stamp}</span>{decides && <button type="button" aria-label={`Bỏ mốc ${stamp}`} onClick={() => setDraft({ ...draft, times: draft.times.filter((t) => t !== stamp) })}><X size={13} /></button>}</span>)}
          {decides && draft.times.length < cap && <form className="voice-add" onSubmit={(event) => { event.preventDefault(); if (newTime && !draft.times.includes(newTime)) { setDraft({ ...draft, times: [...draft.times, newTime].sort() }); setNewTime('') } }}><input type="time" value={newTime} aria-label="Mốc giờ mới" onChange={(event) => setNewTime(event.target.value)} /><button className="button button-secondary button-small" disabled={!newTime}>Thêm mốc</button></form>}
        </div>
        <div className="rhythm-days"><span>Ngày</span>{weekdayLong.map((label, i) => <label key={label} className="check-line"><input type="checkbox" checked={draft.weekdays.includes(i + 1)} disabled={!decides} onChange={(event) => setDraft({ ...draft, weekdays: event.target.checked ? [...draft.weekdays, i + 1].sort() : draft.weekdays.filter((d) => d !== i + 1) })} /> {label.replace('Thứ ', 'T').replace('Chủ nhật', 'CN')}</label>)}</div>
        <label>Số tín hiệu mỗi tuần <Hint k="sources.demand" /><input type="number" min={0} max={50} value={draft.wanted} disabled={!decides} onChange={(event) => setDraft({ ...draft, wanted: event.target.value })} aria-label="Số tín hiệu mỗi tuần" /></label>
      </div>
    </section>
  )
}

// What the owner sees of the doors the CTO made for this project: which exist, whether they deliver.
function ProjectConnectorsList({ code }: { code: string }) {
  const doors = useQuery({ queryKey: ['project-connectors', code], queryFn: () => api<ConnectorSummary[]>(`/projects/${code}/watch/connectors`) })
  if (!doors.data || doors.data.length === 0) return null
  return (
    <ul className="watch-health-tracks" aria-label="Cổng nhận">
      {doors.data.map((door) => (
        <li key={door.id} className={door.enabled && door.last_status && door.last_status !== 'ACCEPTED' && door.last_status !== 'EMPTY' ? 'is-warning' : undefined}>
          <strong>{door.name}</strong>
          <span>{connectorKinds[door.kind as WatchConnector['kind']] || door.kind}{door.enabled ? '' : ' · đã đóng'}</span>
          <span className="muted">{door.last_received_at ? `Nhận lần cuối ${formatMoment(door.last_received_at)} · tổng ${door.received_count}` : 'Chưa nhận lần nào'}{door.last_status && door.last_status !== 'ACCEPTED' ? ` · ${deliveryWords[door.last_status as ConnectorDelivery['status']] || door.last_status}` : ''}</span>
        </li>
      ))}
    </ul>
  )
}

// Nguồn và trụ: everything a marketing project listens with, for its owner (FR-MKT-08).
function WatchSourcesPage() {
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const projects = (user?.projects || []).filter((p) => isPostProject(p.kind))
  const wanted = params.get('project') || ''
  const project = projects.find((p) => p.id === wanted || p.code === wanted) || projects[0]
  const decides = user?.role === 'CTO' || user?.role === 'PROJECT_OWNER'
  if (!project) return <><PageHeader title={POST_WORDS.sourcesPage} /><EmptyState icon={<Eye size={22} />} title="Chưa có dự án marketing" text="Trang này dành cho dự án loại Marketing và nội dung." /></>
  const code = project.code
  return (
    <>
      <PageHeader title={POST_WORDS.sourcesPage} helper={[...POST_WORDS.sourcesHelper]} action={projects.length > 1 ? <select aria-label="Dự án" value={project.id} onChange={(event) => setParams({ project: event.target.value })}>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select> : undefined} />
      <PageIntro k="sources" />
      <PillarsEditor key={code} code={code} decides={decides} />
      <ProjectSourcesPanel key={`s-${code}`} code={code} decides={decides} />
      <NetworksPanel key={`n-${code}`} code={code} decides={decides} />
      <RhythmPanel key={`r-${code}`} code={code} decides={decides} />
      <section className="panel voice-form" aria-label="Công cụ quét">
        <div className="panel-heading"><div><h2>Công cụ quét</h2></div></div>
        <WatchHealthPanel base={`/projects/${code}/watch`} />
        <ProjectConnectorsList code={code} />
        <p className="field-help">Luồng quét do CTO cài bên ngoài đọc các cài đặt trên theo mã dự án <code>{project.code}</code> và gửi tín hiệu về; kết quả hiện ở khối {POST_WORDS.hotTopics} trên trang {POST_WORDS.week}. Intake không tự mở trang nào.</p>
      </section>
      <MarketingCommandsPanel projectCode={project.code} />
    </>
  )
}

// Cài đặt > Nguồn quét: the networks the CTO opens for every project, and the daily cap on AI runs.
function WatchPlatformsPage() {
  const queryClient = useQueryClient()
  const platforms = useQuery({ queryKey: ['watch-platforms'], queryFn: () => api<WatchPlatform[]>('/settings/watch-platforms') })
  const limits = useQuery({ queryKey: ['watch-limits'], queryFn: () => api<{ max_ai_runs_per_day: number }>('/settings/watch-limits') })
  const [draft, setDraft] = useState<Record<string, Partial<WatchPlatform>>>({})
  const [cap, setCap] = useState<string>()
  const [error, setError] = useState<unknown>()
  const save = useMutation({
    mutationFn: (code: string) => api<WatchPlatform>(`/settings/watch-platforms/${code}`, { method: 'PUT', body: JSON.stringify(draft[code]) }),
    onMutate: () => setError(undefined),
    onSuccess: (_row, code) => { setDraft((prev) => { const next = { ...prev }; delete next[code]; return next }); void queryClient.invalidateQueries({ queryKey: ['watch-platforms'] }) },
    onError: setError,
  })
  const saveCap = useMutation({
    mutationFn: (value: number) => api<{ max_ai_runs_per_day: number }>('/settings/watch-limits', { method: 'PUT', body: JSON.stringify({ max_ai_runs_per_day: value }) }),
    onMutate: () => setError(undefined), onSuccess: (row) => { queryClient.setQueryData(['watch-limits'], row); setCap(undefined) }, onError: setError,
  })
  const edit = (code: string, field: keyof WatchPlatform, value: unknown) => setDraft((prev) => ({ ...prev, [code]: { ...(prev[code] || {}), [field]: value } }))
  const value = <K extends keyof WatchPlatform>(row: WatchPlatform, field: K): WatchPlatform[K] => (draft[row.code] && field in draft[row.code] ? (draft[row.code][field] as WatchPlatform[K]) : row[field])
  return (
    <>
      <SectionHeader title="Nguồn quét" helper="Kênh nào công cụ quét bên ngoài được đọc, bằng API chính thức hay dịch vụ cào anh cài trong n8n; và mỗi dự án marketing được bao nhiêu lượt AI tóm chủ đề mỗi ngày. Project Owner chỉ bật được trong phạm vi này." />
      {error != null && <ErrorNotice error={new Error(workErrorText(error))} />}
      {platforms.error != null && <ErrorNotice error={platforms.error} onRetry={() => { void platforms.refetch() }} />}
      <section className="panel voice-form">
        <div className="panel-heading"><div><h2>Trần lượt AI mỗi ngày, mỗi dự án</h2><p className="muted">Mỗi mốc giờ trong nhịp của một dự án là một lượt; Làm mới tay thêm tối đa 3 lượt.</p></div>
          <form className="voice-add" onSubmit={(event) => { event.preventDefault(); if (cap !== undefined) saveCap.mutate(Number(cap)) }}>
            <input type="number" min={0} max={8} value={cap ?? String(limits.data?.max_ai_runs_per_day ?? 4)} aria-label="Trần lượt AI mỗi ngày" onChange={(event) => setCap(event.target.value)} />
            <button className="button button-primary button-small" disabled={cap === undefined || saveCap.isPending}>Lưu</button>
          </form>
        </div>
      </section>
      {platforms.isLoading ? <LoadingBlock /> : (
        <section className="panel channel-table-wrap">
          <table className="project-table channel-table">
            <thead><tr><th>Kênh</th><th>Bật</th><th>Đọc bằng</th><th>Ghi chú cho đội</th><th></th></tr></thead>
            <tbody>
              {(platforms.data || []).map((row) => (
                <tr key={row.code} className={row.enabled ? '' : 'is-off'}>
                  <td><input value={value(row, 'label')} onChange={(e) => edit(row.code, 'label', e.target.value)} aria-label={`Tên ${row.code}`} /><small className="muted">{row.code}</small></td>
                  <td><input type="checkbox" checked={value(row, 'enabled')} onChange={(e) => edit(row.code, 'enabled', e.target.checked)} aria-label={`Bật ${row.code}`} /></td>
                  <td><select value={value(row, 'via')} onChange={(e) => edit(row.code, 'via', e.target.value)} aria-label={`Đọc bằng ${row.code}`}><option value="api">API chính thức</option><option value="scrape">Dịch vụ cào</option><option value="none">Chưa có cách</option></select></td>
                  <td><input value={value(row, 'note') ?? ''} onChange={(e) => edit(row.code, 'note', e.target.value || null)} aria-label={`Ghi chú ${row.code}`} /></td>
                  <td className="project-actions">{draft[row.code] && <button type="button" className="button button-primary button-small" disabled={save.isPending} onClick={() => save.mutate(row.code)}>Lưu</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <p className="field-help">Luồng quét đọc <code>GET /api/v1/watch/config</code> (trả mọi dự án đang nghe, kênh bật, giờ quét kế tiếp) và gửi tín hiệu về <code>POST /api/v1/watch/signals</code>; mẫu luồng n8n và cách ký ở <code>docs/stable/watch-flow.md</code>.</p>
      <ConnectorsPanel />
    </>
  )
}

const connectorKinds: Record<WatchConnector['kind'], string> = { GENERIC: 'JSON tùy ý', N8N: 'n8n', MAKE: 'Make, Zapier', APIFY: 'Apify (dịch vụ cào)', MENTION: 'Mention, Brand24' }
const deliveryWords: Record<ConnectorDelivery['status'], string> = { ACCEPTED: 'đã nhận', EMPTY: 'không có mục', INVALID: 'sai định dạng', UNAUTHORIZED: 'sai bí mật' }

// The CTO's doors for outside services (FR-MKT-13): make one, keep its secret once, map and try a sample, watch the log.
function ConnectorsPanel() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const projects = (user?.projects || []).filter((p) => isPostProject(p.kind))
  const [projectId, setProjectId] = useState('')
  const project = projects.find((p) => p.id === projectId) || projects[0]
  const code = project?.code || ''
  const doors = useQuery({ queryKey: ['watch-connectors', code], queryFn: () => api<WatchConnector[]>(`/settings/watch-connectors?project=${code}`), enabled: Boolean(code) })
  const presets = useQuery({ queryKey: ['connector-presets'], queryFn: () => api<Record<string, ConnectorMapping>>('/settings/watch-connectors/presets'), staleTime: 600_000 })
  const pillars = useQuery({ queryKey: ['watch-pillars', code], queryFn: () => api<Pillar[]>(`/projects/${code}/watch/pillars`), enabled: Boolean(code) })
  const [form, setForm] = useState({ name: '', kind: 'GENERIC' as WatchConnector['kind'], via: 'api' as 'api' | 'scrape', default_pillar: '' })
  const [secret, setSecret] = useState<{ name: string; token: string; path: string } | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [mappingText, setMappingText] = useState('')
  const [sample, setSample] = useState('')
  const [tried, setTried] = useState<ConnectorTry | null>(null)
  const [error, setError] = useState<unknown>()
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['watch-connectors', code] }) }
  const create = useMutation({
    mutationFn: () => api<WatchConnector>('/settings/watch-connectors', { method: 'POST', body: JSON.stringify({ project: code, name: form.name.trim(), kind: form.kind, via: form.via, default_pillar: form.default_pillar || null }) }),
    onMutate: () => setError(undefined), onSuccess: (made) => { setSecret({ name: made.name, token: made.token || '', path: made.path }); setForm({ name: '', kind: 'GENERIC', via: 'api', default_pillar: '' }); refresh() }, onError: setError,
  })
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api<WatchConnector>(`/settings/watch-connectors/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    onMutate: () => setError(undefined), onSuccess: refresh, onError: setError,
  })
  const rotate = useMutation({
    mutationFn: (id: string) => api<WatchConnector>(`/settings/watch-connectors/${id}/rotate`, { method: 'POST' }),
    onMutate: () => setError(undefined), onSuccess: (made) => { setSecret({ name: made.name, token: made.token || '', path: made.path }); refresh() }, onError: setError,
  })
  const remove = useMutation({ mutationFn: (id: string) => api<void>(`/settings/watch-connectors/${id}`, { method: 'DELETE' }), onMutate: () => setError(undefined), onSuccess: () => { setOpen(null); refresh() }, onError: setError })
  const tryIt = useMutation({
    mutationFn: ({ id, body }: { id: string; body: string }) => api<ConnectorTry>(`/settings/watch-connectors/${id}/try`, { method: 'POST', body }),
    onMutate: () => { setError(undefined); setTried(null) }, onSuccess: setTried, onError: setError,
  })
  const deliveries = useQuery({ queryKey: ['connector-deliveries', open], queryFn: () => api<ConnectorDelivery[]>(`/settings/watch-connectors/${open}/deliveries`), enabled: Boolean(open) })
  const absolute = (path: string) => `${window.location.origin}${path}`
  const openDoor = (door: WatchConnector) => { setOpen(open === door.id ? null : door.id); setMappingText(JSON.stringify(door.mapping, null, 2)); setSample(''); setTried(null) }
  const saveMapping = (id: string) => {
    try { patch.mutate({ id, body: { mapping: JSON.parse(mappingText) } }) } catch { setError(new Error('Ánh xạ phải là JSON hợp lệ: {"items": "...", "fields": {"url": "...", "title": "..."}}')) }
  }
  if (projects.length === 0) return null
  return (
    <section className="panel voice-form" aria-label="Cổng nhận">
      <div className="panel-heading"><div><h2>Cổng nhận từ dịch vụ ngoài</h2><p className="muted">Mỗi cổng một bí mật riêng, một đường đẩy riêng, một bảng ánh xạ từ payload của dịch vụ sang tín hiệu của Intake. n8n, Make, Zapier, dịch vụ cào hay nghe đều đẩy vào đây; Intake không gọi ngược ra ngoài.</p></div>
        {projects.length > 1 && <select aria-label="Dự án" value={project?.id || ''} onChange={(e) => { setProjectId(e.target.value); setOpen(null) }}>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>}
      </div>
      {error != null && <ErrorNotice error={new Error(workErrorText(error))} />}
      {secret && (
        <div className="connector-secret" role="status">
          <strong>Bí mật của cổng "{secret.name}" chỉ hiện một lần.</strong>
          <div><span>Đường đẩy</span><code>{absolute(secret.path)}</code><CopyText text={absolute(secret.path)} label="Chép" /></div>
          <div><span>Header <code>X-Intake-Token</code></span><code>{secret.token}</code><CopyText text={secret.token} label="Chép" /></div>
          <button type="button" className="text-button" onClick={() => setSecret(null)}>Đã lưu, đóng</button>
        </div>
      )}
      <form className="connector-form" onSubmit={(e) => { e.preventDefault(); if (form.name.trim()) create.mutate() }}>
        <input value={form.name} maxLength={80} placeholder="Tên cổng (Make tìm tin ngành, Apify Facebook…)" aria-label="Tên cổng" onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <select aria-label="Loại dịch vụ" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as WatchConnector['kind'] })}>{(Object.keys(connectorKinds) as WatchConnector['kind'][]).map((k) => <option key={k} value={k}>{connectorKinds[k]}</option>)}</select>
        <select aria-label="Đường lấy dữ liệu" value={form.via} onChange={(e) => setForm({ ...form, via: e.target.value as 'api' | 'scrape' })}><option value="api">API chính thức</option><option value="scrape">Dịch vụ cào (điểm thấp hơn một bậc)</option></select>
        <select aria-label="Trụ mặc định" value={form.default_pillar} onChange={(e) => setForm({ ...form, default_pillar: e.target.value })}><option value="">Không gán trụ mặc định</option>{(pillars.data || []).map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}</select>
        <button className="button button-primary button-small" disabled={!form.name.trim() || create.isPending}>Tạo cổng</button>
      </form>
      {doors.isLoading ? <LoadingBlock /> : (doors.data || []).length === 0 ? <p className="field-help">Chưa có cổng nào cho dự án này.</p> : (
        <ul className="connector-list">
          {(doors.data || []).map((door) => (
            <li key={door.id} className={door.enabled ? undefined : 'is-off'}>
              <div className="connector-head">
                <div><strong>{door.name}</strong> <span className="chip">{connectorKinds[door.kind]}</span> <span className="chip">{door.via === 'scrape' ? 'cào' : 'API'}</span>{door.default_pillar && <span className="chip-pillar">{door.default_pillar}</span>}
                  <small>{door.token_prefix}… · nhận {door.received_count}, từ chối {door.rejected_count}{door.last_received_at ? ` · lần cuối ${formatMoment(door.last_received_at)}` : ' · chưa nhận lần nào'}{door.last_status && door.last_status !== 'ACCEPTED' ? ` · ${deliveryWords[door.last_status as ConnectorDelivery['status']] || door.last_status}` : ''}</small></div>
                <div className="row">
                  <CopyText text={absolute(door.path)} label="Chép đường đẩy" />
                  <button type="button" className={door.enabled ? 'button button-secondary button-small is-posted' : 'button button-secondary button-small'} aria-pressed={door.enabled} disabled={patch.isPending} onClick={() => patch.mutate({ id: door.id, body: { enabled: !door.enabled } })}>{door.enabled ? 'Đang mở' : 'Đã đóng'}</button>
                  <button type="button" className="text-button" onClick={() => openDoor(door)}>{open === door.id ? 'Thu gọn' : 'Ánh xạ, thử, nhật ký'}</button>
                </div>
              </div>
              {open === door.id && (
                <div className="connector-detail">
                  <div className="connector-cols">
                    <label>Ánh xạ (đường dẫn từ gốc JSON; <code>items</code> rỗng nếu thân gọi là danh sách)
                      <textarea rows={9} value={mappingText} onChange={(e) => setMappingText(e.target.value)} spellCheck={false} />
                      <span className="row"><button type="button" className="button button-secondary button-small" disabled={patch.isPending} onClick={() => saveMapping(door.id)}>Lưu ánh xạ</button>
                        {presets.data && <button type="button" className="text-button" onClick={() => setMappingText(JSON.stringify(presets.data![door.kind], null, 2))}>Lấy mẫu {connectorKinds[door.kind]}</button>}</span>
                    </label>
                    <label>Thử với payload mẫu (không lưu gì)
                      <textarea rows={9} value={sample} placeholder='Dán JSON dịch vụ sẽ gửi, ví dụ {"items": [{"url": "https://…", "title": "…"}]}' onChange={(e) => setSample(e.target.value)} spellCheck={false} />
                      <span className="row"><button type="button" className="button button-secondary button-small" disabled={!sample.trim() || tryIt.isPending} onClick={() => { try { JSON.parse(sample); tryIt.mutate({ id: door.id, body: sample }) } catch { setError(new Error('Payload mẫu phải là JSON hợp lệ')) } }}>Thử ánh xạ</button></span>
                    </label>
                  </div>
                  {tried && (
                    <div className="connector-try">
                      <strong>Sẽ nhận {tried.would_accept}/{tried.items.length} mục{tried.problems.length ? ` · ${tried.problems.join('; ')}` : ''}</strong>
                      <ul>{tried.items.map((item, i) => <li key={i} className={item.would_reject.length ? 'is-rejected' : undefined}><span>{item.title || '(không có tiêu đề)'}</span><small>{item.url || '(không có url)'}{item.keyword ? ` · ${item.keyword}` : ''}{item.pillar ? ` · ${item.pillar}` : ''}{item.published_at ? ` · ${formatDay(item.published_at.slice(0, 10))}` : ''}{item.would_reject.length ? ` · từ chối: ${item.would_reject.join(', ')}` : ''}{item.notes.length ? ` · ${item.notes.join(', ')}` : ''}</small></li>)}</ul>
                    </div>
                  )}
                  <div className="connector-log">
                    <strong>Nhật ký {deliveries.data?.length || 0} lần gọi gần nhất</strong>
                    {(deliveries.data || []).length === 0 ? <small className="muted">Chưa có lần gọi nào.</small> : <ul>{(deliveries.data || []).map((d, i) => <li key={i}><span>{formatMoment(d.at)}</span><span className={`network-state is-${d.status === 'ACCEPTED' ? 'api' : 'closed'}`}>{deliveryWords[d.status]}</span><small>nhận {d.accepted} · trùng {d.duplicates} · từ chối {d.rejected}{d.note ? ` · ${d.note}` : ''}</small></li>)}</ul>}
                  </div>
                  <div className="row">
                    <button type="button" className="text-button" disabled={rotate.isPending} onClick={() => rotate.mutate(door.id)}>Cấp bí mật mới</button>
                    <button type="button" className="text-button post-drop" disabled={remove.isPending} onClick={() => remove.mutate(door.id)}>Xóa cổng</button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="field-help">Dịch vụ gửi <code>POST</code> JSON tới đường đẩy với header <code>X-Intake-Token</code>; tối đa 50 mục mỗi lần, 512 KB. Mọi cổng đổ vào cùng một chỗ với luồng quét n8n: trùng địa chỉ, hạn mức tuần, kho 600 và chủ đề nóng dùng chung.</p>
    </section>
  )
}

// The emergency stop of the posting flow and the per-channel switch live on Kênh đăng; this is the stop.
function PublishPauseToggle() {
  const queryClient = useQueryClient()
  const pause = useQuery({ queryKey: ['publish-pause'], queryFn: () => api<{ paused: boolean }>('/settings/publish-pause') })
  const save = useMutation({ mutationFn: (paused: boolean) => api<{ paused: boolean }>('/settings/publish-pause', { method: 'PUT', body: JSON.stringify({ paused }) }), onSuccess: (row) => queryClient.setQueryData(['publish-pause'], row) })
  if (!pause.data) return null
  return (
    <div className={pause.data.paused ? 'publish-pause is-paused' : 'publish-pause'} role="status">
      <span>{pause.data.paused ? 'Đang dừng khẩn: không bản nào được đưa cho luồng đăng, kể cả kênh đã bật tự đăng.' : 'Luồng đăng đang nhận bản Đã duyệt và Sẵn sàng tới giờ của các kênh bật "Tự đăng".'}</span>
      <button type="button" className={pause.data.paused ? 'button button-primary button-small' : 'button button-secondary button-small'} disabled={save.isPending} onClick={() => save.mutate(!pause.data!.paused)}>{pause.data.paused ? 'Cho đăng lại' : 'Dừng khẩn'}</button>
    </div>
  )
}

// Tuần này: channels down, days across; a tile per channel version.
function WeekBoardPage() {
  const { user } = useAuth()
  const { setRightPanel } = useShell()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const decides = user?.role === 'CTO' || user?.role === 'PROJECT_OWNER'
  const projects = (user?.projects || []).filter((p) => isPostProject(p.kind) || user?.role !== 'CTO')
  const wanted = params.get('project') || ''
  const project = projects.find((p) => p.id === wanted || p.code === wanted) || projects[0]
  const projectId = project?.id || ''
  const week = params.get('week') || mondayOf(todayInPlanningTimezone())
  const days = Array.from({ length: 7 }, (_, i) => addDays(week, i))
  const rules = useQuery(channelRulesQuery)
  const board = useQuery({ queryKey: ['work', projectId, 'week', week], queryFn: () => api<WorkItem[]>(`/work?project=${projectId}&week=${week}`), enabled: Boolean(projectId), refetchInterval: 60_000 })
  const members = useQuery({ queryKey: ['planning-members'], queryFn: () => api<WorkforceMember[]>('/planning/members'), enabled: decides })
  const campaigns = useQuery({ queryKey: ['work-campaigns', projectId], queryFn: () => api<{ name: string; count: number }[]>(`/work/campaigns?project=${projectId}`), enabled: Boolean(projectId) && decides })
  const projectMembers = useMemo(() => (members.data || []).filter((m) => m.status === 'ACTIVE' && m.project_mappings.some((x) => x.project_id === projectId && x.active)), [members.data, projectId])
  const [memberFilter, setMemberFilter] = useState('')
  const [campaignFilter, setCampaignFilter] = useState('')
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [error, setError] = useState<unknown>()
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['work'] }); void queryClient.invalidateQueries({ queryKey: ['work-detail'] }) }
  const setParam = (key: string, value: string | null) => setParams((current) => { const next = new URLSearchParams(current); if (value) next.set(key, value); else next.delete(key); return next }, { replace: true })
  const rows = (board.data || []).filter((row) => !row.parent_id && row.status !== 'CANCELLED' && (!memberFilter || row.member_id === memberFilter) && (!campaignFilter || row.campaign === campaignFilter))
  type Tile = { row: WorkItem; version: WorkItem['channels'][number]; day: string }
  const tiles: Tile[] = rows.flatMap((row) => row.channels.map((version) => ({ row, version, day: dayOfStamp(version.publish_at) || '' })).filter((tile) => tile.day && days.includes(tile.day)))
  const channelsShown = CHANNEL_ORDER.filter((code) => tiles.some((t) => t.version.channel === code) || (rules.data || []).some((r) => r.code === code && r.enabled && ['FACEBOOK_PAGE', 'FACEBOOK_PERSONAL', 'X', 'LINKEDIN', 'TIKTOK'].includes(code)))
  const today = todayInPlanningTimezone()
  const scheduled = tiles.filter((t) => t.version.status !== 'PUBLISHED').length
  const review = rows.filter((row) => row.status === 'ACCEPTANCE').length
  const late = (board.data || []).flatMap((row) => row.channels).filter((v) => v.status !== 'PUBLISHED' && v.publish_at && (dayOfStamp(v.publish_at) || '') < today).length
  const moveDate = useMutation({
    mutationFn: ({ tile, day }: { tile: Tile; day: string }) => api<WorkDetail>(`/work/${tile.row.id}/channels/${tile.version.id}`, { method: 'PATCH', body: JSON.stringify({ publish_at: stampOf(day, timeOfStamp(tile.version.publish_at) || bestHour(rules.data, tile.version.channel)) }) }),
    onMutate: () => setError(undefined), onSuccess: refresh, onError: setError,
  })
  const bulk = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<{ changed: number }>('/work/bulk-update', { method: 'POST', body: JSON.stringify({ ids: Array.from(picked), ...body }) }),
    onMutate: () => setError(undefined), onSuccess: () => { setPicked(new Set()); refresh() }, onError: setError,
  })
  const [dropping, setDropping] = useState<string | null>(null)
  const openWork = params.get('work') || ''
  const openTopic = params.get('topic') || ''
  const adding = params.get('new') || ''
  const closePanel = () => setParams((current) => { const next = new URLSearchParams(current); next.delete('work'); next.delete('new'); next.delete('channel'); next.delete('day'); next.delete('topic'); return next }, { replace: true })
  // From a topic to the post it became: the topic panel closes, the post opens.
  const openWorkFromTopic = (id: string) => setParams((current) => { const next = new URLSearchParams(current); next.delete('topic'); next.set('work', id); return next }, { replace: true })
  useEffect(() => {
    if (!projectId) return
    if (openTopic) {
      setRightPanel({ title: POST_WORDS.hotTopics, content: <TopicPanel key={openTopic} projectId={projectId} topicId={openTopic} decides={decides} members={projectMembers} week={week} onOpenWork={openWorkFromTopic} onDone={closePanel} />, onClose: closePanel })
      return () => setRightPanel(null)
    }
    if (openWork) {
      setRightPanel({ title: POST_WORDS.unit, content: <WorkDetailPanel key={openWork} workId={openWork} decides={decides} members={projectMembers} onChanged={refresh} onDone={closePanel} onOpen={(id) => setParam('work', id)} postMode />, onClose: closePanel })
      return () => setRightPanel(null)
    }
    if (adding === 'many' && decides) {
      setRightPanel({ title: POST_WORDS.addMany, content: <BulkPostsPanel key={projectId} projectId={projectId} members={projectMembers} onDone={() => { refresh(); closePanel() }} />, onClose: closePanel })
      return () => setRightPanel(null)
    }
    if (adding && decides) {
      setRightPanel({ title: POST_WORDS.add, content: <PostFormPanel key={`${projectId}-${params.get('channel')}-${params.get('day')}`} projectId={projectId} members={projectMembers} campaigns={(campaigns.data || []).map((c) => c.name)} preset={{ channel: params.get('channel') || undefined, day: params.get('day') || undefined }} onDone={() => { refresh(); closePanel() }} />, onClose: closePanel })
      return () => setRightPanel(null)
    }
    return undefined
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openWork, openTopic, week, adding, projectId, decides, projectMembers, campaigns.data, setRightPanel])
  const weekdayNames = ['Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ nhật']
  return (
    <>
      <PageHeader title={POST_WORDS.week} helper={[...POST_WORDS.weekHelper]} action={decides && projectId ? <span className="with-hint"><button type="button" className="button button-primary" onClick={() => setParam('new', '1')}><Plus size={15} /> {POST_WORDS.add}</button><button type="button" className="button button-secondary" onClick={() => setParam('new', 'many')}>{POST_WORDS.addMany}</button><Link to={`/nguon?project=${projectId}`} className="button button-secondary"><Eye size={15} /> {POST_WORDS.sourcesPage}</Link></span> : undefined} />
      <PageIntro k="week" />
      {decides && <AgentHint command="hot_topics" />}
      <div className="week-bar post-week-bar">
        {projects.length > 1 && <select aria-label="Dự án" value={projectId} onChange={(event) => { setParam('project', event.target.value); setParam('work', null) }}>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>}
        <button type="button" className="button button-secondary button-small" onClick={() => setParam('week', addDays(week, -7))}>← Tuần trước</button>
        <strong>{formatDay(week)} đến {formatDay(addDays(week, 6))}</strong>
        <button type="button" className="button button-secondary button-small" onClick={() => setParam('week', addDays(week, 7))}>Tuần sau →</button>
        {week !== mondayOf(today) && <button type="button" className="text-button" onClick={() => setParam('week', null)}>Về tuần này</button>}
        <span className="post-week-numbers"><span><strong>{scheduled}</strong> đã lên lịch</span><span><strong>{review}</strong> chờ duyệt</span><span className={late > 0 ? 'is-late' : ''}><strong>{late}</strong> trễ <Hint k="week.late" /></span></span>
      </div>
      <div className="work-board-bar">
        {projectMembers.length > 0 && <select aria-label="Người làm" value={memberFilter} onChange={(event) => setMemberFilter(event.target.value)}><option value="">Mọi người</option>{projectMembers.map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}</select>}
        {(campaigns.data || []).length > 0 && <select aria-label="Chiến dịch" value={campaignFilter} onChange={(event) => setCampaignFilter(event.target.value)}><option value="">Mọi chiến dịch</option>{(campaigns.data || []).map((c) => <option key={c.name} value={c.name}>{c.name} ({c.count})</option>)}</select>}
        {picked.size > 0 && decides && (
          <span className="post-bulk-bar">
            <span>{picked.size} bài đã chọn</span>
            <select aria-label="Giao cho" defaultValue="" onChange={(event) => { if (event.target.value) bulk.mutate({ member_id: event.target.value }); event.target.value = '' }}><option value="">Giao cho…</option>{projectMembers.map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}</select>
            <input type="date" aria-label="Đổi ngày đăng" onChange={(event) => { if (event.target.value) bulk.mutate({ publish_at: stampOf(event.target.value, '09:00') }) }} />
            <button type="button" className="text-button" onClick={() => setPicked(new Set())}>Bỏ chọn</button>
          </span>
        )}
      </div>
      {error != null && <ErrorNotice error={new Error(workErrorText(error))} />}
      {board.error != null && <ErrorNotice error={board.error} onRetry={() => { void board.refetch() }} />}
      {projectId && <HotTopicsBlock projectId={projectId} decides={decides} onOpenTopic={(id) => setParam('topic', id)} onOpenWork={openWorkFromTopic} />}
      {!projectId ? <EmptyState icon={<CalendarDays size={22} />} title="Chưa có dự án" text="Anh/chị chưa thuộc dự án marketing nào đang hoạt động." /> : board.isLoading ? <LoadingBlock /> : (
        <div className="panel post-week" role="table" aria-label="Lịch tuần theo kênh">
          <div className="post-week-head" role="row"><span role="columnheader">Kênh</span>{days.map((day, i) => <span key={day} role="columnheader" className={day === today ? 'is-today' : ''}>{weekdayNames[i]}<small>{formatDay(day)}</small></span>)}</div>
          {channelsShown.map((code) => (
            <div className="post-week-row" role="row" key={code}>
              <span role="rowheader" className="post-week-channel">{CHANNEL_SHORT[code] || code}</span>
              {days.map((day) => {
                const cell = `${code}:${day}`
                const here = tiles.filter((t) => t.version.channel === code && t.day === day)
                return (
                  <div role="cell" key={cell} className={`post-week-cell${dropping === cell ? ' drop-here' : ''}${day === today ? ' is-today' : ''}`}
                    onDragOver={(event) => { if (decides) { event.preventDefault(); setDropping(cell) } }}
                    onDragLeave={() => { if (dropping === cell) setDropping(null) }}
                    onDrop={(event) => { event.preventDefault(); setDropping(null); const [workId, versionId] = event.dataTransfer.getData('text/plain').split(':'); const tile = tiles.find((t) => t.row.id === workId && t.version.id === versionId); if (tile && tile.version.channel === code && tile.day !== day) moveDate.mutate({ tile, day }) }}>
                    {here.map((tile) => (
                      <article key={tile.version.id} className={`post-tile is-${postColumnOf(tile.row.status).toLowerCase()}${tile.version.status === 'PUBLISHED' ? ' is-published' : ''}${tile.row.urgent ? ' is-urgent' : ''}${picked.has(tile.row.id) ? ' is-picked' : ''}`} draggable={decides && tile.version.status !== 'PUBLISHED'}
                        onDragStart={(event) => { event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', `${tile.row.id}:${tile.version.id}`) }}>
                        {decides && <input type="checkbox" className="post-tile-pick" aria-label={`Chọn ${tile.row.title}`} checked={picked.has(tile.row.id)} onChange={(event) => setPicked((prev) => { const next = new Set(prev); if (event.target.checked) next.add(tile.row.id); else next.delete(tile.row.id); return next })} />}
                        <button type="button" className="post-tile-title" onClick={() => setParam('work', tile.row.id)}>{tile.row.urgent && <span className="post-urgent-dot" title="Gấp" />}{tile.row.title}</button>
                        <small>{tile.row.member_name || 'chưa giao'} · {timeOfStamp(tile.version.publish_at)} · {tile.version.status === 'PUBLISHED' ? 'đã đăng' : POST_STATUS_LABELS[tile.row.status]}</small>
                      </article>
                    ))}
                    {decides && <button type="button" className="post-cell-add" aria-label={`Thêm bài ${CHANNEL_NAMES[code]} ${formatDay(day)}`} title="Thêm bài ở kênh và ngày này" onClick={() => { setParam('channel', code); setParam('day', day); setParam('new', '1') }}>+</button>}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}
      <p className="field-help"><Hint k="week.cell_add" /> Dấu + trong ô thêm bài ngay kênh và ngày đó. Trên điện thoại, mở thẻ rồi đổi ngày thay vì kéo.</p>
    </>
  )
}

// Chờ duyệt: what the owner reads and decides, two buttons.
function ReviewPage() {
  const { user } = useAuth()
  const { setRightPanel } = useShell()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const decides = user?.role === 'CTO' || user?.role === 'PROJECT_OWNER'
  const list = useQuery({ queryKey: ['work-review'], queryFn: () => api<WorkItem[]>('/work/review'), enabled: decides, refetchInterval: 60_000 })
  const [note, setNote] = useState<Record<string, string>>({})
  const [sendingBack, setSendingBack] = useState<string | null>(null)
  const [error, setError] = useState<unknown>()
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['work-review'] }); void queryClient.invalidateQueries({ queryKey: ['work'] }) }
  const move = useMutation({
    mutationFn: ({ row, status, text }: { row: WorkItem; status: WorkItemStatus; text?: string }) => api<WorkItem>(`/work/${row.id}/move`, { method: 'POST', body: JSON.stringify({ expected_version: row.version, status, note: text || null }) }),
    onMutate: () => setError(undefined), onSuccess: () => { setSendingBack(null); refresh() }, onError: setError,
  })
  const openWork = params.get('work') || ''
  const closePanel = () => setParams((current) => { const next = new URLSearchParams(current); next.delete('work'); return next }, { replace: true })
  useEffect(() => {
    if (!openWork) return undefined
    setRightPanel({ title: POST_WORDS.unit, content: <WorkDetailPanel key={openWork} workId={openWork} decides={decides} members={[]} onChanged={refresh} onDone={closePanel} onOpen={(id) => setParams((c) => { const n = new URLSearchParams(c); n.set('work', id); return n })} postMode />, onClose: closePanel })
    return () => setRightPanel(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openWork, decides, setRightPanel])
  const rows = (list.data || []).filter((row) => row.project_kind === 'NON_CODE' || user?.mode === 'MARKETING')
  return (
    <>
      <PageHeader title={POST_WORDS.review} helper={[...POST_WORDS.reviewHelper]} />
      <PageIntro k="review" />
      {error != null && <ErrorNotice error={new Error(workErrorText(error))} />}
      {list.isLoading ? <LoadingBlock /> : rows.length === 0 ? <div className="panel"><EmptyState icon={<BadgeCheck size={22} />} title="Không có bài chờ duyệt" text="Khi người làm bấm Gửi duyệt, bài hiện ở đây." /></div> : (
        <ul className="review-list">
          {rows.map((row) => (
            <li key={row.id} className="panel review-card">
              <div className="review-head">
                <button type="button" className="work-card-title" onClick={() => setParams((c) => { const n = new URLSearchParams(c); n.set('work', row.id); return n })}>{row.urgent && <span className="post-urgent-dot" title="Gấp" />}{row.title}</button>
                <small>{dotted([row.project_name, row.member_name || 'chưa giao', row.campaign, `gửi ${formatDate(row.updated_at)}`].filter(Boolean) as ReactNode[])}</small>
              </div>
              <ChannelChips row={row} />
              {row.description && <p className="review-text">{row.description}</p>}
              {row.link_count > 0 && <p className="field-help">{row.link_count} link đính kèm: mở thẻ để xem.</p>}
              <div className="review-actions">
                <button type="button" className="button button-primary button-small" disabled={move.isPending} onClick={() => move.mutate({ row, status: 'APPROVED' })}>{POST_WORDS.approve}</button>
                {sendingBack === row.id ? (
                  <form className="review-send-back" onSubmit={(event) => { event.preventDefault(); if ((note[row.id] || '').trim().length >= 3) move.mutate({ row, status: 'IN_PROGRESS', text: note[row.id].trim() }) }}>
                    <input value={note[row.id] || ''} onChange={(event) => setNote({ ...note, [row.id]: event.target.value })} placeholder={POST_WORDS.sendBackAsk} autoFocus aria-label="Cần sửa gì" />
                    <button type="submit" className="button button-secondary button-small" disabled={move.isPending || (note[row.id] || '').trim().length < 3}>Gửi lại người làm</button>
                    <button type="button" className="text-button" onClick={() => setSendingBack(null)}>Thôi</button>
                  </form>
                ) : <button type="button" className="button button-secondary button-small" onClick={() => setSendingBack(row.id)}>{POST_WORDS.sendBack} <Hint k="review.send_back" /></button>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

// Cài đặt > Kênh đăng: the CTO's table of what each channel allows.
function ChannelRulesPage() {
  const queryClient = useQueryClient()
  const rules = useQuery(channelRulesQuery)
  const [draft, setDraft] = useState<Record<string, Partial<ChannelRule>>>({})
  const [error, setError] = useState<unknown>()
  const save = useMutation({
    mutationFn: (code: string) => api<ChannelRule>(`/channel-rules/${code}`, { method: 'PUT', body: JSON.stringify(draft[code]) }),
    onMutate: () => setError(undefined),
    onSuccess: (_row, code) => { setDraft((prev) => { const next = { ...prev }; delete next[code]; return next }); void queryClient.invalidateQueries({ queryKey: ['channel-rules'] }) },
    onError: setError,
  })
  const edit = (code: string, field: keyof ChannelRule, value: unknown) => setDraft((prev) => ({ ...prev, [code]: { ...(prev[code] || {}), [field]: value } }))
  const value = <K extends keyof ChannelRule>(row: ChannelRule, field: K): ChannelRule[K] => (draft[row.code] && field in draft[row.code] ? (draft[row.code][field] as ChannelRule[K]) : row[field])
  return (
    <>
      <SectionHeader title="Kênh đăng" helper="Mỗi kênh cho phép gì: ký tự, ảnh, hashtag, link, ngôn ngữ, giờ tốt. Bộ đếm trong thẻ bài và AI soạn bản kênh đọc từ bảng này; nền tảng đổi luật thì sửa ở đây, không cần cập nhật phần mềm." />
      <PublishPauseToggle />
      {error != null && <ErrorNotice error={error} />}
      {rules.error != null && <ErrorNotice error={rules.error} onRetry={() => { void rules.refetch() }} />}
      {rules.isLoading ? <LoadingBlock /> : (
        <section className="panel channel-table-wrap">
          <table className="project-table channel-table">
            <thead><tr><th>Kênh</th><th>Ngôn ngữ</th><th>Ký tự tối đa</th><th>Nên dùng</th><th>Bài dài</th><th>Ảnh</th><th>Tỉ lệ ảnh</th><th>Tỉ lệ video</th><th>Hashtag</th><th>Link tính ký tự</th><th>Giờ tốt</th><th>Bật</th><th>Tự đăng</th><th></th></tr></thead>
            <tbody>
              {(rules.data || []).map((row) => (
                <tr key={row.code} className={row.enabled ? '' : 'is-off'}>
                  <td><input value={value(row, 'label')} onChange={(e) => edit(row.code, 'label', e.target.value)} aria-label={`Tên ${row.code}`} /><small className="muted">{row.code}</small></td>
                  <td><select value={value(row, 'language')} onChange={(e) => edit(row.code, 'language', e.target.value)} aria-label={`Ngôn ngữ ${row.code}`}><option value="vi">Tiếng Việt</option><option value="en">English</option></select></td>
                  <td><input type="number" min={1} value={value(row, 'max_chars')} onChange={(e) => edit(row.code, 'max_chars', Number(e.target.value))} aria-label={`Ký tự tối đa ${row.code}`} /></td>
                  <td><input type="number" min={0} value={value(row, 'recommended_chars') ?? ''} onChange={(e) => edit(row.code, 'recommended_chars', e.target.value ? Number(e.target.value) : null)} aria-label={`Nên dùng ${row.code}`} /></td>
                  <td><input type="number" min={0} value={value(row, 'long_max_chars') ?? ''} onChange={(e) => edit(row.code, 'long_max_chars', e.target.value ? Number(e.target.value) : null)} aria-label={`Bài dài ${row.code}`} placeholder="—" /></td>
                  <td><input type="number" min={0} value={value(row, 'max_images')} onChange={(e) => edit(row.code, 'max_images', Number(e.target.value))} aria-label={`Ảnh ${row.code}`} /></td>
                  <td><input value={value(row, 'image_ratio') ?? ''} onChange={(e) => edit(row.code, 'image_ratio', e.target.value || null)} aria-label={`Tỉ lệ ảnh ${row.code}`} /></td>
                  <td><input value={value(row, 'video_ratio') ?? ''} onChange={(e) => edit(row.code, 'video_ratio', e.target.value || null)} aria-label={`Tỉ lệ video ${row.code}`} /></td>
                  <td><input type="number" min={0} value={value(row, 'hashtag_max')} onChange={(e) => edit(row.code, 'hashtag_max', Number(e.target.value))} aria-label={`Hashtag ${row.code}`} /></td>
                  <td><label className="check-line"><input type="checkbox" checked={value(row, 'link_counts_chars')} onChange={(e) => edit(row.code, 'link_counts_chars', e.target.checked)} /> {value(row, 'link_chars') > 0 ? `${value(row, 'link_chars')} ký tự` : 'có'}</label></td>
                  <td><input value={(value(row, 'best_hours') || []).join(', ')} onChange={(e) => edit(row.code, 'best_hours', e.target.value.split(',').map((h) => h.trim()).filter(Boolean))} aria-label={`Giờ tốt ${row.code}`} placeholder="09:00, 19:30" /></td>
                  <td><input type="checkbox" checked={value(row, 'enabled')} onChange={(e) => edit(row.code, 'enabled', e.target.checked)} aria-label={`Bật ${row.code}`} /></td>
                  <td><input type="checkbox" checked={value(row, 'auto_publish')} onChange={(e) => edit(row.code, 'auto_publish', e.target.checked)} aria-label={`Tự đăng ${row.code}`} /></td>
                  <td className="project-actions">{draft[row.code] && <button type="button" className="button button-primary button-small" disabled={save.isPending} onClick={() => save.mutate(row.code)}>Lưu</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <p className="field-help">"Tự đăng": bản Đã duyệt và Sẵn sàng của kênh đó, tới giờ đăng, được đưa cho luồng đăng bên ngoài (n8n hoặc dịch vụ) qua <code>GET /api/v1/publish/queue</code>; luồng đăng xong báo link về và bản sang Đã đăng. Kênh chưa bật thì người làm đăng tay như trước.</p>
    </>
  )
}

function WorkBoardPage() {
  const { user } = useAuth()
  const { setRightPanel } = useShell()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const decides = user?.role === 'CTO' || user?.role === 'PROJECT_OWNER'
  // The person's projects come with their login (FR-MKT-03), whatever their role.
  const projects = useMemo(() => [...(user?.projects || [])].sort((a, b) => a.name.localeCompare(b.name)), [user?.projects])
  const wanted = params.get('project') || ''
  const project = projects.find((row) => row.id === wanted || row.code === wanted) || projects[0]
  const projectId = project?.id || ''
  // A marketing project is dressed as posts, for everyone who opens it (FR-MKT-03).
  const postMode = user?.mode === 'MARKETING' || isPostProject(project?.kind)
  const columns = postMode ? POST_COLUMNS : workColumns
  const campaigns = useQuery({ queryKey: ['work-campaigns', projectId], queryFn: () => api<{ name: string; count: number }[]>(`/work/campaigns?project=${projectId}`), enabled: Boolean(projectId) && postMode })
  const [includeClosed, setIncludeClosed] = useState(false)
  const board = useQuery({ queryKey: ['work', projectId, includeClosed], queryFn: () => api<WorkItem[]>(`/work?project=${projectId}${includeClosed ? '&include_closed=true' : ''}`), enabled: Boolean(projectId), refetchInterval: 60_000 })
  const [error, setError] = useState<unknown>()
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['work'] }); void queryClient.invalidateQueries({ queryKey: ['work-detail'] }) }
  const move = useMutation({
    mutationFn: ({ id, version, status, note }: { id: string; version: number; status: WorkItemStatus; note?: string }) =>
      api<WorkItem>(`/work/${id}/move`, { method: 'POST', body: JSON.stringify({ expected_version: version, status, note: note || null }) }),
    onMutate: () => setError(undefined),
    onSuccess: refresh,
    onError: (err) => { setError(err); if (err instanceof ApiError && err.code === 'STALE_VERSION') refresh() },
  })
  const [dropping, setDropping] = useState<WorkItemStatus | null>(null)
  const [asking, setAsking] = useState<{ row: WorkItem; status: WorkItemStatus } | null>(null)
  const [reason, setReason] = useState('')
  const rows = board.data || []
  const byId = useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows])
  const [videoOnly, setVideoOnly] = useState(false)
  // Steps stay inside their parent's card; only parents and plain work stand in the columns.
  const stepsOf = useMemo(() => {
    const map = new Map<string, WorkItem[]>()
    for (const row of rows) if (row.parent_id) map.set(row.parent_id, [...(map.get(row.parent_id) || []), row].sort((a, b) => (a.step_order || 0) - (b.step_order || 0)))
    return map
  }, [rows])
  const cards = rows.filter((row) => !row.parent_id && (!videoOnly || row.template) && (!postMode || row.status !== 'CANCELLED' || includeClosed))
  const requestMove = (row: WorkItem, status: WorkItemStatus) => {
    if (status === row.status) return
    if (status === 'CANCELLED') { setReason(''); setAsking({ row, status }); return }
    move.mutate({ id: row.id, version: row.version, status })
  }
  const openWork = params.get('work') || ''
  const members = useQuery({ queryKey: ['planning-members'], queryFn: () => api<WorkforceMember[]>('/planning/members'), enabled: decides })
  const projectMembers = useMemo(() => (members.data || []).filter((member) => member.status === 'ACTIVE' && member.project_mappings.some((mapping) => mapping.project_id === projectId)), [members.data, projectId])
  const closePanel = () => { setParams((current) => { const next = new URLSearchParams(current); next.delete('work'); next.delete('new'); return next }, { replace: true }) }
  const adding = params.get('new') || ''
  useEffect(() => {
    if (!projectId) return
    if (openWork) {
      setRightPanel({ title: postMode ? POST_WORDS.unit : 'Việc', content: <WorkDetailPanel key={openWork} workId={openWork} decides={decides} members={projectMembers} onChanged={refresh} onDone={closePanel} onOpen={(id) => setParam('work', id)} postMode={postMode} />, onClose: closePanel })
      return () => setRightPanel(null)
    }
    if (adding === 'many' && decides && postMode) {
      setRightPanel({ title: POST_WORDS.addMany, content: <BulkPostsPanel key={projectId} projectId={projectId} members={projectMembers} onDone={() => { refresh(); closePanel() }} />, onClose: closePanel })
      return () => setRightPanel(null)
    }
    if (adding && decides) {
      setRightPanel({ title: postMode ? POST_WORDS.add : 'Thêm việc', content: postMode
        ? <PostFormPanel key={projectId} projectId={projectId} members={projectMembers} campaigns={(campaigns.data || []).map((c) => c.name)} onDone={() => { refresh(); closePanel() }} />
        : <WorkFormPanel key={projectId} projectId={projectId} members={projectMembers} onDone={() => { refresh(); closePanel() }} />, onClose: closePanel })
      return () => setRightPanel(null)
    }
    return undefined
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openWork, adding, projectId, decides, projectMembers, setRightPanel, postMode, campaigns.data])
  const setParam = (key: string, value: string | null) => setParams((current) => { const next = new URLSearchParams(current); if (value) next.set(key, value); else next.delete(key); return next }, { replace: true })
  const loading = false
  return (
    <>
      <PageHeader title={postMode ? POST_WORDS.board : 'Việc'} helper={postMode ? [...POST_WORDS.boardHelper] : ['Việc nội bộ của một dự án: việc không phải code, hoặc tính năng cần bàn trước khi thành Issue (ADR-0066).', 'Kéo thẻ sang cột khác, hoặc chọn cột ngay trên thẻ. Thả vào Bỏ thì phải ghi lý do.', 'Người làm chỉ chuyển việc của mình giữa Sẵn sàng, Đang làm và Chờ nghiệm thu.', 'Ở dự án phần mềm, một việc đã bàn xong có nút Tạo Issue trong thẻ.']}
        action={decides && projectId ? <span className="with-hint"><button type="button" className="button button-primary" onClick={() => setParam('new', '1')}><Plus size={15} /> {postMode ? POST_WORDS.add : 'Thêm việc'}</button>{postMode && <button type="button" className="button button-secondary" onClick={() => setParam('new', 'many')}>{POST_WORDS.addMany}</button>}</span> : undefined} />
      <PageIntro k={postMode ? 'posts' : 'work'} />
      <div className="work-board-bar">
        {projects.length > 1 && <select aria-label="Dự án" value={projectId} onChange={(event) => { setParam('project', event.target.value); setParam('work', null) }}>{projects.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select>}
        {projects.length === 1 && <strong>{project?.name}</strong>}
        <label className="work-board-toggle"><input type="checkbox" checked={includeClosed} onChange={(event) => setIncludeClosed(event.target.checked)} /> {postMode ? 'Cả bài cũ và bài đã bỏ' : 'Cả việc Xong và Bỏ cũ hơn 30 ngày'}</label>
        {!postMode && <label className="work-board-toggle"><input type="checkbox" checked={videoOnly} onChange={(event) => setVideoOnly(event.target.checked)} /> Chỉ video (việc có quy trình) <Hint k="work.video_only" /></label>}
        {postMode && <Link className="text-button" to={`/tuan-nay?project=${projectId}`}>Xem theo tuần</Link>}
      </div>
      {error != null && <ErrorNotice error={new Error(workErrorText(error))} />}
      {board.error != null && <ErrorNotice error={board.error} onRetry={() => { void board.refetch() }} />}
      {loading || (projectId && board.isLoading) ? <LoadingBlock /> : !projectId ? (
        <EmptyState icon={<ListChecks size={22} />} title="Chưa có dự án" text="Anh/chị chưa thuộc dự án nào đang hoạt động." />
      ) : (
        <div className="work-board" role="list" aria-label="Bảng việc">
          {columns.map((column) => {
            const items = cards.filter((row) => (postMode ? postColumnOf(row.status) : row.status) === column.value).sort((a, b) => Number(b.urgent) - Number(a.urgent))
            const accepts = decides || user?.role === 'DEVELOPER'
            return (
              <section key={column.value} role="listitem" className={`work-col work-col-${column.value.toLowerCase()}${dropping === column.value ? ' drop-here' : ''}`}
                onDragOver={(event) => { if (accepts) { event.preventDefault(); setDropping(column.value) } }}
                onDragLeave={() => { if (dropping === column.value) setDropping(null) }}
                onDrop={(event) => { event.preventDefault(); setDropping(null); const row = byId.get(event.dataTransfer.getData('text/plain')); if (row) requestMove(row, column.value) }}>
                <header className="work-col-head"><strong>{column.label} <Hint k={`${postMode ? 'post' : 'work'}.col.${column.value}` as HintKey} /></strong><span>{items.length}</span></header>
                {items.length === 0 ? <span className="work-col-empty">{dropping === column.value ? 'Thả vào đây' : '—'}</span>
                  : items.map((row) => <WorkCard key={row.id} row={row} steps={stepsOf.get(row.id) || []} canDrag={accepts && row.outcome !== 'ISSUE'} busy={move.isPending} onOpen={() => setParam('work', row.id)} onOpenStep={(id) => setParam('work', id)} onMove={(status) => requestMove(row, status)} postMode={postMode} />)}
              </section>
            )
          })}
        </div>
      )}
      {asking && (
        <ConfirmDialog title={`Bỏ việc ${asking.row.code}?`} confirmLabel="Bỏ việc" busyLabel="Đang ghi…" busy={move.isPending} error={move.error}
          onCancel={() => setAsking(null)} onConfirm={() => { move.mutate({ id: asking.row.id, version: asking.row.version, status: 'CANCELLED', note: reason.trim() }, { onSuccess: () => setAsking(null) }) }}>
          <p>{asking.row.title}</p>
          <label className="work-reason">Lý do (bắt buộc)<textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Vì sao không làm nữa" /></label>
        </ConfirmDialog>
      )}
    </>
  )
}

function WorkFormPanel({ projectId, members, onDone }: { projectId: string; members: WorkforceMember[]; onDone: () => void }) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState<Priority>('P3')
  const [memberId, setMemberId] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [status, setStatus] = useState<WorkItemStatus>('DISCUSS')
  const [template, setTemplate] = useState<'' | 'VIDEO'>('')
  const create = useMutation({
    mutationFn: () => api<WorkItem>('/work', { method: 'POST', body: JSON.stringify({ project: projectId, title: title.trim(), description: description.trim() || null, priority, member_id: memberId || null, due_date: dueDate || null, status, template: template || null }) }),
    onSuccess: onDone,
  })
  return (
    <form className="panel-form" onSubmit={(event) => { event.preventDefault(); if (title.trim()) create.mutate() }}>
      <label>Tiêu đề<input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={255} autoFocus required /></label>
      <label>Mô tả<textarea rows={4} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Cần gì, cho ai, xong là thế nào. Không dán tên hay tin nhắn của khách." /></label>
      <div className="panel-form-row">
        <label>Ưu tiên<select value={priority} onChange={(event) => setPriority(event.target.value as Priority)}>{['P0', 'P1', 'P2', 'P3'].map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>Cột<select value={status} onChange={(event) => setStatus(event.target.value as WorkItemStatus)}>{workColumns.filter((column) => column.value !== 'DONE' && column.value !== 'CANCELLED').map((column) => <option key={column.value} value={column.value}>{column.label}</option>)}</select></label>
      </div>
      <div className="panel-form-row">
        <label>Người làm<select value={memberId} onChange={(event) => setMemberId(event.target.value)}><option value="">Chưa giao</option>{members.map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>
        <label>Hạn<input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} /></label>
      </div>
      <label><span>Mẫu quy trình <Hint k="work.template" /></span><select value={template} onChange={(event) => setTemplate(event.target.value as '' | 'VIDEO')}><option value="">Không, một việc đơn</option><option value="VIDEO">Video: Brief, Kịch bản, Quay, Dựng, Duyệt, Đăng</option></select>
        {template === 'VIDEO' && <span className="field-help">Sáu bước thành sáu việc con, cùng ưu tiên; Duyệt và Đăng chỉ Xong khi có link hoặc lý do.</span>}</label>
      {create.error != null && <ErrorNotice error={new Error(workErrorText(create.error))} />}
      <div className="panel-form-actions"><button type="submit" className="button button-primary" disabled={create.isPending || !title.trim()}>{create.isPending ? 'Đang lưu…' : 'Thêm việc'}</button></div>
    </form>
  )
}

function WorkDetailPanel({ workId, decides, members, onChanged, onDone, onOpen, postMode = false }: { workId: string; decides: boolean; members: WorkforceMember[]; onChanged: () => void; onDone: () => void; onOpen: (id: string) => void; postMode?: boolean }) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const detail = useQuery({ queryKey: ['work-detail', workId], queryFn: () => api<WorkDetail>(`/work/${workId}`) })
  const row = detail.data
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState<Priority>('P3')
  const [memberId, setMemberId] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [campaign, setCampaign] = useState('')
  const [urgent, setUrgent] = useState(false)
  const [comment, setComment] = useState('')
  const [linkUrl, setLinkUrl] = useState('')
  const [linkNote, setLinkNote] = useState('')
  const [askingIssue, setAskingIssue] = useState(false)
  const [error, setError] = useState<unknown>()
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['work-detail', workId] }); onChanged() }
  const startEdit = () => { if (!row) return; setTitle(row.title); setDescription(row.description); setPriority(row.priority); setMemberId(row.member_id || ''); setDueDate(row.due_date || ''); setCampaign(row.campaign || ''); setUrgent(row.urgent); setEditing(true) }
  const save = useMutation({
    mutationFn: () => api<WorkItem>(`/work/${workId}`, { method: 'PATCH', body: JSON.stringify({ expected_version: row!.version, title: title.trim(), description, priority, member_id: memberId || null, clear_member: !memberId, due_date: dueDate || null, clear_due: !dueDate, campaign: campaign.trim() || null, clear_campaign: !campaign.trim(), urgent }) }),
    onMutate: () => setError(undefined), onSuccess: () => { setEditing(false); refresh() }, onError: setError,
  })
  // A move that needs a word (dropped, sent back, evidence missing) asks for it here instead of failing.
  const [pendingMove, setPendingMove] = useState<{ id: string; version: number; status: WorkItemStatus; why: string } | null>(null)
  const [moveNote, setMoveNote] = useState('')
  const move = useMutation({
    mutationFn: ({ id, version, status, note }: { id: string; version: number; status: WorkItemStatus; note?: string }) =>
      api<WorkItem>(`/work/${id}/move`, { method: 'POST', body: JSON.stringify({ expected_version: version, status, note: note || null }) }),
    onMutate: () => setError(undefined),
    onSuccess: () => { setPendingMove(null); setMoveNote(''); refresh() },
    onError: (err, vars) => {
      const code = err instanceof ApiError ? err.code : undefined
      if ((code === 'NOTE_REQUIRED' || code === 'EVIDENCE_REQUIRED') && !vars.note) { setPendingMove({ id: vars.id, version: vars.version, status: vars.status, why: code }); return }
      setError(err)
    },
  })
  const requestMove = (target: WorkItem, status: WorkItemStatus) => {
    if (status === target.status) return
    if (status === 'CANCELLED') { setMoveNote(''); setPendingMove({ id: target.id, version: target.version, status, why: 'NOTE_REQUIRED' }); return }
    move.mutate({ id: target.id, version: target.version, status })
  }
  const say = useMutation({
    mutationFn: () => api<WorkDetail>(`/work/${workId}/comments`, { method: 'POST', body: JSON.stringify({ body: comment.trim() }) }),
    onMutate: () => setError(undefined), onSuccess: () => { setComment(''); refresh() }, onError: setError,
  })
  const unsay = useMutation({
    mutationFn: (commentId: string) => api<void>(`/work/${workId}/comments/${commentId}`, { method: 'DELETE' }),
    onMutate: () => setError(undefined), onSuccess: refresh, onError: setError,
  })
  const link = useMutation({
    mutationFn: () => api<WorkDetail>(`/work/${workId}/links`, { method: 'POST', body: JSON.stringify({ url: linkUrl.trim(), note: linkNote.trim() || null }) }),
    onMutate: () => setError(undefined), onSuccess: () => { setLinkUrl(''); setLinkNote(''); refresh() }, onError: setError,
  })
  const unlink = useMutation({
    mutationFn: (linkId: string) => api<void>(`/work/${workId}/links/${linkId}`, { method: 'DELETE' }),
    onMutate: () => setError(undefined), onSuccess: refresh, onError: setError,
  })
  const toIssue = useMutation({
    mutationFn: () => api<WorkDetail>(`/work/${workId}/issue`, { method: 'POST' }),
    onMutate: () => setError(undefined), onSuccess: () => { setAskingIssue(false); refresh() }, onError: setError,
  })
  if (detail.isLoading) return <LoadingBlock />
  if (detail.error != null || !row) return <ErrorNotice error={detail.error || new Error('Không tìm thấy việc')} onRetry={() => { void detail.refetch() }} />
  const closed = row.status === 'DONE' || row.status === 'CANCELLED'
  const mine = Boolean(user?.member_id) && row.member_id === user?.member_id
  const canIssue = decides && row.project_kind === 'SOFTWARE' && !closed && !row.issue_pending && row.outcome !== 'ISSUE'
  return (
    <div className="work-detail">
      <div className="work-detail-head">
        <span className="public-id">{row.code}</span>
        <span className={`status work-status-${postColumnOf(row.status).toLowerCase()}`}>{postMode ? POST_STATUS_LABELS[row.status] : workColumnLabels[row.status]}</span>
        {postMode ? (row.urgent && <span className="post-urgent">Gấp</span>) : <PriorityBadge priority={row.priority} />}
      </div>
      {editing ? (
        <form className="panel-form" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
          <label>Tiêu đề<input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={255} required /></label>
          <label>Mô tả<textarea rows={4} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
          {!postMode && <div className="panel-form-row">
            <label>Ưu tiên<select value={priority} onChange={(event) => setPriority(event.target.value as Priority)}>{['P0', 'P1', 'P2', 'P3'].map((value) => <option key={value}>{value}</option>)}</select></label>
            <label>Hạn<input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} /></label>
          </div>}
          {postMode && <div className="panel-form-row"><label>Chiến dịch<input value={campaign} onChange={(event) => setCampaign(event.target.value)} maxLength={80} /></label><label className="check-line"><input type="checkbox" checked={urgent} onChange={(event) => setUrgent(event.target.checked)} /> Gấp</label></div>}
          <label>Người làm<select value={memberId} onChange={(event) => setMemberId(event.target.value)}><option value="">Chưa giao</option>{members.map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>
          <div className="panel-form-actions">
            <button type="button" className="button button-secondary" onClick={() => setEditing(false)}>Thôi</button>
            <button type="submit" className="button button-primary" disabled={save.isPending || !title.trim()}>{save.isPending ? 'Đang lưu…' : 'Lưu'}</button>
          </div>
        </form>
      ) : (
        <>
          {row.parent_code && row.parent_id && <p className="work-step-of">Bước {row.step_order} · {row.step_label} của <button type="button" className="text-button" onClick={() => onOpen(row.parent_id!)}>{row.parent_code}</button>{row.evidence_required ? ' · cần link hoặc lý do khi Xong' : ''}</p>}
          <h2 className="work-detail-title">{row.title}</h2>
          {row.description ? <p className="work-detail-text">{row.description}</p> : <p className="field-help">Chưa có mô tả.</p>}
          <dl className="work-detail-facts">
            <dt>Người làm</dt><dd>{row.member_name || 'Chưa giao'}</dd>
            {!postMode && <><dt>Hạn</dt><dd>{row.due_date ? formatDay(row.due_date) : 'Chưa đặt'}</dd></>}
            {postMode && row.campaign && <><dt>Chiến dịch</dt><dd>{row.campaign}</dd></>}
            {postMode && row.format && <><dt>Định dạng</dt><dd>{FORMAT_LABELS[row.format] || row.format}</dd></>}
            {!postMode && row.intake_public_id && <><dt>Từ Intake</dt><dd><Link to={`/intakes/${row.intake_id}`}>{row.intake_public_id}</Link></dd></>}
            {row.meeting_id && <><dt>Từ họp</dt><dd><Link to={`/meetings?id=${row.meeting_id}`}>{row.meeting_title || 'Cuộc họp'}</Link>{row.meeting_at ? ` · ${formatDay(row.meeting_at.slice(0, 10))}` : ''}</dd></>}
            {row.issue_external_id && <><dt>Issue</dt><dd>{row.issue_url ? <a href={row.issue_url} target="_blank" rel="noreferrer">{row.issue_system === 'GITHUB' ? 'GitHub' : 'GitLab'} #{row.issue_external_id}</a> : `#${row.issue_external_id}`}</dd></>}
            {row.closed_note && <><dt>{row.status === 'CANCELLED' ? 'Lý do bỏ' : 'Ghi chú'}</dt><dd>{row.closed_note}</dd></>}
            <dt>Tạo</dt><dd>{row.created_by_name || 'hệ thống'} · {formatDate(row.created_at)}</dd>
          </dl>
          {row.template && row.steps.length > 0 && (
            <section className="work-steps-list">
              <h3>Các bước <small>{row.steps_done}/{row.steps_total}</small> <Hint k="work.steps" /></h3>
              <ol>
                {row.steps.map((step) => (
                  <li key={step.id} className={`step-${step.status.toLowerCase()}`}>
                    <button type="button" className="text-button" onClick={() => onOpen(step.id)}>{step.step_order}. {step.step_label}</button>
                    <small>{[step.member_name || 'chưa giao', step.due_date ? `hạn ${formatDay(step.due_date)}` : '', step.link_count ? `${step.link_count} link` : ''].filter(Boolean).join(' · ')}</small>
                    <select aria-label={`Cột của bước ${step.step_label}`} value={step.status} disabled={move.isPending || step.outcome === 'ISSUE'} onChange={(event) => requestMove(step, event.target.value as WorkItemStatus)}>{workColumns.map((column) => <option key={column.value} value={column.value}>{column.label}</option>)}</select>
                  </li>
                ))}
              </ol>
            </section>
          )}
          {pendingMove && (
            <form className="work-move-reason" onSubmit={(event) => { event.preventDefault(); if (moveNote.trim().length >= 3) move.mutate({ id: pendingMove.id, version: pendingMove.version, status: pendingMove.status, note: moveNote.trim() }) }}>
              <label>{pendingMove.why === 'EVIDENCE_REQUIRED' ? 'Bước này cần một link (bản cắt, bài đã đăng). Chưa có link thì ghi lý do:' : pendingMove.status === 'CANCELLED' ? (postMode ? POST_WORDS.dropAsk : 'Lý do bỏ:') : (postMode ? POST_WORDS.sendBackAsk : 'Trả lại thì nói cần sửa gì (sẽ ghi vào Thảo luận):')}
                <textarea rows={2} value={moveNote} onChange={(event) => setMoveNote(event.target.value)} autoFocus /></label>
              {move.error != null && <ErrorNotice error={new Error(workErrorText(move.error))} />}
              <div className="panel-form-actions">
                <button type="button" className="button button-secondary button-small" onClick={() => { setPendingMove(null); setMoveNote('') }}>Thôi</button>
                <button type="submit" className="button button-primary button-small" disabled={move.isPending || moveNote.trim().length < 3}>{pendingMove.status === 'CANCELLED' ? (postMode ? POST_WORDS.drop : 'Bỏ việc') : postMode ? POST_WORDS.sendBack : `Sang ${workColumnLabels[pendingMove.status]}`}</button>
              </div>
            </form>
          )}
          {!postMode && row.issue_pending && <p className="notice notice-info">Đang tạo Issue từ việc này. Khi Issue có, việc chuyển sang Xong. Nếu đồng bộ lỗi, xem ở Intake {row.intake_public_id}.</p>}
          {postMode && !closed && <AgentHint command="draft_post" argument={row.code} />}
          {postMode && <PostChannelsBlock row={row} decides={decides} mine={mine} onChanged={refresh} onError={setError} />}
          <div className="work-detail-actions">
            {postMode ? <PostActions row={row} decides={decides} mine={mine} onMove={(status) => requestMove(row, status)} />
              : row.outcome !== 'ISSUE' && <label><span>Cột <Hint k="work.column_pick" /></span><select value={row.status} disabled={move.isPending} onChange={(event) => requestMove(row, event.target.value as WorkItemStatus)}>{workColumns.map((column) => <option key={column.value} value={column.value}>{column.label}</option>)}</select></label>}
            {decides && !closed && <button type="button" className="button button-secondary button-small" onClick={startEdit}><Pencil size={14} /> Sửa</button>}
            {!postMode && canIssue && <span className="with-hint"><button type="button" className="button button-secondary button-small" onClick={() => setAskingIssue(true)}><ArrowUpRight size={14} /> Tạo Issue</button><Hint k="work.issue" /></span>}
          </div>
        </>
      )}
      {error != null && <ErrorNotice error={new Error(workErrorText(error))} />}
      <section className="work-links">
        <h3>Liên kết <small>{row.links.length}</small> <Hint k="work.links" /></h3>
        {row.links.length === 0 ? <p className="field-help">Thư mục Drive, thiết kế Canva, bản cắt, bài đã đăng: dán link, Intake không giữ tệp.</p> : (
          <ul className="work-link-list">
            {row.links.map((line) => (
              <li key={line.id}>
                <a href={line.url} target="_blank" rel="noreferrer"><Link2 size={13} aria-hidden="true" />{line.note || line.url.replace(/^https?:\/\//, '').slice(0, 60)}</a>
                <small>{dotted([line.source === 'AGENT' ? `agent của ${line.added_by_name || 'ai đó'}` : line.added_by_name || 'ai đó', formatDate(line.created_at)])}</small>
                {(line.mine || user?.role === 'CTO') && <button type="button" className="icon-button" aria-label="Gỡ link" title="Gỡ link" disabled={unlink.isPending} onClick={() => unlink.mutate(line.id)}><Trash2 size={13} /></button>}
              </li>
            ))}
          </ul>
        )}
        <form className="work-link-form" onSubmit={(event) => { event.preventDefault(); if (/^https?:\/\//i.test(linkUrl.trim())) link.mutate() }}>
          <input type="url" value={linkUrl} onChange={(event) => setLinkUrl(event.target.value)} placeholder="https://…" aria-label="Địa chỉ link" />
          <input value={linkNote} onChange={(event) => setLinkNote(event.target.value)} maxLength={300} placeholder="Link này là gì" aria-label="Ghi chú link" />
          <button type="submit" className="button button-secondary button-small" disabled={link.isPending || !/^https?:\/\//i.test(linkUrl.trim())}>{link.isPending ? 'Đang thêm…' : 'Thêm link'}</button>
        </form>
      </section>
      <section className="work-discussion">
        <h3>Thảo luận <small>{row.comments.length}</small> <Hint k="work.discussion" /></h3>
        {row.comments.length === 0 ? <p className="field-help">Chưa ai nói gì. Chỗ này để Project Owner và đội bàn trước khi làm.</p> : (
          <ul className="work-comments">
            {row.comments.map((line) => (
              <li key={line.id}>
                <header><strong>{line.user_name || 'ai đó'}</strong><small>{formatDate(line.created_at)}</small>
                  {(line.mine || user?.role === 'CTO') && <button type="button" className="icon-button" aria-label="Xóa bình luận" title="Xóa bình luận" disabled={unsay.isPending} onClick={() => unsay.mutate(line.id)}><Trash2 size={13} /></button>}
                </header>
                <p>{line.body}</p>
              </li>
            ))}
          </ul>
        )}
        <form className="work-comment-form" onSubmit={(event) => { event.preventDefault(); if (comment.trim().length >= 2) say.mutate() }}>
          <textarea rows={2} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Viết cho đội đọc; không dán tin nhắn hay tên khách." />
          <button type="submit" className="button button-secondary button-small" disabled={say.isPending || comment.trim().length < 2}>{say.isPending ? 'Đang gửi…' : 'Gửi'}</button>
        </form>
      </section>
      <details className="work-history">
        <summary><History size={14} aria-hidden="true" /> Lịch sử <small>{row.history.length} dòng</small></summary>
        <ul className="decision-rows">
          {row.history.map((line, index) => (
            <li key={`${line.at}-${index}`}>
              <span className="decision-kind">{workEventWords[line.event_type] || line.event_type}</span>
              <div><strong>{workEventText(line) || ' '}</strong><small>{dotted([line.actor_name || 'hệ thống', formatDate(line.at)])}</small></div>
            </li>
          ))}
        </ul>
      </details>
      {askingIssue && (
        <ConfirmDialog plain title={`Tạo Issue từ ${row.code}?`} confirmLabel="Tạo Issue" busyLabel="Đang gửi…" busy={toIssue.isPending} error={toIssue.error} onCancel={() => setAskingIssue(false)} onConfirm={() => toIssue.mutate()}>
          <p>{row.intake_public_id ? `Intake ${row.intake_public_id} được quyết định lại sang nơi giao việc của dự án và đưa vào hàng đồng bộ.` : 'Một Intake sẽ được tạo từ việc này, duyệt sang nơi giao việc của dự án và đưa vào hàng đồng bộ.'} Khi Issue tạo xong, việc này chuyển sang Xong và theo dõi tiếp ở GitLab/GitHub.</p>
        </ConfirmDialog>
      )}
      <p className="work-detail-foot"><button type="button" className="text-button" onClick={onDone}>Đóng</button></p>
    </div>
  )
}

// Everyone's door: say what a project you are on (or manage) needs, with pictures; see what became of it. Owners
// and the CTO also read and decide the suggestions of the projects they manage here (FR-FBK-01..03).
function FeedbackPage() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const decides = user?.role === 'CTO' || user?.role === 'PROJECT_OWNER'
  const linked = Boolean(user?.member_id)
  const today = todayInPlanningTimezone()
  // A member's projects come with their day; an owner's with the projects list; both for someone who is both.
  const day = useQuery({ queryKey: ['my-day', today], queryFn: () => api<MyDay>(`/planning/my-day/${today}`), enabled: linked, retry: false })
  const owned = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects'), enabled: decides })
  const mine = useQuery({ queryKey: ['feedback', 'mine'], queryFn: () => api<FeedbackItem[]>('/feedback?mine=true&limit=50') })
  const managed = useQuery({ queryKey: ['feedback', 'managed'], queryFn: () => api<FeedbackItem[]>('/feedback?limit=100'), enabled: decides })
  const projects = useMemo(() => {
    const byId = new Map<string, { id: string; name: string }>()
    for (const project of day.data?.projects || []) byId.set(project.id, { id: project.id, name: project.name })
    for (const project of owned.data || []) if (project.kind === 'SOFTWARE' && project.status === 'ACTIVE') byId.set(project.id, { id: project.id, name: project.name })
    return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name))
  }, [day.data, owned.data])
  const loading = (linked && day.isLoading) || (decides && owned.isLoading)
  const [projectId, setProjectId] = useState('')
  const [text, setText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  const [stage, setStage] = useState<string | null>(null)
  const [error, setError] = useState<unknown>()
  const chosen = projectId || projects[0]?.id || ''
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['feedback'] }); void queryClient.invalidateQueries({ queryKey: ['intakes'] }); void queryClient.invalidateQueries({ queryKey: ['alert-intakes'] }) }
  const submit = async () => {
    setError(undefined)
    try {
      setStage('Đang gửi góp ý…')
      const created = await api<FeedbackItem>('/feedback', { method: 'POST', body: JSON.stringify({ project: chosen, text: text.trim() }) })
      for (let index = 0; index < files.length; index += 1) {
        setStage(`Đang tải ảnh ${index + 1}/${files.length}…`)
        const body = new FormData()
        body.append('file', files[index])
        await api(`/feedback/${created.id}/files`, { method: 'POST', body })
      }
      setText(''); setFiles([])
      if (fileRef.current) fileRef.current.value = ''
      setStage('Đã gửi. Project Owner của dự án sẽ nhận hoặc trả lời; kết quả hiện ở danh sách dưới và qua Telegram nếu bạn đã gắn.')
      refresh()
    } catch (caught) {
      setStage(null); setError(caught)
    }
  }
  const managedRows = managed.data || []
  const pendingManaged = managedRows.filter((row) => row.status === 'PENDING')
  return (
    <>
      <PageHeader title="Góp ý" helper={[
        'Thấy lỗi, thấy việc nên làm cho dự án mình đang ở hoặc mình quản: ghi ở đây, kèm ảnh màn hình nếu có.',
        'Góp ý chưa phải yêu cầu. Project Owner của dự án đọc rồi nhận (thành Intake, AI đọc) hoặc trả lời vì sao chưa.',
        'Cũng gửi được qua Telegram: nhắn "góp ý <mã dự án> ..." hoặc gửi ảnh cho bot; agent dùng tool suggest_intake.',
        ...(decides ? ['Góp ý của dự án anh/chị quản nằm ở khối dưới cùng, kể cả đã quyết; góp ý đang chờ cũng hiện trên "Chờ phê duyệt".'] : []),
      ]} />
      <PageIntro k="feedback" />
      <section className="panel feedback-form">
        <div className="panel-heading"><div><h2>Góp ý mới <Hint k="feedback.new" /></h2></div></div>
        {loading ? <LoadingBlock /> : projects.length === 0 ? <p className="field-help">{decides ? 'Chưa quản dự án phần mềm nào và tài khoản chưa gắn nhân sự.' : 'Bạn chưa thuộc dự án phần mềm nào; nhờ CTO thêm ở Cài đặt › Nhân sự.'}</p> : (
          <div className="feedback-fields">
            <label>Dự án<select value={chosen} onChange={(event) => setProjectId(event.target.value)}>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
            <label>Điều nên làm<textarea rows={5} value={text} maxLength={20000} onChange={(event) => setText(event.target.value)} placeholder="Màn nào, bước nào, thấy gì, mong gì. Càng cụ thể càng dễ nhận." /></label>
            <label>Ảnh hoặc PDF (tối đa 3, mỗi tệp 5 MB)<input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp,application/pdf" multiple onChange={(event) => setFiles(Array.from(event.target.files || []).slice(0, 3))} /></label>
            {files.length > 0 && <p className="field-help">{files.map((file) => file.name).join(' · ')}</p>}
            <div className="project-brief-foot"><span className="field-help">{stage || 'Không ghi tên khách, số điện thoại hay nội dung tin nhắn thật; mô tả bằng lời.'}</span><button type="button" className="button button-primary" disabled={text.trim().length < 5 || !chosen || (stage !== null && stage.startsWith('Đang'))} onClick={() => { void submit() }}>Gửi góp ý</button></div>
            {error != null && <ErrorNotice error={error} />}
          </div>
        )}
      </section>
      <section className="panel feedback-mine">
        <div className="panel-heading"><div><h2>Góp ý của tôi</h2><p>Mới nhất trước.</p></div></div>
        {mine.isLoading ? <LoadingBlock /> : (mine.data || []).length === 0 ? <p className="field-help">Chưa có góp ý nào.</p> : (
          <ul className="feedback-list">{(mine.data || []).map((row) => <FeedbackCard key={row.id} row={row} decide={false} onDone={refresh} linkIntake={decides} />)}</ul>
        )}
      </section>
      {decides && (
        <section className="panel feedback-managed">
          <div className="panel-heading"><div><h2>Góp ý trong dự án tôi quản{pendingManaged.length > 0 ? <> <span className="status">{pendingManaged.length} chờ</span></> : null}</h2><p>Của nhân sự trong các dự án anh/chị quản, kể cả đã nhận hay chưa nhận.</p></div></div>
          {managed.isLoading ? <LoadingBlock /> : managedRows.length === 0 ? <p className="field-help">Chưa có góp ý nào trong dự án anh/chị quản.</p> : (
            <ul className="feedback-list">{managedRows.map((row) => <FeedbackCard key={row.id} row={row} decide onDone={refresh} linkIntake />)}</ul>
          )}
        </section>
      )}
    </>
  )
}

// Areas still changing: marked Beta in the menu and switched off by BETA_FEATURES_ENABLED.
const BETA_PATHS = ['/viec', '/tuan-nay', '/duyet', '/nguon', '/rieng/nguon']
function isBetaPath(to: string) { return BETA_PATHS.includes(to) }

function BetaOnly() {
  const { user } = useAuth()
  const shell = useOutletContext<ShellContext>()
  return user?.beta_features_enabled === false ? <NotFoundPage /> : <Outlet context={shell} />
}

function NotFoundPage() {
  return <EmptyState icon={<CircleHelp size={20} />} title="Không tìm thấy trang" text="Đường dẫn này không tồn tại trong Private Intake." />
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/welcome" element={<WelcomePage />} />
        <Route element={<ProtectedLayout />}>
          <Route index element={<TodayPage />} />
          <Route path="intakes/new" element={<NewIntakePage />} />
          <Route path="intakes" element={<IntakeListPage />} />
          <Route path="intakes/:id" element={<IntakeDetailPage />} />
          <Route path="planning" element={<PlanningPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="approvals" element={<ApprovalQueuePage />} />
          <Route path="meetings" element={<MeetingsPage />} />
          <Route path="changelog" element={<ChangelogPage />} />
          <Route path="tuan-qua" element={<WeekPage />} />
          <Route path="nghiem-thu" element={<AcceptancePage />} />
          <Route path="viec-rieng" element={<PersonalTasksPage />} />
          <Route path="viec-cua-toi" element={<MyDayPage />} />
          <Route path="gop-y" element={<FeedbackPage />} />
          <Route element={<BetaOnly />}>
            <Route path="viec" element={<WorkBoardPage />} />
            <Route path="tuan-nay" element={<WeekBoardPage />} />
            <Route path="duyet" element={<ReviewPage />} />
            <Route path="nguon" element={<WatchSourcesPage />} />
          </Route>
          <Route path="huong-dan" element={<GuidePage />} />
          <Route element={<ProjectManagerOnly />}>
            <Route path="projects" element={<ManagedProjectsPage />} />
            <Route path="projects/:code" element={<ProjectDetailsPage />} />
          </Route>
          <Route element={<CtoOnly />}>
            <Route path="setup" element={<SetupPage />} />
          </Route>
          <Route path="rieng" element={<CtoOnly />}>
            <Route index element={<PrivateIdeasPage />} />
            <Route path="y/:id" element={<PrivateIdeaPage />} />
            <Route path="giong" element={<PrivateVoicePage />} />
            <Route element={<BetaOnly />}>
              <Route path="nguon" element={<PrivateWatchPage />} />
            </Route>
          </Route>
          <Route path="settings" element={<SettingsLayout />}>
            <Route index element={<SettingsIndex />} />
            <Route element={<CtoOnly />}>
              <Route path="projects" element={<ProjectsPage />} />
              <Route path="projects/new" element={<ProjectWizardPage />} />
              <Route path="projects/:code" element={<ProjectEditPage />} />
              <Route path="members" element={<MembersSettings />} />
              <Route path="users" element={<UsersSettings />} />
              <Route path="ai" element={<AiSettings />} />
              <Route path="system" element={<SystemSettings />} />
              <Route element={<BetaOnly />}>
                <Route path="channels" element={<ChannelRulesPage />} />
                <Route path="watch" element={<WatchPlatformsPage />} />
              </Route>
            </Route>
            <Route path="glossary" element={<GlossarySettings />} />
            <Route path="account" element={<AccountPage />} />
          </Route>
          <Route path="account" element={<Navigate to="/settings/account" replace />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </AuthProvider>
  )
}
