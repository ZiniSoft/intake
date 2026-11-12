import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'


const here = path.dirname(fileURLToPath(import.meta.url))
const repositoryRoot = path.resolve(here, '..', '..')
const baseUrl = process.env.PUBLIC_DEMO_BASE_URL || 'http://127.0.0.1:8080'
const chromePath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const outputDir = process.env.PUBLIC_DEMO_OUTPUT_DIR || path.join(repositoryRoot, 'docs', 'public', 'demo', 'output')


if (!fs.existsSync(chromePath)) throw new Error(`Chrome executable not found: ${chromePath}`)
fs.mkdirSync(outputDir, { recursive: true })

const envelope = (data) => JSON.stringify({ success: true, data, request_id: 'public-demo-video' })
const user = {
  subject: 'alex.morgan',
  email: 'alex.morgan@example.test',
  display_name: 'Alex Morgan',
  role: 'CTO',
  can_view_raw: true,
  can_approve: true,
  mfa_enabled: false,
  project_ids: null,
  must_change_password: false,
  member_id: 'member-alex',
}
const project = {
  id: 'project-nova',
  code: 'nova',
  intake_key: 'NVA',
  name: 'Nova',
  status: 'ACTIVE',
  kind: 'SOFTWARE',
  gitlab_project_id: null,
  gitlab_project_url: null,
  gitlab_enabled: false,
  github_repository: 'ZiniSoft/intake-demo',
  github_project_url: 'https://github.com/ZiniSoft/intake-demo',
  github_enabled: true,
  telegram_chat_title: null,
  telegram_linked: false,
  github_token_ref: 'demo-ref',
  delivery_system: 'GITHUB',
  owner_member_id: 'member-alex',
  owner_name: 'Alex Morgan',
  done_evidence: 'COMMIT',
  acceptance_policy: 'CTO_ALWAYS',
  agent_ready: true,
  previous_delivery: null,
}
const intake = {
  id: 'intake-nova-export',
  public_id: 'NVA-26W46-001',
  project_id: project.id,
  channel: 'MANUAL',
  item_type: 'BUG',
  status: 'PENDING_APPROVAL',
  lifecycle_stage: 'REVIEW',
  normalized_title: 'Support large report exports',
  normalized_summary: 'Large reports fail when the export exceeds 10,000 records. Move the export to a background job and give the user visible progress and a safe retry path.',
  details: {
    where: 'Reports / Export',
    steps: ['Open a report containing more than 10,000 records.', 'Choose Export.', 'Wait approximately 30 seconds.'],
    expected: 'The export completes in the background without blocking the interface.',
    subtasks: [],
    acceptance: ['Large exports complete without blocking the user interface.', 'The user can see export progress.', 'Failed exports provide a clear retry option.'],
    open_questions: [],
    related: [],
    split_suggested: false,
    clarifications: [],
  },
  duplicate_of_id: null,
  duplicate_of: null,
  duplicate_issue: null,
  suggested_priority: 'P1',
  proposed_route: 'GITHUB',
  approved_priority: null,
  approved_route: null,
  sync_targets: [],
  work_item: null,
  fix_hints: null,
  needs_cto_acceptance: true,
  agent_readiness: { score: 92, band: 'READY', reasons: ['Clear scope and testable acceptance criteria'], missing: [] },
  approval_owner: 'CTO',
  approval_overdue: false,
  version: 3,
  created_at: '2026-11-11T07:00:00Z',
  updated_at: '2026-11-11T07:00:05Z',
}
const journey = {
  intake_id: intake.id,
  intake_public_id: intake.public_id,
  project_id: project.id,
  status: intake.status,
  received_at: intake.created_at,
  channel: intake.channel,
  decision: null,
  issue: null,
  other_target: null,
  work_item: null,
  previous_targets: [],
  sync_status: null,
  accepted_at: null,
  verification: null,
  plans: [],
  waiting_in_plan: null,
  work: null,
  unlogged_evidence: null,
}

const rawRequest = 'Customer export fails when the report contains more than 10,000 records. Please investigate and provide a safer export option.'
const voicePath = process.argv[2]
if (!voicePath || !fs.existsSync(voicePath)) throw new Error('Pass the ElevenLabs WAV path as the first argument.')

