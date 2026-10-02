import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { resolve, extname, sep } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("../dist/", import.meta.url)));
const mime = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".json": "application/json",
  ".woff2": "font/woff2",
  ".png": "image/png",
};
const server = process.env.PLAYGROUND_URL
  ? undefined
  : createServer(async (request, response) => {
      try {
        const pathname = decodeURIComponent(
          new URL(request.url, "http://localhost").pathname,
        );
        const requested = resolve(root, `.${pathname}`);
        if (requested !== root && !requested.startsWith(`${root}${sep}`))
          throw new Error("path outside build");
        const filePath = pathname.endsWith("/")
          ? resolve(requested, "index.html")
          : requested;
        response.writeHead(200, {
          "content-type": mime[extname(filePath)] ?? "application/octet-stream",
        });
        response.end(await readFile(filePath));
      } catch {
        response.writeHead(404);
        response.end("Not found");
      }
    });
let url = process.env.PLAYGROUND_URL;
if (server) {
  await new Promise((ok, fail) => {
    server.once("error", fail);
    server.listen(0, "127.0.0.1", ok);
  });
  url = `http://127.0.0.1:${server.address().port}/playground/`;
}
const browser = await chromium.launch({ headless: true });
const failures = [];
let checks = 0;
const check = (condition, message) => {
  checks++;
  if (!condition) failures.push(message);
};
const cleared = async (page) =>
  (await page.locator("#result-title").textContent()) === "Ready to run" &&
  (await page.locator("#customer-name").textContent()) === "—" &&
  (await page.locator("#bound-customer-id").textContent()) === "—" &&
  (await page.locator("#trace-result").textContent()) ===
    "Operation result · —" &&
  (await page.locator("[data-step].active").count()) === 0 &&
  !(await page.locator("#rejection").textContent()).trim();
