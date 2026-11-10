import { ReactNode, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ALL_HINTS, ALL_INTROS } from './hints'
import { HINTS_EN, INTROS_EN } from './hints_en'
import { Locale, useLocale } from './i18n'

// The user guide in one place (FR-UI-18): the signed-in page, the public page at /huong-dan and the static copy on
// GitHub Pages all render this module, so a change to the words reaches the three at once.
// Every text is a pair [Vietnamese, English].

export type Bi = readonly [string, string]
const pick = (locale: Locale, value: Bi) => (locale === 'en' ? value[1] : value[0])

export const GUIDE_REPO_URL = 'https://github.com/ZiniSoft/intake' // export-gate: allow (public repository)

const LOOP_STEPS = [
  { number: '01', title: ['Tiếp nhận', 'Capture'], actor: ['Con người', 'People'], tone: 'human', text: ['Gom góp ý, email, Telegram, cuộc họp, ảnh và ghi chú vào một nơi riêng tư.', 'Collect feedback, email, Telegram messages, meetings, pictures and notes in one private place.'] },
  { number: '02', title: ['Chuẩn hóa', 'Normalize'], actor: ['AI đề xuất', 'AI suggests'], tone: 'ai', text: ['AI đọc nguồn và đề xuất tiêu đề, mô tả, ưu tiên cùng câu hỏi còn thiếu.', 'AI reads the source and suggests a title, a description, a priority and the questions still open.'] },
  { number: '03', title: ['Duyệt', 'Approve'], actor: ['Người quyết', 'Decision maker'], tone: 'human', text: ['CTO hoặc Project Owner làm rõ và chọn nơi xử lý. AI không tự gửi việc ra ngoài.', 'The CTO or a Project Owner clarifies and picks where the work goes. AI never sends work out on its own.'] },
  { number: '04', title: ['Thực hiện', 'Deliver'], actor: ['Người làm + agent', 'People + agents'], tone: 'mixed', text: ['Issue, kế hoạch ngày và agent cùng đưa việc đến người làm, có trạng thái và bằng chứng.', 'Issues, the daily plan and agents bring work to the people doing it, with status and evidence.'] },
  { number: '05', title: ['Nghiệm thu', 'Accept'], actor: ['Người xác nhận', 'Reviewer'], tone: 'human', text: ['Kiểm kết quả bằng bằng chứng, xác nhận hoặc trả lại đúng bước để làm tiếp.', 'Check the result against evidence, then confirm it or send it back to the right step.'] },
] as const satisfies readonly { number: string; title: Bi; actor: Bi; tone: string; text: Bi }[]

export function IntakeWorkLoop() {
  const { locale } = useLocale()
  const t = (value: Bi) => pick(locale, value)
  const root = useRef<HTMLDivElement>(null)
  const [active, setActive] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [played, setPlayed] = useState(false)
  const [reducedMotion, setReducedMotion] = useState(false)
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setReducedMotion(media.matches)
    update()
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  useEffect(() => {
    if (reducedMotion || played || !root.current) return
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return
      setPlayed(true)
      setPlaying(true)
      observer.disconnect()
    }, { threshold: 0.35 })
    observer.observe(root.current)
    return () => observer.disconnect()
  }, [played, reducedMotion])
  useEffect(() => {
    if (!playing) return
    setActive(0)
    let index = 0
    const timer = window.setInterval(() => {
      index += 1
      if (index >= LOOP_STEPS.length) {
        window.clearInterval(timer)
        setPlaying(false)
        return
      }
      setActive(index)
    }, 1250)
    return () => window.clearInterval(timer)
  }, [playing])
  const current = LOOP_STEPS[active]
  return (
    <div ref={root} className={`intake-loop${playing ? ' is-playing' : ''}`}>
      <div className="intake-loop-head"><div><strong>{t(['Năm bước thành một vòng lặp công việc', 'Five steps, one work loop'])}</strong><span>{playing ? t(['Đang minh họa một lượt', 'Playing one round']) : t(['Bấm từng bước để xem giải thích', 'Select a step to read what happens'])}</span></div><span>{active + 1}/{LOOP_STEPS.length}</span></div>
      <ol className="intake-flow-steps" aria-label={t(['Năm bước trong vòng lặp công việc của Intake', 'The five steps of the Intake work loop'])}>
        {LOOP_STEPS.map((step, index) => <li key={step.number} className={`intake-flow-step is-${step.tone}${index === active ? ' is-active' : ''}${index < active ? ' is-complete' : ''}`}>
          <button type="button" aria-pressed={index === active} aria-label={`${step.number}. ${t(step.title)}: ${t(step.text)}`} onClick={() => { setPlaying(false); setPlayed(true); setActive(index) }}>
            <span>{step.number}</span><strong>{t(step.title)}</strong><small>{t(step.actor)}</small>
          </button>
        </li>)}
      </ol>
      <div className="intake-flow-return" aria-label={t(['Kết quả chưa đạt sẽ quay lại đúng bước cần làm tiếp', 'A result that falls short goes back to the step that needs more work'])}>
        <svg viewBox="0 0 100 18" preserveAspectRatio="none" aria-hidden="true" focusable="false"><defs><marker id="intake-return-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto"><path d="M 0 0 L 8 4 L 0 8 z" /></marker></defs><path d="M 92 2 C 92 15, 8 15, 8 2" markerEnd="url(#intake-return-arrow)" /></svg>
        <span>{t(['Chưa đạt thì quay lại đúng bước, không làm lại từ đầu', 'Not good enough? Back to the right step, not to the start'])}</span>
      </div>
      <div className={`intake-flow-detail is-${current.tone}`} key={current.number}>
        <span>{current.number}</span><div><small>{t(current.actor)}</small><strong>{t(current.title)}</strong><p>{t(current.text)}</p></div>
      </div>
      <div className="intake-loop-legend"><span><i className="is-ai" />{t(['AI đề xuất', 'AI suggests'])}</span><span><i className="is-human" />{t(['Con người xác nhận', 'People confirm'])}</span><span><i className="is-mixed" />{t(['Người làm và agent', 'People and agents'])}</span></div>
    </div>
  )
}

const ROLES: readonly { role: Bi; start: Bi; text: Bi }[] = [
  { role: ['CTO', 'CTO'], start: ['Hôm nay', 'Today'], text: ['Xem việc quá hạn, yêu cầu chờ duyệt, kế hoạch chưa chốt và việc chờ nghiệm thu trên toàn hệ thống.', 'See overdue work, requests waiting for approval, plans not yet locked and work waiting for acceptance across every project.'] },
  { role: ['Project Owner', 'Project Owner'], start: ['Hôm nay và Dự án', 'Today and Projects'], text: ['Duyệt yêu cầu trong dự án, quản lý đội, xếp kế hoạch, phân công và xác nhận kết quả.', 'Approve requests in your projects, manage the team, plan the day, assign work and confirm results.'] },
  { role: ['Thành viên', 'Team member'], start: ['Việc của tôi', 'My work'], text: ['Nhận việc theo ưu tiên, báo Đang làm, Xong hoặc Bị chặn; gửi góp ý và báo cáo cuối ngày.', 'Pick up work by priority, report In progress, Done or Blocked, send feedback and an end-of-day report.'] },
  { role: ['Agent', 'Agent'], start: ['Tài khoản và agent', 'Account and agents'], text: ['Dùng token cá nhân và lệnh ngắn để đọc việc hôm nay, đề xuất việc, ghi tiến độ và soạn báo cáo.', 'Uses a personal token and short commands to read today\'s work, propose work, log progress and draft the report.'] },
]

const FEATURES: readonly { area: Bi; value: Bi; status: Bi; tone: string }[] = [
  { area: ['Tiếp nhận và duyệt', 'Capture and approval'], value: ['Form, email, cuộc họp, ảnh/PDF, AI chuẩn hóa, làm rõ, duyệt, hoãn, từ chối và đánh dấu trùng.', 'Form, email, meetings, pictures and PDFs, AI normalization, clarification, approve, defer, reject and mark as duplicate.'], status: ['Lõi', 'Core'], tone: 'core' },
  { area: ['Nơi thực hiện', 'Where work happens'], value: ['Đồng bộ GitLab/GitHub hoặc bảng Việc nội bộ sáu cột, có thảo luận, link và lịch sử.', 'Sync with GitLab or GitHub, or a six-column internal Work board with discussion, links and history.'], status: ['Lõi', 'Core'], tone: 'core' },
  { area: ['Daily Planning', 'Daily planning'], value: ['Sức chứa theo người, kế hoạch sáng/chiều, việc chờ phân công, chốt kế hoạch và chuyển tiếp việc dở.', 'Capacity per person, morning and afternoon plans, work waiting for assignment, plan lock and carry-over of unfinished work.'], status: ['Lõi', 'Core'], tone: 'core' },
  { area: ['Báo cáo và nghiệm thu', 'Reports and acceptance'], value: ['Đọc báo cáo ngày, đối chiếu Issue, gom bằng chứng và xác nhận hoặc trả lại kết quả.', 'Read daily reports, match them to Issues, gather evidence and confirm or return the result.'], status: ['Lõi', 'Core'], tone: 'core' },
  { area: ['Cuộc họp và thông báo', 'Meetings and notifications'], value: ['Ghi âm hoặc tải audio, biên bản có người nói, tạo Intake từ mục hành động và nhắc qua Telegram.', 'Record or upload audio, get minutes with speakers, turn action items into Intakes and get reminders on Telegram.'], status: ['Tùy chọn', 'Optional'], tone: 'optional' },
  { area: ['Agent và MCP', 'Agents and MCP'], value: ['Công cụ cho Codex, Claude Code và luồng tự động đọc kế hoạch, tạo yêu cầu, cập nhật việc và ghi lịch sử.', 'Tools for Codex, Claude Code and automations to read the plan, create requests, update work and log history.'], status: ['Tùy chọn', 'Optional'], tone: 'optional' },
  { area: ['Nội dung và nguồn theo dõi', 'Content and watched sources'], value: ['Trụ nội dung, bài theo kênh, chủ đề nóng, nguồn quét và không gian giọng viết riêng.', 'Content pillars, posts per channel, hot topics, watched sources and a private writing-voice space.'], status: ['Beta', 'Beta'], tone: 'beta' },
  { area: ['Tự lưu trữ và bảo mật', 'Self-hosting and security'], value: ['Docker, phân quyền theo dự án, MFA, token cá nhân, mã hóa dữ liệu nhạy cảm, backup và restore có kiểm tra.', 'Docker, per-project permissions, MFA, personal tokens, encryption of sensitive data, verified backup and restore.'], status: ['Nền tảng', 'Foundation'], tone: 'foundation' },
]