let approved = false
let synced = false

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds))
const translations = new Map([
  ['Riêng', 'Private'],
  ['Việc riêng', 'Personal work'],
  ['Đánh dấu trùng', 'Mark duplicate'],
  ['Sẵn sàng cho agent', 'Ready for an agent'],
  ['Sau khi được xếp việc', 'After planning'],
  ['Chưa có ai ghi việc đã làm', 'No work has been logged'],
  ['Các bước', 'Steps'],
  ['Kết quả mong đợi:', 'Expected result:'],
  ['Thêm việc con', 'Add subtask'],
  ['Việc khó', 'High-risk work'],
  ['Duyệt và tạo mục trên GitHub?', 'Approve and create a GitHub Issue?'],
  ['Duyệt và đồng bộ sang GitHub', 'Approve and sync to GitHub'],
  ['Đang duyệt và đồng bộ…', 'Approving and syncing…'],
  ['Nơi nhận:', 'Destination:'],
  ['Độ ưu tiên:', 'Priority:'],
  ['Đủ để agent nhận; chép lệnh ở dòng đồng bộ bên dưới.', 'Ready for an agent; the delivery command appears below.'],
  ['Mở trang tạo Issue trên GitHub', 'Open prefilled GitHub Issue'],
  ['Chỉ mang tiêu đề, tóm tắt và chi tiết đã chuẩn hóa. Chữ gốc của khách không được gửi.', 'Only normalized content is included. The original customer text is never sent.'],
  ['Lịch sử chạy AI', 'AI run history'],
  ['Lịch sử xử lý', 'Processing history'],
  ['Gợi ý cho người sửa', 'Implementation guidance'],
  ['Kế hoạch 11/11 đã chốt', 'Plan for Nov 11 closed'],
  ['Chép', 'Copy'],
  ['Mở work item', 'Open work item'],
])


async function translateVisibleText(page) {
  await page.evaluate((pairs) => {
    const replacements = new Map(pairs)
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    const nodes = []
    while (walker.nextNode()) nodes.push(walker.currentNode)
    for (const node of nodes) {
      const original = node.nodeValue || ''
      let next = original
      for (const [source, target] of replacements) next = next.split(source).join(target)
      if (next !== original) node.nodeValue = next
    }
  }, [...translations])
}


async function showCaption(page, text) {
  void page
  void text
}


async function showOpeningCard(page) {
  await page.setContent(`<!doctype html><html><head><meta charset="utf-8"><style>
    *{box-sizing:border-box}body{margin:0;background:#0d121a;color:#fff;font-family:Inter,Segoe UI,sans-serif;height:100vh;display:grid;place-items:center;overflow:hidden}
    .glow{position:absolute;width:680px;height:680px;border-radius:50%;background:radial-gradient(circle,rgba(26,188,156,.22),transparent 65%);filter:blur(12px)}
    main{position:relative;text-align:center}.mark{display:inline-grid;place-items:center;width:76px;height:76px;border-radius:20px;background:#fff;color:#0d121a;font-size:42px;font-weight:800;margin-bottom:30px}
    h1{font-size:86px;line-height:1;margin:0 0 20px;letter-spacing:-.045em}.lead{font-size:36px;color:#d7e0ea;margin:0}.sub{margin-top:24px;font-size:20px;color:#8ea0b5;letter-spacing:.06em;text-transform:uppercase}
  </style></head><body><div class="glow"></div><main><div class="mark">✓</div><h1>Intake</h1><p class="lead">From request to traceable work</p><p class="sub">AI-assisted intake with human approval</p></main></body></html>`)
}


async function showPlanningOverlay(page) {
  await page.evaluate(() => {
    const overlay = document.createElement('div')
    overlay.id = 'public-demo-planning'
    overlay.innerHTML = `
      <style>
        #public-demo-planning{position:fixed;inset:0;z-index:2147483600;background:rgba(13,18,26,.56);display:grid;place-items:center;font-family:Inter,Segoe UI,sans-serif}
        #public-demo-planning .card{width:980px;background:white;border-radius:24px;padding:42px;box-shadow:0 30px 90px rgba(0,0,0,.28);color:#111827}
        #public-demo-planning .eyebrow{color:#0f766e;font-weight:750;text-transform:uppercase;letter-spacing:.08em;font-size:16px}
        #public-demo-planning h2{font-size:40px;margin:10px 0 28px}
        #public-demo-planning .row{display:grid;grid-template-columns:1.5fr 1fr 1fr .8fr;gap:18px;align-items:center;padding:24px;border:1px solid #dfe5ec;border-radius:16px;background:#f8fafc}
        #public-demo-planning strong{display:block;font-size:22px;margin-bottom:7px}#public-demo-planning span{color:#64748b;font-size:17px}
        #public-demo-planning .status{display:inline-block;background:#dcfce7;color:#166534;padding:9px 14px;border-radius:999px;font-weight:750;text-align:center}
      </style>
      <div class="card"><div class="eyebrow">Nova · Daily Planning</div><h2>Work scheduled with clear ownership</h2><div class="row"><div><strong>Support large report exports</strong><span>GitHub Issue #42</span></div><div><strong>Maya Chen</strong><span>Developer</span></div><div><strong>Morning</strong><span>3 planned hours</span></div><div class="status">Planned</div></div></div>`
    document.body.appendChild(overlay)
  })
}


