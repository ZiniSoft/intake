// "Kế hoạch theo người" (FR-PLAN-40): every API call is mocked, nothing is written anywhere.
// Run against the Vite dev server: `npx vite --host 127.0.0.1 --port 5173`, then `node e2e/member-plan.mjs`.
import process from 'node:process'

import { chromium } from 'playwright-core'


const baseUrl = process.env.MEMBER_PLAN_BASE_URL || 'http://127.0.0.1:5173'
const chromePath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const shotsDir = process.env.SHOTS_DIR

const envelope = (data) => JSON.stringify({ success: true, data, request_id: 'member-plan-e2e' })
const failure = (status, code, message) => JSON.stringify({ error: code, message, details: [], request_id: 'member-plan-e2e' })
const assert = (condition, message) => { if (!condition) throw new Error(message) }
const shot = async (page, name) => { if (shotsDir) await page.screenshot({ path: `${shotsDir}/${name}.png`, fullPage: true }) }

const ANH = '11111111-0000-4000-8000-000000000001'
const BINH = '11111111-0000-4000-8000-000000000002'
const HIDDEN = '11111111-0000-4000-8000-000000000009'
const DAY = '2031-03-12'
const day = (value) => new Date(`${value}T00:00:00Z`)
const iso = (date) => date.toISOString().slice(0, 10)
const plus = (value, n) => { const date = day(value); date.setUTCDate(date.getUTCDate() + n); return iso(date) }
const monday = plus(DAY, -((day(DAY).getUTCDay() + 6) % 7))

const users = {
  CTO: { subject: 'cto', email: 'cto@example.test', display_name: 'CTO', role: 'CTO', can_view_raw: true, can_approve: true, mfa_enabled: false, project_ids: null, must_change_password: false, member_id: null },
  DEVELOPER: { subject: 'dev', email: 'dev@example.test', display_name: 'ZTEST Dev', role: 'DEVELOPER', can_view_raw: false, can_approve: false, mfa_enabled: false, project_ids: [], must_change_password: false, member_id: BINH },
}

function planFor(memberId, from, to) {
  const days = []
  for (let current = from; current <= to; current = plus(current, 1)) {
    const weekend = day(current).getUTCDay() % 6 === 0
    const off = weekend || current === plus(monday, 4)
    const isDay = current === DAY
    days.push({
      date: current, capacity_hours: off ? 0 : 8, personal_hours: isDay ? 2 : 0, available_hours: off ? 0 : isDay ? 6 : 8,
      planned_hours: isDay ? 9 : 0, off,
      items: isDay ? [
        { kind: 'ASSIGNMENT', id: 'a1', run_id: 'r1', run_status: 'APPROVED', project_id: 'p1', project: 'ZTA', project_name: 'ZTEST Alpha', title: 'ZTEST sửa trang đăng nhập', issue: '42', issue_url: 'https://gitlab.example.test/zta/-/issues/42', intake: null, priority: 'P1', slot: 'MORNING', hours: 4, work_type: 'ISSUE', status: 'DONE', accepted_at: `${DAY}T10:00:00Z` },
        { kind: 'WORK_ITEM', id: 'w1', code: 'ZTA-W1', title: 'ZTEST viết hướng dẫn', status: 'IN_PROGRESS', priority: null, project_id: 'p1', project: 'ZTA', project_name: 'ZTEST Alpha', channel: null, urgent: false, due_date: DAY, closed: false },
      ] : [],
      hidden_projects: isDay ? [{ name: 'ZTEST Beta', hours: 5 }] : [],
    })
  }
  return {
    member: { member_id: memberId, display_name: memberId === ANH ? 'ZTEST Anh' : 'ZTEST Bình', is_me: false }, from, to, days,
    totals: {
      planned_hours: days.reduce((sum, row) => sum + row.planned_hours, 0), available_hours: days.reduce((sum, row) => sum + row.available_hours, 0),
      personal_hours: days.reduce((sum, row) => sum + row.personal_hours, 0), off_days: days.filter((row) => row.off && day(row.date).getUTCDay() % 6 !== 0).length,
      by_project: days.some((row) => row.date === DAY) ? [{ name: 'ZTEST Beta', hours: 5, visible: false }, { name: 'ZTEST Alpha', hours: 4, visible: true }] : [],
      work_status: { PLANNED: 0, IN_PROGRESS: 0, DONE: days.some((row) => row.date === DAY) ? 1 : 0, BLOCKED: 0 }, accepted: days.some((row) => row.date === DAY) ? 1 : 0,
      work_items: days.some((row) => row.date === DAY) ? { IN_PROGRESS: 1 } : {},
    },
  }
}

