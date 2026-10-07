import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { gunzipSync } from 'node:zlib';
import { chromium } from 'playwright';

// Exercise the real CDN SDK while intercepting ingestion so no test events reach production.
// The automation override below is test-only; assert the original shipped config retains bot filtering.
const browser = await chromium.launch();
try {
  for (const path of ['/', '/playground/']) {
    const context = await browser.newContext({ userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36' });
    await context.addInitScript(() => {
      Object.defineProperty(navigator, 'webdriver', { get: () => false });
      const stub = [];
      window.posthog = stub;
      Object.defineProperty(stub, 'init', { configurable: true, set(fn) {
        Object.defineProperty(stub, 'init', { configurable: true, value(token, config, name) {
          window.__originalAnalyticsConfig = config;
          return fn(token, { ...config, opt_out_useragent_filter: true }, name);
        } });
      } });
    });
    const events = [];
    await context.route('https://us.i.posthog.com/**', async route => {
      const body = route.request().postDataBuffer();
      if (body) {
        let decoded;
        try { decoded = gunzipSync(body).toString(); } catch { decoded = body.toString(); }
        const payload = JSON.parse(decoded);
        events.push(...(payload.batch ?? (Array.isArray(payload) ? payload : payload.event ? [payload] : [])));
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":1}' });
    });
    await context.route('https://summonpot.test/**', async route => {
      const pathname = new URL(route.request().url()).pathname;
      const file = pathname === '/playground/' ? 'playground/index.html' : 'index.html';
      await route.fulfill({ contentType: 'text/html', body: await readFile(new URL(`../dist/${file}`, import.meta.url), 'utf8') });
    });
    const page = await context.newPage();
    await page.goto(`https://summonpot.test${path}`);
    await page.waitForFunction(() => window.posthog?.__loaded);
    await page.waitForTimeout(4000);
    const views = events.filter(event => event.event === '$pageview');
    assert.equal(views.length, 1, `${path} must emit exactly one initial pageview`);
    assert.equal(new URL(views[0].properties.$current_url).pathname, path);
    const config = await page.evaluate(() => ({ replay: window.__originalAnalyticsConfig.disable_session_recording, profiles: window.__originalAnalyticsConfig.person_profiles, bots: window.__originalAnalyticsConfig.opt_out_useragent_filter === true }));
    assert.deepEqual(config, { replay: true, profiles: 'identified_only', bots: false });
    console.log(`${path}: one pageview; privacy and bot filtering preserved`);
    await context.close();
  }
} finally {
  await browser.close();
}
