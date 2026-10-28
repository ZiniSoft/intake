import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'


const here = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(here, '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const baseUrl = process.env.COMPOSER_UI_BASE_URL || 'http://127.0.0.1:5173'
const chromePath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const evidenceDir = process.env.COMPOSER_UI_EVIDENCE_DIR || path.join(repositoryRoot, 'docs', 'stable', 'gates', 'evidence', '2026-10-04-ui-composer')
const fakeIntakeId = '00000000-0000-4000-8000-00000000c0de'


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
  return JSON.stringify({ success: true, data, request_id: 'composer-ui-e2e' })
}


function assert(condition, message) {
  if (!condition) throw new Error(message)
}


const env = readEnv(path.join(repositoryRoot, '.env'))
assert(env.CTO_INITIAL_PASSWORD, 'CTO_INITIAL_PASSWORD is required in .env')
assert(fs.existsSync(chromePath), `Chrome executable not found: ${chromePath}`)
fs.mkdirSync(evidenceDir, { recursive: true })

const browser = await chromium.launch({ executablePath: chromePath, headless: true })
const results = []
const mutations = []


async function newSession(viewport) {
  const context = await browser.newContext({ locale: 'vi-VN', timezoneId: 'Asia/Ho_Chi_Minh', viewport })
  const page = await context.newPage()
  const pageErrors = []
  page.on('pageerror', (error) => pageErrors.push(error.message))

  // Every write to the Intake API is intercepted: the run must not create pilot data or call the AI provider.
  await page.route('**/api/v1/intakes', async (route) => {
    const request = route.request()
    if (request.method() !== 'POST') return route.continue()
    mutations.push({ kind: 'create', headers: request.headers(), body: request.postDataJSON() })
    await route.fulfill({ status: 201, contentType: 'application/json', body: envelope({ id: fakeIntakeId, public_id: 'E2E-26W40-001' }) })
  })
  await page.route(`**/api/v1/intakes/${fakeIntakeId}/attachments`, async (route) => {
    mutations.push({ kind: 'attachment', contentType: route.request().headers()['content-type'] })
    await route.fulfill({ status: 201, contentType: 'application/json', body: envelope({ id: 'attachment-e2e' }) })
  })
  await page.route(`**/api/v1/intakes/${fakeIntakeId}/process`, async (route) => {
    mutations.push({ kind: 'process' })
    await route.fulfill({ status: 202, contentType: 'application/json', body: envelope({ status: 'processing_queued' }) })
  })

  await page.goto(`${baseUrl}/login`, { waitUntil: 'networkidle' })
  await page.getByLabel('Tài khoản').fill('cto')
  await page.getByLabel('Mật khẩu').fill(env.CTO_INITIAL_PASSWORD)
  await page.getByRole('button', { name: 'Đăng nhập an toàn' }).click()
  await page.waitForURL((url) => url.pathname !== '/login', { timeout: 30_000 })
  return { context, page, pageErrors }
}


async function openComposer(page, search = '') {
  await page.goto(`${baseUrl}/intakes/new${search}`, { waitUntil: 'networkidle' })
  await page.getByLabel('Nội dung gốc').waitFor()
  await page.waitForFunction(() => !document.querySelector('select[aria-label="Dự án"]')?.disabled)
}


async function scenario(id, title, page, body) {
  const entry = { id, title, status: 'passed', checks: [], screenshot: `${id}.png` }
  const check = (condition, message) => {
    assert(condition, message)
    entry.checks.push(message)
  }
  try {
    await body(check)
  } catch (error) {
    entry.status = 'failed'
    entry.error = error instanceof Error ? error.message : String(error)
  }
  try {
    await page.screenshot({ path: path.join(evidenceDir, entry.screenshot), fullPage: false })
  } catch {
    entry.screenshot = null
  }
  results.push(entry)
  console.log(`${entry.status === 'passed' ? 'PASS' : 'FAIL'} ${id} ${title}${entry.error ? ` :: ${entry.error}` : ''}`)
}


