import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
import { chromium } from 'playwright';
const root = resolve('dist');
const mime = {'.html':'text/html','.css':'text/css','.js':'text/javascript','.svg':'image/svg+xml','.png':'image/png','.woff2':'font/woff2'};
const server = createServer(async (req,res) => {
  try {
    const path = decodeURIComponent(new URL(req.url,'http://localhost').pathname);
    const file = resolve(root, `.${path}`, path.endsWith('/') ? 'index.html' : '');
    if (!file.startsWith(root+sep)) throw new Error('outside build');
    res.writeHead(200,{'content-type':mime[extname(file)]||'application/octet-stream'});res.end(await readFile(file));
  } catch {if (!res.headersSent) {res.writeHead(404);res.end('Not found');}}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const base=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true});
const failures=[];let checks=0;const cases=[];
const check=(ok,message)=>{checks++;if(!ok)failures.push(message)};
const out=process.env.SITE_THEME_EVIDENCE;
if(out)await mkdir(out,{recursive:true});
try {
 for(const route of ['/','/quick-start/','/architecture/','/capabilities/','/guides/operations/','/internals/execution/','/reference/operations/','/build/agent-choice/','/build/direct-execution/']) {
  for(const theme of ['light','dark']) {
   const page=await browser.newPage({viewport:{width:1280,height:900},colorScheme:theme==='light'?'dark':'light',reducedMotion:'reduce'});
   page.on('pageerror',e=>failures.push(`${route} ${theme}: ${e.message}`));
   const response=await page.goto(base+route,{waitUntil:'networkidle'});check(response.ok(),`${route}: HTTP ${response.status()}`);
   await page.locator('starlight-theme-select select').first().selectOption(theme);
   await page.evaluate(async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))});
   const inspect=async()=>page.evaluate((route)=>{
    const channels=c=>c.match(/[\d.]+/g).slice(0,3).map(Number);
    const luminance=c=>{const [r,g,b]=channels(c).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4});return .2126*r+.7152*g+.0722*b};
    const background=n=>{while(n){const c=getComputedStyle(n).backgroundColor;if(!/rgba\([^)]*,\s*0(?:\.0+)?\)$/.test(c)&&c!=='transparent')return c;n=n.parentElement}throw new Error('No opaque background')};
    const elements=[...document.querySelectorAll('header .site-title, header starlight-theme-select select, header starlight-theme-select label, header button[data-open-modal], main p, main h1, main h2, main h3, main li, main a, .sidebar a, .expressive-code .code span[style]')];
    const colors=elements.filter(n=>n.getClientRects().length&&n.textContent.trim()).map(n=>{
      const s=getComputedStyle(n);const bg=background(n);const a=luminance(s.color),b=luminance(bg);
      return {selector:n.tagName,text:n.textContent.trim().slice(0,55),fg:s.color,bg,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
    });

    const primaryLink=document.querySelector('.framework-action.primary');
    const heading=route==='/'?document.querySelector('.framework-hero h1'):document.querySelector('.content-panel h1'),sidebar=document.querySelector('.sidebar-pane');
    return {theme:document.documentElement.dataset.theme,bg:getComputedStyle(document.body).backgroundColor,bgLuminance:luminance(getComputedStyle(document.body).backgroundColor),font:getComputedStyle(document.body).fontFamily,headerHeight:getComputedStyle(document.querySelector('header.header')).height,primaryRadius:primaryLink&&getComputedStyle(primaryLink).borderRadius,homepageFrames:document.querySelectorAll('iframe').length,playgroundLink:[...document.querySelectorAll('main a')].some(a=>a.getAttribute('href')==='/playground/'),modePot:[...document.querySelectorAll('header.header a')].some(a=>a.textContent.trim()==='ModePot'&&a.getAttribute('href')==='https://modepot.io/'),headingLeft:heading?.getBoundingClientRect().left,sidebarRight:sidebar?.getBoundingClientRect().right,colors,document:document.documentElement.scrollWidth,body:document.body.scrollWidth,viewport:innerWidth,heroImage:document.querySelector('.framework-art img')?.getAttribute('src'),heroBackground:document.querySelector('.framework-hero')&&getComputedStyle(document.querySelector('.framework-hero')).backgroundImage};
   },route);
   const state=await inspect();check(state.theme===theme,`${route}: theme control did not switch`);check(state.modePot,`${route} ${theme}: visible ModePot return link missing from the header`);
   if(route==='/') {
    check(theme==='light'?state.bg==='rgb(248, 247, 244)':state.bg==='rgb(22, 24, 27)',`${theme}: rendered canvas is not the shared family canvas (${state.bg})`);
    check(state.font.startsWith('"Avenir Next", Avenir, "Segoe UI", sans-serif'),`${theme}: rendered body font does not resolve to the shared family stack (${state.font})`);
    check(state.headerHeight==='64px',`${theme}: rendered header is not 64px (${state.headerHeight})`);
    check(state.primaryRadius==='6px',`${theme}: rendered primary CTA is not 6px (${state.primaryRadius})`);
    check(state.modePot,`${theme}: visible ModePot return link missing from the header`);
   }
   check(theme==='light'?state.bgLuminance>.8:state.bgLuminance<.06,`${route} ${theme}: page background contradicts selected theme (${state.bg})`);
   for(const c of state.colors)check(c.ratio>=4.5,`${route} ${theme}: ${c.text} contrast ${c.ratio.toFixed(2)} (${c.fg} on ${c.bg})`);
   check(state.document<=1280&&state.body<=1280,`${route} ${theme}: desktop overflow`);
   if(route!=='/')check(state.headingLeft>=state.sidebarRight-1,`${route} ${theme}: documentation heading is obscured by the fixed sidebar (${state.headingLeft} < ${state.sidebarRight})`);
   if(route==='/') {
    check(state.heroBackground==='none',`${theme}: obsolete green hero wash remains`);
    check(Boolean(state.heroImage),`${theme}: canonical artwork missing`);
    check(state.homepageFrames===0,`${theme}: homepage must link to the standalone playground, not embed it`);
    check(state.playgroundLink,`${theme}: homepage playground action missing`);
    await page.evaluate(() => scrollTo(0,0));
    if(out)await page.screenshot({path:`${out}/homepage-1280-${theme}.png`,fullPage:true});
    await page.setViewportSize({width:320,height:390});
    await page.evaluate(async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))});
    const mobile=await inspect();check(mobile.document<=320&&mobile.body<=320,`${theme}: mobile overflow`);
    if(out)await page.screenshot({path:`${out}/homepage-320-${theme}.png`,fullPage:true});
    await page.setViewportSize({width:1280,height:900});
    const opposite = theme==='light'?'dark':'light';
    await page.locator('starlight-theme-select select').first().selectOption('auto');
    await page.waitForFunction(value => document.documentElement.dataset.theme===value, opposite);
    const automatic=await inspect();
    check(automatic.theme===opposite && (opposite==='light'?automatic.bgLuminance>.8:automatic.bgLuminance<.06),`${theme}: Auto did not resolve the system theme consistently`);

   }
   cases.push({route,theme,background:state.bg,minimumContrast:Math.min(...state.colors.map(c=>c.ratio))});
   if(out && route!=='/') { await page.evaluate(() => scrollTo(0,0)); await page.screenshot({path:`${out}/docs-${route.replaceAll('/','-')}-${theme}.png`,fullPage:true}); }
   await page.close();
  }
 }
 for (const route of ['/', '/quick-start/', '/guides/operations/', '/build/agent-choice/']) for (const theme of ['light', 'dark']) for (const width of [320,390,400,401]) {
  const page = await browser.newPage({ viewport: { width, height: 768 }, colorScheme: theme === 'light' ? 'dark' : 'light', reducedMotion: 'reduce' });
  await page.goto(base + route, { waitUntil: 'networkidle' });
  await page.locator('starlight-theme-select select').first().selectOption(theme);
  await page.evaluate(async () => { await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); });
  const identity = await page.locator('header .site-title').evaluate(n => ({ width: n.getBoundingClientRect().width, client: n.clientWidth, content: n.scrollWidth, text: n.textContent.trim() }));
  check(identity.width >= 90 && identity.content <= identity.client + 1 && identity.text === 'Summonpot', `${route} ${theme} ${width}: narrow header clips product identity (${JSON.stringify(identity)})`);
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.body.scrollWidth <= innerWidth), `${route} ${theme} ${width}: narrow header causes overflow`);
  const covered = await page.evaluate(() => [...document.querySelectorAll('header .family-return, header button[data-open-modal], header starlight-theme-select select')].filter(n => { const r = n.getBoundingClientRect(); const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return !r.width || !r.height || !hit || !n.contains(hit); }).map(n => n.tagName + ':' + (n.textContent?.trim() || n.getAttribute('aria-label'))));
  check(covered.length === 0, `${route} ${theme} ${width}: narrow header controls are covered (${covered.join(', ')})`);
  if (out && width===320) await page.screenshot({ path: resolve(out, `${route === '/' ? 'home' : route.replaceAll('/','-')}-320-${theme}.png`) });
  if (out && route==='/guides/operations/' && width!==320) await page.screenshot({path:resolve(out, `guides-operations-${width}-${theme}.png`)});
  await page.close();
 }
}finally{await browser.close();await new Promise(r=>server.close(r));}
console.log(JSON.stringify({checks,cases,failures},null,2));
if(failures.length)process.exitCode=1;
