// Sound stays on this computer first and reaches the server from there (FR-REC-14, ADR-0044).
// Chrome with a fake microphone; the live-transcript socket is intercepted so nothing goes to the provider.
//   node e2e/recording-sync.mjs            (needs the stack on 127.0.0.1:8080 and CTO_INITIAL_PASSWORD in ../.env)
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const require = createRequire(path.join(here, '..', 'package.json'))
const { chromium } = require('playwright-core')
const base = process.env.INTAKE_BASE || 'http://127.0.0.1:8080'
const password = readFileSync(path.join(here, '..', '..', '.env'), 'utf8').match(/^CTO_INITIAL_PASSWORD=(.*)$/m)[1].trim()
const chromePath = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const results = []
const check = (ok, label) => { results.push({ ok, label }); console.log(`${ok ? 'PASS' : 'FAIL'} ${label}`) }
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const browser = await chromium.launch({ executablePath: chromePath, headless: true, args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required'] })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ['microphone'] })
const page = await context.newPage()
// No audio to the provider: the socket is answered here with an "error" the page already knows how to show.
// A gateway report saying its own line out is behind: the page must name that leg.
await page.routeWebSocket(/\/api\/v1\/meetings\/.*\/stream/, (ws) => {
  ws.onMessage(() => {})
  setTimeout(() => ws.send(JSON.stringify({ type: 'health', backlog_seconds: 6.5, client_gap_ms: 300, provider_rtt_ms: 210, dropped: 0 })), 3000)
})
await page.goto(`${base}/login?lang=vi`)
await page.getByLabel(/Tên đăng nhập|Tài khoản/).fill('cto')
await page.getByLabel(/Mật khẩu/).fill(password)
await page.getByRole('button', { name: /Đăng nhập/ }).click()
await page.waitForURL((url) => !url.pathname.startsWith('/login'))

const meetingOf = async (id) => (await (await page.request.get(`${base}/api/v1/meetings/${id}`)).json()).data
const localChunks = () => page.evaluate(() => new Promise((resolve) => {
  const open = indexedDB.open('intake-recording')
  open.onsuccess = () => { const db = open.result; const all = db.transaction('chunks').objectStore('chunks').getAll(); all.onsuccess = () => { resolve(all.result.length); db.close() } }
  open.onerror = () => resolve(-1)
}))
const startMic = async () => {
  await page.goto(`${base}/intakes/new?panel=record`)
  await page.locator('.recording-panel select').first().selectOption({ index: 1 })
  await page.locator('input[name="recording-source"][value="MIC"]').check()
  await page.locator('.recording-panel .button-primary').click()
  await page.locator('.live-recording').waitFor()
  await page.waitForFunction(() => /Đang ghi|Đang nghe/.test(document.querySelector('.live-recording strong')?.textContent || ''), null, { timeout: 15000 })
  const id = await page.evaluate(() => new Promise((resolve) => { const open = indexedDB.open('intake-recording'); open.onsuccess = () => { const db = open.result; const all = db.transaction('meetings').objectStore('meetings').getAll(); all.onsuccess = () => { resolve(all.result.at(-1)?.meetingId); db.close() } } }))
  return id
}

// 1. A line that drops for 25 seconds mid-recording loses nothing: the chunks wait on the computer, then go up.
let blocked = false
await page.route(/\/api\/v1\/meetings\/[^/]+\/audio/, (route) => (blocked ? route.abort('connectionfailed') : route.continue()))
const first = await startMic()
check(Boolean(first), 'Ghi âm bằng micro giả bắt đầu, có bản ghi trong IndexedDB')
await page.locator('.live-recording .recording-sync', { hasText: 'Server → dịch vụ chuyển chữ nghẽn' }).waitFor({ timeout: 20000 })
check(true, 'Báo cáo health của gateway: dòng tình trạng gọi tên chặng server → nhà cung cấp')
await wait(9000)
blocked = true
await wait(25000)
const syncText = await page.locator('.live-recording .recording-sync').textContent().catch(() => '')
check(/gián đoạn|chờ/.test(syncText || ''), `Đường truyền rớt: giao diện báo "${(syncText || '').trim()}"`)
const held = await localChunks()
check(held >= 2, `Đoạn giữ trên máy trong lúc rớt: ${held}`)
blocked = false
await wait(12000)
await page.locator('.live-recording .button-danger').click()
await page.waitForFunction(() => /Đã ghi|Xong|Kết thúc|Bản ghi/.test(document.querySelector('.live-recording strong')?.textContent || '') || document.querySelector('.live-recording .icon-button[aria-label="Đóng bản ghi này"]'), null, { timeout: 60000 })
const done = await meetingOf(first)
check(done.status === 'FINISHED', `Cuộc họp kết thúc: ${done.status}`)
check(done.audio_chunk_count >= 4 && (await localChunks()) === 0, `Server giữ ${done.audio_chunk_count} đoạn, máy còn ${await localChunks()}`)
check(done.duration_seconds >= 45 && done.duration_seconds <= 70, `Thời lượng theo trình duyệt: ${done.duration_seconds} s`)

// 2. The line is down when the meeting ends and the tab is reloaded: the rest goes up on the next visit.
const second = await startMic()
await wait(12000)
blocked = true
await wait(3000)
await page.locator('.live-recording .button-danger').click()
await page.locator('.live-recording .notice', { hasText: 'chưa lên server' }).waitFor({ timeout: 40000 })
check(true, 'Kết thúc khi mất mạng: báo số đoạn còn chờ, không treo')
const before = await meetingOf(second)
check(before.status === 'RECORDING', `Server vẫn RECORDING trong lúc chờ: ${before.status}`)
page.removeAllListeners('dialog')
page.on('dialog', (dialog) => dialog.accept())
await page.reload()
await page.locator('.recording-indicator.is-pending').waitFor({ timeout: 15000 })
check(true, 'Sau khi tải lại: thanh trên báo đang gửi nốt bản ghi cũ')
blocked = false
await page.locator('.recording-indicator.is-done', { hasText: 'Bản ghi cũ đã lên đủ' }).waitFor({ timeout: 60000 })
const after = await meetingOf(second)
check(after.status === 'FINISHED' && after.audio_chunk_count >= 1 && (await localChunks()) === 0, `Sau khi nối lại: ${after.status}, ${after.audio_chunk_count} đoạn trên server, máy còn ${await localChunks()}`)

// Clean up the two meetings made for the check.
for (const id of [first, second]) await page.request.delete(`${base}/api/v1/meetings/${id}`, { headers: { 'X-CSRF-Token': (await context.cookies()).find((c) => c.name === 'intake_csrf')?.value || '' } })
await browser.close()
const failed = results.filter((r) => !r.ok).length
console.log(JSON.stringify({ passed: results.length - failed, failed }))
process.exit(failed ? 1 : 0)