// Written for people outside the team: what changed for a user, without internal projects or retired tools.
const HISTORY_GROUPS: readonly { title: Bi; latest: string; tone: string; entries: readonly { date: string; title: Bi; text: Bi }[] }[] = [
  {
    title: ['Thiết lập và trải nghiệm bắt đầu', 'Setup and first run'], latest: '06/11/2026', tone: 'onboarding', entries: [
      { date: '06/11/2026', title: ['Hướng dẫn công khai Anh - Việt', 'Public guide in English and Vietnamese'], text: ['Trang hướng dẫn mở được không cần đăng nhập, có bản tĩnh trên GitHub Pages để chia sẻ.', 'The guide opens without signing in, with a static copy on GitHub Pages to share.'] },
      { date: '06/11/2026', title: ['Cấu hình AI theo ba nhóm việc', 'AI setup in three groups'], text: ['Chọn model riêng cho chữ, ảnh và giọng nói; mỗi nhóm kiểm bằng mẫu thật và báo rõ khi model không còn hoặc không đọc được ảnh.', 'Pick a model for text, pictures and speech; each group is checked with a real sample and says clearly when a model is gone or cannot read pictures.'] },
      { date: '04/11/2026', title: ['Trình hướng dẫn ba bước và dự án mẫu', 'Three-step walkthrough and a sample project'], text: ['Bản cài mới dùng thử được ngay với dự án mẫu, không cần khóa AI; menu gọn lúc đầu và mở rộng khi đã quen.', 'A fresh install can be tried at once on a sample project, without an AI key; the menu starts small and grows when you are ready.'] },
      { date: '31/10/2026', title: ['Chọn nhà cung cấp và model dễ hơn', 'Easier provider and model choice'], text: ['Kiểm tra kết nối, tải danh sách model và chỉ cần một model mặc định cho lần thiết lập đầu.', 'Test the connection, load the model list and set just one default model the first time.'] },
      { date: '27/10/2026', title: ['Cài một lệnh và tạo tài khoản trên web', 'One-command install and web account setup'], text: ['Trình cài tự sinh secret, chỉ mở ở localhost lúc đầu và dẫn từng bước tạo CTO, Project Owner và khóa AI.', 'The installer generates secrets, listens on localhost only at first and walks you through the CTO, a Project Owner and the AI key.'] },
      { date: '25/10/2026', title: ['Màn thiết lập đầu tiên', 'First-run setup screen'], text: ['Tạo dự án đầu tiên, nối repository GitLab/GitHub hoặc bắt đầu với một dự án trống.', 'Create the first project, connect a GitLab or GitHub repository, or start with an empty project.'] },
    ],
  },
  {
    title: ['Dự án và đội ngũ', 'Projects and people'], latest: '03/11/2026', tone: 'people', entries: [
      { date: '03/11/2026', title: ['Nhân sự theo dự án', 'People per project'], text: ['Thêm nhiều người một lần, gắn tài khoản GitLab/GitHub và xem chi tiết Telegram trên từng người.', 'Add several people at once, link their GitLab or GitHub accounts and see Telegram details per person.'] },
      { date: '30/10/2026', title: ['Quản lý thành viên ngay trong dự án', 'Manage members inside a project'], text: ['CTO và Project Owner thêm hoặc gỡ người đúng phạm vi mà không xóa hồ sơ, tài khoản hay lịch sử.', 'The CTO and Project Owners add or remove people within their scope without deleting profiles, accounts or history.'] },
    ],
  },
  {
    title: ['Bảo mật và vận hành', 'Security and operations'], latest: '31/10/2026', tone: 'security', entries: [
      { date: '31/10/2026', title: ['Khu nội dung Beta tách riêng', 'Beta content area kept apart'], text: ['Khu nội dung và nguồn theo dõi tắt mặc định và không ảnh hưởng các dự án phần mềm khi chưa bật.', 'The content and watched-sources area is off by default and does not touch software projects until you turn it on.'] },
      { date: '30/10/2026', title: ['Phát hành mã nguồn mở', 'Open-source release'], text: ['Giấy phép Apache-2.0, README Anh - Việt, demo dữ liệu hư cấu và cổng quét secret trước mỗi lần phát hành.', 'Apache-2.0 license, README in English and Vietnamese, a demo with fictional data and a secret scan before every release.'] },
      { date: '30/10/2026', title: ['Gia cố tài khoản, restore và Telegram', 'Hardened accounts, restore and Telegram'], text: ['Đổi mật khẩu thì thu hồi phiên và token, kiểm archive trước khi restore và che token bot khỏi log.', 'Changing a password revokes sessions and tokens, archives are checked before restore and bot tokens are kept out of logs.'] },
    ],
  },
  {
    title: ['Intake, phê duyệt và nghiệm thu', 'Intake, approval and acceptance'], latest: '30/10/2026', tone: 'intake', entries: [
      { date: '30/10/2026', title: ['Đánh dấu trùng với Issue đã có', 'Mark as duplicate of an existing Issue'], text: ['Đóng Intake trùng bằng số Issue ngay cả khi AI không gợi ý, vẫn giữ lịch sử truy vết.', 'Close a duplicate Intake with an Issue number even when AI did not suggest it, keeping the trail.'] },
      { date: '29/10/2026', title: ['Project Owner xác nhận xong xuyên suốt', 'Project Owner sign-off everywhere'], text: ['Kết quả được phản ánh nhất quán trên Intake, kế hoạch và hàng nghiệm thu.', 'The result shows the same way on the Intake, the plan and the acceptance queue.'] },
      { date: '21/10/2026', title: ['Tám chặng quản lý Intake', 'Eight stages for an Intake'], text: ['Tiếp nhận, làm rõ, duyệt, xếp việc, thực hiện và nghiệm thu dùng cùng một trạng thái trên mọi màn.', 'Capture, clarify, approve, schedule, deliver and accept use the same status on every screen.'] },
      { date: '14/10/2026', title: ['Đọc ảnh và PDF bằng AI vision', 'Pictures and PDFs read by AI vision'], text: ['Ảnh chat, giao diện, chữ tay và PDF scan được ghép vào nguồn để AI chuẩn hóa cùng yêu cầu.', 'Chat screenshots, UI captures, handwriting and scanned PDFs join the source so AI normalizes them with the request.'] },
    ],
  },
  {
    title: ['Kế hoạch, Việc và agent', 'Planning, Work and agents'], latest: '22/10/2026', tone: 'delivery', entries: [
      { date: '22/10/2026', title: ['Đồng bộ GitLab và GitHub ổn định', 'Reliable GitLab and GitHub sync'], text: ['Mọi việc mới đi sang tracker của dự án hoặc bảng Việc nội bộ, cùng một luồng trạng thái.', 'All new work goes to the project tracker or the internal Work board, with one status flow.'] },
      { date: '21/10/2026', title: ['Việc của tôi và Daily Planning thống nhất', 'My work and Daily planning aligned'], text: ['Mỗi Issue chỉ có một thẻ trong ngày, mở được tracker và giữ trạng thái nghiệm thu ngay trên kế hoạch.', 'Each Issue has one card per day, opens in the tracker and keeps its acceptance state on the plan.'] },
      { date: '18/10/2026', title: ['Bảng Việc nội bộ và khu nội dung Beta', 'Internal Work board and Beta content area'], text: ['Việc cần bàn hoặc không phải code có bảng sáu cột; khu bài đăng có quy trình riêng theo kênh và lịch.', 'Work to discuss or not about code gets a six-column board; posts have their own flow per channel and schedule.'] },
      { date: '09/10/2026', title: ['Agent ghi lịch sử xử lý', 'Agents log their work'], text: ['Codex và Claude Code đọc việc qua MCP, ghi nguyên nhân, thay đổi, test và bằng chứng để người duyệt nghiệm thu.', 'Codex and Claude Code read work over MCP and log the cause, the change, tests and evidence for the reviewer.'] },
    ],
  },
  {
    title: ['Nền móng tiếp nhận đa nguồn', 'Multi-source foundation'], latest: '14/10/2026', tone: 'foundation', entries: [
      { date: '01-14/10/2026', title: ['Báo cáo ngày, cuộc họp, Telegram và MCP', 'Daily reports, meetings, Telegram and MCP'], text: ['Intake phát triển từ hộp yêu cầu thành bàn điều hành ngày có báo cáo, kế hoạch, nhắc việc và agent.', 'Intake grows from a request inbox into a daily control desk with reports, plans, reminders and agents.'] },
      { date: '29/09/2026', title: ['Luồng Intake đầu tiên', 'The first Intake flow'], text: ['Tiếp nhận yêu cầu, AI chuẩn hóa, con người duyệt và đồng bộ sang nơi giao việc.', 'Capture a request, let AI normalize it, have a person approve it and sync it to where work is assigned.'] },
    ],
  },
]

type GuideCatalogPage = {
  key: string
  title: Bi
  route: string
  audience: Bi
  roles: readonly string[]
  purpose: Bi
  steps: readonly Bi[]
  actions: readonly { label: Bi; text: Bi }[]
  hintPage?: string
  marketingOnly?: boolean
}

const LEADS: readonly string[] = ['CTO', 'PROJECT_OWNER']
const EVERYONE: readonly string[] = ['CTO', 'PROJECT_OWNER', 'DEVELOPER']
const AUDIENCE_LEADS: Bi = ['CTO, Project Owner', 'CTO, Project Owner']

