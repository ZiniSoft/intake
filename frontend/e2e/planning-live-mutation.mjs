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
const planDate = process.env.PLANNING_LIVE_TEST_DATE || '2099-12-31'
const evidencePath = path.join(repositoryRoot, 'data', 'planning-live-mutation-result.json')


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


function assert(condition, message) {
  if (!condition) throw new Error(message)
}


const env = readEnv(path.join(repositoryRoot, '.env'))
assert(env.CTO_INITIAL_PASSWORD, 'CTO_INITIAL_PASSWORD is required in .env')
assert(fs.existsSync(chromePath), `Chrome executable not found: ${chromePath}`)

const browser = await chromium.launch({ executablePath: chromePath, headless: true })
const context = await browser.newContext({ locale: 'vi-VN', viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const title = `E2E Planning Quick Add ${new Date().toISOString()}`
let evidence = { planning_live_mutation: 'started', plan_date: planDate, title }

try {
  await page.goto(`${baseUrl}/login?lang=vi`, { waitUntil: 'networkidle' })
  await page.getByLabel('Tài khoản').fill('cto')
  await page.getByLabel('Mật khẩu').fill(env.CTO_INITIAL_PASSWORD)
  await page.getByRole('button', { name: 'Đăng nhập an toàn' }).click()
  await page.waitForURL((url) => url.pathname !== '/login', { timeout: 30_000 })

  await page.getByRole('link', { name: 'Daily Planning' }).click()
  await page.getByRole('heading', { name: 'Kế hoạch triển khai trong ngày' }).waitFor()
  await page.getByLabel('Ngày kế hoạch').fill(planDate)

  const runResponsePromise = page.waitForResponse((response) => response.url().endsWith('/api/v1/planning/runs') && response.request().method() === 'POST')
  await page.getByRole('button', { name: 'Mở / tạo Planning Run' }).click()
  const runEnvelope = await (await runResponsePromise).json()
  const run = runEnvelope.data
  assert(run?.id, 'Planning Run response did not include an id')
  evidence = { ...evidence, run_id: run.id }
  fs.writeFileSync(evidencePath, JSON.stringify(evidence, null, 2))

  await page.getByRole('heading', { name: 'Thêm yêu cầu buổi sáng' }).waitFor()
  await page.getByRole('button', { name: 'Form nhanh' }).click()
  await page.getByLabel('Tiêu đề').fill(title)
  await page.getByLabel('Mô tả').fill('Mutation E2E nội bộ; chỉ xác nhận Intake và candidate, không approve GitLab.')
  await page.getByLabel('Giờ dự kiến').fill('2')

  const candidateResponsePromise = page.waitForResponse((response) => response.url().includes(`/api/v1/planning/runs/${run.id}/quick-add`) && response.request().method() === 'POST')
  await page.getByRole('button', { name: '+ Thêm candidate' }).click()
  const candidateEnvelope = await (await candidateResponsePromise).json()
  const candidate = candidateEnvelope.data
  assert(candidate?.id && candidate?.intake_id, 'Quick Add response did not include candidate and Intake ids')
  await page.getByText(title).first().waitFor()

  evidence = {
    ...evidence,
    planning_live_mutation: 'passed',
    candidate_id: candidate.id,
    intake_id: candidate.intake_id,
    intake_public_id: candidate.source_reference,
  }
  fs.writeFileSync(evidencePath, JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify(evidence))
} finally {
  await browser.close()
}
