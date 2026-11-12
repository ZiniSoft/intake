import process from 'node:process'

import { chromium } from 'playwright-core'

const baseUrl = process.env.SETTINGS_TABS_BASE_URL || 'http://127.0.0.1:8080'
const chromePath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const envelope = (data) => JSON.stringify({ success: true, data, request_id: 'settings-tabs-locale-e2e' })
const assert = (condition, message) => { if (!condition) throw new Error(message) }

const browser = await chromium.launch({ executablePath: chromePath, headless: true })
const context = await browser.newContext({ locale: 'en-US', viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()

try {
  await page.route('**/api/v1/**', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ subject: 'cto', email: 'cto@example.test', display_name: 'Test CTO', role: 'CTO', can_view_raw: true, can_approve: true, mfa_enabled: true, project_ids: null, must_change_password: false, member_id: 'member-cto' }) }))
  await page.route('**/api/v1/setup', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ completed: true, wizard: false }) }))
  await page.route('**/api/v1/auth/agent-commands', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ commands: [], install: { bash: '', powershell: '', repo: '' } }) }))
  await page.route('**/api/v1/intakes*', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ items: [], summary: { pending_approval: 0 }, total: 0 }) }))
  await page.route('**/api/v1/changelog', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ build: { sha: '' }, behind: 0, entries: [] }) }))
  await page.route('**/api/v1/private-space/watch/health', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ tracks: [], check_hours: 24 }) }))
  await page.route('**/api/v1/planning/overview/*', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ projects: [], overdue_total: 0 }) }))
  await page.route('**/api/v1/projects', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/planning/members*', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/users', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/meetings/glossary*', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/ai/providers', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/ai/routes', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/notify/telegram/messages*', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/notify/telegram', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ bot_username: null, bot_seen_at: null, projects: [], members: [], holidays: [] }) }))
  await page.route('**/api/v1/operations/status', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ status: 'ok', web: 'ok', worker_ai: 'ok', ai_configured: false, ai_source: 'none', storage: 'ok', backup: 'unknown', backup_detail: { state: 'missing', last_ok_at: null, last_ok_size_bytes: null, last_error_code: null } }) }))
  await page.route('**/api/v1/hints', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ dismissed: [] }) }))
  await page.route('**/api/v1/auth/tokens', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))

  const checks = [
    ['/settings/members', 'Team', 'By project', ['Nhân sự', 'Theo dự án', 'Thêm nhân sự']],
    ['/settings/users', 'Users', 'Developer accounts', ['Người dùng', 'Tài khoản Developer', 'Cấp lại mật khẩu']],
    ['/settings/glossary', 'Glossary', 'No terms yet.', ['Thuật ngữ', 'Phạm vi', 'Thêm']],
    ['/settings/ai', 'AI', 'How AI works in Intake', ['AI làm gì trong Intake', 'Nhà cung cấp', 'Cấu hình 3 nhóm model xử lý công việc']],
    ['/settings/system', 'System', 'Telegram reminders', ['Hệ thống', 'Nhắc việc qua Telegram', 'Trạng thái', 'Ranh giới riêng tư']],
    ['/settings/account', 'Settings', 'Password', ['Mật khẩu', 'Xác thực hai lớp', 'Mã khôi phục', 'Hướng dẫn nhanh']],
  ]

  for (const [path, heading, visible, forbidden] of checks) {
    await page.goto(`${baseUrl}${path}?lang=en`, { waitUntil: 'networkidle' })
    await page.getByRole('heading', { name: heading, exact: true }).first().waitFor()
    await page.getByText(visible, { exact: true }).first().waitFor()
    for (const value of forbidden) {
      assert(await page.getByText(value, { exact: true }).count() === 0, `${path} still shows Vietnamese UI text: ${value}`)
    }
    const bodyText = await page.locator('body').innerText()
    const vietnameseLine = bodyText.split('\n').find((line) => /[À-ỹĐđ]/u.test(line))
    assert(!vietnameseLine, `${path} still shows Vietnamese characters: ${vietnameseLine}`)
  }

  console.log('settings-tabs-locale: ok')
} finally {
  await browser.close()
}
