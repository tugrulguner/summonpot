import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';

const root = resolve('dist');
const mime = { '.html':'text/html', '.css':'text/css', '.js':'text/javascript', '.png':'image/png', '.svg':'image/svg+xml', '.woff2':'font/woff2' };
const server = createServer(async (req,res) => {
  try {
    const pathname = decodeURIComponent(new URL(req.url,'http://localhost').pathname);
    const requested = resolve(root, `.${pathname}`);
    if (requested !== root && !requested.startsWith(`${root}${sep}`)) throw new Error('outside build');
    const file = pathname.endsWith('/') ? resolve(requested,'index.html') : requested;
    res.writeHead(200, {'content-type':mime[extname(file)] || 'application/octet-stream'});
    res.end(await readFile(file));
  } catch { res.writeHead(404); res.end('Not found'); }
});
await new Promise((ok,fail)=>{server.once('error',fail);server.listen(0,'127.0.0.1',ok);});
const browser = await chromium.launch({headless:true});
const failures=[]; let checks=0;
const check=(ok,message)=>{checks++;if(!ok)failures.push(message);};
const evidence=process.env.HOMEPAGE_EVIDENCE;
try {
 for (const theme of ['light','dark']) for (const width of [2560,1920,1440,1280,1024,820,769,768,401,390,320]) {
  const page=await browser.newPage({viewport:{width,height:850},colorScheme:theme==='light'?'dark':'light',reducedMotion:'reduce'});
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  const response=await page.goto(`http://127.0.0.1:${server.address().port}/`,{waitUntil:'networkidle'});
  check(response?.status()===200,`${width}/${theme}: homepage did not load`);
  await page.locator('starlight-theme-select select').selectOption(theme);
  await page.evaluate(async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));});
  const state=await page.evaluate(()=>{
   const box=s=>{const r=document.querySelector(s)?.getBoundingClientRect();return r&&{x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}};
   const links=[...document.querySelectorAll('.framework-actions a')].map(a=>({text:a.textContent.trim(),href:a.getAttribute('href'),cls:a.className,box:(()=>{const r=a.getBoundingClientRect();return {width:r.width,height:r.height,bottom:r.bottom}})()}));
   const main=document.querySelector('.main-frame')?.getBoundingClientRect();
   const markdown=document.querySelector('.sl-markdown-content')?.getBoundingClientRect();
   return {main:main&&{x:main.x,width:main.width,right:main.right},markdown:markdown&&{x:markdown.x,width:markdown.width,right:markdown.right},hero:box('.framework-hero'),copy:box('.framework-copy'),art:box('.framework-art'),image:box('.framework-art img'),actions:links,credit:box('.framework-copy .creator-attribution'),install:box('.installation-strip'),notice:box('.maturity-notice'),demo:box('.project-demo'),installCommand:document.querySelector('.installation-strip code')?.textContent,theme:document.documentElement.dataset.theme, overflow:document.documentElement.scrollWidth>innerWidth, h1:[...document.querySelectorAll('main h1')].filter(x=>x.getClientRects().length).map(x=>x.textContent.trim()), frames:document.querySelectorAll('iframe').length, body:getComputedStyle(document.body).backgroundColor};
  });
  check(state.theme===theme,`${width}: theme mismatch`);
  check(state.installCommand==='pip install "summonpot[serve,cli]"',`${width}/${theme}: install command must preserve ASCII shell quotes: ${state.installCommand}`);
  check(state.h1.length===1&&state.h1[0]==='APIs for the AI era, one simple contract.',`${width}: expected one canonical first-fold H1: ${state.h1.join('|')}`);
  check(state.hero&&state.copy&&state.art&&state.image,`${width}: hero geometry/art missing`);
  check(state.hero&&Math.abs(state.hero.x-(width-state.hero.width)/2)<=2,`${width}/${theme}: hero is not horizontally centered (${JSON.stringify(state.hero)})`);
  for(const [name,section] of [['hero',state.hero],['installation',state.install],['maturity',state.notice],['demo',state.demo]]) if(section) check(Math.abs(section.x-(width-section.width)/2)<=20,`${width}/${theme}: ${name} section is not centered with balanced page gutters (${JSON.stringify(section)})`);
  if(width>700) check(state.main&&state.markdown&&Math.abs(state.markdown.x-(width-state.markdown.width)/2)<=2,`${width}/${theme}: main content axis is off-center (${JSON.stringify({main:state.main,markdown:state.markdown})})`);
  if(width>608){check(state.art.x>state.copy.x,`${width}: art does not follow copy on desktop/tablet`);check(state.image.x>=state.art.x&&state.image.right<=state.art.right+1,`${width}: art escapes its bounded frame`);}
  else check(state.art.y>=state.copy.bottom-1,`${width}: mobile art does not follow copy`);
  check(state.actions.map(a=>a.text).join('|').startsWith('Quick start|Playground|GitHub'),`${width}: CTA order incorrect`);
  check(state.actions[0]?.href==='/quick-start/'&&state.actions[1]?.href==='/playground/'&&state.actions[2]?.href==='https://github.com/tugrulguner/summonpot',`${width}: CTA destinations incorrect`);
  check(state.actions.every(a=>a.box.height>=44),`${width}: action target below 44px`);
  check(state.credit?.y>=Math.max(...state.actions.map(a=>a.box.bottom)),`${width}: creator credit is not immediately after the actions`);
  check(state.install&&state.notice&&state.demo&&state.install.y>state.hero.y&&state.notice.y>state.install.y&&state.demo.y>state.notice.y,`${width}: installation/maturity/demo section order incorrect`);
  check(state.frames===0,`${width}: homepage must link to, not embed, the standalone playground (${state.frames} iframe(s))`);
  check(!state.overflow,`${width}: horizontal overflow`);
  check(errors.length===0,`${width}/${theme}: browser errors ${errors.join('; ')}`);
  if(evidence){const {mkdir}=await import('node:fs/promises');await mkdir(evidence,{recursive:true});await page.screenshot({path:resolve(evidence,`summonpot-${width}-${theme}.png`),fullPage:true});if(width===1280||width===390)await page.screenshot({path:resolve(evidence,`summonpot-${width}-${theme}-firstfold.png`)});}
  await page.close();
 }
} finally {await browser.close();await new Promise(ok=>server.close(ok));}
console.log(JSON.stringify({checks,failures},null,2));if(failures.length)process.exitCode=1;
