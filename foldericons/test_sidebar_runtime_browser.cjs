const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const installed=process.env.FILEPOINT_TEST_INSTALLED==='1';
const source=fs.readFileSync(path.join(__dirname,'client.js'),'utf8')
 .replaceAll(installed ? '(display-mode: standalone), (display-mode: window-controls-overlay)' : '__unused_test_marker__','(min-width: 0px)');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:850}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
   const url=route.request().url();
   if(url.endsWith('/files/Home/'))return route.fulfill({contentType:'text/html',body:'<body class="plexpoint-explorer-layout"><div id="app"><header class="flexbar"></header><nav id="sidebar" class="active" style="width:320px;left:0"><div class="sidebar-links"><div class="sidebar-links-header">Navigation</div><div class="sidebar-links-content"><div class="file-tree file-tree-root"><div class="tree-list">'+['ZimaOS HDD','Documents','Downloads','Gallery','Media'].map(n=>`<div class="tree-item"><div class="tree-node has-children"><span class="expand-icon">chevron_right</span><span class="node-icon">folder</span><span class="node-name">${n}</span></div></div>`).join('')+'</div></div></div></div></nav><div id="main"><div class="listing-view-root"><div class="listing-items"></div></div></div></div></body>'});
   if(url.includes('/__foldericons/icons'))return route.fulfill({json:{icons:Object.fromEntries(['ZimaOS HDD','Documents','Downloads','Gallery','Media'].map(n=>[n,{material:'folder'}])),hidden:[],storage:{}}});
   if(url.includes('/__foldericons/'))return route.fulfill({json:{items:[],devices:[],preferences:{},accounts:[],sessions:[]}});
   if(url.includes('/api/users'))return route.fulfill({json:{username:'test',sidebarLinks:[],permissions:{},preview:{},scopes:[]}});
   return route.fulfill({json:{items:[]}});
  });
  await page.goto('http://filepoint.test/files/Home/');
  await page.addScriptTag({content:source});
  await page.waitForTimeout(1000);
  if(installed)assert.equal(await page.locator('.plexpoint-v63-sidebar-overlay-scrollbar').count(),0,'installed mode uses only the native scrollbar');
  await page.evaluate(()=>{
   window.mutations={};window.sidebarObserver=new MutationObserver(records=>{
    for(const record of records){const el=record.target;const key=(el.id||el.className||el.nodeName)+':'+(record.attributeName||record.type);mutations[key]=(mutations[key]||0)+1;}
   });sidebarObserver.observe(document.querySelector('#sidebar'),{attributes:true,childList:true,subtree:true,characterData:true});
  });
  for(const target of [730,960,1440,730]){
   // A snap produces several resize events, then the DOM must settle.
   for(const width of [target+40,target+12,target])await page.setViewportSize({width,height:850});
   await page.waitForTimeout(250);
   await page.evaluate(()=>{window.mutations={};});
   await page.waitForTimeout(1600); // crosses the icon hydrator's 1400ms timer
   const mutations=await page.evaluate(()=>window.mutations);
   assert.deepEqual(mutations,{},`idle sidebar must stop mutating after snapping to ${target}px`);
  }
  // Verify selection feedback can still update after removing the idle loop.
  await page.evaluate(()=>{
   const status=document.createElement('div');status.id='status-bar';status.innerHTML='<div class="status-info"><span class="button">1 item selected</span></div>';document.body.append(status);
  });
  await page.waitForTimeout(100);
  assert.equal(await page.locator('#plexpoint-sidebar-selection-status').getAttribute('hidden'),null);
  assert.match(await page.locator('.plexpoint-sidebar-selection-text').textContent(),/1 item selected/);
  await page.evaluate(()=>document.querySelector('#status-bar').remove());
  await page.waitForTimeout(100);
  assert.notEqual(await page.locator('#plexpoint-sidebar-selection-status').getAttribute('hidden'),null);
  await page.evaluate(()=>document.querySelector('#plexpoint-recycle-bin-link').classList.add('current-item'));
  await page.waitForTimeout(100);
  assert(await page.locator('#plexpoint-recycle-bin-link').evaluate(el=>el.classList.contains('current-item')),'enhancement preserves native selected-row classes');
  assert.deepEqual(errors,[],'full client runs without JavaScript errors');
  console.log('PASS: full client runtime settles to zero sidebar mutations after snap resize bursts at 730/960/1440px; icon polling stays idle; selection footer still updates.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