const PAGE_GROUPS: readonly { index: string; title: Bi; description: Bi; pages: readonly GuideCatalogPage[] }[] = [
  {
    index: '01', title: ['Tiếp nhận và ra quyết định', 'Capture and decide'], description: ['Luồng quan trọng nhất: ghi đúng nội dung nguồn, để AI chuẩn hóa, kiểm tra rồi quyết định nơi xử lý.', 'The most important flow: record the source as it is, let AI normalize it, check it, then decide where it goes.'], pages: [
      {
        key: 'new-intake', title: ['Tạo Intake', 'New Intake'], route: '/intakes/new', audience: AUDIENCE_LEADS, roles: LEADS,
        purpose: ['Ghi lại nguyên văn phản hồi, email, ghi chú hoặc lời nói trước khi AI chuẩn hóa. Đây là điểm bắt đầu của mọi yêu cầu.', 'Record the feedback, email, note or spoken words as they are before AI normalizes them. Every request starts here.'],
        steps: [['Chọn đúng dự án và kênh tiếp nhận.', 'Pick the project and the channel it came from.'], ['Dán nguyên văn nội dung; thêm file, thời điểm hoặc người gửi nếu cần.', 'Paste the original text; add files, the time received or the sender if needed.'], ['Bấm Lưu & phân tích, rồi mở chi tiết để kiểm kết quả AI và câu hỏi còn thiếu.', 'Select Save & analyze, then open the detail page to check the AI result and the open questions.']],
        actions: [
          { label: ['Nút +', 'The + button'], text: ['Đính kèm PDF/ảnh tối đa 5 MB, thêm thời điểm tiếp nhận, người gửi hoặc mở Ghi âm cuộc họp.', 'Attach a PDF or picture up to 5 MB, add the time received or the sender, or open meeting recording.'] },
          { label: ['Dự án', 'Project'], text: ['Chọn nơi sở hữu yêu cầu. Quyền duyệt, Issue và kế hoạch đều đi theo dự án này.', 'Picks who owns the request. Approval rights, Issues and plans all follow this project.'] },
          { label: ['Kênh', 'Channel'], text: ['Ghi nguồn yêu cầu như nhập tay, email, Zalo, cuộc họp hoặc kênh khác.', 'Records where the request came from: typed in, email, Zalo, a meeting or another channel.'] },
          { label: ['Việc khó', 'Hard task'], text: ['CTO đánh dấu khi muốn nghiệm thu cuối luôn quay về CTO, kể cả Project Owner đã xác nhận.', 'The CTO marks it when final acceptance must come back to the CTO, even after a Project Owner confirms.'] },
          { label: ['Nói để nhập', 'Dictate'], text: ['Dành cho một người đọc yêu cầu; chọn bản chữ thô hoặc bản AI tóm tắt để đưa vào ô nội dung.', 'For one person reading a request aloud; choose the raw transcript or the AI summary for the content box.'] },
          { label: ['Lưu & phân tích', 'Save & analyze'], text: ['Lưu nội dung nguồn trước, tải file lên, rồi mới gọi AI. Nếu AI lỗi, Intake vẫn không mất.', 'Saves the source first, uploads files, then calls AI. If AI fails, the Intake is not lost.'] },
        ],
      },
      {
        key: 'intakes', title: ['Tất cả Intake và trang chi tiết', 'All Intakes and the detail page'], route: '/intakes', audience: AUDIENCE_LEADS, roles: LEADS,
        purpose: ['Tìm lại mọi yêu cầu đã chuẩn hóa và mở hành trình đầy đủ từ tiếp nhận đến nghiệm thu.', 'Find any normalized request and open its full journey from capture to acceptance.'],
        steps: [['Lọc theo dự án, trạng thái, ưu tiên hoặc nơi giao việc.', 'Filter by project, status, priority or delivery target.'], ['Mở một Intake để đọc nội dung nguồn, kết quả AI, câu hỏi và đề xuất xử lý.', 'Open an Intake to read the source, the AI result, the questions and the suggested handling.'], ['Thực hiện quyết định trên trang chi tiết; không quyết chỉ từ dòng danh sách.', 'Decide on the detail page, never from the list row alone.']],
        actions: [
          { label: ['Phân tích lại', 'Analyze again'], text: ['Cho AI đọc lại sau khi đã bổ sung ngữ cảnh hoặc trả lời câu hỏi.', 'Lets AI read again after you add context or answer questions.'] },
          { label: ['Trả lời câu hỏi', 'Answer questions'], text: ['Bổ sung điều AI còn thiếu; có thể đánh dấu câu không cần trả lời.', 'Fill in what AI is missing; a question can be marked as not needed.'] },
          { label: ['Duyệt', 'Approve'], text: ['Chọn tuyến GitLab, GitHub, Việc nội bộ hoặc chỉ phản hồi; hệ thống hỏi lại trước khi tạo dữ liệu bên ngoài.', 'Choose GitLab, GitHub, the internal Work board or reply only; the app asks again before creating anything outside.'] },
          { label: ['Cần làm rõ / Hoãn / Từ chối', 'Clarify / Defer / Reject'], text: ['Ghi quyết định và lý do để hành trình có thể truy vết.', 'Records the decision and the reason so the journey can be traced.'] },
          { label: ['Đánh dấu trùng', 'Mark as duplicate'], text: ['Đóng yêu cầu và dẫn sang Intake hoặc Issue đã có, không xóa lịch sử.', 'Closes the request and points to the existing Intake or Issue, keeping the history.'] },
          { label: ['Rút lại phê duyệt', 'Withdraw approval'], text: ['Mở lại quyết định khi chọn sai; Issue cũ được cập nhật hoặc mở lại thay vì tạo trùng.', 'Reopens a wrong decision; the existing Issue is updated or reopened instead of duplicated.'] },
        ],
      },
      {
        key: 'meetings', title: ['Cuộc họp', 'Meetings'], route: '/meetings', audience: AUDIENCE_LEADS, roles: LEADS,
        purpose: ['Ghi âm, nhận bản chữ tách người nói và biến các mục hành động trong meeting note thành Intake hoặc Việc.', 'Record, get a transcript split by speaker and turn action items from the meeting note into Intakes or Work.'],
        steps: [['Bấm Ghi âm cuộc họp, chọn dự án và kết thúc bản ghi khi họp xong.', 'Select Record meeting, pick the project and stop when the meeting ends.'], ['Chờ bản chữ và meeting note; đổi tên người nói, sửa tóm tắt hoặc tạo lại note nếu cần.', 'Wait for the transcript and the note; rename speakers, edit the summary or regenerate the note if needed.'], ['Kiểm từng mục note, chọn đích rồi tạo Intake hoặc Việc.', 'Check each item, pick a target, then create Intakes or Work.']],
        actions: [
          { label: ['Ghi âm cuộc họp', 'Record meeting'], text: ['Mở trình ghi nhiều người nói. Âm thanh được gửi dần và xử lý sau khi kết thúc.', 'Opens the multi-speaker recorder. Audio is sent as you go and processed when you stop.'] },
          { label: ['Dự án của cuộc họp', 'Meeting project'], text: ['Gán toàn bộ mục note chưa xử lý vào đúng dự án; có thể đổi trước khi tạo Intake.', 'Assigns every unprocessed item to the right project; it can be changed before creating Intakes.'] },
          { label: ['Nghe lại / Tải xuống', 'Play / Download'], text: ['Mở hoặc tải bản ghi. Bấm mốc thời gian trong bản chữ để nghe từ đúng đoạn.', 'Plays or downloads the recording. Select a timestamp in the transcript to listen from that point.'] },
          { label: ['Lưu tên', 'Save name'], text: ['Thay nhãn người nói bằng tên thật trong toàn bộ bản chữ.', 'Replaces a speaker label with a real name across the transcript.'] },
          { label: ['Tạo theo đề xuất', 'Create as suggested'], text: ['Việc, câu hỏi và rủi ro đi vào bảng Việc; yêu cầu và bug thành Intake; quyết định chỉ được ghi nhận.', 'Tasks, questions and risks go to the Work board; requests and bugs become Intakes; decisions are only recorded.'] },
          { label: ['Tạo Intake cho mục đã chọn', 'Create Intakes for selected'], text: ['Ép các dòng được tick thành Intake để AI đọc và đưa sang Chờ phê duyệt.', 'Turns the ticked rows into Intakes for AI to read and sends them to Approvals.'] },
          { label: ['Tạo lại', 'Regenerate'], text: ['Tạo lại meeting note từ bản chữ; các mục chưa thành Intake sẽ được thay bằng bản mới.', 'Rebuilds the meeting note from the transcript; items not yet turned into Intakes are replaced.'] },
        ],
      },
      {
        key: 'approvals', title: ['Chờ phê duyệt', 'Approvals'], route: '/approvals', audience: AUDIENCE_LEADS, roles: LEADS,
        purpose: ['Hàng chờ để chọn yêu cầu cần đọc. Quyết định cuối cùng luôn thực hiện trên trang chi tiết Intake.', 'The queue for choosing what to read next. The final decision is always made on the Intake detail page.'],
        steps: [['Ưu tiên P0/P1 và mục quá hạn.', 'Start with P0/P1 and overdue items.'], ['Lọc Của tôi hoặc Tất cả, rồi mở yêu cầu để kiểm nguồn và kết quả AI.', 'Filter Mine or All, then open a request to check the source and the AI result.'], ['Duyệt, yêu cầu làm rõ, hoãn hoặc từ chối trên trang chi tiết.', 'Approve, ask for clarification, defer or reject on the detail page.']],
        actions: [
          { label: ['Của tôi / Tất cả', 'Mine / All'], text: ['CTO xem phần mình phải quyết hoặc cả phần đang thuộc Project Owner.', 'The CTO sees what they must decide, or also what belongs to Project Owners.'] },
          { label: ['Lọc dự án', 'Project filter'], text: ['Thu hẹp hàng chờ và lịch sử quyết định theo một dự án.', 'Narrows the queue and decision history to one project.'] },
          { label: ['Đã quyết định gần đây', 'Recently decided'], text: ['Tìm lại quyết định đã rời hàng chờ theo mã, tiêu đề, lý do hoặc người quyết.', 'Finds decisions that left the queue by code, title, reason or decision maker.'] },
        ],
      },
    ],
  },
  {
    index: '02', title: ['Lập kế hoạch, thực hiện và nghiệm thu', 'Plan, deliver and accept'], description: ['Sau khi duyệt, công việc được xếp người và giờ, thực hiện có trạng thái, rồi kiểm bằng chứng trước khi đóng.', 'After approval, work gets a person and hours, is delivered with status, and is checked against evidence before it closes.'], pages: [
      {
        key: 'today', title: ['Hôm nay', 'Today'], route: '/', audience: AUDIENCE_LEADS, roles: LEADS, purpose: ['Bảng điều hành ngắn gọn: việc quá hạn, yêu cầu chờ duyệt, kế hoạch chưa chốt, báo cáo thiếu và việc chờ nghiệm thu.', 'A short control board: overdue work, requests waiting for approval, unlocked plans, missing reports and work waiting for acceptance.'],
        steps: [['Đọc cảnh báo từ trên xuống theo mức độ gấp.', 'Read the alerts top down, most urgent first.'], ['Xử lý mục đang chờ thay vì dùng trang này như báo cáo trang trí.', 'Act on what is waiting; this page is not a decorative report.'], ['Chuyển sang Ngày mai hoặc Theo nhân sự khi cần xếp kế hoạch.', 'Switch to Tomorrow or By person when you need to plan.']],
        actions: [{ label: ['Thẻ cảnh báo', 'Alert cards'], text: ['Mở thẳng đúng hàng chờ hoặc dự án cần xử lý.', 'Open the exact queue or project that needs attention.'] }, { label: ['Ngày mai', 'Tomorrow'], text: ['Xem kế hoạch dự kiến và phần còn thiếu trước khi chốt.', 'Shows the draft plan and what is missing before it is locked.'] }, { label: ['Theo nhân sự', 'By person'], text: ['Kiểm tra tải việc và giờ còn trống của từng người.', 'Shows each person\'s load and free hours.'] }],
      },
      {
        key: 'planning', title: ['Daily Planning', 'Daily planning'], route: '/planning', audience: AUDIENCE_LEADS, roles: LEADS, purpose: ['Tạo bản kế hoạch ngày, nhận việc chờ, phân công người và giờ, xử lý cảnh báo rồi chốt.', 'Build the day plan, take in waiting work, assign people and hours, clear warnings and lock it.'],
        steps: [['Chọn ngày và dự án, mở bản kế hoạch.', 'Pick a day and a project, open the plan.'], ['Nhận đề xuất, thêm Issue nếu cần, phân công người, buổi và số giờ.', 'Accept proposals, add Issues if needed, assign the person, the half-day and the hours.'], ['Đọc cảnh báo, chốt kế hoạch và theo dõi đồng bộ GitLab/GitHub.', 'Read the warnings, lock the plan and watch the GitLab/GitHub sync.']],
        actions: [{ label: ['Mở kế hoạch', 'Open plan'], text: ['Tạo hoặc mở revision đang làm của ngày đã chọn.', 'Creates or opens the working revision for the chosen day.'] }, { label: ['Nhận đề xuất', 'Accept proposals'], text: ['Đưa các việc nhân sự hoặc agent đề xuất vào hàng chờ phân công.', 'Moves work proposed by people or agents into the assignment queue.'] }, { label: ['Thêm việc', 'Add work'], text: ['Thêm Issue hoặc Intake đủ điều kiện vào kế hoạch.', 'Adds an eligible Issue or Intake to the plan.'] }, { label: ['Sức chứa', 'Capacity'], text: ['Chỉnh giờ làm, nghỉ hoặc giới hạn riêng cho một người trong ngày.', 'Adjusts working hours, leave or a personal limit for one person that day.'] }, { label: ['Chốt kế hoạch', 'Lock plan'], text: ['Khóa snapshot của ngày và đồng bộ các trường đã đổi sang tracker.', 'Freezes the day\'s snapshot and syncs changed fields to the tracker.'] }, { label: ['Mở lại', 'Reopen'], text: ['Tạo revision mới để sửa; bản đã chốt trước đó vẫn được giữ.', 'Creates a new revision to edit; the previously locked one is kept.'] }],
      },
      {
        key: 'work', title: ['Việc', 'Work'], route: '/viec', audience: ['Mọi vai trò', 'Every role'], roles: EVERYONE, purpose: ['Bảng việc nội bộ cho việc không phải code hoặc việc cần bàn trước khi thành Issue.', 'The internal board for work that is not code, or that needs discussion before it becomes an Issue.'],
        steps: [['Tạo hoặc nhận thẻ ở Cần bàn.', 'Create or pick up a card in To discuss.'], ['Bàn trong Thảo luận, giao người và hạn rồi chuyển qua các cột.', 'Talk it through in Discussion, assign a person and a due date, then move it along the columns.'], ['Khi đủ rõ, tạo Issue hoặc nghiệm thu ngay trên bảng.', 'Once it is clear, create an Issue or accept it right on the board.']],
        actions: [{ label: ['Đổi cột', 'Change column'], text: ['Kéo thẻ hoặc chọn trạng thái; Bỏ và trả lại từ Chờ nghiệm thu phải có lý do.', 'Drag the card or pick a status; Cancel and sending back from Acceptance need a reason.'] }, { label: ['Tạo Issue', 'Create Issue'], text: ['Chuyển việc phần mềm đã rõ sang GitLab/GitHub để vào Daily Planning.', 'Sends clear software work to GitLab or GitHub so it enters Daily planning.'] }, { label: ['Liên kết', 'Links'], text: ['Gắn Drive, thiết kế, bản cắt hoặc kết quả đã đăng làm bằng chứng.', 'Attach Drive folders, designs, cuts or published results as evidence.'] }, { label: ['Thảo luận', 'Discussion'], text: ['Ghi điều đội đã thống nhất; không dán dữ liệu khách hàng.', 'Record what the team agreed; never paste customer data.'] }], hintPage: 'work',
      },
      {
        key: 'my-day', title: ['Việc của tôi', 'My work'], route: '/viec-cua-toi', audience: ['Mọi thành viên', 'Every member'], roles: EVERYONE, purpose: ['Danh sách việc của chính bạn trong ngày, ưu tiên cao trước.', 'Your own work for the day, highest priority first.'],
        steps: [['Đặt Đang làm khi bắt đầu.', 'Set In progress when you start.'], ['Đặt Xong và thêm link, commit hoặc MR nếu có.', 'Set Done and add a link, commit or MR if there is one.'], ['Báo Bị chặn sớm và nêu rõ cần ai hỗ trợ.', 'Report Blocked early and say who you need.']],
        actions: [{ label: ['Trạng thái', 'Status'], text: ['Báo PLANNED, Đang làm, Xong hoặc Bị chặn cho Project Owner và CTO.', 'Tells the Project Owner and the CTO: Planned, In progress, Done or Blocked.'] }, { label: ['Thêm bằng chứng', 'Add evidence'], text: ['Gắn kết quả để Nghiệm thu không phải đoán việc đã xong ở đâu.', 'Attach the result so Acceptance does not have to guess where the work is.'] }, { label: ['Đề xuất việc', 'Propose work'], text: ['Đưa việc ngoài kế hoạch vào hàng chờ để Project Owner xếp hoặc bỏ qua.', 'Puts unplanned work in the queue for the Project Owner to schedule or skip.'] }], hintPage: 'my_day',
      },
      {
        key: 'acceptance', title: ['Nghiệm thu', 'Acceptance'], route: '/nghiem-thu', audience: AUDIENCE_LEADS, roles: LEADS, purpose: ['Kiểm việc được báo xong, đối chiếu bằng chứng và xác nhận hoặc trả lại với lý do cụ thể.', 'Check work reported as done, compare it with the evidence and confirm it or return it with a clear reason.'],
        steps: [['Mở Intake và bằng chứng từ thẻ.', 'Open the Intake and the evidence from the card.'], ['Nếu đúng, xác nhận hoàn tất; nếu thiếu bằng chứng, ghi rõ lý do vẫn nghiệm thu.', 'If it is right, confirm it; if evidence is missing, write why you accept it anyway.'], ['Nếu chưa đúng, trả lại và mô tả điều phải sửa.', 'If it is not right, send it back and describe what to fix.']],
        actions: [{ label: ['Đúng là xong', 'Really done'], text: ['Ghi nghiệm thu, cập nhật trạng thái xuyên suốt và xếp lệnh đóng Issue nếu có.', 'Records acceptance, updates the status everywhere and queues closing the Issue if there is one.'] }, { label: ['Chưa xong', 'Not done'], text: ['Đưa việc về kế hoạch đang mở dưới dạng Làm lại, kèm lý do.', 'Puts the work back on the open plan as Rework, with the reason.'] }, { label: ['Đã kiểm, đã triển khai', 'Checked and deployed'], text: ['CTO xác nhận lịch sử xử lý do người hoặc agent ghi.', 'The CTO confirms the work log written by a person or an agent.'] }, { label: ['Thêm 5 việc', 'Five more'], text: ['Lấy thêm việc vào mẫu nghiệm thu hôm nay khi hàng chờ còn dài.', 'Adds more work to today\'s acceptance sample when the queue is long.'] }],
      },
      {
        key: 'reports', title: ['Báo cáo ngày', 'Daily reports'], route: '/reports', audience: AUDIENCE_LEADS, roles: LEADS, purpose: ['Đọc báo cáo cuối ngày, đối chiếu task với thư gốc và dùng phần dở dang cho kế hoạch tiếp theo.', 'Read end-of-day reports, compare tasks with the original email and use unfinished work for the next plan.'],
        steps: [['Kiểm người gửi, ngày báo cáo và trạng thái đọc.', 'Check the sender, the report date and whether it was read correctly.'], ['So sánh task đã trích với thư gốc trước khi dùng.', 'Compare the extracted tasks with the original email before using them.'], ['Sửa task sai, gắn Issue hoặc xử lý báo cáo lỗi định dạng.', 'Fix wrong tasks, link Issues or handle reports with a broken format.']],
        actions: [{ label: ['Quét hộp thư', 'Scan mailbox'], text: ['CTO yêu cầu kiểm tra thư mới ngay thay vì chờ lịch.', 'The CTO asks for a mailbox check now instead of waiting for the schedule.'] }, { label: ['Xem thư gốc', 'View original'], text: ['Mở nội dung mã hóa có audit để đối chiếu với dữ liệu AI trích.', 'Opens the encrypted original, with an audit entry, to compare with what AI extracted.'] }, { label: ['Sửa task', 'Edit task'], text: ['Chỉnh tiêu đề, trạng thái, giờ hoặc Issue khi AI đọc chưa đúng.', 'Corrects the title, status, hours or Issue when AI read it wrong.'] }],
      },
      {
        key: 'week-summary', title: ['Tuần qua', 'Last week'], route: '/tuan-qua', audience: AUDIENCE_LEADS, roles: LEADS, purpose: ['Xem tuần bằng số: giờ đã xếp, giờ báo cáo, việc xong, nghiệm thu và điểm nghẽn quy trình.', 'The week in numbers: planned hours, reported hours, work done, acceptance and process bottlenecks.'],
        steps: [['Chọn tuần và phạm vi dự án.', 'Pick the week and the project scope.'], ['Đọc chênh lệch giữa kế hoạch, báo cáo và nghiệm thu.', 'Read the gaps between plan, reports and acceptance.'], ['Mở mục bất thường để xử lý ở trang nguồn thay vì sửa số liệu tổng hợp.', 'Open anything unusual and fix it at its source page, not in the totals.']],
        actions: [{ label: ['Chọn tuần', 'Pick week'], text: ['Đổi khoảng báo cáo theo tuần làm việc.', 'Changes the reporting range by working week.'] }, { label: ['Lọc dự án', 'Project filter'], text: ['Xem toàn bộ phạm vi hoặc một dự án cụ thể.', 'Shows the whole scope or one project.'] }],
      },
    ],
  },
  {
    index: '03', title: ['Quản trị đội và công cụ hỗ trợ', 'Team admin and supporting tools'], description: ['Các trang cần dùng sau khi luồng cốt lõi đã vận hành ổn định.', 'Pages you need once the core flow runs smoothly.'], pages: [
      {
        key: 'projects', title: ['Dự án và nhân sự', 'Projects and people'], route: '/projects', audience: AUDIENCE_LEADS, roles: LEADS, purpose: ['Xem dự án được phép quản lý, đội ngũ, Project Owner và trạng thái nối tài khoản tracker.', 'See the projects you manage, the team, the Project Owner and whether tracker accounts are linked.'],
        steps: [['Mở dự án để xem đội và người chịu trách nhiệm.', 'Open a project to see the team and who is responsible.'], ['Thêm nhân sự đang hoạt động; gắn đúng tài khoản GitLab/GitHub.', 'Add active people and link the right GitLab or GitHub account.'], ['CTO dùng Cài đặt khi cần tạo dự án, sửa hồ sơ hoặc cấu hình integration.', 'The CTO uses Settings to create projects, edit profiles or configure integrations.']],
        actions: [{ label: ['Thêm nhân sự', 'Add people'], text: ['Chọn một hoặc nhiều người vào dự án; thao tác lặp lại không tạo membership trùng.', 'Add one or more people to the project; repeating it never creates a duplicate membership.'] }, { label: ['Chọn GitLab/GitHub', 'Pick GitLab/GitHub'], text: ['Gắn tài khoản tracker để phân công và đọc báo cáo đúng người.', 'Links the tracker account so assignments and reports reach the right person.'] }, { label: ['Gỡ khỏi dự án', 'Remove from project'], text: ['Chỉ bỏ membership; hồ sơ, tài khoản, lịch sử và các dự án khác vẫn giữ.', 'Removes only the membership; the profile, account, history and other projects stay.'] }],
      },
      {
        key: 'personal', title: ['Việc riêng', 'Personal tasks'], route: '/viec-rieng', audience: ['Mọi thành viên', 'Every member'], roles: EVERYONE, purpose: ['Quản lý việc cá nhân ngoài dự án theo ma trận Eisenhower; người khác không thấy nội dung.', 'Manage personal tasks outside projects on an Eisenhower matrix; nobody else sees them.'],
        steps: [['Thêm việc, giờ dự kiến và ngày hoặc giờ nhắc.', 'Add a task, its expected hours and a reminder date or time.'], ['Đánh dấu Quan trọng; Khẩn được tự tính và có thể ghi đè.', 'Mark it Important; Urgent is worked out for you and can be overridden.'], ['Kéo giữa bốn ô hoặc đánh dấu Xong, Bỏ.', 'Drag between the four boxes or mark it Done or Dropped.']],
        actions: [{ label: ['Thêm việc riêng', 'Add personal task'], text: ['Tạo việc hành chính, gặp đối tác hoặc học; số giờ làm giảm giờ trống của bạn.', 'Create admin work, a partner meeting or study time; its hours reduce your free time.'] }, { label: ['Nhắc lúc', 'Remind at'], text: ['Bot Telegram nhắc riêng đúng giờ nếu tài khoản đã liên kết.', 'The Telegram bot reminds you privately on time if your account is linked.'] }, { label: ['Khôi phục', 'Restore'], text: ['Đưa việc đã bỏ trở lại ô Lên lịch.', 'Puts a dropped task back in the Schedule box.'] }],
      },
      {
        key: 'feedback', title: ['Góp ý', 'Feedback'], route: '/gop-y', audience: ['Mọi thành viên', 'Every member'], roles: EVERYONE, purpose: ['Gửi điều dự án nên làm mà chưa cần tự viết thành yêu cầu chính thức.', 'Send something the project should do without writing a formal request yourself.'],
        steps: [['Mô tả bằng lời của bạn, có thể kèm ảnh.', 'Describe it in your own words, with a picture if useful.'], ['Project Owner nhận thì góp ý thành Intake và AI đọc.', 'When the Project Owner accepts it, it becomes an Intake and AI reads it.'], ['Nếu chưa nhận, người gửi thấy lý do.', 'If it is not accepted, the sender sees why.']],
        actions: [{ label: ['Gửi góp ý', 'Send feedback'], text: ['Tạo đề xuất chờ Project Owner; không tự tạo Intake ngay.', 'Creates a proposal for the Project Owner; it does not create an Intake right away.'] }, { label: ['Nhận thành Intake', 'Accept as Intake'], text: ['Project Owner chuyển góp ý thành yêu cầu chính thức.', 'The Project Owner turns the feedback into a formal request.'] }, { label: ['Chưa nhận', 'Decline'], text: ['Từ chối kèm một lý do ngắn cho người gửi.', 'Declines with a short reason for the sender.'] }], hintPage: 'feedback',
      },
      {
        key: 'account', title: ['Tài khoản và agent', 'Account and agents'], route: '/settings/account', audience: ['Mọi thành viên', 'Every member'], roles: EVERYONE, purpose: ['Bảo vệ tài khoản và cấp quyền có kiểm soát cho Codex, Claude Code hoặc luồng tự động.', 'Protect your account and give Codex, Claude Code or automations controlled access.'],
        steps: [['Đổi mật khẩu, bật MFA và lưu mã khôi phục.', 'Change your password, turn on MFA and keep the recovery codes.'], ['Tạo một token riêng cho mỗi máy hoặc agent.', 'Create a separate token for each machine or agent.'], ['Cài lệnh ngắn rồi dùng agent để đọc việc và gửi báo cáo.', 'Install the short commands, then let the agent read your work and send reports.']],
        actions: [{ label: ['Tạo token', 'Create token'], text: ['Token chỉ hiện một lần; mất thì thu hồi và tạo token mới.', 'A token is shown once; if you lose it, revoke it and create a new one.'] }, { label: ['Thu hồi', 'Revoke'], text: ['Ngắt ngay quyền của một máy hoặc agent mà không đổi mật khẩu.', 'Cuts off one machine or agent at once without changing your password.'] }, { label: ['Lệnh cho agent', 'Agent commands'], text: ['Cài /in-today, /in-end-day và các lệnh phù hợp vai trò.', 'Install /in-today, /in-end-day and the commands for your role.'] }], hintPage: 'account',
      },
    ],
  },
  {
    index: '04', title: ['Nội dung và nguồn theo dõi (Beta)', 'Content and watched sources (Beta)'], description: ['Khu Beta, đặt sau luồng Intake cốt lõi vì giao diện và quy tắc còn có thể thay đổi.', 'A Beta area, placed after the core Intake flow because its screens and rules may still change.'], pages: [
      { key: 'marketing-week', title: ['Tuần này', 'This week'], route: '/tuan-nay', audience: ['Đội nội dung', 'Content team'], roles: EVERYONE, marketingOnly: true, purpose: ['Lịch bài theo ngày và kênh, kèm chủ đề nóng từ các nguồn đã cấu hình.', 'The post calendar by day and channel, with hot topics from the sources you set up.'], steps: [['Xem lịch theo kênh và ngày.', 'Read the calendar by channel and day.'], ['Thêm hoặc kéo bài để đổi ngày.', 'Add posts or drag them to change the day.'], ['Xử lý bài trễ và chủ đề nóng.', 'Handle late posts and hot topics.']], actions: [{ label: ['Thêm bài', 'Add post'], text: ['Tạo một bài hoặc nhiều bài và trải theo lịch.', 'Create one or many posts and spread them over the calendar.'] }, { label: ['Thành bài / Thành chuỗi', 'To post / To series'], text: ['Biến chủ đề nóng thành nội dung có nguồn tham khảo.', 'Turns a hot topic into content with its sources attached.'] }], hintPage: 'week' },
      { key: 'marketing-posts', title: ['Bài', 'Posts'], route: '/viec', audience: ['Đội nội dung', 'Content team'], roles: EVERYONE, marketingOnly: true, purpose: ['Bảng bài từ Ý tưởng đến Đã đăng.', 'The post board from Idea to Published.'], steps: [['Giao người, kênh và ngày.', 'Assign the person, channel and date.'], ['Soạn bản cho từng kênh và gửi duyệt.', 'Write the version for each channel and send it for review.'], ['Đăng, dán link và đánh dấu hoàn tất.', 'Publish, paste the link and mark it done.']], actions: [{ label: ['Gửi duyệt', 'Send for review'], text: ['Đưa bài sang Project Owner kiểm.', 'Sends the post to the Project Owner to check.'] }, { label: ['Đã đăng', 'Published'], text: ['Xác nhận từng kênh và lưu link bài thật.', 'Confirms each channel and keeps the link to the live post.'] }], hintPage: 'posts' },
      { key: 'marketing-review', title: ['Chờ duyệt bài', 'Post review'], route: '/duyet', audience: ['Project Owner nội dung', 'Content Project Owner'], roles: LEADS, marketingOnly: true, purpose: ['Kiểm chữ, link thiết kế và lịch trước khi bài được phép đăng.', 'Check the words, design links and schedule before a post may go out.'], steps: [['Mở bài và đọc từng bản kênh.', 'Open the post and read each channel version.'], ['Duyệt hoặc trả lại với yêu cầu sửa cụ thể.', 'Approve it or send it back with a specific fix.']], actions: [{ label: ['Duyệt', 'Approve'], text: ['Đưa bài sang Đã duyệt, chờ ngày đăng.', 'Moves the post to Approved, waiting for its date.'] }, { label: ['Sửa lại', 'Send back'], text: ['Trả về Đang làm và ghi lý do trong Thảo luận.', 'Returns it to In progress and writes the reason in Discussion.'] }], hintPage: 'review' },
      { key: 'marketing-sources', title: ['Nguồn và trụ', 'Sources and pillars'], route: '/nguon', audience: ['Project Owner nội dung', 'Content Project Owner'], roles: LEADS, marketingOnly: true, purpose: ['Khai trụ nội dung, nguồn theo dõi, mạng xã hội và nhịp AI tóm chủ đề.', 'Set the content pillars, watched sources, social networks and how often AI summarizes topics.'], steps: [['Viết trụ đủ rõ để người mới hiểu.', 'Write pillars clear enough for a newcomer.'], ['Thêm nguồn và bật mạng được phép.', 'Add sources and turn on the allowed networks.'], ['Đặt nhịp quét vừa đủ rồi kiểm kết quả ở Tuần này.', 'Set a modest scan rhythm, then check the result in This week.']], actions: [{ label: ['Làm mới chủ đề', 'Refresh topics'], text: ['Chạy lại ngay sau khi đổi nguồn hoặc từ khóa; có giới hạn mỗi ngày.', 'Runs again right after you change sources or keywords; limited per day.'] }, { label: ['Lệnh cho agent', 'Agent commands'], text: ['Cho agent đọc chủ đề và soạn bản kênh, không tự đăng.', 'Lets an agent read topics and draft channel versions; it never publishes.'] }], hintPage: 'sources' },
    ],
  },
  {
    index: '05', title: ['Khu riêng của CTO', 'CTO-only areas'], description: ['Những trang chỉ CTO thấy: cấu hình hệ thống, AI, tích hợp và không gian riêng.', 'Pages only the CTO sees: system settings, AI, integrations and a private space.'], pages: [
      { key: 'settings', title: ['Cài đặt hệ thống', 'System settings'], route: '/settings', audience: ['CTO', 'CTO'], roles: ['CTO'], purpose: ['Tạo dự án, quản lý tài khoản, nối GitLab/GitHub, Telegram, hộp thư báo cáo và sao lưu.', 'Create projects, manage accounts, connect GitLab or GitHub, Telegram, the report mailbox and backups.'], steps: [['Tạo dự án và gán Project Owner.', 'Create projects and assign a Project Owner.'], ['Nối tracker và kiểm kết nối trước khi duyệt Intake đầu tiên.', 'Connect the tracker and test it before approving the first Intake.'], ['Bật Telegram và hộp thư khi đội đã quen luồng chính.', 'Turn on Telegram and the mailbox once the team knows the main flow.']], actions: [{ label: ['Kiểm kết nối', 'Test connection'], text: ['Gọi thử tracker bằng token đã lưu, báo rõ khi thiếu quyền.', 'Calls the tracker with the stored token and says clearly when a permission is missing.'] }, { label: ['Sao lưu', 'Backup'], text: ['Tạo bản sao lưu có kiểm tra để restore được khi cần.', 'Creates a verified backup that can be restored when needed.'] }] },
      { key: 'ai-config', title: ['Cấu hình AI', 'AI configuration'], route: '/settings/ai', audience: ['CTO', 'CTO'], roles: ['CTO'], purpose: ['Chọn nhà cung cấp và model cho ba nhóm việc: chữ, ảnh và giọng nói.', 'Choose the provider and model for three groups of work: text, pictures and speech.'], steps: [['Thêm nhà cung cấp và khóa API; khóa được mã hóa và không hiện lại.', 'Add a provider and its API key; the key is encrypted and never shown again.'], ['Chọn model từ danh sách cho từng nhóm.', 'Pick a model from the list for each group.'], ['Bấm kiểm với mẫu thật để biết model đọc được ảnh hay nghe được không.', 'Run the sample check to see whether the model reads pictures or understands speech.']], actions: [{ label: ['Kiểm bằng mẫu', 'Sample check'], text: ['Gửi một ảnh hoặc đoạn âm thanh mẫu, báo rõ khi model không còn hoặc không hỗ trợ.', 'Sends a sample picture or audio clip and says clearly when the model is gone or unsupported.'] }] },
      { key: 'private-space', title: ['Không gian riêng', 'Private space'], route: '/rieng', audience: ['CTO', 'CTO'], roles: ['CTO'], purpose: ['Ghi chú, giọng viết và nguyên liệu nội dung chỉ CTO đọc; không đi vào dự án nào.', 'Notes, writing voice and content material only the CTO reads; none of it enters a project.'], steps: [['Ghi lại ý tưởng hoặc đọc để nhập.', 'Write down an idea or dictate it.'], ['Dùng làm nguồn khi soạn bài hoặc báo cáo.', 'Use it as a source when drafting posts or reports.']], actions: [{ label: ['Giọng viết', 'Writing voice'], text: ['Lưu mẫu giọng để AI soạn bài giống cách CTO viết.', 'Keeps voice samples so AI drafts in the way the CTO writes.'] }] },
    ],
  },
]

