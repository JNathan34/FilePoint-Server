const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'client.js'),'utf8');
const start=source.indexOf('Plexpoint Explorer V96 — DOM-DRIVEN');
function extract(name){const begin=source.indexOf(`  function ${name}(`,start);return source.slice(begin,source.indexOf('\n  function ',begin+1));}
const css=extract('installStyle').match(/style.textContent = `([\s\S]*?)`;/)[1].replaceAll('${NOTICE_ID}','plexpoint-v96-upload-notification');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  const page=await browser.newPage({viewport:{width:960,height:800}});
  const font=Buffer.from(await (await fetch('https://files.plexpoint.uk/public/static/fonts/material-symbols.woff2')).arrayBuffer()).toString('base64');
  await page.setContent(`<style>
   @font-face{font-family:Material Symbols;src:url('data:font/woff2;base64,${font}')}
   .material-symbols{font:normal 24px 'Material Symbols';font-feature-settings:'liga';}
   body{background:#142029;color:#eee;font:14px Arial} ${css}
  </style><div class="upload-list" hidden></div><aside id="plexpoint-v96-upload-notification" data-collapsed="false"><div class="pp-v96-header"><div class="pp-v96-heading">Upload needs attention · 2/4 files</div><button class="pp-v96-action">Open</button></div><div class="pp-upload-list"></div></aside>`);
  await page.addScriptTag({content:`
   const rowMemory=new WeakMap();
   ${['textNode','setText','createUploadCard','realRowButton','clickRealRowButton','updateRowControls','parseByteValue','rowProgress','rowName','summarizeRows','formatBytes','formatRemaining','updateSpeed','uploadQueueForRow','uploadRowInfo','updateUploadIcon','prepareUploadGroups','renderUploadCards'].map(extract).join('\n')}
   window.queue=[
    {id:1,name:'Coursework',type:'directory',path:'/Documents/Coursework/'},
    {id:2,name:'Past Examination Paper',type:'directory',path:'/Documents/Coursework/Past Examination Paper/'},
    {id:3,name:'Exemplar',type:'directory',path:'/Documents/Coursework/Exemplar/'},
    {id:4,name:'Solution',type:'directory',path:'/Documents/Coursework/Exemplar/Solution/'},
    {id:5,name:'Part A.pdf',path:'/Documents/Coursework/Past Examination Paper/Part A.pdf'},
    {id:6,name:'Part A.pdf',path:'/Documents/Coursework/Exemplar/Solution/Part A.pdf',status:'Conflict'},
    {id:7,name:'Part B - Activity 1.docx',path:'/Documents/Coursework/Exemplar/Part B - Activity 1.docx'},
    {id:8,name:'Presentation.pptx',path:'/Documents/Coursework/Presentation.pptx',status:'2 MB / 10 MB',active:true}
   ];
   const host=document.querySelector('.upload-list');window.calls=[];
   const instance={setupState:{files:queue}};
   for(const item of queue){
    const row=document.createElement('div');row.className='upload-item';
    row.__vueParentComponent=instance;row.__vnode={key:item.id};
    row.innerHTML='<i class="file-icon"></i><p class="file-name"></p><div class="status-label vue-simple-progress-text"></div>';
    row.querySelector('.file-name').textContent=item.name;
    row.querySelector('.file-icon').textContent=item.type==='directory'?'folder':'insert_drive_file';
    row.querySelector('.status-label').textContent=item.status||'Completed';
    for(const action of item.active?['Pause','Cancel']:item.status==='Conflict'?['Replace']:[]){const button=document.createElement('button');button.setAttribute('aria-label',action);button.onclick=()=>calls.push([item.id,action]);row.append(button);}
    host.append(row);
   }
   window.ui={cards:new Map(),list:document.querySelector('.pp-upload-list')};
   window.render=()=>renderUploadCards(summarizeRows([...host.children]),ui);window.render();
  `});
  assert.equal(await page.locator('.pp-upload-group').count(),4,'nested directory structure retained without duplicate directory cards');
  assert.equal(await page.locator('.pp-v96-card').count(),4,'only real files become cards');
  assert.equal(await page.locator('.pp-upload-group').first().locator(':scope > summary .pp-upload-folder-status').textContent(),'2/4 files · Needs attention');
  const duplicateCards=page.locator('.pp-v96-card').filter({has:page.locator('.pp-v96-name',{hasText:'Part A.pdf'})});
  assert.equal(await duplicateCards.count(),2,'same name in different folders stays separate');
  assert.equal(await page.locator('.pp-v96-icon').filter({hasText:'picture_as_pdf'}).count(),2);
  assert.equal(await page.locator('.pp-v96-icon img').count(),2,'Office artwork reused');
  assert.equal(await page.locator('.pp-upload-group[data-mode="error"]:not([open])').count(),0,'error folder ancestors automatically reveal affected file');
  await page.getByRole('button',{name:'Pause upload: Presentation.pptx'}).click();
  await page.getByRole('button',{name:'Cancel upload: Presentation.pptx'}).click();
  assert.deepEqual(await page.evaluate(()=>calls),[[8,'Pause'],[8,'Cancel']]);
  await page.evaluate(()=>{
   const group=[...ui.groups.values()].find(g=>g.label.textContent==='Exemplar');group.details.open=false;
   window.original=ui.cards.get(document.querySelectorAll('.upload-item')[7]).card;
   window.render();
   if(group.details.open)throw Error('user collapse was reset');
   if(original!==ui.cards.get(document.querySelectorAll('.upload-item')[7]).card)throw Error('progress rebuilt card');
   // Production fallback when Vue does not expose an element vnode key.
   for(const row of document.querySelectorAll('.upload-item')) delete row.__vnode;
   window.render();
   // The deployed production bundle exposes only component roots through its
   // mounted __vue__ mixin, not Vue devtools properties on ordinary DOM rows.
   for(const row of document.querySelectorAll('.upload-item')) delete row.__vueParentComponent;
   document.querySelector('.upload-list').__vue__={$:{subTree:{children:[{component:{setupState:{files:queue}}}]}}};
   window.render();
  });
  assert.equal(await page.locator('.pp-upload-group').count(),4,'row-index lookup resolves native queue metadata without vnode keys');
  for(const width of [960,390,320]){
   await page.setViewportSize({width,height:800});
   const metrics=await page.evaluate(()=>{const el=document.querySelector('aside'),box=el.getBoundingClientRect();return{left:box.left,right:box.right,width:el.clientWidth,scroll:el.scrollWidth};});
   assert(metrics.left>=0&&metrics.right<=width,`notification fits at ${width}`);
   assert(metrics.scroll<=metrics.width,`no horizontal overflow at ${width}`);
  }
  await page.setViewportSize({width:960,height:800});
  await page.evaluate(async()=>{for(const group of ui.groups.values())group.details.open=true;await document.fonts.ready;});
  await page.locator('aside').screenshot({path:path.join(__dirname,'upload-groups-preview.png')});
  await page.evaluate(()=>{
   const host=document.querySelector('.upload-list');host.children[5].remove();queue.splice(5,1);window.render();
  });
  assert.equal(await page.locator('.pp-v96-card').count(),3,'removed upload removed from nested group');
  assert.equal(await page.locator('.pp-upload-group[data-mode="error"]').count(),0,'group error clears when failed job removed');
  console.log('PASS: native queue paths, nested folders, duplicate filenames, folder/file icons, aggregate counts, error expansion, stable collapse/cards, correct controls, row-index fallback, removal and 320–960px layout.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
