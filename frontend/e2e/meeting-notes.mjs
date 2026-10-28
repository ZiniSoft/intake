import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'


// Live check of the meeting page on the newest meeting: speaker-separated transcript, rename a speaker,
// listen back, edit the note and turn one item into an Intake. It writes to the database it runs against.
const here = path.dirname(fileURLToPath(import.meta.url))
const repositoryRoot = path.resolve(here, '..', '..')
const baseUrl = process.env.MEETING_UI_BASE_URL || 'http://127.0.0.1:5173'
const chromePath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const waitSeconds = Number(process.env.MEETING_WAIT_SECONDS || 240)
const createIntake = process.env.MEETING_CREATE_INTAKE !== 'false'


function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const env = Object.fromEntries(fs.readFileSync(path.join(repositoryRoot, '.env'), 'utf8').split(/\r?\n/).filter((line) => /^[A-Z_]+=/.test(line)).map((line) => [line.slice(0, line.indexOf('=')), line.slice(line.indexOf('=') + 1).trim().replace(/^["']|["']$/g, '')]))
const browser = await chromium.launch({ executablePath: chromePath, headless: true, args: ['--autoplay-policy=no-user-gesture-required'] })
const context = await browser.newContext({ locale: 'vi-VN', viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const pageErrors = []
page.on('pageerror', (error) => pageErrors.push(error.message))
page.on('dialog', (dialog) => { void dialog.accept() })
const result = { base_url: baseUrl, checks: [] }
const check = (condition, message) => { assert(condition, message); result.checks.push(message) }

try {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'networkidle' })
  await page.getByLabel('Tài khoản').fill('cto')
  await page.getByLabel('Mật khẩu').fill(env.CTO_INITIAL_PASSWORD)
  await page.getByRole('button', { name: 'Đăng nhập an toàn' }).click()
  await page.waitForURL((url) => url.pathname !== '/login')

  await page.getByRole('navigation', { name: 'Điều hướng chính' }).getByRole('link', { name: 'Cuộc họp' }).click()
  await page.getByRole('heading', { name: 'Meeting note' }).waitFor()
  const meetingId = await page.evaluate(async () => (await (await fetch('/api/v1/meetings', { credentials: 'include' })).json()).data[0].id)
  result.meeting_id = meetingId

  const deadline = Date.now() + waitSeconds * 1000
  let detail
  for (;;) {
    detail = await page.evaluate(async (id) => (await (await fetch(`/api/v1/meetings/${id}`, { credentials: 'include' })).json()).data, meetingId)
    if (detail.transcript_status === 'DONE' && detail.note_status === 'DONE') break
    assert(!['FAILED'].includes(detail.transcript_status) && detail.note_status !== 'FAILED', `Processing failed: transcript ${detail.transcript_status}, note ${detail.note_status}`)
    assert(Date.now() < deadline, `Still processing after ${waitSeconds}s: transcript ${detail.transcript_status}, note ${detail.note_status}`)
    await page.waitForTimeout(5000)
  }
  result.speakers = detail.speakers.length
  result.turns = detail.segments.length
  result.note_items = detail.note_items.map((item) => item.kind)
  check(detail.transcript_source === 'BATCH' && detail.speakers.length >= 2, `Bản chữ đã tách ${detail.speakers.length} người nói, ${detail.segments.length} lượt`)
  check(detail.provider_data_deleted === true, 'Bản sao phía ElevenLabs đã được xóa')
  check(Boolean(detail.note_summary) && detail.note_items.length > 0, `Meeting note có tóm tắt và ${detail.note_items.length} mục`)

  await page.reload({ waitUntil: 'networkidle' })
  await page.locator('.report-row').first().click()
  await page.locator('.meeting-note').waitFor()
  check((await page.locator('.note-group h3').allInnerTexts()).map((text) => text.replace(/\s*\d+$/, '').trim()).join(' | ') === 'Quyết định | Yêu cầu, bug, thay đổi phạm vi | Việc cần làm | Câu hỏi mở và rủi ro', 'Note có đủ 4 nhóm')
  check((await page.locator('.ai-tag', { hasText: 'Đã tách người nói' }).count()) === 1, 'Trang hiện nhãn "Đã tách người nói"')

  const speakerInput = page.locator('.speaker-names input').first()
  // A rerun on the same meeting must still change the name, otherwise the save button stays disabled.
  const speakerName = (await speakerInput.inputValue()) === 'Anh Thanh' ? 'Anh Thành' : 'Anh Thanh'
  await speakerInput.fill(speakerName)
  await page.getByRole('button', { name: 'Lưu tên người nói' }).click()
  await page.locator('.meeting-transcript small', { hasText: speakerName }).first().waitFor()
  check(true, 'Đổi "Thành viên 1" thành tên thật và bản chữ hiện tên mới')

  await page.getByRole('button', { name: 'Nghe lại' }).click()
  await page.locator('audio').waitFor({ timeout: 30_000 })
  // Really play it: a blocked blob URL (CSP media-src) or an undecodable file never advances currentTime.
  const playedSeconds = await page.locator('audio').evaluate(async (element) => {
    try { await element.play() } catch (playError) { return `play failed: ${playError.message}` }
    await new Promise((resolve) => setTimeout(resolve, 3000))
    element.pause()
    return element.error ? `media error ${element.error.code}` : element.currentTime
  })
  result.audio_played_seconds = playedSeconds
  check(typeof playedSeconds === 'number' && playedSeconds > 1, 'Nghe lại: bản ghi phát được trong trình duyệt')

  await page.getByRole('button', { name: 'Sửa tóm tắt' }).click()
  const summary = await page.getByLabel('Tóm tắt cuộc họp').inputValue()
  await page.getByLabel('Tóm tắt cuộc họp').fill(`${summary} (CTO đã xem)`)
  await page.getByRole('button', { name: 'Lưu tóm tắt' }).click()
  await page.locator('.note-summary p', { hasText: '(CTO đã xem)' }).waitFor()
  check(true, 'Sửa và lưu được tóm tắt')

  const actionable = page.locator('.note-group .report-items > li', { has: page.getByRole('button', { name: 'Tạo Intake' }) })
  result.actionable_items = await actionable.count()
  check(result.actionable_items > 0, `Có ${result.actionable_items} mục có thể thành Intake`)
  const target = actionable.first()
  await target.hover()
  await target.getByRole('button', { name: /^Sửa mục/ }).click()
  await page.locator('.report-item-edit').getByLabel('Dự án').selectOption('orbit')
  await page.locator('.report-item-edit').getByLabel('Người phụ trách').fill('Anh Thanh')
  await page.getByRole('button', { name: 'Lưu mục' }).click()
  await page.locator('.note-group .report-items > li small', { hasText: 'CTO đã sửa' }).first().waitFor()
  check(true, 'Sửa một mục: đổi dự án và người phụ trách, mục được ghi nhãn "CTO đã sửa"')

  if (createIntake) {
    const edited = page.locator('.note-group .report-items > li', { hasText: 'CTO đã sửa' }).first()
    await edited.getByRole('button', { name: 'Tạo Intake' }).click()
    const link = page.locator('.note-intake-link').first()
    await link.waitFor({ timeout: 30_000 })
    await link.click()
    await page.waitForURL(/\/intakes\/[0-9a-f-]{36}$/)
    result.intake_id = page.url().split('/').pop()
    await page.locator('.detail-header h1').waitFor()
    const meta = await page.locator('.detail-header p').innerText()
    check(meta.includes('Meeting'), 'Mục note thành Intake kênh Meeting và mở được trang chi tiết')
    const intake = await page.evaluate(async (id) => (await (await fetch(`/api/v1/intakes/${id}`, { credentials: 'include' })).json()).data, result.intake_id)
    result.intake_public_id = intake.public_id
    result.intake_project = intake.project_id
    result.intake_status = intake.status
  }
  await page.screenshot({ path: path.join(os.tmpdir(), 'meeting-notes-intake.png') })
  await page.goto(`${baseUrl}/meetings?id=${meetingId}`, { waitUntil: 'networkidle' })
  await page.locator('.meeting-note').waitFor()
  await page.screenshot({ path: path.join(os.tmpdir(), 'meeting-notes.png'), fullPage: true })
  check(pageErrors.length === 0, 'Không có lỗi JavaScript')
  result.meeting_notes = 'passed'
} catch (error) {
  result.meeting_notes = 'failed'
  result.error = error instanceof Error ? error.message : String(error)
  result.page_errors = pageErrors
  await page.screenshot({ path: path.join(os.tmpdir(), 'meeting-notes-failed.png'), fullPage: true }).catch(() => {})
} finally {
  await browser.close()
}
console.log(JSON.stringify(result, null, 2))
process.exit(result.meeting_notes === 'passed' ? 0 : 1)
