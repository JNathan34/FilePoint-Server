// Check the installed-window paint rules in an isolated Edge fixture. Display
// mode cannot be emulated through CDP, so activate only this media block here.
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'client.js'),'utf8');
const begin=source.indexOf('/* Installed FilePoint windows:');
const end=source.indexOf('/* Plexpoint sidebar refresh stability:',begin);
const css=source.slice(begin,end).match(/style.textContent = `([\s\S]*?)`;/)[1];
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  const page=await browser.newPage({viewport:{width:960,height:850},deviceScaleFactor:2});
  await page.setContent(`<style>
   #sidebar{position:fixed;top:110px;bottom:0;width:320px;transform:translateZ(0);will-change:left;backface-visibility:hidden;backdrop-filter:blur(16px);background:#111d2570}
   .sidebar-links{height:100%;display:flex;flex-direction:column}.sidebar-links-content{flex:1;min-height:0;overflow:auto}.tree-node{height:44px}
   ${css}</style><body class="plexpoint-explorer-layout"><div id="app"><nav id="sidebar"><div class="sidebar-links"><div>Navigation</div><div class="sidebar-links-content">${Array.from({length:40},(_,i)=>`<div class="tree-node">Folder ${i}</div>`).join('')}</div><div class="plexpoint-v63-sidebar-overlay-scrollbar"></div></div></nav></div></body>`);
  assert.notEqual(await page.locator('#sidebar').evaluate(el=>getComputedStyle(el).transform),'none','installed-only rule leaves normal browser untouched');
  await page.addStyleTag({content:css.replace('@media (display-mode: standalone), (display-mode: window-controls-overlay)','@media all')});
  for(const width of [1440,960,730,600,730,1440]){
   await page.setViewportSize({width,height:850});
   const paint=await page.locator('#sidebar').evaluate(el=>{const s=getComputedStyle(el);return{transform:s.transform,blur:s.backdropFilter,willChange:s.willChange,backface:s.backfaceVisibility,background:s.backgroundColor};});
   assert.deepEqual(paint,{transform:'none',blur:'none',willChange:'auto',backface:'visible',background:'rgb(17, 29, 37)'});
   await page.evaluate(()=>{
    document.documentElement.classList.add('plexpoint-transparent-effects');
    document.documentElement.style.setProperty('--plexpoint-v168-blur','blur(16px) saturate(1.45)');
   });
   const glass=await page.locator('#sidebar').evaluate(el=>{
    const s=getComputedStyle(el);return {transform:s.transform,blur:s.backdropFilter,background:s.backgroundColor,willChange:s.willChange};
   });
   assert.equal(glass.background,'rgba(8, 15, 21, 0.44)','enabled transparency stays translucent in installed windows');
   assert.match(glass.blur,/blur\(16px\)/,'wallpaper is blurred behind the sidebar');
   assert.equal(glass.transform,'none','glass does not restore the old forced 3D layer');
   assert.equal(glass.willChange,'auto');
   assert.equal(await page.locator('.sidebar-links-content').evaluate(el=>getComputedStyle(el).backdropFilter),'none','scrolling content has no second blur layer');
   await page.evaluate(()=>document.documentElement.classList.remove('plexpoint-transparent-effects'));
   const scroll=await page.locator('.sidebar-links-content').evaluate(el=>{el.scrollTop=300;const s=getComputedStyle(el);return{top:el.scrollTop,width:s.scrollbarWidth,gutter:s.scrollbarGutter,native:getComputedStyle(el,'::-webkit-scrollbar').display};});
   assert.equal(scroll.top,300,'native vertical scrolling works');
   assert.equal(scroll.width,'auto');assert.equal(scroll.native,'block');assert.equal(scroll.gutter,'stable');
   assert.equal(await page.locator('.plexpoint-v63-sidebar-overlay-scrollbar').evaluate(el=>getComputedStyle(el).display),'none');
  }
  console.log('PASS: Edge installed-mode paint rules at 2x display scale; transparency on/off, single glass surface, no forced 3D layer, functioning native scrollbar; normal browser unaffected. Standalone media block activated by fixture.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