async function showEndCard(page) {
  await page.goto('about:blank')
  await page.setContent(`<!doctype html><html><head><meta charset="utf-8"><style>
    *{box-sizing:border-box}body{margin:0;background:#0d121a;color:#fff;font-family:Inter,Segoe UI,sans-serif;height:100vh;display:grid;place-items:center;overflow:hidden}
    main{text-align:center}.mark{display:inline-grid;place-items:center;width:64px;height:64px;border-radius:17px;background:#fff;color:#0d121a;font-size:34px;font-weight:800;margin-bottom:22px}
    h1{font-size:66px;margin:0 0 34px}.line{font-size:36px;line-height:1.5;margin:0;opacity:0;transform:translateY(10px);animation:show .5s ease forwards}.line:nth-of-type(1){animation-delay:.1s}.line:nth-of-type(2){animation-delay:4s}.line:nth-of-type(3){animation-delay:5.5s;color:#5eead4;font-weight:750}
    .repo{margin-top:46px;color:#94a3b8;font-size:22px;letter-spacing:.02em}@keyframes show{to{opacity:1;transform:none}}
  </style></head><body><main><div class="mark">✓</div><h1>Intake</h1><p class="line">AI proposes.</p><p class="line">People decide.</p><p class="line">Every step stays traceable.</p><p class="repo">github.com/ZiniSoft/intake · Apache-2.0</p></main></body></html>`)
}


function applySyncedFixture() {
  approved = true
  synced = true
  intake.status = 'SYNCED'
  intake.lifecycle_stage = 'DELIVERY'
  intake.approved_priority = 'P2'
  intake.approved_route = 'GITHUB'
  intake.version = 4
  intake.sync_targets = [{ system: 'GITHUB', status: 'SUCCEEDED', external_id: '42', sequence_id: null, external_url: 'https://github.com/ZiniSoft/intake-demo/issues/42', error_code: null, updated_at: '2026-11-11T07:00:24Z', superseded: false }]
  journey.status = intake.status
  journey.decision = { action: 'APPROVED', at: '2026-11-11T07:00:20Z', by: 'Alex Morgan', route: 'GITHUB', priority: 'P2' }
  journey.issue = { system: 'GITHUB', external_id: '42', url: 'https://github.com/ZiniSoft/intake-demo/issues/42' }
  journey.sync_status = 'SUCCEEDED'
  journey.plans = [{ plan_date: '2026-11-11', run_id: 'plan-nova', assignment_id: 'assignment-maya', member_name: 'Maya Chen', slot: 'MORNING', planned_hours: 3, settled: true, work_status: 'PLANNED', work_status_at: '2026-11-11T07:00:28Z', accepted_at: null }]
}


