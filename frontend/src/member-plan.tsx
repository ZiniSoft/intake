// One person's plan across projects and days, read only (FR-PLAN-40, ADR-0081).
// The server decides what the viewer may see: projects they do not share come back as a name and hours only,
// and someone else's personal tasks come back as hours only.
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, ExternalLink } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, formatError } from './api'
import type { MemberPlan, MemberPlanDay, MemberPlanItem, PlanPeople, WorkItemStatus } from './types'

type PlanView = 'ngay' | 'tuan' | 'thang'

const WEEKDAYS = ['Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ nhật']
const WEEKDAYS_SHORT = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']
const ASSIGNMENT_STATUS: Record<string, string> = { PLANNED: 'Chưa bắt đầu', IN_PROGRESS: 'Đang làm', DONE: 'Xong', BLOCKED: 'Bị chặn' }
const WORK_STATUS: Record<WorkItemStatus, string> = {
  DISCUSS: 'Cần bàn', READY: 'Sẵn sàng', IN_PROGRESS: 'Đang làm', ACCEPTANCE: 'Chờ nghiệm thu', APPROVED: 'Đã duyệt', DONE: 'Xong', CANCELLED: 'Bỏ',
}
const PERSONAL_STATUS: Record<string, string> = { PLANNED: 'Chưa làm', DONE: 'Xong', SKIPPED: 'Bỏ qua' }
const SLOTS: Record<string, string> = { MORNING: 'Sáng', AFTERNOON: 'Chiều' }

const hours = (value: number) => (Number.isInteger(value) ? `${value}` : value.toFixed(1))
const parseDay = (value: string) => new Date(`${value}T00:00:00Z`)
const formatDay = (date: Date) => date.toISOString().slice(0, 10)
const addDays = (value: string, days: number) => { const date = parseDay(value); date.setUTCDate(date.getUTCDate() + days); return formatDay(date) }
const weekdayIndex = (value: string) => (parseDay(value).getUTCDay() + 6) % 7
const dayMonth = (value: string) => { const date = parseDay(value); return `${date.getUTCDate()}/${date.getUTCMonth() + 1}` }
const isDay = (value: string | null): value is string => Boolean(value && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(parseDay(value).getTime()))

function todayInVietnam() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
}

// The days a view covers: one day, Monday to Sunday, or the calendar month.
export function planRange(view: PlanView, day: string): { from: string; to: string } {
  if (view === 'ngay') return { from: day, to: day }
  if (view === 'tuan') { const from = addDays(day, -weekdayIndex(day)); return { from, to: addDays(from, 6) } }
  const date = parseDay(day)
  const from = formatDay(new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1)))
  const to = formatDay(new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)))
  return { from, to }
}

function shiftPeriod(view: PlanView, day: string, step: 1 | -1) {
  if (view === 'ngay') return addDays(day, step)
  if (view === 'tuan') return addDays(day, 7 * step)
  const date = parseDay(day)
  return formatDay(new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + step, 1)))
}

function periodLabel(view: PlanView, from: string, to: string) {
  const year = parseDay(to).getUTCFullYear()
  if (view === 'ngay') return `${WEEKDAYS[weekdayIndex(from)]} ${dayMonth(from)}/${year}`
  if (view === 'tuan') return `Tuần ${dayMonth(from)} - ${dayMonth(to)}/${year}`
  return `Tháng ${parseDay(from).getUTCMonth() + 1}/${year}`
}

