import process from 'node:process'

import { chromium } from 'playwright-core'


const baseUrl = process.env.SETUP_UI_BASE_URL || 'http://127.0.0.1:5173'
const chromePath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const envelope = (data) => JSON.stringify({ success: true, data, request_id: 'setup-demo-e2e' })
const assert = (condition, message) => { if (!condition) throw new Error(message) }

// Auth and every API call are mocked: no server, no key, no real data.
const calls = []
let hasDemo = false
const state = () => ({ completed: hasDemo, has_project: false, has_private_space: false, sample_available: true, wizard: true, ai_ready: false, has_demo: hasDemo, demo_available: true })

const browser = await chromium.launch({ executablePath: chromePath, headless: true })
const page = await (await browser.newContext({ locale: 'vi-VN', viewport: { width: 1440, height: 1100 } })).newPage()

try {
  await page.route('**/api/v1/**', (r) => r.fulfill({ contentType: 'application/json', body: envelope(r.request().url().endsWith('/changelog') ? { entries: [], build: { sha: '' } } : r.request().url().includes('/planning/overview/') ? { plan_date: '2026-11-04', generated_at: '2026-11-04T01:00:00Z', gitlab_snapshot_at: null, missing_projects: 0, overdue_total: 0, projects: [], cto_time: null } : []) }))
  await page.route('**/api/v1/auth/agent-commands', (r) => r.fulfill({ contentType: 'application/json', body: envelope({ commands: [] }) }))
  await page.route('**/api/v1/auth/me', (r) => r.fulfill({ contentType: 'application/json', body: envelope({ subject: 'cto', email: 'cto@example.test', display_name: 'CTO', role: 'CTO', can_view_raw: true, can_approve: true, mfa_enabled: false, project_ids: null, must_change_password: false, member_id: null }) }))
  await page.route('**/api/v1/setup', (r) => r.fulfill({ contentType: 'application/json', body: envelope(state()) }))
  await page.route('**/api/v1/projects', (r) => r.fulfill({ contentType: 'application/json', body: envelope(hasDemo ? [{ id: 'p-demo', code: 'demo', intake_key: 'DEM', name: 'Dự án mẫu', status: 'ACTIVE', kind: 'SOFTWARE', gitlab_enabled: false, github_enabled: false, telegram_linked: false, agent_ready: false }] : []) }))
  await page.route('**/api/v1/intakes?**', (r) => r.fulfill({ contentType: 'application/json', body: envelope({ items: hasDemo ? [{ id: 'i1', public_id: 'DEM-1', project_id: 'p-demo', status: 'PENDING_APPROVAL', normalized_title: 'Mẫu', lifecycle_stage: 'REVIEW', suggested_priority: 'P2', approved_priority: null, sync_targets: [], created_at: '2026-11-04T01:00:00Z', updated_at: '2026-11-04T01:00:00Z' }] : [], next_cursor: null, limit: 10, summary: { total_items: 0, p0_attention: 0, p1_attention: 0, pending_approval: 0, sync_failed: 0 } }) }))
  await page.route('**/api/v1/setup/demo-project',(r) => { calls.push(r.request().method()); hasDemo = true; return r.fulfill({ contentType: 'application/json', body: envelope(state()) }) })

  await page.goto(`${baseUrl}/setup`, { waitUntil: 'networkidle' })
  // Step 1 offers the demo; no key exists, so step 2 would keep "Tiếp tục" closed.
  await page.getByRole('button', { name: /Nối khóa AI của tôi/ }).click()
  assert(await page.getByRole('button', { name: 'Tiếp tục' }).isDisabled(), 'continue must wait for a key')
  await page.getByRole('button', { name: 'Quay lại' }).click()
  await page.getByRole('button', { name: /Dùng thử với dự án mẫu/ }).click()
  await page.getByRole('heading', { name: 'Xong, vào làm việc' }).waitFor({ timeout: 4000 })
  assert(calls.join() === 'POST', `expected one POST, got ${calls.join()}`)
  await page.getByRole('link', { name: 'Mở dự án mẫu' }).click()
  await page.waitForURL(/\/intakes\?project=demo/)
  await page.getByText('Đây là dữ liệu mẫu.').waitFor({ timeout: 4000 }).catch(async (e) => { console.log(page.url(), (await page.locator('main').innerText()).slice(0, 500)); throw e })

  // The basic menu hides the rest; one click brings it back and the choice is remembered.
  const nav = page.locator('aside nav, nav[aria-label]').first()
  assert(await nav.getByRole('link', { name: 'Daily Planning' }).count() === 0, 'basic menu must hide Daily Planning')
  await nav.locator('button.nav-mode-toggle').click()
  assert(await nav.getByRole('link', { name: 'Daily Planning' }).count() === 1, 'full menu must show Daily Planning')
  await page.reload({ waitUntil: 'networkidle' })
  assert(await nav.getByRole('link', { name: 'Daily Planning' }).count() === 1, 'the menu choice must survive a reload')

  // Today shows the "Bắt đầu" card; the demo's own requests do not tick "Gửi một yêu cầu thử".
  await page.goto(`${baseUrl}/`, { waitUntil: 'networkidle' })
  const card = page.getByRole('region', { name: 'Bắt đầu' })
  await card.waitFor({ timeout: 4000 })
  assert(await card.getByRole('img', { name: 'Đã xong' }).count() === 0, 'nothing is done yet')
  await card.getByRole('button', { name: 'Ẩn' }).click()
  await page.reload({ waitUntil: 'networkidle' })
  assert(await page.getByRole('region', { name: 'Bắt đầu' }).count() === 0, 'the card must stay hidden')
  console.log('setup-demo-project: ok')
} finally {
  await browser.close()
}
