import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'


const here = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(here, '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const baseUrl = process.env.PLANNING_UI_BASE_URL || 'http://127.0.0.1:8080'
const chromePath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'


function readEnv(filePath) {
  const values = {}
  for (const originalLine of fs.readFileSync(filePath, 'utf8').split(/\r?\n/)) {
    const line = originalLine.trim()
    if (!line || line.startsWith('#')) continue
    const separator = line.indexOf('=')
    if (separator < 1) continue
    const key = line.slice(0, separator).trim()
    let value = line.slice(separator + 1).trim()
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1)
    values[key] = value
  }
  return values
}


function envelope(data) {
  return JSON.stringify({ success: true, data, request_id: 'planning-ui-e2e' })
}


function assert(condition, message) {
  if (!condition) throw new Error(message)
}


const env = readEnv(path.join(repositoryRoot, '.env'))
assert(env.CTO_INITIAL_PASSWORD, 'CTO_INITIAL_PASSWORD is required in .env')
assert(fs.existsSync(chromePath), `Chrome executable not found: ${chromePath}`)

const browser = await chromium.launch({ executablePath: chromePath, headless: true })
const context = await browser.newContext({ locale: 'vi-VN', viewport: { width: 1440, height: 1100 } })
const page = await context.newPage()

try {
  await page.goto(`${baseUrl}/login?lang=vi`, { waitUntil: 'networkidle' })
  await page.getByLabel('Tài khoản').fill('cto')
  await page.getByLabel('Mật khẩu').fill(env.CTO_INITIAL_PASSWORD)
  await page.getByRole('button', { name: 'Đăng nhập an toàn' }).click()
  await page.waitForURL((url) => url.pathname !== '/login', { timeout: 30_000 })

  const projectsResponse = await page.evaluate(async () => {
    const response = await fetch('/api/v1/projects', { credentials: 'include' })
    return response.json()
  })
  const project = projectsResponse.data[0]
  assert(project?.id, 'Seeded project is required')
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
  const memberId = '20000000-0000-4000-8000-000000000001'
  const candidateId = '30000000-0000-4000-8000-000000000001'
  const assignmentId = '40000000-0000-4000-8000-000000000001'
  const planningRun = {
    id: '50000000-0000-4000-8000-000000000001',
    plan_date: today,
    timezone: 'Asia/Ho_Chi_Minh',
    project_ids: [project.id],
    status: 'REVIEW_REQUIRED',
    version: 4,
    revision: 1,
    source_snapshot_at: new Date().toISOString(),
    candidates: [{
      id: candidateId,
      planning_run_id: '50000000-0000-4000-8000-000000000001',
      project_id: project.id,
      member_id: memberId,
      intake_id: null,
      assignment_id: assignmentId,
      source_type: 'GITLAB',
      source_reference: 'https://gitlab.test/issues/125',
      gitlab_issue_external_id: '125',
      plane_reference: null,
      title: 'Hoàn thiện luồng onboarding khách hàng',
      summary: 'Candidate lấy từ GitLab read model và được xếp vào buổi sáng.',
      status: 'ASSIGNED',
      proposed_priority: 'P1',
      requested_hours: 4,
      target_slot: 'MORNING',
      created_at: new Date().toISOString(),
    }],
    assignments: [{
      id: assignmentId,
      project_id: project.id,
      member_id: memberId,
      slot: 'MORNING',
      work_type: 'DEVELOPMENT',
      is_primary: true,
      planned_hours: 4,
      source_type: 'GITLAB',
      source_reference: 'https://gitlab.test/issues/125',
      gitlab_issue_external_id: '125',
      proposed_priority: 'P1',
      approved_priority: null,
      proposed_assignee_external_id: '42',
      approved_assignee_external_id: null,
      proposed_milestone_external_id: '9',
      approved_milestone_external_id: null,
      proposed_due_date: today,
      approved_due_date: null,
      dependency_state: null,
      source_state: 'opened',
      override_reason: null,
      version: 1,
    }],
    warnings: [{
      id: '60000000-0000-4000-8000-000000000001',
      code: 'REPORT_MISSING',
      severity: 'WARNING',
      message: 'Thiếu Daily Report; kế hoạch vẫn chạy và GitLab là nguồn chính.',
      member_id: memberId,
      project_id: project.id,
      acknowledged_at: null,
    }],
  }
  const syncStatus = {
    planning_run_id: planningRun.id,
    snapshot_id: '70000000-0000-4000-8000-000000000001',
    status: 'SYNC_FAILED',
    jobs: [{
      id: '80000000-0000-4000-8000-000000000001',
      project_id: project.id,
      gitlab_issue_external_id: '125',
      status: 'FAILED',
      attempt: 1,
      max_attempts: 5,
      error_code: 'GITLAB_TEMPORARILY_UNAVAILABLE',
      next_attempt_at: null,
      updated_at: new Date().toISOString(),
    }],
  }

  await page.route('**/api/v1/planning/members', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope([{
    id: memberId,
    display_name: 'Nguyễn Minh Anh',
    email_reference: 'minh.anh@example.com',
    status: 'ACTIVE',
    timezone: 'Asia/Ho_Chi_Minh',
    default_weekday_hours: 8,
    project_mappings: [{ project_id: project.id, gitlab_user_external_id: '42', role: 'Developer', active: true }],
  }]) }))
  await page.route('**/api/v1/planning/capacities/*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope([{
    member_id: memberId,
    display_name: 'Nguyễn Minh Anh',
    work_date: today,
    base_hours: 8,
    override_hours: null,
    meeting_hours: 1,
    review_hours: 1,
    support_hours: 0,
    fixed_hours: 0,
    available_hours: 6,
    override_reason: null,
    version: 1,
  }]) }))
  await page.route('**/api/v1/planning/runs', async (route) => {
    if (route.request().method() === 'POST') await route.fulfill({ status: 201, contentType: 'application/json', body: envelope(planningRun) })
    else await route.continue()
  })
  await page.route(`**/api/v1/planning/runs/${planningRun.id}`, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope(planningRun) }))
  await page.route(`**/api/v1/planning/runs/${planningRun.id}/sync-jobs`, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope(syncStatus) }))
  await page.route(`**/api/v1/planning/runs/${planningRun.id}/sync-jobs/${syncStatus.jobs[0].id}/retry`, (route) => {
    syncStatus.jobs[0].status = 'PENDING'
    syncStatus.jobs[0].error_code = null
    syncStatus.status = 'SYNCING'
    return route.fulfill({ status: 202, contentType: 'application/json', body: envelope(syncStatus.jobs[0]) })
  })

  await page.getByRole('link', { name: 'Daily Planning' }).click()
  await page.getByRole('heading', { name: 'Kế hoạch triển khai trong ngày' }).waitFor()
  await page.getByText('Nguyễn Minh Anh').waitFor()
  await page.getByRole('button', { name: 'Mở / tạo Planning Run' }).click()
  await page.getByRole('heading', { name: 'Thêm yêu cầu buổi sáng' }).waitFor()
  await page.getByRole('heading', { name: 'Phân bổ sáng / chiều' }).waitFor()
  await page.getByText('Hoàn thiện luồng onboarding khách hàng').first().waitFor()
  await page.getByText('REPORT_MISSING').waitFor()
  await page.getByRole('heading', { name: 'Đồng bộ theo từng Issue' }).waitFor()
  await page.getByText('GITLAB_TEMPORARILY_UNAVAILABLE').waitFor()
  await page.getByRole('button', { name: 'Thử lại đồng bộ' }).click()
  await page.getByText('PENDING').waitFor()
  await page.screenshot({ path: path.join(repositoryRoot, 'data', 'planning-ui-desktop.png'), fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Kế hoạch triển khai trong ngày' }).waitFor()
  await page.getByRole('button', { name: 'Mở / tạo Planning Run' }).click()
  await page.getByRole('heading', { name: 'Phân bổ sáng / chiều' }).waitFor()
  await page.screenshot({ path: path.join(repositoryRoot, 'data', 'planning-ui-mobile.png'), fullPage: true })
  console.log(JSON.stringify({ planning_ui: 'passed', desktop: true, mobile: true }))
} finally {
  await browser.close()
}
