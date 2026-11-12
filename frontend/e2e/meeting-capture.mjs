import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'


// Live check of meeting capture: Chrome's fake microphone plays a WAV file, the app records it,
// the gateway streams it to the speech-to-text provider and the transcript must come back.
// This calls the real provider and writes one meeting to the database it runs against.
const here = path.dirname(fileURLToPath(import.meta.url))
const repositoryRoot = path.resolve(here, '..', '..')
const baseUrl = process.env.MEETING_UI_BASE_URL || 'http://127.0.0.1:5173'
const chromePath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const audioFile = process.env.MEETING_FAKE_AUDIO
const expected = (process.env.MEETING_EXPECTED_WORDS || '').split(',').map((word) => word.trim().toLowerCase()).filter(Boolean)
const listenSeconds = Number(process.env.MEETING_LISTEN_SECONDS || 45)


function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const env = Object.fromEntries(fs.readFileSync(path.join(repositoryRoot, '.env'), 'utf8').split(/\r?\n/).filter((line) => /^[A-Z_]+=/.test(line)).map((line) => [line.slice(0, line.indexOf('=')), line.slice(line.indexOf('=') + 1).trim().replace(/^["']|["']$/g, '')]))
assert(env.CTO_INITIAL_PASSWORD, 'CTO_INITIAL_PASSWORD is required in .env')
assert(audioFile && fs.existsSync(audioFile), 'MEETING_FAKE_AUDIO must point to a 16-bit WAV file')

const browser = await chromium.launch({
  executablePath: chromePath,
  headless: true,
  args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-audio-capture=${audioFile}%noloop`],
})
const context = await browser.newContext({ locale: 'vi-VN', viewport: { width: 1440, height: 900 }, permissions: ['microphone'] })
const page = await context.newPage()
const pageErrors = []
page.on('pageerror', (error) => pageErrors.push(error.message))
const result = { base_url: baseUrl }

try {
  await page.goto(`${baseUrl}/login?lang=vi`, { waitUntil: 'networkidle' })
  await page.getByLabel('Tài khoản').fill('cto')
  await page.getByLabel('Mật khẩu').fill(env.CTO_INITIAL_PASSWORD)
  await page.getByRole('button', { name: 'Đăng nhập an toàn' }).click()
  await page.waitForURL((url) => url.pathname !== '/login')
  await page.goto(`${baseUrl}/intakes/new?panel=record`, { waitUntil: 'networkidle' })
  const panel = page.locator('.right-panel')
  await panel.getByRole('radio', { name: /Chỉ micro/ }).check()
  await panel.getByLabel('Dự án của cuộc họp').selectOption('orbit')
  for (const term of (process.env.MEETING_ADD_TERMS || '').split(',').map((value) => value.trim()).filter(Boolean)) {
    if (await panel.locator('.glossary-terms .chip', { hasText: term }).count()) continue
    await panel.getByLabel('Thuật ngữ mới').fill(term)
    await panel.getByRole('button', { name: 'Thêm', exact: true }).click()
    await panel.locator('.glossary-terms .chip', { hasText: term }).waitFor()
  }
  result.glossary_terms = await panel.locator('.glossary-terms .chip').count()

  const started = page.waitForResponse((response) => response.url().endsWith('/api/v1/meetings') && response.request().method() === 'POST')
  await panel.getByRole('button', { name: 'Bắt đầu ghi âm' }).click()
  const meeting = (await (await started).json()).data
  result.meeting_id = meeting.id
  await panel.getByText('Đang ghi').waitFor({ timeout: 20_000 })

  await page.waitForFunction(() => document.querySelectorAll('.live-transcript p:not(.muted)').length > 0, null, { timeout: 30_000 })
  result.first_text_seconds = Number(await panel.locator('.recording-status span').last().innerText().then((clock) => clock.split(':').reduce((minutes, seconds) => Number(minutes) * 60 + Number(seconds))))
  await page.waitForTimeout(listenSeconds * 1000)
  result.live_lines = await panel.locator('.live-transcript p:not(.muted):not(.live-partial)').count()
  await page.screenshot({ path: path.join(os.tmpdir(), 'meeting-capture-live.png') })

  await panel.getByRole('button', { name: 'Kết thúc ghi âm' }).click()
  await panel.getByRole('button', { name: 'Chèn bản chữ vào ô soạn' }).waitFor({ timeout: 40_000 })
  const transcript = (await panel.locator('.live-transcript').innerText()).trim()
  result.transcript_characters = transcript.length
  result.transcript = transcript
  const lowered = transcript.toLowerCase()
  result.expected_found = expected.filter((word) => lowered.includes(word))
  result.expected_missing = expected.filter((word) => !lowered.includes(word))

  await panel.getByRole('button', { name: 'Chèn bản chữ vào ô soạn' }).click()
  result.inserted_into_composer = (await page.getByLabel('Nội dung gốc').inputValue()).trim() === transcript.replace(/\n+/g, '\n').trim()
  result.channel = await page.getByLabel('Kênh').inputValue()

  const detail = await page.evaluate(async (id) => (await (await fetch(`/api/v1/meetings/${id}`, { credentials: 'include' })).json()).data, meeting.id)
  result.status = detail.status
  result.duration_seconds = detail.duration_seconds
  result.audio_chunks = detail.audio_chunk_count
  result.audio_bytes = detail.audio_bytes
  result.saved_segments = detail.segments.length
  result.page_errors = pageErrors

  assert(detail.status === 'FINISHED', 'Meeting did not finish')
  assert(detail.audio_chunk_count > 0 && detail.audio_bytes > 0, 'No audio chunk was stored')
  assert(detail.segments.length > 0 && transcript.length > 20, 'No transcript came back from the provider')
  assert(result.expected_missing.length === 0, `Missing expected words: ${result.expected_missing.join(', ')}`)
  assert(pageErrors.length === 0, `Page errors: ${pageErrors.join(' | ')}`)
  result.meeting_capture = 'passed'
} catch (error) {
  result.meeting_capture = 'failed'
  result.error = error instanceof Error ? error.message : String(error)
  result.page_errors = pageErrors
  await page.screenshot({ path: path.join(os.tmpdir(), 'meeting-capture-failed.png') }).catch(() => {})
} finally {
  await browser.close()
}
console.log(JSON.stringify(result, null, 2))
process.exit(result.meeting_capture === 'passed' ? 0 : 1)