async function muxVideoWithVoice(rawVideoPath, wavPath, finalPath) {
  const videoBuffer = fs.readFileSync(rawVideoPath)
  const audioBuffer = fs.readFileSync(wavPath)
  const preferredMime = finalPath.toLowerCase().endsWith('.mp4') ? 'video/mp4;codecs=avc1.42E01E,mp4a.40.2' : 'video/webm;codecs=vp9,opus'
  const muxBrowser = await chromium.launch({ executablePath: chromePath, headless: true, args: ['--autoplay-policy=no-user-gesture-required'] })
  const muxPage = await muxBrowser.newPage()
  await muxPage.exposeFunction('saveMuxedVideo', (base64) => fs.writeFileSync(finalPath, Buffer.from(base64, 'base64')))
  await muxPage.route('http://demo.local/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === '/screen.webm') return route.fulfill({ status: 200, contentType: 'video/webm', body: videoBuffer })
    if (pathname === '/voice.wav') return route.fulfill({ status: 200, contentType: 'audio/wav', body: audioBuffer })
    return route.fulfill({ status: 200, contentType: 'text/html', body: `<!doctype html><html><body style="margin:0;background:#000"><video id="screen" muted playsinline src="/screen.webm" style="display:none"></video><audio id="voice" src="/voice.wav" style="display:none"></audio><canvas id="output" width="1920" height="1080"></canvas><script>
      window.done = false;
      (async () => {
        const screen = document.getElementById('screen');
        const voice = document.getElementById('voice');
        const canvas = document.getElementById('output');
        const context = canvas.getContext('2d');
        const cues = [
          [0, 3.4, 'Requests rarely arrive as clear engineering tickets.'],
          [3.85, 10.5, 'They often begin as short messages with missing context, unclear priorities, and uncertain expectations.'],
          [11.1, 16.05, 'Intake helps transform these requests into structured, traceable work.'],
          [16.65, 21.9, 'Artificial intelligence reviews the original message, identifies the key details, and proposes a practical next step.'],
          [22.5, 31.5, 'A person then checks the proposal, makes any necessary changes, and decides whether it should be approved.'],
          [32.1, 37.85, 'Once approved, the work can be synchronized with GitHub and included in the daily plan.'],
          [38.35, 44.4, 'The original request, the human decision, and the delivery record remain connected.'],
        ];
        await Promise.all([new Promise(r => screen.onloadedmetadata = r), new Promise(r => voice.onloadedmetadata = r)]);
        const roundRect = (x, y, width, height, radius) => {
          context.beginPath(); context.roundRect(x, y, width, height, radius); context.fill();
        };
        const draw = () => {
          context.drawImage(screen, 0, 0, 1920, 1080);
          const cue = cues.find(row => voice.currentTime >= row[0] && voice.currentTime <= row[1]);
          if (cue) {
            context.font = '600 28px Segoe UI, sans-serif';
            context.textAlign = 'center'; context.textBaseline = 'middle';
            const maxWidth = 1440; const words = cue[2].split(' '); const lines = []; let line = '';
            for (const word of words) { const next = line ? line + ' ' + word : word; if (context.measureText(next).width > maxWidth && line) { lines.push(line); line = word; } else line = next; }
            if (line) lines.push(line);
            const boxHeight = 30 + lines.length * 38; const y = 1080 - 74 - boxHeight;
            context.fillStyle = 'rgba(13,18,26,.9)'; roundRect(960 - 760, y, 1520, boxHeight, 14);
            context.fillStyle = '#fff'; lines.forEach((text, index) => context.fillText(text, 960, y + 23 + index * 38));
          }
          if (!window.done) requestAnimationFrame(draw);
        };
        const videoStream = canvas.captureStream(30);
        const audioStream = voice.captureStream();
        const combined = new MediaStream([...videoStream.getVideoTracks(), ...audioStream.getAudioTracks()]);
        const preferredMime = ${JSON.stringify(preferredMime)};
        const mimeType = MediaRecorder.isTypeSupported(preferredMime) ? preferredMime : 'video/webm;codecs=vp9,opus';
        const chunks = [];
        const recorder = new MediaRecorder(combined, { mimeType, videoBitsPerSecond: 10000000, audioBitsPerSecond: 192000 });
        recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
        recorder.onstop = async () => {
          const bytes = new Uint8Array(await new Blob(chunks, { type: mimeType }).arrayBuffer());
          let binary = '';
          for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
          await window.saveMuxedVideo(btoa(binary));
          window.done = true;
        };
        recorder.start(1000);
        draw();
        await Promise.all([screen.play(), voice.play()]);
        voice.onended = () => recorder.stop();
      })().catch(error => { window.muxError = String(error && error.stack || error); });
    <\/script></body></html>` })
  })
  await muxPage.goto('http://demo.local/', { waitUntil: 'load' })
  await muxPage.waitForFunction(() => window.done || window.muxError, null, { timeout: 120_000 })
  const error = await muxPage.evaluate(() => window.muxError || null)
  await muxBrowser.close()
  if (error) throw new Error(`Browser mux failed: ${error}`)
}


if (process.argv.includes('--mux-only')) {
  const silentPath = path.join(outputDir, 'intake-public-demo-silent.webm')
  const mp4Path = path.join(outputDir, 'intake-public-demo-final.mp4')
  if (!fs.existsSync(silentPath)) throw new Error(`Silent recording not found: ${silentPath}`)
  await muxVideoWithVoice(silentPath, voicePath, mp4Path)
  console.log(JSON.stringify({ final_video: mp4Path, voice: voicePath }, null, 2))
  process.exit(0)
}