// How to make the GitLab or GitHub token Intake needs (FR-INTG-23, ADR-0080). The same words appear in the first-run
// setup, beside the token fields and in the guide below.
export const GITLAB_MIN_ROLE = 'Reporter'

export function gitlabTokenUrl(base?: string) {
  const root = (base || 'https://gitlab.com').trim().replace(/\/+$/, '').replace(/\/api\/v4$/, '')
  return `${root}/-/user_settings/personal_access_tokens?name=Intake&scopes=api,read_repository`
}

export const GITHUB_TOKEN_URL = 'https://github.com/settings/personal-access-tokens/new?name=Intake&description=Intake%20-%20Issues%20and%20project%20context&contents=read&issues=write'

const GITLAB_STEPS: readonly Bi[] = [
  [`Đăng nhập GitLab bằng tài khoản có vai trò tối thiểu ${GITLAB_MIN_ROLE} trong các dự án cần nối (nên dùng một tài khoản riêng cho Intake thay vì tài khoản cá nhân).`, `Sign in to GitLab with an account that has at least the ${GITLAB_MIN_ROLE} role on the projects to link (a separate account for Intake is better than a personal one).`],
  ['Mở Preferences → Access tokens → Add new token (nút bên dưới mở sẵn trang này, đã điền tên và hai scope).', 'Open Preferences → Access tokens → Add new token (the button below opens that page with the name and both scopes filled in).'],
  ['Chọn hai scope: api (tạo và cập nhật Issue) và read_repository (đọc tệp ngữ cảnh dự án). Đặt ngày hết hạn và ghi lại để thay token trước ngày đó.', 'Tick two scopes: api (create and update Issues) and read_repository (read the project context file). Set an expiry date and note it so you replace the token before then.'],
  ['Bấm Create, chép token ngay (GitLab chỉ hiện một lần), dán vào Intake ở Dự án → Kết nối GitLab, bấm Lưu rồi Kiểm tra quyền.', 'Click Create, copy the token right away (GitLab shows it only once), paste it in Intake under Projects → GitLab connection, Save, then Check permissions.'],
]