async function open(browser, role, viewport = { width: 1440, height: 1000 }) {
  const context = await browser.newContext({ locale: 'vi-VN', viewport })
  const page = await context.newPage()
  const requests = []
  await page.route('**/api/v1/**', (r) => r.fulfill({ contentType: 'application/json', body: envelope(r.request().url().includes('/changelog') ? { entries: [], build: { sha: 'e2e0000', built_at: null } } : []) }))
  await page.route('**/api/v1/auth/me', (r) => r.fulfill({ contentType: 'application/json', body: envelope(users[role]) }))
  await page.route('**/api/v1/setup', (r) => r.fulfill({ contentType: 'application/json', body: envelope({ completed: true, wizard: false }) }))
  await page.route('**/api/v1/planning/people', (r) => r.fulfill({ contentType: 'application/json', body: envelope({
    me: users[role].member_id,
    members: [{ member_id: ANH, display_name: 'ZTEST Anh', is_me: false }, { member_id: BINH, display_name: 'ZTEST Bình', is_me: role === 'DEVELOPER' }],
  }) }))
  await page.route(/\/api\/v1\/planning\/people\/[^/]+\/plan\?/, (r) => {
    const url = new URL(r.request().url())
    const memberId = url.pathname.split('/').at(-2)
    requests.push({ memberId, from: url.searchParams.get('from'), to: url.searchParams.get('to') })
    if (memberId === HIDDEN) return r.fulfill({ status: 404, contentType: 'application/json', body: failure(404, 'MEMBER_NOT_FOUND', 'Member was not found') })
    return r.fulfill({ contentType: 'application/json', body: envelope(planFor(memberId, url.searchParams.get('from'), url.searchParams.get('to'))) })
  })
  return { context, page, requests }
}

