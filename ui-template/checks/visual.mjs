// Visual check: the gallery and the top bar are photographed and compared with the reference pictures in checks/baseline.
// A difference means the look of a component changed. If the change is intended, run `npm run check:visual -- --update`
// and commit the new pictures together with the change.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import pixelmatch from 'pixelmatch'
import { chromium } from 'playwright-core'
import { PNG } from 'pngjs'
import { createServer } from 'vite'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const baseline = path.join(root, 'checks', 'baseline')
const output = path.join(root, 'checks', 'output')
const update = process.argv.includes('--update')
// A browser already on the machine is used; set CHROME_PATH when it is somewhere else.
const browserPath = [process.env.CHROME_PATH, 'C:/Program Files/Google/Chrome/Application/chrome.exe', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome', '/usr/bin/chromium']
  .find((candidate) => candidate && fs.existsSync(candidate))
if (!browserPath) {
  console.error('No Chrome found. Set CHROME_PATH to a Chrome or Chromium executable.')
  process.exit(2)
}

const views = [
  { name: 'desktop-vi', width: 1440, height: 900, language: 'vi' },
  { name: 'mobile-vi', width: 390, height: 800, language: 'vi' },
  { name: 'desktop-en', width: 1440, height: 900, language: 'en' },
]
// On one machine two runs give identical pictures, so almost nothing is tolerated. A rounded corner changing by a few
// pixels is already a few hundred differing pixels. Raise VISUAL_TOLERANCE_PIXELS only to compare across machines.
const TOLERANCE = Number(process.env.VISUAL_TOLERANCE_PIXELS || 20)

const server = await createServer({ root, logLevel: 'error', server: { port: 5181, strictPort: true, host: '127.0.0.1' } })
await server.listen()
const browser = await chromium.launch({ executablePath: browserPath, headless: true })
fs.mkdirSync(baseline, { recursive: true })
fs.rmSync(output, { recursive: true, force: true })
let failed = 0
try {
  for (const view of views) {
    const context = await browser.newContext({ viewport: { width: view.width, height: view.height }, deviceScaleFactor: 1, reducedMotion: 'reduce' })
    await context.addInitScript(([language]) => {
      localStorage.setItem('ui.language', language)
      sessionStorage.setItem('ui.session', JSON.stringify({ name: 'An Nguyễn', email: 'an@congty.vn', mustChangePassword: false }))
    }, [view.language])
    const page = await context.newPage()
    // The first request makes the dev server prepare the app, which can take a while on a cold start.
    await page.goto('http://127.0.0.1:5181/gallery', { waitUntil: 'load', timeout: 120_000 })
    await page.locator('.gallery').waitFor({ timeout: 120_000 })
    await page.waitForLoadState('networkidle')
    await page.evaluate(() => document.fonts.ready)
    // Two pictures per view: every component block, and the top bar. The sidebar is left out on purpose,
    // because it changes whenever a project adds a screen, which is not a change to the standard.
    for (const [part, selector] of [['gallery', '.gallery'], ['topbar', '.shell-topbar']]) {
      const name = `${part}-${view.name}`
      const shot = PNG.sync.read(await page.locator(selector).screenshot())
      const reference = path.join(baseline, `${name}.png`)
      if (update || !fs.existsSync(reference)) {
        fs.writeFileSync(reference, PNG.sync.write(shot))
        console.log(`${update ? 'updated' : 'created'}  ${name}.png (${shot.width}x${shot.height})`)
        continue
      }
      const expected = PNG.sync.read(fs.readFileSync(reference))
      let differing = Infinity
      let diff = null
      if (expected.width === shot.width && expected.height === shot.height) {
        diff = new PNG({ width: shot.width, height: shot.height })
        differing = pixelmatch(expected.data, shot.data, diff.data, shot.width, shot.height, { threshold: 0.03 })
      }
      if (differing > TOLERANCE) {
        failed += 1
        fs.mkdirSync(output, { recursive: true })
        fs.writeFileSync(path.join(output, `${name}.actual.png`), PNG.sync.write(shot))
        if (diff) fs.writeFileSync(path.join(output, `${name}.diff.png`), PNG.sync.write(diff))
        console.log(`DIFFERENT ${name}: ${diff ? `${differing} pixels changed` : `size changed from ${expected.width}x${expected.height} to ${shot.width}x${shot.height}`}. See checks/output/.`)
      } else {
        console.log(`same     ${name}${differing > 0 ? ` (${differing} pixels differ, within tolerance)` : ''}`)
      }
    }
    await context.close()
  }
} finally {
  await browser.close()
  await server.close()
}
if (failed > 0) {
  console.log(`\n${failed} picture(s) changed. If intended: npm run check:visual -- --update, then commit checks/baseline.`)
  process.exit(1)
}