const GITHUB_STEPS: readonly Bi[] = [
  ['Mỗi khách một token fine-grained, chỉ thấy repo của khách đó. Mở Settings → Developer settings → Fine-grained tokens → Generate new token (nút bên dưới mở sẵn trang này).', 'One fine-grained token per customer, seeing only that customer\'s repository. Open Settings → Developer settings → Fine-grained tokens → Generate new token (the button below opens that page).'],
  ['Resource owner: tài khoản hoặc tổ chức sở hữu repo. Repository access: Only select repositories → chọn đúng repo của khách (đừng chọn Public repositories, lựa chọn đó chỉ cho đọc).', 'Resource owner: the account or organization that owns the repository. Repository access: Only select repositories → pick the customer\'s repository (not Public repositories, which is read-only).'],
  ['Ở mục Repositories (không phải Organizations), Add permissions: Issues = Read and write, Contents = Read-only (Metadata = Read-only có sẵn). Đặt ngày hết hạn.', 'Under Repositories (not Organizations), Add permissions: Issues = Read and write, Contents = Read-only (Metadata = Read-only comes with it). Set an expiry date.'],
  ['Nếu tổ chức bắt duyệt token, nhờ owner của tổ chức duyệt. Chép token, dán vào Intake ở Dự án → Token GitHub với tên như GITHUB_TOKEN_KHACH_A, rồi Kiểm tra quyền với repo owner/name.', 'If the organization requires approval, ask an organization owner to approve it. Copy the token, paste it in Intake under Projects → GitHub tokens with a name such as GITHUB_TOKEN_CUSTOMER_A, then Check permissions against owner/name.'],
]

