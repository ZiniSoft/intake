import process from 'node:process'

import { chromium } from 'playwright-core'

const baseUrl = process.env.SETUP_UI_BASE_URL || 'http://127.0.0.1:5173'
const chromePath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const envelope = (data) => JSON.stringify({ success: true, data, request_id: 'setup-locale-e2e' })
const assert = (condition, message) => { if (!condition) throw new Error(message) }

const browser = await chromium.launch({ executablePath: chromePath, headless: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await context.newPage()

try {
  await page.route('**/api/v1/setup/status', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ needs_bootstrap: true }) }))
  await page.route('**/api/v1/setup/bootstrap', (route) => route.fulfill({ contentType: 'application/json', body: envelope({ needs_bootstrap: false }) }))
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ success: false, error: 'UNAUTHENTICATED' }) }))

  await page.goto(`${baseUrl}/welcome`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Welcome to Intake' }).waitFor()
  assert(await page.locator('html').getAttribute('lang') === 'en', 'a new browser must default to English')
  assert(await page.getByRole('button', { name: 'EN' }).getAttribute('aria-pressed') === 'true', 'EN must be selected by default')

  await page.getByRole('button', { name: 'VI' }).click()
  await page.getByRole('heading', { name: 'Chào mừng đến với Intake' }).waitFor()
  assert(await page.evaluate(() => localStorage.getItem('intake.locale')) === 'vi', 'the browser preference must be stored locally')

  await page.reload({ waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Chào mừng đến với Intake' }).waitFor()

  await page.goto(`${baseUrl}/welcome?lang=en`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Welcome to Intake' }).waitFor()
  assert(await page.evaluate(() => localStorage.getItem('intake.locale')) === 'en', 'an explicit query parameter must replace the stored preference')
  await page.getByRole('checkbox', { name: 'Create a Project Owner account now' }).uncheck()
  await page.getByLabel('Email').fill('cto@example.test')
  await page.getByLabel('Display name').fill('Test CTO')
  await page.getByLabel('Password (at least 8 characters)').fill('test-password-123')
  await page.getByLabel('Confirm password').fill('test-password-123')
  const bootstrapRequest = page.waitForRequest((request) => request.url().endsWith('/api/v1/setup/bootstrap') && request.method() === 'POST')
  await page.getByRole('button', { name: 'Create accounts and continue' }).click()
  const bootstrapBody = (await bootstrapRequest).postDataJSON()
  assert(bootstrapBody.locale === 'en', `bootstrap must receive the selected English locale, got ${bootstrapBody.locale}`)
  console.log('setup-locale: ok')
} finally {
  await browser.close()
}