try {
  const page = await browser.newPage({
    viewport: { width: 1280, height: 900 },
    colorScheme: "light",
    reducedMotion: "reduce",
  });
  const browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  const response = await page.goto(url, { waitUntil: "networkidle" });
  check(response?.ok(), `served URL failed: ${response?.status()} ${url}`);
  check(
    (await page.title()) === "Summonpot playground",
    `wrong title: ${await page.title()}`,
  );
  check(
    (await page.locator("h1").textContent()).includes("bounded choice"),
    "bounded authority heading missing",
  );
  await page.evaluate(async () => { await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); });
  const composition = await page.evaluate(() => {
    const rect = selector => { const r = document.querySelector(selector).getBoundingClientRect(); return {top:r.top,bottom:r.bottom,height:r.height,width:r.width}; };
    return { run:rect('.actions button[type="submit"]'), reset:rect('#reset'), code:rect('.code-panel'), controls:rect('.controls-panel'), result:rect('.result'), flow:document.querySelectorAll('.contract-flow li').length, closed:[...document.querySelectorAll('.full-source,.execution-detail')].every(d => !d.open) };
  });
  check(composition.run.height === 44 && composition.reset.height === 44 && composition.run.top === composition.reset.top, 'primary actions must share a 44px height and baseline');
  check(Math.abs(composition.code.top - composition.controls.top) <= 1 && composition.result.bottom <= composition.controls.bottom, 'code and interactive result must form one aligned workbench');
  check(composition.flow === 3 && composition.closed, 'authority flow must be visible and secondary details initially closed');
  check((await page.locator('.intro').innerText()).includes('The request owns the customer ID'), 'the defining request/choice distinction must lead the playground');
  const code = await page.locator(".primary-code pre").innerText();
  check(/def load_customer\(\s*customer_id: str,\s*format: Literal\["summary", "detailed"\],?\s*\)/.test(code), "operation input annotations must preserve the shipped bounded choice");
  check(await page.getByRole("link", { name: "ModePot ↗", exact: true }).getAttribute("href") === "https://modepot.io/", "canonical family return link missing");
  check(
    (await page.locator(".code-panel .panel-heading").innerText()).includes(
      "examples/07_bound_operation.py",
    ),
    "source label missing",
  );
  for (const token of [
    'FromRequest("customer_id")',
    "AgentChoice()",
    "Required(customer_lookup, calls=Exactly(1))",
    "output=CustomerRecord",
  ])
    check(code.includes(token), `visible shipped example missing ${token}`);
  check(
    await page
      .locator(".boundary")
      .innerText()
      .then((t) => t.includes("No model") && t.includes("browser preview")),
    "browser-only boundary is unclear",
  );
  const run = () =>
    page.locator("#customer-form").evaluate((form) => form.requestSubmit());
  const waitRunning = () =>
    page.waitForFunction(
      () =>
        document.querySelector("#trace-result")?.textContent ===
        "Operation result · running",
    );
  const waitDone = () =>
    page.waitForFunction(
      () =>
        document.querySelectorAll("[data-step].active").length === 4 &&
        document.querySelector("#customer-name")?.textContent !== "—",
    );
  const shot = (name) =>
    page.screenshot({
      path: resolve(tmpdir(), `summonpot-playground-${name}.png`),
      fullPage: true,
    });
  await shot("1280-light");

  await run();
  await waitRunning();
  await page.locator("#reset").click();
  check(await cleared(page), "reset did not immediately cancel and clear run");
  await page.waitForTimeout(1050);
  check(await cleared(page), "cancelled timers changed reset state");

  await run();
  await waitDone();
  check(
    (await page.locator("#customer-name").textContent()) === "Ada" &&
      (await page.locator("#customer-status").textContent()) === "active",
    "customer-7 result did not reflect local operation record",
  );
  check(
    (await page.locator("#trace-input").textContent()) ===
      "FromRequest · customer_id=customer-7" &&
      (await page.locator("#trace-choice").textContent()).includes(
        "AgentChoice · summary",
      ) &&
      (await page.locator("#trace-result").textContent()).includes(
        "customer-7 / Ada / active / summary",
      ),
    "request/choice/operation trace incorrect",
  );
  check((await page.locator("#bound-customer-id").textContent()) === "customer-7", "the operation result must visibly preserve the request-owned ID");
  await page.locator("#try-override").click();
  check(
    (await page.locator("#rejection").textContent()).includes("FromRequest") &&
      (await page.locator('[name="customer_id"]').inputValue()) ===
        "customer-7",
    "operation override was not rejected without changing request-owned ID",
  );
  await page.locator('[name="customer_id"]').fill("customer-9");
  check(await cleared(page), "editing request did not clear stale completion");
  await run();
  await waitDone();
  check(
    (await page.locator("#customer-name").textContent()) === "Grace" &&
      (await page.locator("#customer-status").textContent()) === "paused",
    "customer-9 result did not change with request",
  );
  await page.locator('[name="format"]').selectOption("detailed");
  await run();
  await waitDone();
  check((await page.locator("#bound-customer-id").textContent()) === "customer-9", "a different allowed format must preserve the changed request-owned ID");
  check(
    (await page.locator("#trace-choice").textContent()).includes(
      "AgentChoice · detailed",
    ),
    "bounded choice change absent from trace",
  );

  // Submit a rapid second request during the first operation; only the newer request may complete.
  await page.locator('[name="customer_id"]').fill("customer-7");
  await run();
  await waitRunning();
  await page.locator('[name="customer_id"]').fill("customer-9");
  await run();
  await waitDone();
  check(
    (await page.locator("#customer-name").textContent()) === "Grace" &&
      (await page.locator("#trace-input").textContent()).endsWith("customer-9"),
    "stale operation overwrote rapid second request",
  );

  for (const value of ["customer-8", ""]) {
    await page.locator('[name="customer_id"]').fill(value);
    await run();
    check(
      (await page.locator("#rejection").textContent()).includes("Rejected:") &&
        (await page.locator("#result-title").textContent()) ===
          "Ready to run" &&
        (await page.locator("[data-step].active").count()) === 0,
      `invalid request ID ${JSON.stringify(value)} was not rejected before execution`,
    );
    await page.locator("#reset").click();
  }
  await page.locator('[name="customer_id"]').fill("customer-7");
  await page.locator('[name="format"]').evaluate((el) => {
    const o = document.createElement("option");
    o.value = "unsupported";
    o.textContent = "Unsupported";
    el.append(o);
    el.value = "unsupported";
  });
  await run();
  check(
    (await page.locator("#rejection").textContent()).includes(
      "AgentChoice values",
    ) && (await page.locator("[data-step].active").count()) === 0,
    "unsupported choice not rejected before operation",
  );
  await page.locator("#reset").click();

  await page.setViewportSize({ width: 768, height: 900 });
  check(
    await page.locator("body").evaluate((el) => el.scrollWidth <= innerWidth),
    "768px layout overflows horizontally",
  );
  await shot("768-light");
  await page.setViewportSize({ width: 320, height: 390 });
  check(
    await page.locator("body").evaluate((el) => el.scrollWidth <= innerWidth),
    "320px layout overflows horizontally",
  );
  await shot("320-light");
  const readContrast = () =>
    page.evaluate(() => {
      const rgb = (s) => {
        const x = s.trim();
        if (x.startsWith("#")) {
          const h = x.slice(1);
          return h.length === 3
            ? [...h].map((c) => parseInt(c + c, 16))
            : [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
        }
        const m = x.match(/[\d.]+/g).map(Number);
        return m.slice(0, 3);
      };
      const lum = (s) =>
        rgb(s)
          .map((v) => {
            v /= 255;
            return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
          })
          .reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0);
      const ratio = (a, b) => {
        const x = lum(a),
          y = lum(b);
        return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
      };
      const root = getComputedStyle(document.documentElement),
        bg = root.getPropertyValue("--bg").trim(),
        codeBg = getComputedStyle(document.querySelector(".primary-code pre")).backgroundColor;
      const button = getComputedStyle(
        document.querySelector('button[type="submit"]'),
      );
      return {
        body: ratio(root.getPropertyValue("--ink"), bg),
        muted: ratio(root.getPropertyValue("--muted"), bg),
        accent: ratio(root.getPropertyValue("--accent"), bg),
        button: ratio(button.color, button.backgroundColor),
        codeTokens: [
          ...document.querySelectorAll(
            ".primary-code span[style]",
          ),
        ].map((e) => ratio(getComputedStyle(e).color, codeBg)),
      };
    });
  const lightContrast = await readContrast();
  await page.emulateMedia({ colorScheme: "dark" });
  await shot("320-dark");
  check(
    await page.locator("body").evaluate((el) => el.scrollWidth <= innerWidth),
    "320px dark layout overflows horizontally",
  );
  await page.setViewportSize({ width: 768, height: 900 });
  check(
    await page.locator("body").evaluate((el) => el.scrollWidth <= innerWidth),
    "768px dark layout overflows horizontally",
  );
  await shot("768-dark");
  await page.setViewportSize({ width: 1280, height: 900 });
  check(
    await page.locator("body").evaluate((el) => el.scrollWidth <= innerWidth),
    "1280px dark layout overflows horizontally",
  );
  await shot("1280-dark");
  const darkContrast = await readContrast();
  for (const [theme, c] of [
    ["light", lightContrast],
    ["dark", darkContrast],
  ])
    check(
      c.body >= 4.5 &&
        c.muted >= 4.5 &&
        c.accent >= 4.5 &&
        c.button >= 4.5 &&
        c.codeTokens.length > 0 && c.codeTokens.every((x) => x >= 4.5),
      `${theme} text contrast below WCAG AA: ${JSON.stringify(c)}`,
    );
  await page.locator('[name="customer_id"]').fill("customer-8");
  await run();
  check(
    (await page.locator("#rejection").textContent()).includes("Rejected:"),
    "invalid ID feedback absent in dark scheme",
  );
  check(
    browserErrors.length === 0,
    `browser errors: ${browserErrors.join("; ")}`,
  );
  console.log(
    JSON.stringify(
      {
        url,
        checks,
        contrast: { light: lightContrast, dark: darkContrast },
        screenshots: [
          "1280-light",
          "768-light",
          "320-light",
          "1280-dark",
          "768-dark",
          "320-dark",
        ].map((n) => resolve(tmpdir(), `summonpot-playground-${n}.png`)),
        browserErrors,
        failures,
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
  if (server) await new Promise((ok) => server.close(ok));
}
if (failures.length) process.exitCode = 1;