export function TokenGuide({ system, gitlabBase, compact = false }: { system: 'GITLAB' | 'GITHUB'; gitlabBase?: string; compact?: boolean }) {
  const { locale } = useLocale()
  const t = (value: Bi) => pick(locale, value)
  const steps = system === 'GITLAB' ? GITLAB_STEPS : GITHUB_STEPS
  const href = system === 'GITLAB' ? gitlabTokenUrl(gitlabBase) : GITHUB_TOKEN_URL
  return (
    <div className={`token-guide${compact ? ' is-compact' : ''}`}>
      <ol>{steps.map((step) => <li key={step[1]}>{t(step)}</li>)}</ol>
      <p>
        <a className="button button-secondary button-small" href={href} target="_blank" rel="noreferrer">
          {system === 'GITLAB' ? t(['Mở trang tạo token GitLab', 'Open the GitLab token page']) : t(['Mở trang tạo token GitHub', 'Open the GitHub token page'])}
        </a>
      </p>
      <p className="token-guide-note">{system === 'GITLAB'
        ? t(['Token chỉ lưu trên máy chủ Intake, đã mã hóa; màn hình chỉ hiện 4 ký tự cuối. Cài qua .env (GITLAB_TOKEN) vẫn chạy, token lưu trên màn hình được ưu tiên.', 'The token is kept on the Intake server, encrypted; screens show only its last 4 characters. A GITLAB_TOKEN in .env still works; a token saved on the screen wins.'])
        : t(['Token lưu mã hóa trên máy chủ Intake; màn hình chỉ hiện 4 ký tự cuối. Một token chỉ dùng cho repo của một khách để dữ liệu khách không lẫn nhau.', 'Tokens are kept encrypted on the Intake server; screens show only the last 4 characters. One token serves one customer\'s repository so customers\' data never mix.'])}</p>
    </div>
  )
}

const ACCESS_LABELS: Record<string, { label: Bi; fix: Bi }> = {
  'GITLAB.token_valid': { label: ['Token còn dùng được', 'Token works'], fix: ['Token sai, đã bị thu hồi hoặc hết hạn: tạo token mới và lưu lại.', 'The token is wrong, revoked or expired: create a new one and save it.'] },
  'GITLAB.scope_api': { label: ['Scope api (tạo và cập nhật Issue)', 'Scope api (create and update Issues)'], fix: ['Tạo lại token có tick scope api.', 'Create the token again with the api scope ticked.'] },
  'GITLAB.scope_read_repository': { label: ['Scope read_repository (đọc tệp ngữ cảnh dự án)', 'Scope read_repository (read the project context file)'], fix: ['GitLab không cho thêm scope vào token đã tạo: tạo token mới có tick cả api và read_repository, rồi lưu lại.', 'GitLab cannot add a scope to an existing token: create a new one with both api and read_repository ticked, then save it.'] },
  'GITLAB.expires': { label: ['Ngày hết hạn', 'Expiry date'], fix: ['Tạo token mới và lưu lại trước ngày hết hạn.', 'Create a new token and save it before it expires.'] },
  'GITLAB.project_found': { label: ['Thấy dự án trên GitLab', 'Project visible on GitLab'], fix: ['Kiểm tra đường dẫn nhóm/dự án, hoặc thêm tài khoản của token vào dự án.', 'Check the group/project path, or add the token\'s account to the project.'] },
  'GITLAB.project_role': { label: [`Vai trò trong dự án (tối thiểu ${GITLAB_MIN_ROLE})`, `Role on the project (at least ${GITLAB_MIN_ROLE})`], fix: [`Nâng vai trò của tài khoản lên ${GITLAB_MIN_ROLE} trở lên trong Manage → Members của dự án.`, `Raise the account to ${GITLAB_MIN_ROLE} or higher under the project's Manage → Members.`] },
  'GITHUB.token_valid': { label: ['Token còn dùng được', 'Token works'], fix: ['Token sai, đã bị thu hồi hoặc hết hạn: tạo token mới và lưu lại cùng tên.', 'The token is wrong, revoked or expired: create a new one and save it under the same name.'] },
  'GITHUB.metadata': { label: ['Token thấy repo', 'Token sees the repository'], fix: ['Sửa token: Resource owner phải là tổ chức hoặc tài khoản sở hữu repo, Repository access chọn đúng repo này. Nếu tổ chức bắt duyệt token, nhờ owner duyệt.', 'Edit the token: the Resource owner must be the organization or account that owns the repository, and Repository access must include it. If the organization requires approval, ask an owner to approve it.'] },
  'GITHUB.issues_enabled': { label: ['Repo đang bật Issues', 'Issues turned on for the repository'], fix: ['Bật Issues trong Settings → General → Features của repo.', 'Turn on Issues under the repository\'s Settings → General → Features.'] },
  'GITHUB.issues_read': { label: ['Đọc Issue', 'Read Issues'], fix: ['Sửa token: Issues = Read and write.', 'Edit the token: Issues = Read and write.'] },
  'GITHUB.issues_write': { label: ['Tạo và sửa Issue', 'Create and edit Issues'], fix: ['Sửa token: Issues = Read and write.', 'Edit the token: Issues = Read and write.'] },
  'GITHUB.contents_read': { label: ['Đọc mã (Contents, cho tệp ngữ cảnh dự án)', 'Read code (Contents, for the project context file)'], fix: ['Sửa token: Contents = Read-only.', 'Edit the token: Contents = Read-only.'] },
  'GITHUB.expires': { label: ['Ngày hết hạn', 'Expiry date'], fix: ['Tạo token mới và lưu lại cùng tên trước ngày hết hạn.', 'Create a new token and save it under the same name before it expires.'] },
}

// The worker names the usual cause of a refusal in `detail` (ADR-0080 operations note); these replace the generic fix.
const ACCESS_CAUSES: Record<string, Bi> = {
  'GITHUB.issues_write.public_read_only': ['Repo công khai nên token đọc được, nhưng chưa được ghi. Hay gặp: Repository access đang là "Public repositories" (chỉ đọc), hoặc Issues được thêm ở mục Organizations thay vì Repositories, hoặc token đang chờ owner tổ chức duyệt. Sửa: Only select repositories → chọn repo này, mục Repositories → Issues = Read and write, bấm Update.', 'The repository is public, so the token can read it but not write. Usually: Repository access is "Public repositories" (read-only), Issues was added under Organizations instead of Repositories, or the token still awaits the organization owner\'s approval. Fix: Only select repositories → pick this repository, Repositories → Issues = Read and write, then Update.'],
  'GITHUB.issues_write.read_only': ['Token đọc được Issue nhưng không ghi được: Issues đang là Read-only. Sửa token ở mục Repositories: Issues = Read and write.', 'The token reads Issues but cannot write them: Issues is Read-only. Edit the token under Repositories: Issues = Read and write.'],
  'GITHUB.issues_write.org_policy': ['Tổ chức đang giới hạn token fine-grained (thường là thời hạn tối đa). Tạo lại token với ngày hết hạn ngắn hơn, hoặc nhờ owner xem Settings → Personal access tokens của tổ chức.', 'The organization limits fine-grained tokens (usually their maximum lifetime). Create the token again with an earlier expiry, or ask an owner to check the organization\'s Settings → Personal access tokens.'],
  'GITHUB.metadata.org_policy': ['Tổ chức đang giới hạn token fine-grained (thường là thời hạn tối đa). Tạo lại token với ngày hết hạn ngắn hơn, hoặc nhờ owner xem Settings → Personal access tokens của tổ chức.', 'The organization limits fine-grained tokens (usually their maximum lifetime). Create the token again with an earlier expiry, or ask an owner to check the organization\'s Settings → Personal access tokens.'],
}

const CAUSE_CODES = new Set(['public_read_only', 'read_only', 'org_policy'])

