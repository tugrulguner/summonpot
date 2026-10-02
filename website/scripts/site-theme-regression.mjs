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
  } catch {res.writeHead(404);res.end('Not found');}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const base=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true});
const failures=[];let checks=0;const cases=[];
const check=(ok,message)=>{checks++;if(!ok)failures.push(message)};
const out=process.env.SITE_THEME_EVIDENCE;
if(out)await mkdir(out,{recursive:true});
try {
 for(const route of ['/','/quick-start/','/architecture/','/capabilities/']) {
  for(const theme of ['light','dark']) {
   const page=await browser.newPage({viewport:{width:1280,height:900},colorScheme:theme==='light'?'dark':'light',reducedMotion:'reduce'});
   page.on('pageerror',e=>failures.push(`${route} ${theme}: ${e.message}`));
   const response=await page.goto(base+route,{waitUntil:'networkidle'});check(response.ok(),`${route}: HTTP ${response.status()}`);
   await page.locator('starlight-theme-select select').first().selectOption(theme);
   await page.evaluate(async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))});
   const inspect=async()=>page.evaluate(()=>{
    const channels=c=>c.match(/[\d.]+/g).slice(0,3).map(Number);
    const luminance=c=>{const [r,g,b]=channels(c).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4});return .2126*r+.7152*g+.0722*b};
    const background=n=>{while(n){const c=getComputedStyle(n).backgroundColor;if(!/rgba\([^)]*,\s*0(?:\.0+)?\)$/.test(c)&&c!=='transparent')return c;n=n.parentElement}throw new Error('No opaque background')};
    const elements=[...document.querySelectorAll('header .site-title, header starlight-theme-select select, header starlight-theme-select label, header button[data-open-modal], main p, main h1, main h2, main h3, main li, main a, .sidebar a, .expressive-code .code span[style]')];
    const colors=elements.filter(n=>n.getClientRects().length&&n.textContent.trim()).map(n=>{
      const s=getComputedStyle(n);const bg=background(n);const a=luminance(s.color),b=luminance(bg);
      return {selector:n.tagName,text:n.textContent.trim().slice(0,55),fg:s.color,bg,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
    });
    const frame=document.querySelector('iframe');
    return {theme:document.documentElement.dataset.theme,bg:getComputedStyle(document.body).backgroundColor,bgLuminance:luminance(getComputedStyle(document.body).backgroundColor),colors,document:document.documentElement.scrollWidth,body:document.body.scrollWidth,viewport:innerWidth,heroImage:document.querySelector('.hero img')?.getAttribute('src'),heroBackground:document.querySelector('.hero')&&getComputedStyle(document.querySelector('.hero')).backgroundImage,frameDark:frame?.contentWindow.matchMedia('(prefers-color-scheme: dark)').matches};
   });
   const state=await inspect();check(state.theme===theme,`${route}: theme control did not switch`);
   check(theme==='light'?state.bgLuminance>.8:state.bgLuminance<.06,`${route} ${theme}: page background contradicts selected theme (${state.bg})`);
   for(const c of state.colors)check(c.ratio>=4.5,`${route} ${theme}: ${c.text} contrast ${c.ratio.toFixed(2)} (${c.fg} on ${c.bg})`);
   check(state.document<=1280&&state.body<=1280,`${route} ${theme}: desktop overflow`);
   if(route==='/') {
    check(state.heroBackground==='none',`${theme}: obsolete green hero wash remains`);
    check(Boolean(state.heroImage),`${theme}: canonical artwork missing`);
    await page.locator('iframe').scrollIntoViewIfNeeded();
    await page.frameLocator('iframe').locator('h1').waitFor();
    const frameState = await page.locator('iframe').evaluate(frame => ({
      theme: frame.contentDocument.documentElement.dataset.theme,
      bg: frame.contentWindow.getComputedStyle(frame.contentDocument.body).backgroundColor,
    }));
    const frameChannels = frameState.bg.match(/[\d.]+/g).slice(0,3).map(Number);
    check(frameState.theme===theme && frameChannels.every(v => theme==='light'?v>230:v<40),`${theme}: embedded preview contradicts explicit site theme (${frameState.bg})`);
    const opposite = theme==='light'?'dark':'light';
    await page.locator('starlight-theme-select select').first().selectOption(opposite);
    await page.waitForFunction(value => document.querySelector('iframe').contentDocument.documentElement.dataset.theme===value, opposite);
    check(await page.locator('iframe').evaluate(frame => frame.contentDocument.documentElement.dataset.theme)===opposite,`${theme}: existing embed did not follow a theme switch`);
    await page.locator('starlight-theme-select select').first().selectOption(theme);
    await page.waitForFunction(value => document.querySelector('iframe').contentDocument.documentElement.dataset.theme===value, theme);
    await page.evaluate(() => scrollTo(0,0));
    if(out)await page.screenshot({path:`${out}/homepage-1280-${theme}.png`,fullPage:true});
    await page.setViewportSize({width:320,height:390});
    await page.evaluate(async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))});
    const mobile=await inspect();check(mobile.document<=320&&mobile.body<=320,`${theme}: mobile overflow`);
    if(out)await page.screenshot({path:`${out}/homepage-320-${theme}.png`,fullPage:true});
    await page.setViewportSize({width:1280,height:900});
    await page.locator('starlight-theme-select select').first().selectOption('auto');
    await page.waitForFunction(value => document.documentElement.dataset.theme===value, opposite);
    const automatic=await inspect();
    check(automatic.theme===opposite && (opposite==='light'?automatic.bgLuminance>.8:automatic.bgLuminance<.06),`${theme}: Auto did not resolve the system theme consistently`);
    await page.waitForFunction(value => document.querySelector('iframe').contentDocument.documentElement.dataset.theme===value, opposite);
    check(await page.locator('iframe').evaluate(frame=>frame.contentDocument.documentElement.dataset.theme)===opposite,`${theme}: embedded preview did not follow Auto`);
   }
   cases.push({route,theme,background:state.bg,minimumContrast:Math.min(...state.colors.map(c=>c.ratio))});
   await page.close();
  }
 }
}finally{await browser.close();await new Promise(r=>server.close(r));}
console.log(JSON.stringify({checks,cases,failures},null,2));
if(failures.length)process.exitCode=1;
