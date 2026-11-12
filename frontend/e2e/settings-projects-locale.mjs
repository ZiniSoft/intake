import process from 'node:process'

import { chromium } from 'playwright-core'

const baseUrl = process.env.SETTINGS_PROJECTS_BASE_URL || 'http://127.0.0.1:8080'
const chromePath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const envelope = (data) => JSON.stringify({ success: true, data, request_id: 'settings-projects-locale-e2e' })
const assert = (condition, message) => { if (!condition) throw new Error(message) }

const browser = await chromium.launch({ executablePath: chromePath, headless: true })
const context = await browser.newContext({ locale: 'en-US', viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()

try {
  await page.route('**/api/v1/**', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ subject: 'cto', email: 'cto@example.test', display_name: 'CTO', role: 'CTO', can_view_raw: true, can_approve: true, mfa_enabled: true, project_ids: null, must_change_password: false, member_id: null }) }))
  await page.route('**/api/v1/setup', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ completed: true, wizard: false }) }))
  await page.route('**/api/v1/auth/agent-commands', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ commands: [], install: { bash: '', powershell: '', repo: '' } }) }))
  await page.route('**/api/v1/intakes*', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ items: [], summary: { pending_approval: 0 }, total: 0 }) }))
  await page.route('**/api/v1/changelog', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ build: { sha: '' }, behind: 0, entries: [] }) }))
  await page.route('**/api/v1/operations/status', (route) => route.fulfill({ contentType: 'application/json', body: envelope({}) }))
  await page.route('**/api/v1/private-space/watch/health', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ tracks: [], check_hours: 24 }) }))
  await page.route('**/api/v1/planning/overview/*', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ projects: [], overdue_total: 0 }) }))
  await page.route('**/api/v1/projects', (route) => route.fulfill({ contentType: 'application/json', body: envelope([{ id: 'project-1', code: 'DEMO', intake_key: 'DEM', name: 'Sample Project', kind: 'SOFTWARE', status: 'ACTIVE', owner_name: null, delivery_system: 'GITHUB', github_repository: 'example/sample', github_project_url: null, github_enabled: false, gitlab_project_id: null, gitlab_project_url: null, gitlab_enabled: false, telegram_linked: false, telegram_chat_title: null }]) }))
  await page.route('**/api/v1/integrations/github-tokens', (route) => route.fulfill({ contentType: 'application/json', body: envelope([]) }))
  await page.route('**/api/v1/integrations/gitlab-connection', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ source: 'NONE', configured: false, linked_projects: 0, base_url: 'https://gitlab.com', key_hint: null }) }))
  await page.route('**/api/v1/showcase?locale=en', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ groups: {}, items: [] }) }))

  await page.goto(`${baseUrl}/settings/projects?lang=en`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Settings' }).waitFor()
  await page.getByRole('heading', { name: 'Projects', exact: true }).waitFor()
  await page.getByRole('link', { name: 'Create project' }).waitFor()
  await page.getByRole('columnheader', { name: 'Delivery tracker' }).waitFor()
  await page.getByRole('heading', { name: 'GitLab connection' }).waitFor()
  await page.getByRole('heading', { name: 'GitHub tokens' }).waitFor()
  await page.getByRole('heading', { name: 'Sample and open-source projects' }).waitFor()
  for (const value of ['Cài đặt', 'Dự án', 'Tạo dự án', 'Nơi giao việc', 'Nhóm Telegram', 'Token GitHub', 'Dự án mẫu và open source']) {
    assert(await page.getByText(value, { exact: true }).count() === 0, `English Settings > Projects still shows Vietnamese UI text: ${value}`)
  }
  console.log('settings-projects-locale: ok')
} finally {
  await browser.close()
}