function Notice({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const requestId = error instanceof ApiError ? error.requestId : undefined
  const missing = error instanceof ApiError && error.code === 'MEMBER_NOT_FOUND'
  return (
    <div className="notice notice-error notice-with-action" role="alert">
      <div><strong>{missing ? 'Bạn không xem được kế hoạch của người này.' : formatError(error)}</strong>{requestId && <small>Request ID: {requestId}</small>}</div>
      {!missing && <button className="button button-secondary button-small" type="button" onClick={onRetry}>Thử lại</button>}
    </div>
  )
}

function Loading() {
  return <div className="loading-block"><span className="spinner" />Đang tải dữ liệu…</div>
}

function PlanItem({ item, day, compact }: { item: MemberPlanItem; day: string; compact: boolean }) {
  if (item.kind === 'PERSONAL') {
    return (
      <li className={`mp-item mp-personal is-${item.status.toLowerCase()}`}>
        <span className="mp-kind">Việc riêng</span>
        <span className="mp-title">{item.title}</span>
        {!compact && <small>{[item.start_time, item.hours > 0 ? `${hours(item.hours)} giờ` : '', PERSONAL_STATUS[item.status] || item.status].filter(Boolean).join(' · ')}</small>}
      </li>
    )
  }
  if (item.kind === 'WORK_ITEM') {
    return (
      <li className={`mp-item mp-work${item.closed ? ' is-closed' : ''}`}>
        <span className="mp-kind">{item.channel ? 'Bài' : 'Việc'} {item.code}</span>
        <Link className="mp-title" to={`/viec?project=${item.project_id}&work=${item.id}`}>{item.title}</Link>
        {compact ? <small>{item.project_name} · {WORK_STATUS[item.status] || item.status}</small> : <small>{[item.project_name, WORK_STATUS[item.status] || item.status, item.closed ? 'đã đóng' : item.due_date ? `hạn ${dayMonth(item.due_date)}` : '', item.urgent ? 'khẩn' : ''].filter(Boolean).join(' · ')}</small>}
      </li>
    )
  }
  return (
    <li className={`mp-item mp-assignment is-${item.status.toLowerCase()}`}>
      <span className="mp-kind">{item.priority || 'Việc'}{item.slot && SLOTS[item.slot] ? ` · ${SLOTS[item.slot]}` : ''} · {hours(item.hours)}h</span>
      <Link className="mp-title" to={`/planning?project=${item.project_id}&date=${day}`}>{item.title}</Link>
      {compact ? <small>{item.project_name}{item.status !== 'PLANNED' ? ` · ${ASSIGNMENT_STATUS[item.status] || item.status}` : ''}</small> : (
        <small>
          {[item.project_name, ASSIGNMENT_STATUS[item.status] || item.status, item.accepted_at ? 'đã nghiệm thu' : '', ['DRAFT', 'REVIEW_REQUIRED'].includes(item.run_status) ? 'kế hoạch nháp' : ''].filter(Boolean).join(' · ')}
          {item.issue && (item.issue_url
            ? <> · <a href={item.issue_url} target="_blank" rel="noreferrer">#{item.issue} <ExternalLink size={11} /></a></>
            : <> · #{item.issue}</>)}
        </small>
      )}
    </li>
  )
}

function DayBlock({ day, isMe, compact, today }: { day: MemberPlanDay; isMe: boolean; compact: boolean; today: string }) {
  const empty = day.items.length === 0 && day.hidden_projects.length === 0 && (isMe || day.personal_hours <= 0)
  const over = day.planned_hours > day.available_hours && day.planned_hours > 0
  return (
    <section className={`mp-day${day.off ? ' is-off' : ''}${day.date === today ? ' is-today' : ''}`} aria-label={`${WEEKDAYS[weekdayIndex(day.date)]} ${dayMonth(day.date)}`}>
      <header>
        <strong>{compact ? WEEKDAYS_SHORT[weekdayIndex(day.date)] : WEEKDAYS[weekdayIndex(day.date)]} {dayMonth(day.date)}</strong>
        <span className={over ? 'mp-hours is-over' : 'mp-hours'}>{day.off && day.planned_hours === 0 ? 'Nghỉ' : `${hours(day.planned_hours)}/${hours(day.available_hours)} giờ`}</span>
      </header>
      {empty ? <p className="mp-empty">{day.off ? 'Ngày nghỉ' : 'Chưa có việc'}</p> : (
        <ul>
          {day.items.map((item) => <PlanItem key={`${item.kind}-${item.id}`} item={item} day={day.date} compact={compact} />)}
          {day.hidden_projects.map((project) => <li key={`hidden-${project.name}`} className="mp-item mp-hidden"><span className="mp-title">{project.name}: {hours(project.hours)} giờ</span></li>)}
          {!isMe && day.personal_hours > 0 && <li className="mp-item mp-hidden"><span className="mp-title">Việc riêng: {hours(day.personal_hours)} giờ</span></li>}
        </ul>
      )}
    </section>
  )
}

function MonthGrid({ plan, today, onPick }: { plan: MemberPlan; today: string; onPick: (day: string) => void }) {
  const lead = weekdayIndex(plan.from)
  const cells: (MemberPlanDay | null)[] = [...Array.from({ length: lead }, () => null), ...plan.days]
  while (cells.length % 7 !== 0) cells.push(null)
  return (
    <div className="mp-month" role="grid" aria-label="Lịch tháng">
      {WEEKDAYS_SHORT.map((name) => <div key={name} className="mp-month-head" role="columnheader">{name}</div>)}
      {cells.map((day, index) => {
        if (!day) return <div key={`pad-${index}`} className="mp-month-cell is-pad" />
        const count = day.items.length + day.hidden_projects.length
        const over = day.planned_hours > day.available_hours && day.planned_hours > 0
        return (
          <button key={day.date} type="button" role="gridcell" className={`mp-month-cell${day.off ? ' is-off' : ''}${day.date === today ? ' is-today' : ''}${over ? ' is-over' : ''}`} onClick={() => onPick(day.date)} aria-label={`Xem ngày ${dayMonth(day.date)}`}>
            <strong>{parseDay(day.date).getUTCDate()}</strong>
            <span>{day.off && day.planned_hours === 0 ? 'Nghỉ' : `${hours(day.planned_hours)}/${hours(day.available_hours)}h`}</span>
            {count > 0 && <small>{count} việc</small>}
          </button>
        )
      })}
    </div>
  )
}

function Totals({ plan }: { plan: MemberPlan }) {
  const { totals } = plan
  const statusParts = Object.entries(totals.work_status).filter(([, count]) => count > 0).map(([status, count]) => `${ASSIGNMENT_STATUS[status] || status} ${count}`)
  const workParts = Object.entries(totals.work_items).filter(([, count]) => (count || 0) > 0).map(([status, count]) => `${WORK_STATUS[status as WorkItemStatus] || status} ${count}`)
  return (
    <div className="mp-totals" aria-label="Tổng kỳ">
      <div><span>Đã xếp</span><strong className={totals.planned_hours > totals.available_hours ? 'text-warn' : undefined}>{hours(totals.planned_hours)}/{hours(totals.available_hours)} giờ</strong></div>
      <div><span>Việc riêng</span><strong>{hours(totals.personal_hours)} giờ</strong></div>
      <div><span>Ngày nghỉ</span><strong>{totals.off_days}</strong></div>
      <div><span>Nghiệm thu</span><strong>{totals.accepted}</strong></div>
      {totals.by_project.length > 0 && (
        <p className="mp-projects">Theo dự án: {totals.by_project.map((project) => <span key={project.name} className={project.visible ? 'mp-chip' : 'mp-chip is-hidden'} title={project.visible ? undefined : 'Bạn không chung dự án này: chỉ thấy tên và giờ'}>{project.name} {hours(project.hours)}h</span>)}</p>
      )}
      {statusParts.length > 0 && <p className="mp-projects">Việc trong kế hoạch: {statusParts.join(' · ')}</p>}
      {workParts.length > 0 && <p className="mp-projects">Việc ở khu Việc: {workParts.join(' · ')}</p>}
    </div>
  )
}

export function MemberPlanPage() {
  const [params, setParams] = useSearchParams()
  const today = todayInVietnam()
  const viewParam = params.get('view')
  const view: PlanView = viewParam === 'ngay' || viewParam === 'thang' ? viewParam : 'tuan'
  const dateParam = params.get('date')
  const day = isDay(dateParam) ? dateParam : today
  const people = useQuery({ queryKey: ['plan-people'], queryFn: () => api<PlanPeople>('/planning/people') })
  const members = people.data?.members || []
  const memberId = params.get('member') || people.data?.me || members[0]?.member_id || ''
  const range = planRange(view, day)
  const plan = useQuery({
    queryKey: ['member-plan', memberId, range.from, range.to],
    queryFn: () => api<MemberPlan>(`/planning/people/${memberId}/plan?from=${range.from}&to=${range.to}`),
    enabled: Boolean(memberId),
  })
  const update = (changes: Record<string, string>) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) next.set(key, value)
    if (!next.get('member') && memberId) next.set('member', memberId)
    setParams(next, { replace: true })
  }
  const listed = members.some((member) => member.member_id === memberId)

  return (
    <div className="member-plan">
      <div className="panel mp-toolbar">
        <label className="mp-person">Người
          <select value={memberId} onChange={(event) => update({ member: event.target.value })} disabled={people.isLoading || members.length === 0}>
            {!listed && memberId && <option value={memberId}>Người không có trong danh sách</option>}
            {members.map((member) => <option key={member.member_id} value={member.member_id}>{member.display_name}{member.is_me ? ' (tôi)' : ''}</option>)}
          </select>
        </label>
        <div className="segmented" role="group" aria-label="Xem theo">
          {([['ngay', 'Ngày'], ['tuan', 'Tuần'], ['thang', 'Tháng']] as const).map(([value, label]) => (
            <button key={value} type="button" aria-pressed={view === value} className={view === value ? 'active' : undefined} onClick={() => update({ view: value })}>{label}</button>
          ))}
        </div>
        <div className="mp-nav">
          <button type="button" className="button button-secondary button-small" aria-label="Kỳ trước" onClick={() => update({ date: shiftPeriod(view, day, -1) })}><ChevronLeft size={15} /></button>
          <button type="button" className="button button-secondary button-small" onClick={() => update({ date: today })}>Hôm nay</button>
          <button type="button" className="button button-secondary button-small" aria-label="Kỳ sau" onClick={() => update({ date: shiftPeriod(view, day, 1) })}><ChevronRight size={15} /></button>
          <strong className="mp-period">{periodLabel(view, range.from, range.to)}</strong>
        </div>
      </div>
      {people.error != null && <Notice error={people.error} onRetry={() => { void people.refetch() }} />}
      {people.isLoading ? <Loading /> : !memberId ? (
        <div className="panel mp-none"><p>Chưa có ai để xem: bạn chưa chung dự án nào với ai, và tài khoản chưa gắn với nhân sự.</p></div>
      ) : plan.error != null ? <Notice error={plan.error} onRetry={() => { void plan.refetch() }} /> : plan.isLoading || !plan.data ? <Loading /> : (
        <>
          <Totals plan={plan.data} />
          {view === 'thang'
            ? <MonthGrid plan={plan.data} today={today} onPick={(picked) => update({ view: 'ngay', date: picked })} />
            : <div className={view === 'tuan' ? 'mp-week' : 'mp-single'}>{plan.data.days.map((row) => <DayBlock key={row.date} day={row} isMe={plan.data.member.is_me} compact={view === 'tuan'} today={today} />)}</div>}
          <p className="field-help">Chỉ xem. Ở dự án bạn không chung với người này, bạn chỉ thấy tên dự án và số giờ. Việc riêng của người khác chỉ hiện số giờ. Việc ở khu Việc nằm ở ngày đóng, hoặc ở hạn nếu còn mở.</p>
        </>
      )}
    </div>
  )
}
