import process from 'node:process'

import { chromium } from 'playwright-core'

const baseUrl = process.env.HEADER_LOCALE_BASE_URL || 'http://127.0.0.1:8080'
const chromePath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const envelope = (data) => JSON.stringify({ success: true, data, request_id: 'header-locale-e2e' })
const failure = JSON.stringify({ success: false, error: { code: 'E2E_UNAVAILABLE', message: 'Not needed by this header test' }, request_id: 'header-locale-e2e' })
const assert = (condition, message) => { if (!condition) throw new Error(message) }

const browser = await chromium.launch({ executablePath: chromePath, headless: true })
const context = await browser.newContext({ locale: 'en-US', viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()

try {
  await page.route('**/api/v1/**', (route) => route.fulfill({ status: 503, contentType: 'application/json', body: failure }))
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ subject: 'cto', email: 'cto@example.test', display_name: 'Test CTO', role: 'CTO', can_view_raw: true, can_approve: true, mfa_enabled: true, project_ids: null, must_change_password: false, member_id: 'member-cto' }) }))
  await page.route('**/api/v1/setup', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ completed: true, wizard: false }) }))
  await page.route('**/api/v1/auth/agent-commands', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ commands: [], install: { bash: '', powershell: '', repo: '' } }) }))
  await page.route('**/api/v1/intakes*', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ items: [], summary: { total_items: 0, p0_attention: 0, p1_attention: 0, pending_approval: 0, sync_failed: 0 }, next_cursor: null }) }))
  await page.route('**/api/v1/approvals*', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ items: [], summary: { pending_approval: 0 }, next_cursor: null }) }))
  await page.route('**/api/v1/projects', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/reports/daily', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/meetings', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/acceptance*', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ plan_date: '2026-11-12', sample_size: 5, pending_total: 0, today: [], more: [], decided: [], work_log_pending_total: 0, work_logs_pending: [], work_logs_decided: [] }) }))
  await page.route('**/api/v1/planning/week/*', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ week_start: '2026-11-02', week_end: '2026-11-08', days_passed: 7, generated_at: '2026-11-12T00:00:00Z', projects: [], people: [], process: { requests_new: 0, approved: 0, approved_within_24h: 0, avg_wait_hours: null, from_queue: 0, from_planning: 0, issues_created: 0, avg_to_issue_hours: null, board_days: 0, ready_days: 0, overdue_project_days: 0, escalated_project_days: 0, max_stuck: 0 }, cto_days: [], personal: null, text: 'English weekly summary' }) }))
  await page.route('**/api/v1/planning/members*', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/feedback*', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/changelog*', (route) => {
    const url = new URL(route.request().url())
    assert(url.searchParams.get('lang') === 'en', `English UI requested changelog without lang=en: ${url}`)
    return route.fulfill({ contentType: 'application/json', body: envelope({ build: { sha: 'abcdef0', built_at: null }, latest: '2026-11-11', behind: 0, entries: [{ date: '2026-11-11', title: 'English changelog entry', commits: ['abcdef0'], refs: ['FR-UI-14'], bullets: ['English changelog details.'], cto_only: false }] }) })
  })
  await page.route('**/api/v1/private-space/watch/health', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ tracks: [], check_hours: 24 }) }))
  await page.route('**/api/v1/operations/status', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ status: 'ok', web: 'ok', worker_ai: 'ok', ai_configured: false, ai_source: 'none', storage: 'ok', backup: 'unknown', backup_detail: { state: 'missing', last_ok_at: null, last_ok_size_bytes: null, last_error_code: null } }) }))

  const checks = [
    ['/reports', 'Daily reports'],
    ['/approvals', 'Pending approval'],
    ['/planning', 'Daily Planning'],
    ['/people-planning', 'Plan by person'],
    ['/acceptance', 'Acceptance'],
    ['/projects', 'Projects'],
    ['/feedback', 'Feedback'],
    ['/last-week', 'Last week'],
    ['/intakes', 'All Intake'],
    ['/meetings', 'Meetings'],
    ['/guide', 'Intake user guide'],
  ]

  for (const [path, expected] of checks) {
    await page.goto(`${baseUrl}${path}?lang=en`, { waitUntil: 'networkidle' })
    const topbar = page.locator('.topbar')
    await topbar.getByRole('heading', { name: expected, exact: true }).waitFor()
    const headerText = await topbar.innerText()
    const vietnameseLine = headerText.split('\n').find((line) => /[À-ỹĐđ]/u.test(line))
    assert(!vietnameseLine, `${path} header still shows Vietnamese characters: ${vietnameseLine}`)
  }

  const bodyChecks = [
    ['/reports', 'No reports yet'],
    ['/approvals', 'No pending decisions'],
    ['/acceptance', 'No work pending acceptance'],
    ['/last-week', 'No software projects yet'],
    ['/intakes', 'No Intake found'],
    ['/meetings', 'No meetings yet'],
  ]
  for (const [path, expected] of bodyChecks) {
    await page.goto(`${baseUrl}${path}?lang=en`, { waitUntil: 'networkidle' })
    await page.getByText(expected, { exact: true }).waitFor()
    const bodyText = await page.locator('body').innerText()
    const vietnameseLine = bodyText.split('\n').find((line) => /[À-ỹĐđ]/u.test(line))
    assert(!vietnameseLine, `${path} body still shows Vietnamese characters: ${vietnameseLine}`)
  }

  const legacyRedirects = [
    ['/tuan-qua', '/last-week'],
    ['/nghiem-thu', '/acceptance'],
    ['/ke-hoach-nguoi', '/people-planning'],
    ['/gop-y', '/feedback'],
    ['/huong-dan', '/guide'],
  ]
  for (const [legacy, canonical] of legacyRedirects) {
    await page.goto(`${baseUrl}${legacy}?lang=en&source=legacy#saved-section`, { waitUntil: 'networkidle' })
    const url = new URL(page.url())
    assert(url.pathname === canonical, `${legacy} did not redirect to ${canonical}: ${url}`)
    assert(url.searchParams.get('lang') === 'en' && url.searchParams.get('source') === 'legacy', `${legacy} redirect lost query parameters: ${url}`)
    assert(url.hash === '#saved-section', `${legacy} redirect lost the hash: ${url}`)
  }

  await page.goto(`${baseUrl}/intakes?lang=en`, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: "What's new" }).click()
  const changelogMenu = page.locator('.changelog-menu')
  await changelogMenu.getByText('English changelog entry', { exact: true }).waitFor()
  await changelogMenu.getByText('English changelog details.', { exact: true }).waitFor()
  const changelogText = await changelogMenu.innerText()
  const vietnameseChangelogLine = changelogText.split('\n').find((line) => /[À-ỹĐđ]/u.test(line))
  assert(!vietnameseChangelogLine, `What's new still shows Vietnamese characters: ${vietnameseChangelogLine}`)

  console.log('header-locale: ok')
} finally {
  await browser.close()
}
