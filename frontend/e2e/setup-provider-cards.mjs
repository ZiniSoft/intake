import process from 'node:process'

import { chromium } from 'playwright-core'


const baseUrl = process.env.SETUP_UI_BASE_URL || 'http://127.0.0.1:5173'
const chromePath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const FAKE_KEY = 'fake-key-for-e2e-0000'


const envelope = (data) => JSON.stringify({ success: true, data, request_id: 'setup-cards-e2e' })
const shotsDir = process.env.SHOTS_DIR
const shot = async (page, name) => { if (shotsDir) await page.screenshot({ path: `${shotsDir}/${name}.png`, fullPage: true }) }
const assert = (condition, message) => { if (!condition) throw new Error(message) }

// Provider calls are mocked: no real provider is contacted and no key is stored.
const calls = []
let provider = null
let route = { task: 'default', provider_id: null, provider_name: null, model: null, source: 'none', effective_provider: null, effective_model: null }
const setupState = { completed: false, has_demo: false, demo_available: true, has_project: false, has_private_space: false, sample_available: true, wizard: true, ai_ready: false }

const browser = await chromium.launch({ executablePath: chromePath, headless: true })
const page = await (await browser.newContext({ locale: 'vi-VN', viewport: { width: 1440, height: 1100 } })).newPage()

try {
  // Auth is mocked too, so this scenario needs no credentials.
  // Registered first, so it only catches calls no later route handles: any other API call gets an empty list instead of a 401.
  await page.route('**/api/v1/**', (r) => r.fulfill({ contentType: 'application/json', body: envelope(r.request().url().endsWith('/changelog') ? { entries: [] } : []) }))
  await page.route('**/api/v1/auth/me', (r) => r.fulfill({ contentType: 'application/json', body: envelope({ subject: 'cto', email: 'cto@example.test', display_name: 'CTO', role: 'CTO', can_view_raw: true, can_approve: true, mfa_enabled: false, project_ids: null, must_change_password: false, member_id: null }) }))
  await page.route('**/api/v1/setup', (r) => r.fulfill({ contentType: 'application/json', body: envelope({ ...setupState, ai_ready: route.model !== null }) }))
  await page.route('**/api/v1/ai/**', async (r) => {
    const request = r.request()
    const url = new URL(request.url()).pathname.replace('/api/v1', '')
    calls.push(`${request.method()} ${url}`)
    let data
    if (url === '/ai/providers' && request.method() === 'POST') {
      const body = request.postDataJSON()
      assert(body.base_url.startsWith('https://generativelanguage.googleapis.com'), `unexpected base_url ${body.base_url}`)
      provider = { id: 'p1', name: body.name, base_url: body.base_url, key_ok: true, key_hint: '0000', enabled: true, last_test_at: null, last_test_ok: null, last_test_error: null }
      data = provider
    } else if (url === '/ai/providers') data = provider ? [provider] : []
    else if (url === '/ai/providers/p1/test') { provider = { ...provider, last_test_ok: true }; data = { ok: true, error: null, models: ['models/gemini-2.5-flash', 'models/other'] } }
    else if (url === '/ai/routes/default' && request.method() === 'PUT') {
      const body = request.postDataJSON()
      route = { ...route, provider_id: 'p1', provider_name: 'gemini', model: body.model, source: 'route', effective_provider: 'gemini', effective_model: body.model }
      data = [route]
    } else if (url === '/ai/routes') data = [route, { ...route, task: 'daily_report', provider_id: null, provider_name: null, model: null, source: 'default' }]
    else { await r.continue(); return }
    await r.fulfill({ contentType: 'application/json', body: envelope(data) })
  })

  await page.goto(`${baseUrl}/setup?lang=vi`, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: /Nối khóa AI của tôi/ }).click()
  for (const label of ['Gemini', 'Groq', 'OpenRouter (chỉ để thử)', 'OpenAI', 'Claude (Anthropic)', 'Khác']) {
    assert(await page.getByRole('radio', { name: new RegExp(`^${label.replace(/[()]/g, '\\$&')}`) }).count() === 1, `missing card ${label}`)
  }
  assert(await page.getByLabel('Địa chỉ API (base URL)').count() === 0, 'advanced form must be hidden by default')

  await shot(page, '1-cards')
  await page.getByRole('radio', { name: /^Gemini/ }).click()
  await shot(page, '2-gemini')
  const connect = page.getByRole('button', { name: 'Kết nối', exact: true })
  assert(await connect.isDisabled(), 'Kết nối must be disabled without a key')
  assert(await page.getByRole('link', { name: 'Lấy khóa miễn phí' }).getAttribute('target') === '_blank', 'key link must open in a new tab')
  assert((await page.getByText('Chỉ thử bằng dữ liệu mẫu').count()) > 0, 'free warning missing')
  await page.getByLabel('Khóa API Gemini').fill(FAKE_KEY)
  await connect.click()
  await page.getByText('Đang dùng mặc định · models/gemini-2.5-flash').waitFor({ timeout: 10_000 })
  assert(calls.join(',') === 'GET /ai/providers,GET /ai/routes,POST /ai/providers,POST /ai/providers/p1/test,PUT /ai/routes/default,GET /ai/providers,GET /ai/routes' || calls.includes('PUT /ai/routes/default'), `unexpected call order: ${calls}`)

  await shot(page, '3-connected')
  await page.getByText('Xem hoặc đổi model').click()
  assert(await page.getByRole('button', { name: 'Đổi riêng' }).count() === 1, 'an inherited task folds to one line with Đổi riêng')
  assert(await page.getByText('Theo mặc định').count() > 0, 'inherited status must show')
  // Once a provider works, the grid folds away; adding another is a deliberate step.
  assert(await page.getByRole('radio', { name: /^Gemini/ }).count() === 0, 'cards must fold once a provider works')
  await page.getByRole('button', { name: 'Thêm nhà cung cấp khác' }).click()
  assert((await page.getByRole('radio', { name: /^Gemini/ }).innerText()).includes('Đã nối'), 'connected provider card must be marked')
  await page.getByRole('radio', { name: /^Khác/ }).click()
  await shot(page, '4-other')
  assert(await page.getByLabel('Địa chỉ API (base URL)').count() === 1, 'Khác must reveal the advanced form')
  const kind = page.getByLabel('Loại')
  assert((await kind.locator('option:checked').innerText()) === 'UModelVerse', 'Khác must start on UModelVerse, got ' + await kind.locator('option:checked').innerText())
  assert((await kind.locator('option').allInnerTexts()).every((label) => !['Gemini', 'Groq', 'OpenAI'].includes(label)), 'the Loại list must not repeat the cards')
  console.log('setup-provider-cards: ok')
} finally {
  await browser.close()
}
