const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname,'client.js'),'utf8');
const start = source.indexOf('  let observedExplorerAddress = null;');
const end = source.indexOf('  function ensureExplorerNavigationBar()', start);
const sheets = [...source.matchAll(/style\.textContent\s*=\s*`([\s\S]*?)`;/g)]
  .map(match=>match[1]).filter(css=>!css.includes('${') && /plexpoint-explorer-(address|nav|search)/.test(css));
// V182's authority observer moves the phone stylesheet after legacy layers.
const mobile = sheets.findIndex(css=>css.includes('--plexpoint-mobile-header-row'));
const mobileSheet = sheets.splice(mobile,1)[0];
const styles = [...sheets,mobileSheet].join('\n');
(async()=>{
 const browser = await chromium.launch({headless:true,channel:'msedge'});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:800}});
  await page.setContent(`<style>
    @font-face {font-family:'Material Symbols';src:url('https://files.plexpoint.uk/public/static/fonts/material-symbols.woff2')}
    .material-symbols {font-family:'Material Symbols';font-weight:normal;font-style:normal;line-height:1;font-feature-settings:'liga';}
    body {margin:0;background:#1b242b;color:#edf3f7;font:14px Arial;--safe-area-top:0px;}
    ${styles}
  </style><body class="plexpoint-explorer-layout"><header class="flexbar"><div id="plexpoint-explorer-nav">
    <div class="plexpoint-explorer-nav-buttons"><button class="plexpoint-explorer-nav-button">←</button><button class="plexpoint-explorer-nav-button" data-explorer-nav-action="forward">→</button><button class="plexpoint-explorer-nav-button">↑</button><button class="plexpoint-explorer-nav-button">↻</button></div>
    <div id="plexpoint-explorer-address" tabindex="0"></div><form id="plexpoint-explorer-search"><input placeholder="Search this folder"></form>
  </div></header><main style="padding:160px 25px">Folder contents</main></body>`);
  await page.addScriptTag({content:`
    window.navigated=[];
    window.parts=['Documents','College','ICT LEVEL 3','U03 Using Social Media in a Business'].map((label,i)=>({label,href:'/folder/'+i}));
    function explorerAddressParts(){return window.parts;}
    function navigateExplorerHref(href){window.navigated.push(href);}
    ${source.slice(start,end)}
    window.renderAddress=()=>renderExplorerAddress(document.getElementById('plexpoint-explorer-address'));
    window.renderAddress();
  `});
  await page.evaluate(()=>document.fonts.ready);
  for(const width of [1440,1024,900,800,761,760,600,390,320,1440]) {
    await page.setViewportSize({width,height:800});
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const metrics=await page.evaluate(()=>{
      const bar=document.querySelector('#plexpoint-explorer-address'),last=bar.querySelector('.plexpoint-address-current');
      const box=bar.getBoundingClientRect(), current=last.getBoundingClientRect();
      return {width:bar.clientWidth,scroll:bar.scrollWidth,left:current.left,right:current.right,barLeft:box.left,barRight:box.right,height:bar.clientHeight,
        overflow:getComputedStyle(bar).overflowX,visible:getComputedStyle(last).display!=='none',pageWidth:document.documentElement.scrollWidth, children:[...bar.children].map(el=>({text:el.textContent,hidden:el.hidden,display:getComputedStyle(el).display,width:el.getBoundingClientRect().width,font:getComputedStyle(el).fontFamily}))};
    });
    assert(metrics.visible,`current folder visible at ${width}`);
    assert(metrics.scroll<=metrics.width+1,`no path scrollbar at ${width}: ${JSON.stringify(metrics)}`);
    assert(metrics.right<=metrics.barRight+1 && metrics.left>=metrics.barLeft,`current folder fits at ${width}`);
    assert(metrics.height<=42,`single row at ${width}`);
    assert(metrics.pageWidth<=width,`no page overflow at ${width}`);
  }
  await page.setViewportSize({width:800,height:600});
  const trigger=page.getByRole('button',{name:'Show parent folders'});
  await trigger.waitFor({state:'visible'});
  await trigger.click();
  await page.locator('#plexpoint-address-ancestors').waitFor({state:'visible'});
  assert(await page.locator('#plexpoint-address-ancestors button').count()>0);
  await page.screenshot({path:path.join(__dirname,'address-compact-preview.png')});
  await page.locator('#plexpoint-address-ancestors button').first().click();
  assert.equal(await page.evaluate(()=>window.navigated[0]),'/folder/0');
  await trigger.click(); await page.keyboard.press('Escape');
  await page.locator('#plexpoint-address-ancestors').waitFor({state:'hidden'});
  await trigger.click(); await page.locator('main').click();
  await page.locator('#plexpoint-address-ancestors').waitFor({state:'hidden'});
  await page.evaluate(()=>{
    const bar=document.querySelector('#plexpoint-explorer-address');
    bar.classList.add('plexpoint-address-editing');bar.innerHTML='<input value="typed path">';window.renderAddress();
  });
  assert.equal(await page.locator('#plexpoint-explorer-address input').inputValue(),'typed path','refresh leaves address editing intact');
  console.log('PASS: path bar at 320–1440px; no scrollbar/overflow; current folder visible; ancestor navigation; Escape/outside dismissal; resize recovery; editing preserved.');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
