import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('../dist/', import.meta.url)));
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.json': 'application/json', '.woff2': 'font/woff2', '.png': 'image/png' };
const server = process.env.PLAYGROUND_URL ? undefined : createServer(async (request, response) => {
  try {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    const requested = resolve(root, `.${pathname}`);
    if (requested !== root && !requested.startsWith(`${root}${sep}`)) throw new Error('path outside build');
    const filePath = pathname.endsWith('/') ? resolve(requested, 'index.html') : requested;
    const file = await readFile(filePath);
    response.writeHead(200, { 'content-type': mime[extname(filePath)] ?? 'application/octet-stream' });
    response.end(file);
  } catch {
    response.writeHead(404);
    response.end('Not found');
  }
});
let url = process.env.PLAYGROUND_URL;
if (server) {
  await new Promise((resolveListen, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolveListen);
  });
  url = `http://127.0.0.1:${server.address().port}/playground/`;
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
const failures = [];
const check = (condition, message) => { if (!condition) failures.push(message); };
const text = async (id) => page.locator(`#${id}`).textContent();
const snapshot = async () => ({
  title: await text('result-title'), copy: await text('result-copy'),
  subtotal: await text('subtotal'), tax: await text('tax-result'), total: await text('total'),
  traceInput: await text('trace-input'), traceChoice: await text('trace-choice'), traceResult: await text('trace-result'),
  rejection: await text('rejection'), activeSteps: await page.locator('[data-step].active').count(),
  inputs: await page.locator('#quote-form').evaluate((form) => Object.fromEntries(new FormData(form))),
});
const cleared = (s) => s.title === 'Quote ready' && s.copy.includes('Run the fixed quote operation') && s.subtotal === '—' && s.tax === '—' && s.total === '—' && s.traceInput === 'Waiting for request' && s.traceChoice === 'Summary / detailed' && s.traceResult === 'Fixed quote operation' && s.rejection.trim() === '' && s.activeSteps === 0;
const defaults = { price: '1299', quantity: '3', tax: '8.25', format: 'summary' };
const submit = () => page.locator('#quote-form').evaluate((form) => form.requestSubmit());
const waitForResult = (total = '$42.19') => page.waitForFunction((expected) => document.querySelector('#result-title')?.textContent === 'Summary quote' && document.querySelector('#trace-result')?.textContent === `${expected} · app-calculated` && document.querySelectorAll('[data-step].active').length === 4, total);

try {
  const response = await page.goto(url, { waitUntil: 'networkidle' });
  check(response?.ok(), `served URL failed: ${response?.status()} ${url}`);
  check((await page.title()) === 'Restricted playground · Summonpot', `wrong served page title: ${await page.title()}`);
  check((await page.locator('main > h1').textContent()).includes('Build a quote'), 'playground heading missing');
  const browserErrors = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));

  await submit();
  await page.waitForFunction(() => document.querySelector('#trace-result')?.textContent === 'Calculating…');
  await page.locator('#reset').click();
  const immediatelyReset = await snapshot();
  check(cleared(immediatelyReset), `reset left stale presentation: ${JSON.stringify(immediatelyReset)}`);
  check(JSON.stringify(immediatelyReset.inputs) === JSON.stringify(defaults), `reset did not restore defaults: ${JSON.stringify(immediatelyReset.inputs)}`);
  await page.waitForTimeout(1100);
  const afterCancelledTimers = await snapshot();
  check(cleared(afterCancelledTimers), `old run wrote after reset: ${JSON.stringify(afterCancelledTimers)}`);

  await submit();
  await waitForResult();
  const first = await snapshot();
  check(first.title === 'Summary quote' && first.subtotal === '$38.97' && first.tax === '$3.22' && first.total === '$42.19', `default quote mismatch: ${JSON.stringify(first)}`);
  check(first.traceInput === '1299¢ × 3 · 8.25% tax' && first.traceChoice === 'summary' && first.traceResult === '$42.19 · app-calculated', `default trace mismatch: ${JSON.stringify(first)}`);
  await submit();
  await waitForResult();
  const second = await snapshot();
  check(second.title === 'Summary quote' && second.total === '$42.19' && second.traceResult === '$42.19 · app-calculated', `repeated run mismatch: ${JSON.stringify(second)}`);

  await submit();
  await page.waitForFunction(() => document.querySelector('#trace-result')?.textContent === 'Calculating…');
  await page.locator('[name="price"]').fill('2500');
  const afterInput = await snapshot();
  check(cleared(afterInput), `input change did not clear active result: ${JSON.stringify(afterInput)}`);
  check(JSON.stringify(afterInput.inputs) === JSON.stringify({ ...defaults, price: '2500' }), `input edit changed unexpected values: ${JSON.stringify(afterInput.inputs)}`);
  await page.waitForTimeout(1100);
  const afterInputTimers = await snapshot();
  check(cleared(afterInputTimers), `old run wrote after input edit: ${JSON.stringify(afterInputTimers)}`);
  await submit();
  await waitForResult('$81.19');
  const changed = await snapshot();
  check(changed.subtotal === '$75.00' && changed.tax === '$6.19' && changed.total === '$81.19' && changed.traceInput === '2500¢ × 3 · 8.25% tax', `updated inputs were not used: ${JSON.stringify(changed)}`);

  await page.locator('[data-forbidden="price"]').click();
  check((await text('rejection')).includes('Rejected:'), 'forbidden override did not show rejection');
  await page.locator('#reset').click();
  const afterRejectionReset = await snapshot();
  check(cleared(afterRejectionReset), `rejection/reset left stale presentation: ${JSON.stringify(afterRejectionReset)}`);
  check(JSON.stringify(afterRejectionReset.inputs) === JSON.stringify(defaults), `rejection/reset did not restore defaults: ${JSON.stringify(afterRejectionReset.inputs)}`);
  check(browserErrors.length === 0, `browser errors: ${browserErrors.join('; ')}`);

  console.log(JSON.stringify({ url, title: await page.title(), checks: 17, snapshots: { immediatelyReset, afterCancelledTimers, first, second, afterInput, afterInputTimers, changed, afterRejectionReset }, browserErrors, failures }, null, 2));
} finally {
  await browser.close();
  if (server) await new Promise((resolveClose) => server.close(resolveClose));
}
if (failures.length) process.exitCode = 1;