const desktop = await newSession({ width: 1440, height: 900 })
const { page } = desktop

try {
  await scenario('S01', 'Sidebar chia nhóm và điều hướng toàn app', page, async (check) => {
    await page.goto(`${baseUrl}/`, { waitUntil: 'networkidle' })
    const nav = page.getByRole('navigation', { name: 'Điều hướng chính' })
    const labels = (await nav.getByRole('link').allInnerTexts()).map((text) => text.trim().split('\n')[0].trim())
    check(JSON.stringify(labels) === JSON.stringify(['Hôm nay', 'Báo cáo ngày', 'Chờ phê duyệt', 'Daily Planning', 'Nghiệm thu', 'Tuần qua', 'Tất cả Intake', 'Cuộc họp']), `Sidebar của CTO có đúng 8 mục theo mạch ngày, phần Riêng gập lại: ${labels.join(', ')}`)
    check(await nav.getByText('Việc trong ngày', { exact: true }).isVisible() && await nav.getByText('Tra cứu', { exact: true }).isVisible(), 'Có nhãn nhóm "Việc trong ngày" và "Tra cứu"')
    check(await nav.getByRole('button', { name: 'Riêng' }).isVisible() && !(await nav.getByText('Kho ý tưởng').isVisible()), 'Mục "Riêng" gập lại, ba mục con ẩn')
    await nav.getByRole('button', { name: 'Riêng' }).click()
    check(await nav.getByRole('link', { name: 'Kho ý tưởng' }).isVisible(), 'Bấm "Riêng" mở ba mục con')
    check(await page.locator('.topbar').getByRole('link', { name: 'Cài đặt' }).isVisible(), 'Cài đặt là biểu tượng ở góc phải trên cùng')
    check((await page.locator('.sidebar').getByText('Đăng xuất').count()) === 0, 'Đăng xuất không còn trong sidebar')
    await page.locator('.topbar').getByRole('button', { name: /Tài khoản:/ }).click()
    check(await page.getByRole('menuitem', { name: 'Đăng xuất' }).isVisible() && await page.getByRole('menuitem', { name: 'Tài khoản & bảo mật' }).isVisible(), 'Menu avatar có Tài khoản và Đăng xuất')
    await page.keyboard.press('Escape')
    await page.locator('.topbar').getByRole('button', { name: 'Thêm mới' }).click()
    check(await page.getByRole('menuitem', { name: /Tạo Intake/ }).isVisible() && await page.getByRole('menuitem', { name: /Ghi âm họp/ }).isVisible(), 'Nút "+" mở Tạo Intake và Ghi âm họp')
    await page.getByRole('menuitem', { name: /Tạo Intake/ }).click()
    await page.waitForURL((url) => url.pathname === '/intakes/new')
    await page.waitForFunction(() => document.querySelectorAll('nav[aria-label="Điều hướng chính"] a.active').length === 0, null, { timeout: 5000 }).catch(() => undefined)
    check((await nav.locator('a.active').count()) === 0, 'Vào /intakes/new từ nút "+": không mục sidebar nào được đánh dấu')
    const pages = [['Tất cả Intake', '/intakes'], ['Chờ phê duyệt', '/approvals'], ['Daily Planning', '/planning'], ['Hôm nay', '/']]
    for (const [label, expectedPath] of pages) {
      await nav.getByRole('link', { name: label, exact: true }).click()
      await page.waitForURL((url) => url.pathname === expectedPath)
      await nav.locator('a.active', { hasText: label }).waitFor()
      const active = (await nav.locator('a.active').allInnerTexts()).map((text) => text.trim().split('\n')[0].trim())
      check(active.length === 1 && active[0] === label, `Vào ${expectedPath}: chỉ "${label}" được đánh dấu đang chọn`)
      check((await page.locator('.topbar h1, main h1').count()) > 0, `Trang ${expectedPath} hiển thị tiêu đề trong khung mới`)
    }
  })

  await scenario('S02', 'Thu gọn sidebar còn icon và nhớ trạng thái', page, async (check) => {
    await page.goto(`${baseUrl}/intakes`, { waitUntil: 'networkidle' })
    const sidebar = page.locator('.sidebar')
    const wide = (await sidebar.boundingBox()).width
    await page.getByRole('button', { name: 'Thu gọn thanh bên' }).click()
    await page.waitForTimeout(300)
    const narrow = (await sidebar.boundingBox()).width
    check(wide > 200 && narrow <= 64, `Sidebar thu từ ${Math.round(wide)}px xuống ${Math.round(narrow)}px`)
    check(!(await page.getByRole('navigation', { name: 'Điều hướng chính' }).getByText('Tất cả Intake').isVisible()), 'Nhãn chữ bị ẩn khi thu gọn')
    check((await page.locator('.sidebar .nav-text').evaluateAll((nodes) => nodes.filter((node) => node.getClientRects().length > 0).length)) === 0, 'Không còn chữ nào hiện trong sidebar thu gọn, kể cả tên app và email')
    check(await page.locator('.sidebar .brand-mark').isVisible(), 'Logo ZI vẫn hiện khi thu gọn')
    check((await page.getByRole('navigation', { name: 'Điều hướng chính' }).getByRole('link').first().getAttribute('title')) === 'Hôm nay', 'Icon có tooltip tên mục')
    await page.reload({ waitUntil: 'networkidle' })
    check((await page.locator('.sidebar').boundingBox()).width <= 64, 'Trạng thái thu gọn còn nguyên sau khi tải lại trang')
    await page.screenshot({ path: path.join(evidenceDir, 'S02-collapsed.png') })
    await page.getByRole('button', { name: 'Mở rộng thanh bên' }).click()
    await page.waitForTimeout(300)
    check((await page.locator('.sidebar').boundingBox()).width > 200, 'Mở rộng lại được')
  })

  await scenario('S03', 'Hộp soạn mặc định gọn, không có sidebar phải', page, async (check) => {
    await openComposer(page)
    check(await page.getByRole('heading', { name: 'Tạo Intake mới' }).isVisible(), 'Có tiêu đề "Tạo Intake mới"')
    check(await page.getByLabel('Nội dung gốc').isVisible(), 'Có ô nhập nội dung gốc')
    check((await page.getByLabel('Dự án').inputValue()) === 'orbit', 'Chip Dự án mặc định Orbit')
    check((await page.getByLabel('Kênh').inputValue()) === 'MANUAL', 'Chip Kênh mặc định Nhập tay')
    check(await page.getByRole('button', { name: 'Thêm file, thời điểm hoặc người gửi' }).isVisible(), 'Có nút [+]')
    check(await page.getByRole('button', { name: 'Nói để nhập' }).isVisible(), 'Có nút micro "Nói để nhập"')
    check(await page.getByRole('button', { name: 'Lưu & phân tích' }).isEnabled(), 'Có nút Lưu & phân tích')
    check((await page.locator('.right-panel').count()) === 0, 'Sidebar phải ẩn mặc định')
    check((await page.locator('.composer-chips').count()) === 0, 'Chưa có chip phụ nào khi chưa nhập')
    check((await page.locator('.form-layout, .dropzone').count()) === 0, 'Không còn form hai cột và vùng dropzone cũ')
    const box = await page.locator('.composer').boundingBox()
    check(box.width <= 760 && box.height < 220, `Hộp soạn gọn: ${Math.round(box.width)}x${Math.round(box.height)}px`)
  })

  await scenario('S04', 'Menu [+]: thời điểm tiếp nhận và người gửi thành chip', page, async (check) => {
    await openComposer(page)
    const plus = page.getByRole('button', { name: 'Thêm file, thời điểm hoặc người gửi' })
    await plus.click()
    const items = (await page.getByRole('menuitem').allInnerTexts()).map((text) => text.split('\n')[0].trim())
    check(JSON.stringify(items) === JSON.stringify(['Đính kèm file', 'Thời điểm tiếp nhận', 'Người gửi / tham chiếu', 'Ghi âm cuộc họp']), `Menu [+] có 4 mục: ${items.join(', ')}`)
    await page.getByRole('menuitem', { name: /Thời điểm tiếp nhận/ }).click()
    await page.getByLabel('Thời điểm tiếp nhận').fill('2026-10-03T14:20')
    await page.getByRole('button', { name: 'Xong' }).click()
    check(await page.locator('.chip', { hasText: '14:20' }).isVisible(), 'Chip thời điểm hiện 14:20 03/10/2026')
    await plus.click()
    await page.getByRole('menuitem', { name: /Người gửi/ }).click()
    await page.getByLabel('Người gửi / tham chiếu').fill('Khách hàng A, nhóm Zalo')
    await page.keyboard.press('Enter')
    check(await page.locator('.chip', { hasText: 'Khách hàng A, nhóm Zalo' }).isVisible(), 'Chip người gửi hiện sau khi nhấn Enter')
    check((await page.locator('.composer-popover').count()) === 0, 'Popover tự đóng sau khi nhập')
    await page.locator('.chip-label', { hasText: 'Khách hàng A' }).click()
    check((await page.getByLabel('Người gửi / tham chiếu').inputValue()) === 'Khách hàng A, nhóm Zalo', 'Bấm chip mở lại ô sửa với giá trị cũ')
    await page.getByLabel('Nội dung gốc').click()
    check((await page.locator('.composer-popover').count()) === 0, 'Bấm ra ngoài đóng popover')
    await page.screenshot({ path: path.join(evidenceDir, 'S04-chips.png') })
    await page.getByRole('button', { name: 'Xóa thời điểm tiếp nhận' }).click()
    await page.getByRole('button', { name: 'Xóa người gửi' }).click()
    check((await page.locator('.composer-chips').count()) === 0, 'Xóa hết chip thì hàng chip biến mất')
  })

  await scenario('S05', 'Đính kèm file hợp lệ', page, async (check) => {
    await openComposer(page)
    await page.getByRole('button', { name: 'Thêm file, thời điểm hoặc người gửi' }).click()
    const chooser = page.waitForEvent('filechooser')
    await page.getByRole('menuitem', { name: /Đính kèm file/ }).click()
    await (await chooser).setFiles([
      { name: 'bien-ban-hop.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 synthetic test data') },
      { name: 'man-hinh-loi.png', mimeType: 'image/png', buffer: Buffer.alloc(2048, 1) },
    ])
    check(await page.locator('.chip', { hasText: 'bien-ban-hop.pdf' }).isVisible(), 'Chip file PDF hiện tên file')
    check(await page.locator('.chip', { hasText: 'man-hinh-loi.png' }).isVisible(), 'Chip file PNG hiện tên file')
    check((await page.locator('.chip', { hasText: 'man-hinh-loi.png' }).innerText()).includes('2 KB'), 'Chip hiện dung lượng file')
    await page.getByRole('button', { name: 'Xóa bien-ban-hop.pdf' }).click()
    check((await page.locator('.chip').count()) === 1, 'Xóa một file, còn lại đúng một chip')
  })

  await scenario('S06', 'Chặn file sai loại và file quá 5 MB', page, async (check) => {
    await openComposer(page)
    const input = page.locator('.composer input[type="file"]')
    await input.setInputFiles({ name: 'ghi-chu.txt', mimeType: 'text/plain', buffer: Buffer.from('synthetic') })
    check((await page.getByRole('alert').innerText()).includes('ghi-chu.txt không hợp lệ'), 'File .txt bị từ chối kèm thông báo nêu tên file')
    check((await page.locator('.chip').count()) === 0, 'File sai loại không thành chip')
    await input.setInputFiles({ name: 'qua-lon.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(5 * 1024 * 1024 + 1) })
    check((await page.getByRole('alert').innerText()).includes('qua-lon.pdf không hợp lệ'), 'File PDF lớn hơn 5 MB bị từ chối')
    check((await page.locator('.chip').count()) === 0, 'File quá lớn không thành chip')
    await input.setInputFiles({ name: 'hop-le.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4') })
    check((await page.getByRole('alert').count()) === 0 && (await page.locator('.chip').count()) === 1, 'Chọn file hợp lệ sau đó xóa thông báo lỗi')
  })

  await scenario('S07', 'Không cho lưu khi chưa có nội dung', page, async (check) => {
    await openComposer(page)
    const before = mutations.length
    await page.getByRole('button', { name: 'Lưu & phân tích' }).click()
    check((await page.getByRole('alert').innerText()).includes('Hãy nhập nội dung phản hồi trước khi lưu'), 'Hiện thông báo yêu cầu nhập nội dung')
    await page.getByLabel('Nội dung gốc').fill('   ')
    await page.getByRole('button', { name: 'Lưu & phân tích' }).click()
    check(mutations.length === before, 'Không có request tạo Intake nào được gửi')
    check(new URL(page.url()).pathname === '/intakes/new', 'Vẫn ở trang tạo Intake')
  })

  await scenario('S08', 'Lưu đầy đủ: payload, upload, process và chuyển trang', page, async (check) => {
    await openComposer(page)
    const before = mutations.length
    await page.getByLabel('Dự án').selectOption('ember')
    await page.getByLabel('Kênh').selectOption('MANUAL')
    const text = 'SYNTHETIC TEST DATA: composer flow. Nút xuất báo cáo tuần không tải được file; không có dữ liệu khách hàng.'
    await page.getByLabel('Nội dung gốc').fill(text)
    const plus = page.getByRole('button', { name: 'Thêm file, thời điểm hoặc người gửi' })
    await plus.click()
    await page.getByRole('menuitem', { name: /Thời điểm tiếp nhận/ }).click()
    await page.getByLabel('Thời điểm tiếp nhận').fill('2026-10-03T14:20')
    await page.getByRole('button', { name: 'Xong' }).click()
    await plus.click()
    await page.getByRole('menuitem', { name: /Người gửi/ }).click()
    await page.getByLabel('Người gửi / tham chiếu').fill('Synthetic sender')
    await page.keyboard.press('Enter')
    await page.locator('.composer input[type="file"]').setInputFiles({ name: 'evidence.png', mimeType: 'image/png', buffer: Buffer.alloc(1024, 1) })
    await page.screenshot({ path: path.join(evidenceDir, 'S08-before-save.png') })
    await page.getByRole('button', { name: 'Lưu & phân tích' }).click()
    await page.waitForURL(new RegExp(`/intakes/${fakeIntakeId}$`), { timeout: 15_000 })
    const sent = mutations.slice(before)
    const kinds = sent.map((item) => item.kind)
    check(JSON.stringify(kinds) === JSON.stringify(['create', 'attachment', 'process']), `Thứ tự request: ${kinds.join(' -> ')}`)
    const create = sent[0]
    check(create.body.project_id === 'ember', 'project_id = ember')
    check(create.body.channel === 'MANUAL', 'channel = MANUAL')
    check(create.body.raw_text === text, 'raw_text đúng nguyên văn đã nhập')
    check(create.body.sender_reference === 'Synthetic sender', 'sender_reference đúng')
    check(create.body.received_at === '2026-10-03T07:20:00.000Z', `received_at đổi đúng sang UTC: ${create.body.received_at}`)
    check(/^[0-9a-f-]{36}$/.test(create.headers['idempotency-key'] || ''), 'Có header Idempotency-Key dạng UUID')
    check((sent[1].contentType || '').startsWith('multipart/form-data'), 'File được tải lên dạng multipart')
    check(new URL(page.url()).pathname === `/intakes/${fakeIntakeId}`, 'Chuyển sang trang chi tiết Intake vừa tạo')
  })

  await scenario('S09', 'Ghi âm họp mở sidebar phải theo ngữ cảnh', page, async (check) => {
    await openComposer(page)
    const composerWide = (await page.locator('.page').boundingBox()).width
    check(await page.getByRole('button', { name: 'Nói để nhập' }).isVisible(), 'Nút micro ở ô soạn là "Nói để nhập"')
    await page.getByRole('button', { name: 'Thêm file, thời điểm hoặc người gửi' }).click()
    await page.getByRole('menuitem', { name: /Ghi âm cuộc họp/ }).click()
    const panel = page.locator('.right-panel')
    await panel.waitFor()
    await page.waitForTimeout(300)
    check(await panel.getByRole('heading', { name: 'Ghi âm cuộc họp' }).isVisible(), 'Sidebar phải mở với tiêu đề "Ghi âm cuộc họp"')
    check(new URL(page.url()).searchParams.get('panel') === 'record', 'URL có ?panel=record nên tải lại vẫn mở')
    check((await page.getByLabel('Kênh').inputValue()) === 'MEETING', 'Kênh tự chuyển sang Meeting')
    check(await page.locator('.topbar').getByText('Ghi âm họp', { exact: true }).isVisible(), 'Thanh trên ghi "Ghi âm họp" khi đang ở chế độ ghi')
    check((await page.locator('.page').boundingBox()).width < composerWide, 'Sidebar phải đẩy vùng soạn sang trái, không che lên')
    const sources = (await panel.getByRole('radio').count())
    check(sources === 3, 'Có 3 nguồn âm: cuộc họp online + micro, chỉ micro, tải file có sẵn')
    check(await panel.getByRole('button', { name: 'Bắt đầu ghi âm' }).isDisabled(), 'Chưa chọn dự án thì chưa bấm được Bắt đầu ghi âm')
    await panel.getByLabel('Dự án của cuộc họp').selectOption('orbit')
    check(await panel.getByRole('button', { name: 'Bắt đầu ghi âm' }).isEnabled(), 'Chọn dự án xong thì nút Bắt đầu ghi âm bấm được')
    check((await panel.innerText()).includes('Hiện dần khi đang ghi') && (await panel.innerText()).includes('60 phút') && (await panel.innerText()).includes('90 ngày'), 'Hiện đúng 3 quyết định: bản chữ hiện dần, tối đa 60 phút, lưu 90 ngày')
    check(await panel.getByLabel('Dự án của cuộc họp').isVisible() && await panel.getByLabel('Thuật ngữ mới').isVisible(), 'Có chọn dự án và ô thêm thuật ngữ')
    check((await panel.innerText()).includes('Hãy thông báo cho người tham dự trước khi ghi âm'), 'Có nhắc thông báo cho người tham dự trước khi ghi âm')
    await page.getByLabel('Nội dung gốc').fill('Ghi chú gõ tay trong lúc họp')
    await page.screenshot({ path: path.join(evidenceDir, 'S09-panel-open.png') })
    await panel.getByRole('button', { name: 'Đóng bảng cài đặt' }).click()
    await panel.waitFor({ state: 'detached' })
    check(new URL(page.url()).searchParams.get('panel') === null, 'Đóng sidebar phải xóa ?panel=record')
    check((await page.getByLabel('Nội dung gốc').inputValue()) === 'Ghi chú gõ tay trong lúc họp', 'Nội dung đang soạn không mất khi mở/đóng sidebar phải')
    await page.locator('.topbar').getByRole('button', { name: 'Thêm mới' }).click()
    await page.getByRole('menuitem', { name: /Ghi âm họp/ }).click()
    await page.locator('.right-panel').waitFor()
    check(true, 'Mục "Ghi âm họp" ở sidebar trái mở thẳng sidebar phải')
    await page.getByRole('navigation', { name: 'Điều hướng chính' }).getByRole('link', { name: 'Tất cả Intake' }).click()
    await page.waitForURL((url) => url.pathname === '/intakes')
    await page.locator('.topbar h1', { hasText: 'Tất cả Intake' }).waitFor()
    check((await page.locator('.right-panel').count()) === 0, 'Rời trang tạo Intake thì sidebar phải tự đóng')
  })

  check_no_page_errors(desktop.pageErrors, 'desktop')
  await desktop.context.close()

  const mobile = await newSession({ width: 390, height: 844 })
  await scenario('S10', 'Mobile 390px: menu trượt, hộp soạn vừa màn hình, sidebar phải thành tấm trượt dưới', mobile.page, async (check) => {
    const mobilePage = mobile.page
    await openComposer(mobilePage)
    const overflow = await mobilePage.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    check(overflow <= 0, `Không cuộn ngang (tràn ${overflow}px)`)
    const sidebarBox = await mobilePage.locator('.sidebar').boundingBox()
    check(sidebarBox.x + sidebarBox.width <= 0, 'Sidebar trái ẩn mặc định')
    const bar = await mobilePage.locator('.composer-bar').boundingBox()
    const send = await mobilePage.getByRole('button', { name: 'Lưu & phân tích' }).boundingBox()
    check(send.x + send.width <= bar.x + bar.width + 1 && send.width <= 40, 'Thanh công cụ nằm trọn một hàng, nút lưu thu thành icon')
    await mobilePage.getByRole('button', { name: 'Mở menu' }).click()
    await mobilePage.waitForTimeout(300)
    check((await mobilePage.locator('.sidebar').boundingBox()).x === 0, 'Nút menu mở sidebar trượt')
    check(await mobilePage.getByRole('navigation', { name: 'Điều hướng chính' }).getByText('Tất cả Intake').isVisible(), 'Sidebar mobile hiện đủ nhãn chữ')
    await mobilePage.screenshot({ path: path.join(evidenceDir, 'S10-menu.png') })
    // A tap outside the drawer (to the right of the 264 px sidebar) closes it.
    await mobilePage.locator('.sidebar-backdrop').click({ position: { x: 330, y: 400 } })
    await mobilePage.locator('.sidebar-backdrop').waitFor({ state: 'detached', timeout: 5000 })
    await mobilePage.locator('.topbar').getByRole('button', { name: 'Thêm mới' }).click()
    await mobilePage.getByRole('menuitem', { name: /Ghi âm họp/ }).click()
    const panel = mobilePage.locator('.right-panel')
    await panel.waitFor()
    await mobilePage.waitForTimeout(300)
    const panelBox = await panel.boundingBox()
    check(Math.round(panelBox.width) === 390 && Math.round(panelBox.y + panelBox.height) === 844 && panelBox.y > 100, 'Sidebar phải thành tấm trượt từ dưới, rộng hết màn hình')
    check((await mobilePage.locator('.sidebar').boundingBox()).x < 0, 'Chọn mục xong thì menu trái tự đóng')
    await mobilePage.getByRole('button', { name: 'Đóng bảng cài đặt' }).click()
    await panel.waitFor({ state: 'detached' })
    check(true, 'Đóng được tấm trượt')
  })
  check_no_page_errors(mobile.pageErrors, 'mobile')
  await mobile.context.close()
} finally {
  await browser.close()
}


function check_no_page_errors(errors, label) {
  results.push({ id: `ERR-${label}`, title: `Không có lỗi JavaScript trên ${label}`, status: errors.length === 0 ? 'passed' : 'failed', checks: [], error: errors.join(' | ') || undefined, screenshot: null })
}


const summary = {
  base_url: baseUrl,
  ran_at: new Date().toISOString(),
  intake_api_writes_mocked: true,
  mutations_intercepted: mutations.length,
  passed: results.filter((item) => item.status === 'passed').length,
  failed: results.filter((item) => item.status === 'failed').length,
  results,
}
fs.writeFileSync(path.join(evidenceDir, 'results.json'), `${JSON.stringify(summary, null, 2)}\n`)
console.log(JSON.stringify({ passed: summary.passed, failed: summary.failed, composer_ui: summary.failed === 0 ? 'passed' : 'failed' }))
process.exit(summary.failed === 0 ? 0 : 1)