// Common token mistakes, listed in the guide (#guide-token-mistakes) and linked from a failed check.
const TOKEN_MISTAKES: readonly { system: string; mistake: Bi; fix: Bi }[] = [
  { system: 'GitHub', mistake: ['Chọn "Public repositories" ở Repository access: token chỉ đọc được repo công khai, không tạo được Issue.', 'Picking "Public repositories" under Repository access: the token only reads public repositories and cannot create Issues.'], fix: ['Chọn Only select repositories và chọn repo của khách.', 'Pick Only select repositories and choose the customer\'s repository.'] },
  { system: 'GitHub', mistake: ['Thêm quyền ở mục Organizations (như Issue Fields, Issue Types) thay vì Repositories: trông giống nhưng không cho tạo Issue.', 'Adding permissions under Organizations (such as Issue Fields or Issue Types) instead of Repositories: they look alike but do not allow creating Issues.'], fix: ['Mục Repositories → Add permissions → Issues = Read and write, Contents = Read-only.', 'Repositories → Add permissions → Issues = Read and write, Contents = Read-only.'] },
  { system: 'GitHub', mistake: ['Resource owner là tài khoản cá nhân trong khi repo thuộc tổ chức: token không thấy repo.', 'Resource owner set to a personal account while the repository belongs to an organization: the token cannot see it.'], fix: ['Tạo lại token, Resource owner chọn tổ chức sở hữu repo.', 'Create the token again with the owning organization as Resource owner.'] },
  { system: 'GitHub', mistake: ['Tổ chức bắt duyệt token và token đang chờ: repo riêng tư thì không thấy, repo công khai thì chỉ đọc.', 'The organization requires approval and the token is still pending: a private repository is invisible, a public one is read-only.'], fix: ['Owner tổ chức duyệt ở Settings → Personal access tokens → Pending requests.', 'An organization owner approves it under Settings → Personal access tokens → Pending requests.'] },
  { system: 'GitHub', mistake: ['Tổ chức giới hạn thời hạn token: token đặt hạn quá dài bị từ chối.', 'The organization caps token lifetime: a token with a longer expiry is refused.'], fix: ['Tạo lại token với ngày hết hạn trong giới hạn của tổ chức.', 'Create the token again with an expiry inside the organization\'s limit.'] },
  { system: 'GitLab', mistake: ['Chỉ tick scope api, quên read_repository: Intake không đọc được tệp ngữ cảnh dự án.', 'Ticking only the api scope and forgetting read_repository: Intake cannot read the project context file.'], fix: ['GitLab không cho thêm scope vào token cũ: tạo token mới có cả hai scope rồi lưu lại.', 'GitLab cannot add a scope to an old token: create a new one with both scopes and save it.'] },
  { system: 'GitLab', mistake: [`Tài khoản của token chỉ là Guest hoặc Planner trong dự án.`, 'The token\'s account is only Guest or Planner on the project.'], fix: [`Nâng lên ${GITLAB_MIN_ROLE} trở lên ở Manage → Members của dự án.`, `Raise it to ${GITLAB_MIN_ROLE} or higher under the project's Manage → Members.`] },
  { system: 'GitHub, GitLab', mistake: ['Nghĩ rằng sửa quyền xong phải dán lại token.', 'Thinking the token must be pasted again after changing its permissions.'], fix: ['Sửa quyền trên GitHub không đổi token, chỉ cần bấm Kiểm tra quyền lại. Tạo token mới (hay Regenerate) thì phải lưu token mới vào Intake.', 'Editing permissions on GitHub keeps the same token: just check again. A new or regenerated token must be saved in Intake.'] },
]

function TokenMistakes() {
  const { locale } = useLocale()
  const t = (value: Bi) => pick(locale, value)
  return (
    <div className="guide-table-wrap" id="guide-token-mistakes">
      <h3>{t(['Lỗi thường gặp khi tạo token', 'Common token mistakes'])}</h3>
      <table className="guide-feature-table">
        <thead><tr><th scope="col">{t(['Nơi', 'Where'])}</th><th scope="col">{t(['Lỗi', 'Mistake'])}</th><th scope="col">{t(['Cách sửa', 'Fix'])}</th></tr></thead>
        <tbody>{TOKEN_MISTAKES.map((row) => <tr key={row.mistake[1]}><th scope="row">{row.system}</th><td>{t(row.mistake)}</td><td>{t(row.fix)}</td></tr>)}</tbody>
      </table>
    </div>
  )
}

const ACCESS_STATUS: Record<string, Bi> ={ OK: ['Đủ', 'OK'], MISSING: ['Thiếu', 'Missing'], WARN: ['Lưu ý', 'Warning'], UNKNOWN: ['Chưa rõ', 'Unknown'] }

export type AccessRow = { key: string; status: string; detail: string | null }

export function AccessResultList({ system, ok, checks }: { system: 'GITLAB' | 'GITHUB'; ok: boolean; checks: readonly AccessRow[] }) {
  const { locale } = useLocale()
  const t = (value: Bi) => pick(locale, value)
  const detailText = (row: AccessRow) => {
    if (!row.detail) return ''
    if (row.key === 'expires') {
      if (row.detail === 'never') return t(['không hết hạn', 'never expires'])
      if (row.status === 'MISSING') return t([`đã hết hạn ${row.detail}`, `expired ${row.detail}`])
      if (row.status === 'WARN') return t([`hết hạn ${row.detail}, còn dưới 14 ngày`, `expires ${row.detail}, under 14 days left`])
      return row.detail
    }
    if (row.detail === 'empty') return t(['repo còn trống, chưa kiểm được', 'the repository is empty, nothing to check yet'])
    if (CAUSE_CODES.has(row.detail)) return ''
    return row.detail
  }
  const fixText = (row: AccessRow) => {
    const cause = row.detail ? ACCESS_CAUSES[`${system}.${row.key}.${row.detail}`] : undefined
    const meta = ACCESS_LABELS[`${system}.${row.key}`]
    return cause ? t(cause) : meta ? t(meta.fix) : ''
  }
  return (
    <div className={`access-result ${ok ? 'is-ok' : 'is-missing'}`} role="status">
      <strong>{ok ? t(['Token đủ quyền cho Intake.', 'The token has every permission Intake needs.']) : t(['Token còn thiếu quyền, sửa theo gợi ý dưới đây rồi kiểm lại.', 'The token is missing permissions; fix them as suggested below and check again.'])}</strong>
      <ul className="access-checks">
        {checks.map((row) => {
          const meta = ACCESS_LABELS[`${system}.${row.key}`]
          const detail = detailText(row)
          return (
            <li key={row.key} className={`is-${row.status.toLowerCase()}`}>
              <span className="access-status">{t(ACCESS_STATUS[row.status] ?? ['?', '?'])}</span>
              <span>{meta ? t(meta.label) : row.key}{detail && <small> - {detail}</small>}
                {(row.status === 'MISSING' || row.status === 'WARN') && fixText(row) && <em>{fixText(row)}</em>}
              </span>
            </li>
          )
        })}
      </ul>
      {!ok && <p><a className="text-button" href="/huong-dan#guide-token-mistakes" target="_blank" rel="noreferrer">{t(['Xem các lỗi thường gặp khi tạo token', 'See common token mistakes'])}</a></p>}
    </div>
  )
}

export type GuideAppContext = {
  role: string
  isCto: boolean
  marketing: boolean
  opens: Map<string, { opens: number; people: number }>
  dismissed: readonly string[]
  onReopen: (key: string) => void
  reopenBusy: boolean
  // A section only the signed-in CTO sees, placed after the history.
  ctoSection?: ReactNode
  ctoNav?: { href: string; label: string }
}

function hintText(locale: Locale, key: string) {
  const vi = ALL_HINTS[key]
  const en = HINTS_EN[key]
  return locale === 'en' && en ? en : vi
}

function introText(locale: Locale, page: string) {
  const vi = ALL_INTROS[page]
  const en = INTROS_EN[page]
  return locale === 'en' && en ? en : vi
}

