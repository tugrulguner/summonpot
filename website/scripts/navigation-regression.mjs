import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { resolve, extname, sep } from "node:path";
import { mkdir } from "node:fs/promises";

const evidence = process.env.NAVIGATION_EVIDENCE;
if (evidence) await mkdir(evidence, { recursive: true });
const root = resolve("dist");
const mime = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2" };
const server = createServer(async (request, response) => {
  try {
    const pathname = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
    const requested = resolve(root, `.${pathname}`);
    if (requested !== root && !requested.startsWith(`${root}${sep}`)) throw new Error("outside build");
    const file = pathname.endsWith("/") ? resolve(requested, "index.html") : requested;
    const body = await readFile(file);
    response.writeHead(200, { "content-type": mime[extname(file)] ?? "application/octet-stream" });
    response.end(body);
  } catch {
    try { response.writeHead(404, { "content-type": "text/html; charset=utf-8" }); response.end(await readFile(resolve(root, "404.html"))); }
    catch { response.writeHead(404); response.end("Not found"); }
  }
});
await new Promise((ok, fail) => { server.once("error", fail); server.listen(0, "127.0.0.1", ok); });
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true });
const failures = [];
let checks = 0;
const check = (ok, message) => { checks++; if (!ok) failures.push(message); };
const contrastRatio = locator => locator.evaluate(node => {
  const channels = value => {
    if (value.startsWith("color(srgb")) return value.match(/color\(srgb\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)/).slice(1, 4).map(channel => Number(channel) * 255);
    return value.match(/[-\d.]+/g).slice(0, 3).map(Number);
  };
  const luminance = value => channels(value).map(channel => { const normalized = channel / 255; return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4; }).reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
  let ancestor = node;
  let background = "transparent";
  while (ancestor) {
    background = getComputedStyle(ancestor).backgroundColor;
    if (background !== "transparent" && !/^rgba\([^)]*,\s*0(?:\.0+)?\)$/.test(background)) break;
    ancestor = ancestor.parentElement;
  }
  const foreground = getComputedStyle(node).color;
  const a = luminance(foreground), b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
});
const expected = [
  ["ModePot", "https://modepot.io/"],
  ["GitHub", "https://github.com/tugrulguner/summonpot"],
  ["Community", "https://discord.gg/u3AANZr6RG"],
  ["About Tugrul", "https://tugrul.modepot.io/"],
];
const routes = ["/", "/quick-start/", "/playground/", "/source/readme/", "/source/roadmap/", "/not-a-real-route/"];
try {
  for (const route of routes) for (const width of [1280, 768, 401, 400, 390, 320]) {
    const page = await browser.newPage({ viewport: { width, height: width === 320 ? 850 : 900 }, colorScheme: "dark", reducedMotion: "reduce" });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    const response = await page.goto(base + route, { waitUntil: "networkidle" });
    check(response?.status() === (route === "/not-a-real-route/" ? 404 : 200), `${route} ${width}: unexpected HTTP ${response?.status()}`);
    if (route === "/source/readme/" || route === "/source/roadmap/") {
      const filename = route.endsWith("readme/") ? "README.md" : "ROADMAP.md";
      const sourceLink = page.getByRole("link", { name: filename, exact: true });
      check((await page.locator("main h1").first().innerText()).trim().length > 0, `${route}: source document heading is not rendered`);
      check(await sourceLink.count() === 1 && new RegExp(`/blob/[0-9a-f]{40}/${filename}$`).test(await sourceLink.getAttribute("href") ?? ""), `${route}: source-revision attribution is missing or not commit-pinned`);
      const unpinned = await page.locator("main a").evaluateAll(links => links.map(link => link.getAttribute("href")).filter(href => href && !/^(?:https?:|mailto:|#|\/)/i.test(href)));
      check(unpinned.length === 0, `${route}: relative source links were not rewritten to repository URLs (${unpinned.join(", ")})`);
      if (filename === "README.md") {
        const image = page.locator('main img[src*="summonpot-lockup.png"]');
        check(await image.count() === 1 && new RegExp(`/raw/[0-9a-f]{40}/summonpot-lockup\\.png$`).test(await image.getAttribute("src") ?? ""), `${route}: relative README illustration is missing or not commit-pinned`);
      }
      if (filename === "ROADMAP.md") check(await page.locator("main").innerText().then(text => text.includes("planned work")), `${route}: roadmap planned-work disclaimer is missing`);
    }
    await page.evaluate(async () => { await document.fonts.ready; await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))); });
    if (route !== "/playground/") await page.locator("starlight-theme-select select").first().selectOption("light");
    const desktop = width >= 1024;
    const group = desktop ? ":is(header, .family-header) .family-links" : "#family-mobile-menu .family-mobile-resources";
    if (!desktop) {
      const button = page.locator(".family-menu-button");
      check(await button.count() === 1, `${route} ${width}: labelled Menu control missing`);
      if (await button.count()) {
        check(await button.evaluate(node => { const r=node.getBoundingClientRect(); return r.width >= 44 && r.height >= 44 && r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight; }), `${route} ${width}: Menu hit target is clipped or below 44px`);
        await button.focus(); await page.keyboard.press("Enter");
        check(await button.getAttribute("aria-expanded") === "true", `${route} ${width}: keyboard activation did not expand Menu`);
        for (const [label, href] of expected.slice(1)) {
          const link = page.locator(`${group} a`).filter({ hasText: new RegExp(`^${label}$`) });
          check(await link.count() === 1 && await link.getAttribute("href") === href, `${route} ${width}: Menu lacks top-level ${label} destination ${href}`);
          if (await link.count()) {
            check(await link.evaluate(node => { const r=node.getBoundingClientRect(); const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2); return r.top >= 0 && r.bottom <= innerHeight && r.width >= 44 && r.height >= 44 && Boolean(hit && node.contains(hit)); }), `${route} ${width}: ${label} is clipped, below the initial Menu viewport, or center-covered`);
            check(await contrastRatio(link) >= 4.5, `${route} ${width}: ${label} menu text falls below 4.5:1 contrast`);
          }
        }
        if (evidence && (route === "/" || route === "/playground/") && width !== 1280) await page.screenshot({ path: resolve(evidence, `${route === "/" ? "home" : "playground"}-${width}-menu.png`) });
        await page.keyboard.press("Escape");
        check(await button.getAttribute("aria-expanded") === "false" && await button.evaluate(node => document.activeElement === node), `${route} ${width}: Escape did not close Menu and restore focus`);
      }
    } else {
      const desktopHeaderOrder = await page.evaluate(() => {
        const navigation = document.querySelector('.family-links');
        const theme = document.querySelector('starlight-theme-select');
        return !theme || Boolean(navigation && navigation.compareDocumentPosition(theme) & Node.DOCUMENT_POSITION_FOLLOWING);
      });
      check(desktopHeaderOrder, `${route} ${width}: family navigation must precede theme control like the Intpot reference`);
      if (await page.locator('starlight-theme-select').count()) {
        const familyLinkStyle = await page.locator('.family-links a').first().evaluate(node => ({ fontSize: getComputedStyle(node).fontSize, fontWeight: getComputedStyle(node).fontWeight }));
        check(familyLinkStyle.fontSize === '16px' && familyLinkStyle.fontWeight === '400', `${route} ${width}: family link weight/size must match Intpot (16px/400), got ${familyLinkStyle.fontSize}/${familyLinkStyle.fontWeight}`);
      }
      const labels = await page.locator(`${group} a`).allTextContents();
      check(JSON.stringify(labels.map(x => x.trim())) === JSON.stringify(expected.map(([label]) => label)), `${route} ${width}: desktop resource order/labels are wrong (${labels.join(", ")})`);
      for (const [label, href] of expected) {
        const link = page.locator(`${group} a`).filter({ hasText: new RegExp(`^${label}$`) });
        check(await link.count() === 1 && await link.getAttribute("href") === href, `${route} ${width}: desktop ${label} destination is wrong`);
        if (await link.count()) {
          check(await link.evaluate(node => { const r=node.getBoundingClientRect(); const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2); return r.width >= 44 && r.height >= 44 && r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight && Boolean(hit && node.contains(hit)); }), `${route} ${width}: ${label} target is clipped or center-covered`);
          check(await contrastRatio(link) >= 4.5, `${route} ${width}: ${label} desktop text falls below 4.5:1 contrast`);
        }
      }
      if (evidence && (route === "/" || route === "/playground/")) await page.screenshot({ path: resolve(evidence, `${route === "/" ? "home" : "playground"}-1280.png`) });
    }
    if (route === "/") {
      const attribution = page.getByRole("link", { name: "Created by Tugrul Guner", exact: true });
      check(await attribution.count() === 1 && await attribution.getAttribute("href") === "https://tugrul.modepot.io/", `${width}: creator first-fold link/destination missing`);
      if (await attribution.count()) check(await attribution.evaluate(node => { const r=node.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }), `${width}: creator attribution is outside first fold`);
    }
    if (width < 1024) {
      const modepot = page.locator(".family-home-mobile");
      check(await modepot.count() === 1 && await modepot.isVisible() && await modepot.getAttribute("href") === "https://modepot.io/", `${route} ${width}: always-visible ModePot return missing`);
      if (await modepot.count()) check(await modepot.evaluate(node => { const r=node.getBoundingClientRect(); const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2); return r.width >= 44 && r.height >= 44 && r.left >= 0 && r.right <= innerWidth && Boolean(hit && node.contains(hit)); }), `${route} ${width}: ModePot target is below 44px or center-covered`);
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.body.scrollWidth <= innerWidth), `${route} ${width}: horizontal overflow`);
      const covered = await page.evaluate(() => [...document.querySelectorAll("header .family-home-mobile, header .family-menu-button, header starlight-theme-select select, .family-header>a")].filter(node => { const r=node.getBoundingClientRect(); if (!r.width || !r.height || getComputedStyle(node).display === "none") return false; const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2); return !hit || !node.contains(hit); }).map(node => node.textContent.trim() || node.tagName));
      check(covered.length === 0, `${route} ${width}: compact header controls covered (${covered.join(", ")})`);
    }
    check(errors.length === 0, `${route} ${width}: browser errors ${errors.join("; ")}`);
    await page.close();
  }
} finally { await browser.close(); await new Promise(ok => server.close(ok)); }
console.log(JSON.stringify({ checks, failures }, null, 2));
if (failures.length) process.exitCode = 1;
