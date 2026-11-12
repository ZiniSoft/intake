import process from 'node:process'

import { chromium } from 'playwright-core'

const baseUrl = process.env.PLANNING_LOCALE_BASE_URL || 'http://127.0.0.1:8080'
const chromePath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const envelope = (data) => JSON.stringify({ success: true, data, request_id: 'planning-locale-e2e' })

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const browser = await chromium.launch({ executablePath: chromePath, headless: true })
const context = await browser.newContext({ locale: 'en-US', viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const pageErrors = []
const apiRequests = []
page.on('pageerror', (error) => pageErrors.push(error.message))
page.on('request', (request) => { if (request.url().includes('/api/v1/')) apiRequests.push(new URL(request.url()).pathname) })

try {
  let authHits = 0
  let setupHits = 0
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
  const project = { id: '10000000-0000-4000-8000-000000000001', code: 'DEMO', name: 'Sample Project', kind: 'SOFTWARE', status: 'ACTIVE', owner_member_id: null }
  // Keep unrelated shell queries from reaching the unauthenticated local API and expiring the mocked session.
  await page.route('**/api/v1/**', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/setup', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ completed: true, wizard: false }) }))
  await page.route('**/api/v1/auth/agent-commands', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ commands: [], install: { bash: '', powershell: '', repo: '' } }) }))
  await page.route('**/api/v1/intakes*', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ items: [], summary: { pending_approval: 0 }, total: 0 }) }))
  await page.route('**/api/v1/changelog', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ build: { sha: '' }, behind: 0, entries: [] }) }))
  await page.route('**/api/v1/operations/status', (route) => route.fulfill({ contentType: 'application/json', body: envelope({}) }))
  await page.route('**/api/v1/private-space/watch/health', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ tracks: [], check_hours: 24 }) }))
  await page.route('**/api/v1/planning/overview/*', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ projects: [], overdue_total: 0 }) }))
  await page.route('**/api/v1/setup/status', (route) => { setupHits += 1; return route.fulfill({ contentType: 'application/json', body: envelope({ needs_bootstrap: false }) }) })
  await page.route('**/api/v1/auth/me', (route) => { authHits += 1; return route.fulfill({ contentType: 'application/json', body: envelope({ subject: 'cto', email: 'cto@example.test', display_name: 'CTO', role: 'CTO', can_view_raw: true, can_approve: true, mfa_enabled: false, project_ids: null, must_change_password: false, member_id: null }) }) })
  await page.route('**/api/v1/projects', (route) => route.fulfill({ contentType: 'application/json', body: envelope([project]) }))
  await page.route('**/api/v1/planning/members', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/planning/day-plans/*', (route) => route.fulfill({ contentType: 'application/json', body: envelope({
    plan_date: today,
    projects: [{ id: project.id, code: project.code, name: project.name, owner_name: 'Project Owner', run: { id: 'run-1', status: 'DRAFT', version: 1, revision: 1, open: true, assigned_hours: 3, assignments: 1, warnings: 0, unseen_warnings: 0 }, people: [{ member_id: 'member-1', name: 'Sample Member', hours: 3, planned: 3, elsewhere: [], assignments: [{ id: 'assignment-1', slot: 'MORNING', hours: 3, issue: '101', issue_url: null, title: 'Prepare onboarding flow', intake_id: null, intake_public_id: null, priority: 'P2', work_status: 'PLANNED', accepted: false }] }], free: [], off: [], waiting: [], off_plan: [] }],
    project_order: { mode: 'PRIORITY', project_ids: [] },
    totals: { projects: 1, unclosed: 1, free_hours: 0, free_people: 0, waiting: 0, off_plan: 0, off_plan_actual_minutes: 0 },
  }) }))

  await page.goto(`${baseUrl}/planning?lang=en`, { waitUntil: 'networkidle' })
  if (new URL(page.url()).pathname !== '/planning') {
    throw new Error(`Planning navigation ended at ${page.url()} (auth=${authHits}, setup=${setupHits}): ${(await page.locator('body').innerText()).slice(0, 1000)}`)
  }
  await page.waitForTimeout(500)
  if (await page.getByRole('heading', { name: 'Daily Planning' }).count() === 0) {
    throw new Error(`Daily Planning heading is missing at ${page.url()} (${pageErrors.join(' | ')}) requests=${[...new Set(apiRequests)].join(',')}: ${(await page.locator('body').innerText()).slice(0, 2000)}`)
  }
  await page.getByRole('heading', { name: 'Daily Planning' }).waitFor()
  await page.getByText('Project overview', { exact: true }).waitFor()
  await page.getByRole('button', { name: 'By project' }).waitFor()
  await page.getByRole('button', { name: 'By person' }).waitFor()
  await page.getByLabel('Order').waitFor()
  await page.getByRole('option', { name: 'Processing priority' }).waitFor({ state: 'attached' })

  for (const vietnameseChrome of ['Tổng quan theo dự án', 'Theo dự án', 'Theo người', 'Thứ tự', 'Ưu tiên xử lý', 'Đang xếp', 'Mở kế hoạch']) {
    assert(await page.getByText(vietnameseChrome, { exact: true }).count() === 0, `English Planning still shows Vietnamese UI text: ${vietnameseChrome}`)
  }
  assert(await page.locator('html').getAttribute('lang') === 'en', 'Planning must keep the document language set to English')
  console.log('planning-locale: ok')
} finally {
  await browser.close()
}