// The body of the guide. Without `app` it is the public view: every page and role, no counters, no links into the app.
export function GuideContent({ app }: { app?: GuideAppContext }) {
  const { locale } = useLocale()
  const t = (value: Bi) => pick(locale, value)
  const groups = app
    ? PAGE_GROUPS.map((group) => ({ ...group, pages: group.pages.filter((page) => page.roles.includes(app.role) && (!page.marketingOnly || app.marketing || app.isCto)) })).filter((group) => group.pages.length > 0)
    : PAGE_GROUPS
  useEffect(() => {
    const target = window.location.hash.slice(1)
    if (target) document.getElementById(target.startsWith('guide-') ? target : `guide-${target}`)?.scrollIntoView({ block: 'center' })
  }, [])
  const changelog = app
    ? <Link className="text-button" to="/changelog">{t(['Xem đầy đủ ở Có gì mới', 'See everything in What\'s new'])}</Link>
    : <a className="text-button" href={`${GUIDE_REPO_URL}/blob/main/CHANGELOG.md`} target="_blank" rel="noreferrer">{t(['Xem CHANGELOG trên GitHub', 'See the CHANGELOG on GitHub'])}</a>
  return (
    <>
      <nav className="guide-nav" aria-label={t(['Mục lục hướng dẫn', 'Guide contents'])}>
        <a href="#guide-overview">{t(['Tổng quan', 'Overview'])}</a>
        <a href="#guide-roles">{t(['Theo vai trò', 'By role'])}</a>
        <a href="#guide-features">{t(['Tính năng', 'Features'])}</a>
        <a href="#guide-trackers">{t(['Kết nối GitLab/GitHub', 'GitLab/GitHub connection'])}</a>
        <a href="#guide-history">{t(['Lịch sử', 'History'])}</a>
        {app?.ctoNav && <a href={app.ctoNav.href}>{app.ctoNav.label}</a>}
        {!app && <a href="#guide-self-host">{t(['Tự cài đặt', 'Self-host'])}</a>}
        <a href="#guide-pages">{t(['Từng trang và nút', 'Pages and buttons'])}</a>
      </nav>

      <section className="panel guide-overview" id="guide-overview">
        <div className="guide-overview-copy">
          <span className="guide-eyebrow">Private, self-hosted, human-in-the-loop</span>
          <h2>{t(['Một đường đi có thể truy vết từ phản hồi đến kết quả', 'One traceable path from feedback to result'])}</h2>
          <p>{t(['Intake giúp đội phần mềm không đánh rơi yêu cầu giữa chat, email, cuộc họp, tracker và báo cáo ngày. AI làm phần đọc và đề xuất; con người giữ quyền quyết định, phân công và nghiệm thu.', 'Intake keeps a software team from losing requests between chat, email, meetings, the tracker and daily reports. AI does the reading and suggesting; people keep the decisions, the assignments and the sign-off.'])}</p>
          <div className="guide-principles" aria-label={t(['Nguyên tắc sản phẩm', 'Product principles'])}>
            <span>{t(['Riêng tư theo dự án', 'Private per project'])}</span><span>{t(['AI chỉ đề xuất', 'AI only suggests'])}</span><span>{t(['Bằng chứng trước khi xong', 'Evidence before done'])}</span>
          </div>
        </div>
        <IntakeWorkLoop />
      </section>

      <section className="panel guide-section" id="guide-roles">
        <div className="panel-heading"><div><h2>{t(['Bắt đầu theo vai trò', 'Start by role'])}</h2><p>{t(['Chọn đúng điểm vào trước, rồi mở rộng sang các màn khác khi cần.', 'Start at the right page first, then branch out to other screens as needed.'])}</p></div></div>
        <div className="guide-role-grid">
          {ROLES.map((item) => <article key={item.role[1]}><span>{t(item.role)}</span><h3>{t(['Bắt đầu ở ', 'Start at '])}{t(item.start)}</h3><p>{t(item.text)}</p></article>)}
        </div>
      </section>

      <section className="panel guide-section" id="guide-features">
        <div className="panel-heading"><div><h2>{t(['Bảng tính năng', 'Feature overview'])}</h2><p>{t(['Phân biệt phần lõi, phần tùy chọn và khu đang ở giai đoạn Beta.', 'What is core, what is optional and what is still in Beta.'])}</p></div></div>
        <div className="guide-table-wrap">
          <table className="guide-feature-table">
            <thead><tr><th scope="col">{t(['Khu vực', 'Area'])}</th><th scope="col">{t(['Điều hệ thống làm', 'What it does'])}</th><th scope="col">{t(['Trạng thái', 'Status'])}</th></tr></thead>
            <tbody>{FEATURES.map((row) => <tr key={row.area[1]}><th scope="row">{t(row.area)}</th><td>{t(row.value)}</td><td><span className={`guide-status is-${row.tone}`}>{t(row.status)}</span></td></tr>)}</tbody>
          </table>
        </div>
        <p className="guide-note"><strong>Beta</strong> {t(['nghĩa là giao diện và quy tắc còn có thể đổi. Intake hiện chưa tự đăng bài; các nguồn quét và kênh nội dung chỉ chạy khi CTO chủ động cấu hình.', 'means the screens and rules may still change. Intake does not publish posts by itself; watched sources and content channels run only after the CTO sets them up.'])}</p>
      </section>

      <section className="panel guide-section" id="guide-trackers">
        <div className="panel-heading"><div><h2>{t(['Kết nối GitLab hoặc GitHub', 'Connect GitLab or GitHub'])}</h2><p>{t(['Không bắt buộc để dùng thử. Cần khi muốn Intake tạo Issue trên tracker của đội và đọc tệp ngữ cảnh dự án. Chỉ CTO lưu token; sau khi lưu, bấm Kiểm tra quyền để biết token còn thiếu gì.', 'Not needed to try Intake. Needed for Intake to create Issues on the team\'s tracker and read the project context file. Only the CTO saves tokens; after saving, click Check permissions to see what the token still lacks.'])}</p></div></div>
        <div className="guide-token-grid">
          <article><h3>{t(['GitLab: một token cá nhân cho cả công ty', 'GitLab: one personal access token for the company'])}</h3><TokenGuide system="GITLAB" /></article>
          <article><h3>{t(['GitHub: mỗi khách một token fine-grained', 'GitHub: one fine-grained token per customer'])}</h3><TokenGuide system="GITHUB" /></article>
        </div>
        <TokenMistakes />
        <p className="guide-note">{t(['Nối dự án: khi tạo hoặc sửa dự án, chọn GitLab hay GitHub, chọn repo rồi bấm Kiểm tra kết nối. Token bị từ chối ở đâu thì Kiểm tra quyền chỉ đúng chỗ đó.', 'Linking a project: when creating or editing a project, pick GitLab or GitHub, pick the repository, then Check connection. Wherever the token is refused, Check permissions points at that exact spot.'])}</p>
      </section>

      <section className="panel guide-section" id="guide-history">
        <div className="panel-heading"><div><h2>{t(['Lịch sử phát triển', 'Development history'])}</h2><p>{t(['Nhóm theo chức năng, nhóm có cập nhật mới nhất đứng trước; trong mỗi nhóm, thời gian giảm dần.', 'Grouped by area, the most recently updated group first; newest first inside each group.'])}</p></div>{changelog}</div>
        <div className="guide-history-groups">
          {HISTORY_GROUPS.map((group) => <article className={`guide-history-group is-${group.tone}`} key={group.title[1]}>
            <header><div><h3>{t(group.title)}</h3><p>{t(['Cập nhật gần nhất', 'Last updated'])}</p></div><time>{group.latest}</time></header>
            <ol>{group.entries.map((item) => <li key={`${group.title[1]}-${item.date}-${item.title[1]}`}><time>{item.date}</time><div><strong>{t(item.title)}</strong><p>{t(item.text)}</p></div></li>)}</ol>
          </article>)}
        </div>
      </section>

      {app?.ctoSection}

      {!app && <section className="panel guide-section" id="guide-self-host">
        <div className="panel-heading"><div><h2>{t(['Mã nguồn mở và tự cài đặt', 'Open source and self-hosting'])}</h2><p>{t(['Intake phát hành theo giấy phép Apache-2.0. Bạn tự cài trên máy chủ của mình bằng Docker; dữ liệu không rời khỏi hạ tầng của bạn, trừ phần gửi cho nhà cung cấp AI bạn chọn.', 'Intake is released under the Apache-2.0 license. You run it on your own server with Docker; data stays on your infrastructure, except what goes to the AI provider you choose.'])}</p></div></div>
        <div className="guide-release-grid">
          <article><span>01</span><h3>{t(['Lấy mã', 'Get the code'])}</h3><p><code>git clone {GUIDE_REPO_URL}.git</code></p></article>
          <article><span>02</span><h3>{t(['Cài một lệnh', 'One-command install'])}</h3><p>{t(['Trình cài tự sinh secret và chỉ mở ở localhost cho tới khi bạn tạo xong tài khoản CTO.', 'The installer generates secrets and listens on localhost only until you create the CTO account.'])}</p></article>
          <article><span>03</span><h3>{t(['Dùng thử không cần khóa AI', 'Try it without an AI key'])}</h3><p>{t(['Dự án mẫu với dữ liệu hư cấu cho bạn đi hết vòng lặp trước khi nối GitLab/GitHub hay nhà cung cấp AI.', 'A sample project with fictional data lets you walk the whole loop before connecting GitLab, GitHub or an AI provider.'])}</p></article>
          <article><span>04</span><h3>{t(['Góp ý và đóng góp', 'Feedback and contributions'])}</h3><p>{t(['Mở Issue hoặc Pull Request trên GitHub; README có phần Quick start và hướng dẫn phát triển.', 'Open an Issue or a Pull Request on GitHub; the README has a Quick start and a development guide.'])}</p></article>
        </div>
        <div className="public-guide-cta">
          <a className="button button-primary" href={GUIDE_REPO_URL} target="_blank" rel="noreferrer">{t(['Xem mã trên GitHub', 'View on GitHub'])}</a>
          <a className="button button-secondary" href={`${GUIDE_REPO_URL}#quick-start`} target="_blank" rel="noreferrer">{t(['Cách cài đặt', 'How to install'])}</a>
        </div>
      </section>}

      <div className="guide-pages-heading" id="guide-pages"><h2>{t(['Hướng dẫn theo từng trang và nút', 'Every page and button'])}</h2><p>{app ? t(['Được xếp theo mức độ quan trọng của luồng công việc. Dấu ⓘ trong app vẫn mở đúng lời giải thích tương ứng.', 'Ordered by how central each page is to the work flow. The ⓘ marks in the app open the matching explanation.']) : t(['Được xếp theo mức độ quan trọng của luồng công việc. Mỗi trang ghi rõ vai trò nào thấy nó.', 'Ordered by how central each page is to the work flow. Each page says which roles see it.'])}</p></div>
      {groups.map((group) => (
        <section className="guide-priority-group" key={group.index} aria-labelledby={`guide-group-${group.index}`}>
          <header><span>{group.index}</span><div><h2 id={`guide-group-${group.index}`}>{t(group.title)}</h2><p>{t(group.description)}</p></div></header>
          {group.pages.map((page) => {
            const intro = page.hintPage ? introText(locale, page.hintPage) : undefined
            const rows = page.hintPage ? Object.keys(ALL_HINTS).filter((key) => ALL_HINTS[key].page === page.hintPage) : []
            const dismissed = app && page.hintPage ? app.dismissed.includes(`page.${page.hintPage}`) : false
            return (
              <section className="panel guide-page guide-functional-page" key={page.key} id={`guide-page-${page.key}`}>
                <div className="panel-heading"><div><div className="guide-page-meta"><span>{t(page.audience)}</span>{page.marketingOnly && !app && <span className="guide-status is-beta">Beta</span>}{app && <Link to={page.route}>{t(['Mở trang', 'Open page'])}</Link>}</div><h3>{t(page.title)}</h3><p>{t(page.purpose)}</p></div>
                  {app && dismissed && page.hintPage && <button type="button" className="text-button" disabled={app.reopenBusy} onClick={() => app.onReopen(`page.${page.hintPage}`)}>{t(['Hiện lại lời giới thiệu trên trang', 'Show the page introduction again'])}</button>}</div>
                <div className="guide-page-body">
                  <div><h4>{t(['Quy trình nên làm', 'Recommended steps'])}</h4><ol className="guide-page-steps">{page.steps.map((step) => <li key={step[1]}>{t(step)}</li>)}</ol></div>
                  <div><h4>{t(['Các nút và trường quan trọng', 'Key buttons and fields'])}</h4><dl className="guide-actions">{page.actions.map((action) => <div key={action.label[1]}><dt>{t(action.label)}</dt><dd>{t(action.text)}</dd></div>)}</dl></div>
                </div>
                {intro && <details className="guide-tracked-help" open>
                  <summary>{t(['Giải thích chi tiết đang dùng trong giao diện', 'The detailed explanations shown in the app'])}</summary>
                  <ul className="guide-intro">{intro.lines.map((line) => <li key={line}>{line}</li>)}</ul>
                  {rows.length > 0 && <dl className="guide-hints">
                    {rows.map((key) => {
                      const hint = hintText(locale, key)
                      const count = app?.isCto ? app.opens.get(key) : undefined
                      return <div key={key} id={`guide-${key}`}><dt>{hint.label}{count && <small> · {t(['mở', 'opened'])} {count.opens} {t(['lần', 'times'])}, {count.people} {t(['người, 7 ngày', 'people, 7 days'])}</small>}</dt><dd><strong>{hint.what}</strong> {hint.do}</dd></div>
                    })}
                  </dl>}
                </details>}
              </section>
            )
          })}
        </section>
      ))}
    </>
  )
}

// The page a visitor without an account sees, both at /huong-dan and on GitHub Pages.
export function PublicGuidePage({ variant }: { variant: 'app' | 'pages' }) {
  const { locale, setLocale } = useLocale()
  const t = (value: Bi) => pick(locale, value)
  useEffect(() => {
    document.title = t(['Hướng dẫn sử dụng Intake', 'Intake user guide'])
  }, [locale])
  return (
    <div className="public-guide">
      <header className="public-guide-bar">
        <a className="public-guide-brand" href={variant === 'app' ? '/huong-dan' : './'}>
          <img src={variant === 'app' ? '/icon.svg' : 'icon.svg'} alt="" width={28} height={28} /><strong>Intake</strong>
        </a>
        <div className="public-guide-actions">
          <div className="public-guide-lang" role="group" aria-label={t(['Ngôn ngữ', 'Language'])}>
            <button type="button" aria-pressed={locale === 'vi'} onClick={() => setLocale('vi')}>VI</button>
            <button type="button" aria-pressed={locale === 'en'} onClick={() => setLocale('en')}>EN</button>
          </div>
          <a className="button button-secondary button-small" href={GUIDE_REPO_URL} target="_blank" rel="noreferrer">GitHub</a>
          {variant === 'app' && <a className="button button-primary button-small" href="/login">{t(['Đăng nhập', 'Sign in'])}</a>}
        </div>
      </header>
      <main className="public-guide-main">
        <div className="public-guide-hero">
          <h1>{t(['Hướng dẫn sử dụng Intake', 'Intake user guide'])}</h1>
          <p>{t(['Hiểu vòng đời một yêu cầu, bắt đầu đúng theo vai trò và tra cứu từng trang, từng nút trong hệ thống. Trang này mở công khai để bạn chia sẻ.', 'Understand the life of a request, start in the right place for your role and look up every page and button. This page is public so you can share it.'])}</p>
        </div>
        <GuideContent />
      </main>
      <footer className="public-guide-foot">
        <span>Intake · Apache-2.0</span>
        <a href={GUIDE_REPO_URL} target="_blank" rel="noreferrer">{t(['Mã nguồn trên GitHub', 'Source on GitHub'])}</a>
      </footer>
    </div>
  )
}