const results = {}
const browser = await chromium.launch({ executablePath: chromePath, headless: true })
try {
  // 1. The CTO opens a week: assignments, work items, hidden projects, someone else's personal hours, a day off.
  {
    const { context, page, requests } = await open(browser, 'CTO')
    await page.goto(`${baseUrl}/ke-hoach-nguoi?member=${ANH}&date=${DAY}`, { waitUntil: 'networkidle' })
    await page.getByText('ZTEST sửa trang đăng nhập').waitFor()
    const last = requests.at(-1)
    assert(last.memberId === ANH && last.from === monday && last.to === plus(monday, 6), `week range: ${JSON.stringify(last)}`)
    await page.getByText('ZTEST viết hướng dẫn').waitFor()
    await page.getByText('ZTEST Beta: 5 giờ').waitFor()
    await page.getByText('Việc riêng: 2 giờ').waitFor()
    assert(await page.locator('.mp-day').count() === 7, 'a week shows seven days')
    assert(await page.locator('.mp-day.is-off').count() === 3, 'Friday off and the weekend are marked')
    assert(await page.locator('.mp-hours.is-over').count() === 1, 'the overbooked day is marked')
    await page.getByText('Theo dự án:').waitFor()
    assert(await page.locator('.mp-chip.is-hidden', { hasText: 'ZTEST Beta' }).count() === 1, 'a project the viewer does not share is marked')
    results.week = true
    await shot(page, 'member-plan-week')

    // 2. Next and previous move a week; "Hôm nay" comes back to today.
    const nextRead = page.waitForResponse(/\/plan\?/)
    await page.getByRole('button', { name: 'Kỳ sau' }).click()
    await nextRead
    assert(requests.at(-1).from === plus(monday, 7), `next week: ${JSON.stringify(requests.at(-1))}`)
    await page.getByRole('button', { name: 'Kỳ trước' }).click()
    await page.getByText('ZTEST sửa trang đăng nhập').waitFor()
    results.navigate = true

    // 3. A month: the whole month in one read, a click on a day opens that day.
    await page.getByRole('button', { name: 'Tháng', exact: true }).click()
    await page.locator('.mp-month').waitFor()
    assert(requests.at(-1).from === '2031-03-01' && requests.at(-1).to === '2031-03-31', `month range: ${JSON.stringify(requests.at(-1))}`)
    assert(await page.locator('.mp-month-cell:not(.is-pad)').count() === 31, 'March has 31 cells')
    await shot(page, 'member-plan-month')
    await page.getByRole('gridcell', { name: 'Xem ngày 12/3' }).click()
    await page.waitForURL(/view=ngay/)
    await page.getByText('ZTEST Alpha · Xong · đã nghiệm thu').waitFor()
    assert(await page.getByRole('link', { name: /#42/ }).count() === 1, 'the Issue links out')
    assert(requests.at(-1).from === DAY && requests.at(-1).to === DAY, 'a day reads one day')
    results.month_to_day = true

    // 4. Picking another person reads their plan.
    const binhRead = page.waitForResponse((response) => response.url().includes(`/people/${BINH}/plan?`))
    await page.getByLabel('Người').selectOption(BINH)
    await page.waitForURL(new RegExp(`member=${BINH}`))
    await binhRead
    assert(requests.at(-1).memberId === BINH, 'the picker changes the person')
    results.picker = true

    // 5. Someone the viewer may not see: a plain sentence, no retry.
    await page.goto(`${baseUrl}/ke-hoach-nguoi?member=${HIDDEN}&date=${DAY}`, { waitUntil: 'networkidle' })
    await page.getByText('Bạn không xem được kế hoạch của người này.').waitFor()
    results.not_visible = true

    // 6. From the planning "Theo người" board, a name opens the page.
    await page.route(/\/api\/v1\/planning\/people\/\d{4}-\d{2}-\d{2}$/, (r) => r.fulfill({ contentType: 'application/json', body: envelope({
      plan_date: DAY, over: 0, free: 0,
      people: [{ member_id: ANH, display_name: 'ZTEST Anh', available_hours: 8, planned_hours: 4, free_hours: 4, state: 'FREE', projects: [] }],
    }) }))
    await page.route(/\/api\/v1\/planning\/overview\//, (r) => r.fulfill({ contentType: 'application/json', body: envelope({ projects: [], overdue_total: 0, missing_projects: 0, gitlab_snapshot_at: null }) }))
    await page.route('**/api/v1/auth/agent-commands', (r) => r.fulfill({ contentType: 'application/json', body: envelope({ commands: [] }) }))
    await page.route(/\/api\/v1\/intakes\?/, (r) => r.fulfill({ contentType: 'application/json', body: envelope({ items: [], total: 0, next_cursor: null }) }))
    await page.goto(`${baseUrl}/`, { waitUntil: 'networkidle' })
    const peopleTab = page.getByRole('tab', { name: 'Người', exact: true })
    if (await peopleTab.count() > 0) await peopleTab.first().click()
    await page.waitForLoadState('networkidle')
    const nameLink = page.getByRole('link', { name: 'ZTEST Anh' })
    await nameLink.first().click()
    await page.waitForURL(new RegExp(`/ke-hoach-nguoi\\?member=${ANH}`))
    await page.locator('.mp-week').waitFor()
    results.people_board_link = true
    await context.close()
  }

  // 7. A Developer reaches the page from the menu and starts on their own plan.
  {
    const { context, page, requests } = await open(browser, 'DEVELOPER')
    await page.goto(`${baseUrl}/ke-hoach-nguoi`, { waitUntil: 'networkidle' })
    await page.locator('.mp-week').waitFor()
    const menuLink = page.getByRole('link', { name: 'Kế hoạch theo người' })
    assert(await menuLink.count() === 1 && await menuLink.getAttribute('aria-current') === 'page', 'the Developer menu has the page')
    assert(requests.at(-1).memberId === BINH, 'a Developer starts on themselves')
    assert(await page.getByLabel('Người').inputValue() === BINH, 'the picker shows the Developer')
    results.developer = true
    await context.close()
  }

  // 8. A phone: the week stacks, nothing scrolls sideways.
  {
    const { context, page } = await open(browser, 'CTO', { width: 390, height: 844 })
    await page.goto(`${baseUrl}/ke-hoach-nguoi?member=${ANH}&date=${DAY}`, { waitUntil: 'networkidle' })
    await page.getByText('ZTEST sửa trang đăng nhập').waitFor()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    assert(overflow <= 0, `page scrolls sideways by ${overflow}px`)
    await shot(page, 'member-plan-mobile')
    results.mobile = true
    await context.close()
  }
  console.log(JSON.stringify({ member_plan: 'passed', ...results }))
} finally {
  await browser.close()
}
