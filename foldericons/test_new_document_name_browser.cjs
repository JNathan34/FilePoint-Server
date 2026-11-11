// Real inline create/rename controllers with stubbed resource writes.
const { chromium } = require('playwright');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const assert = require('node:assert/strict');
(async () => {
  const source = readFileSync(join(__dirname, 'client.js'), 'utf8');
  const specs = Array.from(source.matchAll(/\{ label: "([^"]+)", kind: "([^"]+)", extension: "([^"]+)", defaultName: "([^"]+)" \}/g),
    ([,label,kind,extension,defaultName]) => ({label,kind,extension,defaultName}));
  assert.equal(specs.length,6,'test actual New menu document choices');
  const section = (from,to) => {
    const start=source.indexOf(from), end=source.indexOf(to,start);
    assert(start>0 && end>start); return source.slice(start,end);
  };
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try {
    const page=await browser.newPage();
    await page.setContent('<div class="listing-view-root"></div><button id="outside">Outside</button><div id="canvas" style="height:200px;background:#eee">Empty listing area</div>');
    await page.addScriptTag({content:`
      window.created=[]; window.renamed=[]; window.toasts=[];
      // Listing selection can cancel the default mouse focus change.
      window.selectionStarts=0;
      document.getElementById('canvas').addEventListener('mousedown',event=>{window.selectionStarts++;event.preventDefault();});
      const plexpointOfficeTemplates={docx:'',xlsx:'',pptx:''};
      function base64Bytes(){return new Uint8Array(0);}
      function closePlexpointNewSubmenu(){}
      function closeContextMenu(){}
      function contextMenuComponent(){return null;}
      function createTargetForContext(){return {source:'Drive',directory:'/Projects'};}
      function currentRoute(){return {source:'Drive',path:'/Projects'};}
      // This naming-only fixture has no native Vue selection store.
      function listingView(){return null;}
      function normalizeCreateDirectory(path){return path;}
      function joinCreatePath(path,name){return path+'/'+name;}
      function fileBrowserResourcePath(item){return item.path;}
      function showToast(message){window.toasts.push(message);}
      function createWindowsStyleFolder(){window.folderCalls=(window.folderCalls||0)+1;}
      async function createResourceBytes(source,path){
        if(window.createConflict){window.createConflict=false;throw Object.assign(new Error('conflict'),{status:409});}
        window.created.push({source,path});window.pendingName=path.split('/').pop();
      }
      function requestSoftListingReload(){
        if(!window.pendingName)return true;
        const name=window.pendingName;window.pendingName=null;
        setTimeout(()=>{
          const row=document.createElement('div');row.className='listing-item';
          row.dataset.name=name;row.dataset.dir='false';
          row.innerHTML='<div class="text"><div class="name"><span></span></div></div>';
          row.querySelector('span').textContent=name;
          document.querySelector('.listing-view-root').replaceChildren(row);
        },30);return true;
      }
      async function renamePropertiesItem(item,name){
        if(window.renameConflict){window.renameConflict=false;throw new Error('already exists');}
        window.renamed.push({path:item.path,name});item.name=name;
      }
      ${section('  function listingRowByExactName(', '  function beginWindowsInlineFolderRename(')}
      ${section('  function officeTemplateBytes(', '  function openPlexpointNewSubmenu(')}
      const specs=${JSON.stringify(specs)};
      window.startDocument=kind=>invokeContextCreate(null,'template-file',null,'',specs.find(spec=>spec.kind===kind));
    `});
    const input=page.locator('.plexpoint-inline-rename-input');
    await page.evaluate(()=>window.startDocument('docx'));
    await input.waitFor();
    await page.waitForFunction(()=>document.activeElement?.classList.contains('plexpoint-inline-rename-input'));
    await page.locator('#canvas').click();
    assert.equal(await input.count(),0,'clicking blank listing space must end naming even when native selection prevents blur');
    for(const {kind,defaultName} of specs){
      await page.evaluate(kind=>window.startDocument(kind),kind);
      await input.waitFor();
      await page.waitForFunction(()=>document.activeElement?.classList.contains('plexpoint-inline-rename-input'));
      assert.equal(await page.locator('.plexpoint-new-file-overlay').count(),0);
      assert.equal(await input.inputValue(),defaultName);
      assert.deepEqual(await input.evaluate(el=>[el.selectionStart,el.selectionEnd]),[0,defaultName.lastIndexOf('.')]);
      await input.click();
      assert.equal(await input.count(),1,'click inside the name keeps editing');
      const renamesBefore=await page.evaluate(()=>window.renamed.length);
      await page.locator('#canvas').click();
      assert.equal(await input.count(),0,'untouched name finishes on blank-area click');
      assert.equal(await page.locator('.name > span').innerText(),defaultName);
      assert.equal(await page.evaluate(()=>window.renamed.length),renamesBefore,'default needs no rename request');
      await page.evaluate(kind=>window.startDocument(kind),kind);
      await input.waitFor();
      await page.waitForFunction(()=>document.activeElement?.classList.contains('plexpoint-inline-rename-input'));
      await input.press('Q');
      assert.equal(await input.inputValue(),`Q.${kind}`);
      await input.press('Enter');await input.waitFor({state:'detached'});
      assert.equal(await page.locator('.name > span').innerText(),`Q.${kind}`);
    }
    await page.evaluate(()=>window.startDocument('docx'));await input.waitFor();
    await input.fill('Meeting notes');await page.locator('#canvas').click();
    await input.waitFor({state:'detached'});
    assert.equal(await page.locator('.name > span').innerText(),'Meeting notes.docx');
    assert.equal(await page.evaluate(()=>window.renamed.filter(item=>item.name==='Meeting notes.docx').length),1,'pointerdown/mousedown/blur must not duplicate saves');
    for(const blank of ['', '.docx']) {
      await page.evaluate(()=>window.startDocument('docx'));await input.waitFor();
      await input.fill(blank);await page.locator('#canvas').click();
      assert.equal(await input.count(),0);
      assert.equal(await page.locator('.name > span').innerText(),'Document.docx','empty basename keeps the default document name');
    }
    assert(await page.evaluate(()=>window.selectionStarts>=10),'normal listing selection still receives outside clicks');
    await page.evaluate(()=>{window.createConflict=true;window.startDocument('pptx');});
    await input.waitFor();assert.equal(await input.inputValue(),'Presentation (1).pptx');
    await input.press('Escape');
    assert.equal(await page.locator('.name > span').innerText(),'Presentation (1).pptx');
    await page.evaluate(()=>{window.renameConflict=true;window.startDocument('xlsx');});
    await input.waitFor();await input.fill('Taken');await input.press('Enter');
    await page.waitForFunction(()=>window.toasts.some(message=>message.includes('already exists')));
    assert.equal(await input.isEnabled(),true);
    await input.fill('Available');await input.press('Enter');await input.waitFor({state:'detached'});
    assert.equal(await page.locator('.name > span').innerText(),'Available.xlsx');
    await page.evaluate(()=>invokeContextCreate(null,'folder'));
    assert.equal(await page.evaluate(()=>window.folderCalls),1);
    console.log('PASS: six types name inline; Enter, blur, Escape, extensions and collisions; no popup.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
