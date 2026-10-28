import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'


// Live check of the "upload an existing recording" source: the file goes up in parts, the gateway
// transcribes it with speaker separation and the meeting note follows. Calls the real provider.
const here = path.dirname(fileURLToPath(import.meta.url))
const repositoryRoot = path.resolve(here, '..', '..')
const baseUrl = process.env.MEETING_UI_BASE_URL || 'http://127.0.0.1:5173'
const chromePath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const audioFile = process.env.MEETING_UPLOAD_FILE
const waitSeconds = Number(process.env.MEETING_WAIT_SECONDS || 240)


function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const env = Object.fromEntries(fs.readFileSync(path.join(repositoryRoot, '.env'), 'utf8').split(/\r?\n/).filter((line) => /^[A-Z_]+=/.test(line)).map((line) => [line.slice(0, line.indexOf('=')), line.slice(line.indexOf('=') + 1).trim().replace(/^["']|["']$/g, '')]))
assert(audioFile && fs.existsSync(audioFile), 'MEETING_UPLOAD_FILE must point to an audio file')

const browser = await chromium.launch({ executablePath: chromePath, headless: true })
const context = await browser.newContext({ locale: 'vi-VN', viewport: { width: 1440, height: 900 } })
const page = await context.newPage()
const pageErrors = []
page.on('pageerror', (error) => pageErrors.push(error.message))
const result = { base_url: baseUrl }

try {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'networkidle' })
  await page.getByLabel('Tài khoản').fill('cto')
  await page.getByLabel('Mật khẩu').fill(env.CTO_INITIAL_PASSWORD)
  await page.getByRole('button', { name: 'Đăng nhập an toàn' }).click()
  await page.waitForURL((url) => url.pathname !== '/login')
  await page.goto(`${baseUrl}/intakes/new?panel=record`, { waitUntil: 'networkidle' })
  const panel = page.locator('.right-panel')
  await panel.getByRole('radio', { name: /Tải file ghi âm có sẵn/ }).check()
  await panel.getByLabel('Dự án của cuộc họp').selectOption('orbit')
  await panel.getByRole('button', { name: 'Chọn file ghi âm' }).waitFor()
  await panel.locator('input[type="file"]').setInputFiles(audioFile)
  const link = panel.getByRole('link', { name: 'Mở trang cuộc họp' })
  await link.waitFor({ timeout: 120_000 })
  result.meeting_id = new URL(await link.getAttribute('href'), baseUrl).searchParams.get('id')

  const deadline = Date.now() + waitSeconds * 1000
  let detail
  for (;;) {
    detail = await page.evaluate(async (id) => (await (await fetch(`/api/v1/meetings/${id}`, { credentials: 'include' })).json()).data, result.meeting_id)
    if (detail.transcript_status === 'DONE' && detail.note_status === 'DONE') break
    assert(detail.transcript_status !== 'FAILED' && detail.note_status !== 'FAILED', `Processing failed: transcript ${detail.transcript_status}, note ${detail.note_status}`)
    assert(Date.now() < deadline, `Still processing after ${waitSeconds}s: transcript ${detail.transcript_status}, note ${detail.note_status}`)
    await page.waitForTimeout(5000)
  }
  result.source = detail.source
  result.speakers = detail.speakers.length
  result.turns = detail.segments.length
  result.note_items = detail.note_items.length
  result.provider_data_deleted = detail.provider_data_deleted
  assert(detail.source === 'FILE', 'Meeting source must be FILE')
  assert(detail.transcript_source === 'BATCH' && detail.segments.length > 0, 'Uploaded file produced no transcript')
  assert(detail.provider_data_deleted === true, 'Provider copy was not deleted')

  await link.click()
  await page.locator('.meeting-note').waitFor()
  assert(pageErrors.length === 0, `JavaScript errors: ${pageErrors.join('; ')}`)
  result.meeting_upload = 'passed'
} catch (error) {
  result.meeting_upload = 'failed'
  result.error = error instanceof Error ? error.message : String(error)
  result.page_errors = pageErrors
} finally {
  await browser.close()
}
console.log(JSON.stringify(result, null, 2))
process.exit(result.meeting_upload === 'passed' ? 0 : 1)