const browser = await chromium.launch({ executablePath: chromePath, headless: true })
const context = await browser.newContext({
  locale: 'en-US',
  viewport: { width: 1920, height: 1080 },
  recordVideo: { dir: outputDir, size: { width: 1920, height: 1080 } },
})
const page = await context.newPage()
const video = page.video()
const startedAt = Date.now()
const waitUntil = async (seconds) => wait(Math.max(0, startedAt + seconds * 1000 - Date.now()))

await page.route('**/api/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope([]) }))
await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope(user) }))
await page.route('**/api/v1/auth/agent-commands', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope({ commands: [] }) }))
await page.route('**/api/v1/setup', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope({ completed: true, has_project: true, has_private_space: false, sample_available: true, wizard: false, ai_ready: true, has_demo: true, demo_available: true }) }))
await page.route('**/api/v1/projects', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope([project]) }))
await page.route('**/api/v1/intakes', (route) => route.fulfill({ status: route.request().method() === 'POST' ? 201 : 200, contentType: 'application/json', body: envelope(route.request().method() === 'POST' ? intake : { items: [intake], next_cursor: null, limit: 20, summary: { total_items: 1, p0_attention: 0, p1_attention: 1, pending_approval: 1, sync_failed: 0 } }) }))
await page.route(`**/api/v1/intakes/${intake.id}`, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope(intake) }))
await page.route(`**/api/v1/intakes/${intake.id}/raw`, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope({ raw_text: rawRequest, attachments: [] }) }))
await page.route(`**/api/v1/intakes/${intake.id}/attachments`, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope([]) }))
await page.route(`**/api/v1/intakes/${intake.id}/pipeline`, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope({ intake_id: intake.id, public_id: intake.public_id, overall_state: 'SUCCEEDED', stages: [] }) }))
await page.route(`**/api/v1/intakes/${intake.id}/journey`, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope(journey) }))
await page.route(`**/api/v1/intakes/${intake.id}/decisions`, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope([]) }))
await page.route(`**/api/v1/intakes/${intake.id}/work-logs`, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope([]) }))
await page.route(`**/api/v1/intakes/${intake.id}/process`, (route) => route.fulfill({ status: 202, contentType: 'application/json', body: envelope({ status: 'processing_queued' }) }))
await page.route(`**/api/v1/intakes/${intake.id}/approve`, async (route) => {
  approved = true
  intake.status = 'SYNC_PENDING'
  intake.lifecycle_stage = 'DELIVERY'
  intake.approved_priority = 'P2'
  intake.approved_route = 'GITHUB'
  intake.version = 4
  journey.status = intake.status
  journey.decision = { action: 'APPROVED', at: '2026-11-11T07:00:20Z', by: 'Alex Morgan', route: 'GITHUB', priority: 'P2' }
  await route.fulfill({ status: 200, contentType: 'application/json', body: envelope(intake) })
})
await page.route(`**/api/v1/intakes/${intake.id}/sync-status`, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope({
  intake_id: intake.id,
  snapshot_id: approved ? 'snapshot-public-demo' : null,
  job: approved ? { id: 'sync-public-demo', status: synced ? 'SUCCEEDED' : 'PENDING', system: 'GITHUB', external_id: synced ? '42' : null, external_url: synced ? 'https://github.com/ZiniSoft/intake-demo/issues/42' : null, error_code: null } : null,
}) }))
await page.route('**/api/v1/approval-snapshots/snapshot-public-demo/sync', async (route) => {
  applySyncedFixture()
  await route.fulfill({ status: 202, contentType: 'application/json', body: envelope({ id: 'sync-public-demo', status: 'SUCCEEDED' }) })
})
await page.route('**/api/v1/changelog', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope({ entries: [], build: { sha: 'demo' } }) }))
await page.route('**/api/v1/planning/overview/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: envelope({ plan_date: '2026-11-11', generated_at: '2026-11-11T07:00:00Z', gitlab_snapshot_at: null, missing_projects: 0, overdue_total: 0, projects: [], cto_time: null }) }))

try {
  await showOpeningCard(page)
  await showCaption(page, 'Requests rarely arrive as clear engineering tickets.')

  await waitUntil(3.4)
  await showCaption(page, '')
  await page.goto(`${baseUrl}/intakes/new?lang=en`, { waitUntil: 'networkidle' })
  await translateVisibleText(page)
  await showCaption(page, 'They often begin as short messages with missing context, unclear priorities, and uncertain expectations.')
  const sourceInput = page.locator('.composer textarea').first()
  await sourceInput.waitFor({ state: 'visible', timeout: 10_000 }).catch(async (error) => {
    await page.screenshot({ path: path.join(outputDir, 'recorder-composer-error.png') })
    console.error((await page.locator('body').innerText()).slice(0, 3000))
    throw error
  })
  await page.mouse.move(1050, 530, { steps: 18 })
  await sourceInput.click()
  await sourceInput.fill(rawRequest)

  await waitUntil(10.5)
  await showCaption(page, '')
  await page.getByRole('button', { name: 'Save and analyze' }).click()
  await page.goto(`${baseUrl}/intakes/${intake.id}?lang=en`, { waitUntil: 'networkidle' })
  await translateVisibleText(page)

  await waitUntil(11.1)
  await showCaption(page, 'Intake helps transform these requests into structured, traceable work.')
  await page.locator('.normalized-panel').evaluate((element) => { element.style.outline = '4px solid rgba(13,148,136,.45)'; element.style.outlineOffset = '4px' })

  await waitUntil(16.05)
  await showCaption(page, '')
  await page.locator('.normalized-panel').evaluate((element) => { element.style.outline = ''; element.style.outlineOffset = '' })

  await waitUntil(16.65)
  await showCaption(page, 'Artificial intelligence reviews the original message, identifies the key details, and proposes a practical next step.')
  await page.mouse.move(1470, 548, { steps: 24 })
  await page.mouse.wheel(0, 420)

  await waitUntil(21.9)
  await showCaption(page, '')

  await waitUntil(22.5)
  await showCaption(page, 'A person then checks the proposal, makes any necessary changes, and decides whether it should be approved.')
  const decisionBar = page.locator('.decision-bar, .decision-dock').first()
  const prioritySelect = decisionBar.locator('select').first()
  if (await prioritySelect.count()) await prioritySelect.selectOption('P2')
  await page.mouse.move(1180, 1038, { steps: 28 })

  await waitUntil(28.4)
  await page.getByRole('button', { name: 'Approve and sync to GitHub' }).click()
  await wait(250)
  await translateVisibleText(page)
  const dialog = page.getByRole('dialog')
  if (await dialog.count()) {
    await wait(700)
    await dialog.locator('button.button-primary').click()
  }
  applySyncedFixture()

  await waitUntil(31.5)
  await showCaption(page, '')
  await page.goto(`${baseUrl}/intakes/${intake.id}?lang=en`, { waitUntil: 'networkidle' })
  await translateVisibleText(page)

  await waitUntil(32.1)
  await showCaption(page, 'Once approved, the work can be synchronized with GitHub and included in the daily plan.')
  await page.locator('.detail-header').evaluate((element) => { element.style.outline = '4px solid rgba(34,197,94,.35)'; element.style.outlineOffset = '5px' })
  await wait(800)
  await showPlanningOverlay(page)
  await wait(2600)
  await showCaption(page, '')
  await page.goto(`${baseUrl}/intakes/${intake.id}?lang=en`, { waitUntil: 'networkidle' })
  await translateVisibleText(page)
  await showCaption(page, 'The original request, the human decision, and the delivery record remain connected.')
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }))
  const journeyStrip = page.locator('.journey-strip, .intake-journey, .journey').first()
  if (await journeyStrip.count()) await journeyStrip.evaluate((element) => { element.style.outline = '4px solid rgba(59,130,246,.35)'; element.style.outlineOffset = '5px' })

  await waitUntil(44.4)
  await showCaption(page, '')

  await waitUntil(44.9)
  await showEndCard(page)

  await waitUntil(53.76)
} finally {
  await context.close()
  await browser.close()
}

const recordedPath = await video.path()
const silentPath = path.join(outputDir, 'intake-public-demo-silent.webm')
const finalPath = path.join(outputDir, 'intake-public-demo.webm')
fs.copyFileSync(recordedPath, silentPath)
await muxVideoWithVoice(silentPath, voicePath, finalPath)
console.log(JSON.stringify({ silent_video: silentPath, final_video: finalPath, voice: voicePath }, null, 2))
