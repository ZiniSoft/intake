import process from 'node:process'

import { chromium } from 'playwright-core'

// FR-INTG-22, FR-INTG-23: the optional GitLab/GitHub step of the first-run setup. Every API call is mocked.
const baseUrl = process.env.SETUP_UI_BASE_URL || 'http://127.0.0.1:5173'
const chromePath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const shots = process.env.SHOT_DIR
const envelope = (data) => JSON.stringify({ success: true, data, request_id: 'setup-tracker-e2e' })
const assert = (condition, message) => { if (!condition) throw new Error(message) }
const json = (r, data) => r.fulfill({ contentType: 'application/json', body: envelope(data) })

const state = { completed: false, has_project: false, has_private_space: false, sample_available: true, wizard: true, ai_ready: true, has_demo: false, demo_available: true }
const probes = []

const browser = await chromium.launch({ executablePath: chromePath, headless: true })
const page = await (await browser.newContext({ locale: 'vi-VN', viewport: { width: 1280, height: 1100 } })).newPage()

try {
  await page.route('**/api/v1/**', (r) => json(r, r.request().url().endsWith('/changelog') ? { entries: [], build: { sha: '' } } : []))
  await page.route('**/api/v1/auth/agent-commands', (r) => json(r, { commands: [] }))
  await page.route('**/api/v1/auth/me', (r) => json(r, { subject: 'cto', email: 'cto@example.test', display_name: 'CTO', role: 'CTO', can_view_raw: true, can_approve: true, mfa_enabled: false, project_ids: null, must_change_password: false, member_id: null }))
  await page.route('**/api/v1/showcase', (r) => json(r, { items: [] }))
  await page.route('**/api/v1/setup', (r) => json(r, state))
  await page.route('**/api/v1/integrations/gitlab-connection', (r) => json(r, { configured: false, source: 'NONE', base_url: null, key_hint: null, updated_at: null, linked_projects: 0 }))
  await page.route('**/api/v1/integrations/github-tokens', (r) => json(r, [{ name: 'GITHUB_TOKEN_ZTEST', key_hint: 'WXYZ', source: 'APP' }]))
  await page.route('**/api/v1/projects/integration-probes', (r) => {
    const body = r.request().postDataJSON()
    probes.push(body)
    return json(r, { id: 'probe-1', system: body.system, action: body.action, status: 'DONE', error_code: null,
      result: { system: 'GITHUB', ok: false, checks: [{ key: 'token_valid', status: 'OK', detail: null }, { key: 'issues_write', status: 'MISSING', detail: 'public_read_only' }, { key: 'contents_read', status: 'MISSING', detail: null }] } })
  })

  page.on('pageerror', (e) => console.log('page error:', e.stack))
  await page.goto(`${baseUrl}/setup`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Xong, vào làm việc' }).waitFor({ timeout: 4000 })
  await page.getByRole('button', { name: 'Nối GitLab/GitHub' }).click()
  await page.getByRole('heading', { name: /Nối GitLab hoặc GitHub/ }).waitFor({ timeout: 4000 })
  // No token yet: the guide is open and the check waits for a saved token.
  assert(await page.locator('details.token-help').evaluate((node) => node.open), 'the GitLab guide must be open without a token')
  const link = await page.getByRole('link', { name: 'Mở trang tạo token GitLab' }).getAttribute('href')
  assert(link.includes('scopes=api,read_repository'), `token link must preselect scopes: ${link}`)
  assert(await page.getByRole('button', { name: 'Kiểm tra quyền' }).isDisabled(), 'check needs a token')
  if (shots) await page.screenshot({ path: `${shots}/setup-gitlab.png`, fullPage: true })

  await page.getByRole('tab', { name: 'GitHub của khách' }).click()
  await page.getByPlaceholder('ten-khach/ten-repository').fill('ztest/app')
  await page.getByRole('button', { name: 'Kiểm tra quyền' }).click()
  await page.getByText('Token còn thiếu quyền').waitFor({ timeout: 4000 })
  await page.getByText('Sửa token: Contents = Read-only.').waitFor({ timeout: 4000 })
  // FR-INTG-23: the worker's cause code becomes a named hint, never a raw code, with a link to the common mistakes.
  await page.getByText(/Repository access đang là "Public repositories"/).waitFor({ timeout: 4000 })
  assert(!(await page.getByText('public_read_only').count()), 'the cause code must not show as text')
  const mistakes = await page.getByRole('link', { name: 'Xem các lỗi thường gặp khi tạo token' }).getAttribute('href')
  assert(mistakes === '/huong-dan#guide-token-mistakes', `unexpected mistakes link ${mistakes}`)
  assert(probes.length === 1 && probes[0].action === 'ACCESS' && probes[0].token_ref === 'GITHUB_TOKEN_ZTEST', `unexpected probe ${JSON.stringify(probes)}`)
  if (shots) await page.screenshot({ path: `${shots}/setup-github.png`, fullPage: true })

  await page.getByRole('button', { name: 'Để sau' }).click()
  await page.getByRole('heading', { name: 'Xong, vào làm việc' }).waitFor({ timeout: 4000 })
  console.log('setup tracker step: ok')
} catch (error) {
  console.log(page.url(), (await page.locator('body').innerText()).slice(0, 600))
  throw error
} finally {
  await browser.close()
}
