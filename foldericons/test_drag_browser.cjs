// Run with Playwright on NODE_PATH. Isolated fixture; never moves real files.
const { chromium } = require('playwright');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const source = readFileSync(join(__dirname, 'client.js'), 'utf8').replace(/\r\n/g, '\n');
  const start = source.indexOf('  const FILE_MOVE_DRAG_MIME');
  const end = source.indexOf('  /*\n   * V117', start);
  assert(start > 0 && end > start);
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  try {
    const page = await browser.newPage({ viewport: { width: 900, height: 600 } });
    await page.setContent(`<style>
      body { background:#182630; color:#eef5fa; font:14px system-ui; padding:40px; }
      .listing-item { display:flex; align-items:center; width:700px; height:64px;
        padding:0 28px; margin:8px 0; color:inherit; background:#263b49;
        border:1px solid #435968; border-radius:7px; font:inherit; box-sizing:border-box; }
      .listing-item span { pointer-events:auto; }
      #blank { height:180px; }
      i { font-style:normal; }
    </style><div class="listing-view-root">
      <button class="listing-item" data-name="Example report.docx"><span>Example report.docx</span></button>
      <div class="listing-item" data-name="Archive" data-dir="true"><span>Archive</span></div>
      <div class="listing-item" data-name="Other.txt"><a href="#other">Other.txt</a><input aria-label="Rename" value="Other.txt"></div>
      <div id="blank"></div>
    </div>`);
    await page.addScriptTag({ content: `
      window.moves = []; window.clicks = 0; window.externalDrops = 0;
      window.uploadEvents = {dragenter:0,dragover:0,drop:0};
      // Register the uploader before the move controller, as in the real app.
      for (const type of Object.keys(window.uploadEvents)) {
        document.addEventListener(type, () => {
          window.uploadEvents[type]++;
          if (type === 'dragenter') document.body.classList.add('upload-screen-open');
        }, true);
      }
      document.body.classList.add('plexpoint-explorer-layout');
      document.querySelector('button.listing-item').addEventListener('click', () => window.clicks++);
      function isHomeDashboard() { return false; }
      window.currentSource = 'Drive';
      function currentRoute() { return { source:window.currentSource, path:'Test' }; }
      window.canModify = true;
      window.uploads = [];
      function listingView() { return { permissions:{ modify:window.canModify } }; }
      function openFileBrowserPrompt(name, props) {
        window.uploads.push({name, path:props.targetPath, source:props.targetSource,
          files:props.initialItems.map(item => ({name:item.file.name, path:item.relativePath}))});
        return true;
      }
      function listingItemFromRow(row) { return { source:'Drive', path:'/Test/' + row.dataset.name,
        name:row.dataset.name, isDir:row.dataset.dir === 'true' }; }
      function fileBrowserResourcePath(item) { return item.path; }
      function selectedItemsForPlexpointClipboard() { return []; }
      function joinCreatePath(path,name) { return path + '/' + name; }
      async function performFileBrowserMoveCopy(items,operation,options) { window.moves.push({items,operation,options}); }
      function requestSoftListingReload() {}
      async function refreshExplorerHistoryStatus() {}
      function showToast(message) { window.lastToast = message; }
      ${source.slice(start, end)}
      window.uploadDroppedFilesIntoFolder = uploadDroppedFilesIntoFolder;
      installFileMoveDragAndDrop();
      document.addEventListener('drop', () => window.externalDrops++);
    ` });

    const file = page.locator('[data-name="Example report.docx"]');
    await file.click();
    assert.equal(await page.evaluate(() => window.clicks), 1, 'normal row clicks work');
    const box = await file.boundingBox();
    await page.mouse.move(box.x + 160, box.y + 30);
    await page.mouse.down();
    await page.mouse.move(box.x + 180, box.y + 36, { steps: 8 });
    await page.mouse.move(540, 410, { steps: 10 });
    const preview = page.locator('#plexpoint-file-move-preview');
    await preview.waitFor({ state: 'visible' });
    assert.match(await preview.innerText(), /Moving Example report.docx/);
    const first = await preview.boundingBox();
    await page.mouse.move(610, 440, { steps: 8 });
    await page.waitForFunction(() => document.querySelector('#plexpoint-file-move-preview').getBoundingClientRect().x > 600);
    const second = await preview.boundingBox();
    assert(second.x > first.x, 'preview follows the mouse across blank space');
    const folder = page.locator('[data-name="Archive"]');
    const folderBox = await folder.boundingBox();
    await page.mouse.move(folderBox.x + 300, folderBox.y + 30, { steps: 10 });
    await page.waitForFunction(() => document.querySelector('[data-name="Archive"]').classList.contains('plexpoint-file-move-target'));
    // A continuing hover must not remove/readd the class and restart animation.
    await page.evaluate(() => {
      window.targetChanges = 0;
      new MutationObserver(records => { window.targetChanges += records.filter(r => r.attributeName === 'class').length; })
        .observe(document.querySelector('[data-name="Archive"]'), { attributes: true });
    });
    await page.mouse.move(folderBox.x + 320, folderBox.y + 32, { steps: 6 });
    assert.equal(await page.evaluate(() => window.targetChanges), 0);
    await page.screenshot({ path: join(__dirname, 'drag-browser-preview.png') });
    await page.mouse.up();
    await preview.waitFor({ state: 'hidden' });
    assert.deepEqual(await page.evaluate(() => window.moves), [{
      items:[{fromSource:'Drive',from:'/Test/Example report.docx',name:'Example report.docx',
        toSource:'Drive',to:'/Test/Archive/Example report.docx'}], operation:'move',options:{overwrite:false}
    }]);
    assert.equal(await page.evaluate(() => window.externalDrops), 0, 'internal drops do not reach upload handlers');
    await file.dragTo(page.locator('#blank'));
    assert.equal(await page.evaluate(() => window.moves.length), 1, 'invalid drop does not move anything');
    await preview.waitFor({state:'hidden'});
    await page.locator('[data-name="Other.txt"] a').dragTo(folder);
    assert.equal(await page.evaluate(() => window.moves.length), 2, 'filename links can start a row move');
    assert.equal(await page.evaluate(() => window.moves[1].items[0].from), '/Test/Other.txt');
    assert.deepEqual(await page.evaluate(() => window.uploadEvents), {dragenter:0,dragover:0,drop:0},
      'internal drag enter/over/drop never reach the uploader');
    assert.equal(await page.locator('body').evaluate(el => el.classList.contains('upload-screen-open')), false);
    await page.evaluate(() => {
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(new File(['test'], 'upload.txt', {type:'text/plain'}));
      for (const type of ['dragenter','dragover','drop']) {
        document.querySelector('#blank').dispatchEvent(new DragEvent(type, {bubbles:true,cancelable:true,dataTransfer}));
      }
    });
    assert.equal(await page.evaluate(() => window.externalDrops), 1, 'external upload drops are untouched');
    assert.deepEqual(await page.evaluate(() => window.uploadEvents), {dragenter:0,dragover:0,drop:1},
      'native drag overlay stays closed so folders remain targetable');
    await page.evaluate(() => {
      window.desktopDrag = new DataTransfer();
      desktopDrag.items.add(new File(['one'], 'one.txt'));
      desktopDrag.items.add(new File(['two'], 'two.txt'));
      const row = document.querySelector('[data-name="Archive"] span');
      for (const type of ['dragenter','dragover']) row.dispatchEvent(new DragEvent(type,
        {bubbles:true,cancelable:true,dataTransfer:desktopDrag}));
    });
    assert.equal(await folder.evaluate(el => el.classList.contains('plexpoint-file-move-target')), true);
    assert.match(await folder.getAttribute('data-plexpoint-file-move-label'), /upload into Archive/);
    await page.evaluate(() => { window.targetChanges = 0; });
    await page.evaluate(() => document.querySelector('[data-name="Archive"] span').dispatchEvent(
      new DragEvent('dragover', {bubbles:true,cancelable:true,dataTransfer:desktopDrag})));
    assert.equal(await page.evaluate(() => window.targetChanges), 0, 'external hover animation remains stable');
    await page.evaluate(() => document.querySelector('[data-name="Archive"] span').dispatchEvent(
      new DragEvent('drop', {bubbles:true,cancelable:true,dataTransfer:desktopDrag})));
    await page.waitForFunction(() => window.uploads.length === 1);
    assert.deepEqual(await page.evaluate(() => window.uploads[0]), {
      name:'upload',path:'/Test/Archive',source:'Drive',
      files:[{name:'one.txt',path:'one.txt'},{name:'two.txt',path:'two.txt'}]
    });
    assert.equal(await folder.evaluate(el => el.classList.contains('plexpoint-file-move-target')), false);
    assert.equal(await page.evaluate(() => window.externalDrops), 1, 'folder drop never also uploads to parent');
    await page.evaluate(() => {
      const row = document.querySelector('[data-name="Archive"]');
      row.dispatchEvent(new DragEvent('dragover', {bubbles:true,cancelable:true,dataTransfer:desktopDrag}));
      document.querySelector('#blank').dispatchEvent(new DragEvent('dragover',
        {bubbles:true,cancelable:true,dataTransfer:desktopDrag}));
    });
    assert.equal(await folder.evaluate(el => el.classList.contains('plexpoint-file-move-target')), false,
      'leaving the folder clears its highlight');
    await page.evaluate(() => {
      window.canModify = false;
      const row = document.querySelector('[data-name="Archive"]');
      for (const type of ['dragover','drop']) row.dispatchEvent(new DragEvent(type,
        {bubbles:true,cancelable:true,dataTransfer:desktopDrag}));
    });
    assert.equal(await page.evaluate(() => window.uploads.length), 1, 'read-only listing cannot use upload bridge');
    await page.evaluate(async () => {
      const fileEntry = (name) => ({name,isFile:true,file:resolve => resolve(new File(['nested'],name))});
      const directory = (name,batches) => ({name,isDirectory:true,createReader:() => ({
        readEntries:resolve => resolve(batches.shift() || [])
      })});
      const entry = directory('Desktop folder', [
        [fileEntry('first.txt')],
        [directory('Nested', [[fileEntry('second.txt')]])],
      ]);
      await window.uploadDroppedFilesIntoFolder({items:[
        {kind:'file',webkitGetAsEntry:() => entry,getAsFile:() => null}
      ]}, {source:'Drive',path:'/Test/Archive'});
    });
    assert.deepEqual(await page.evaluate(() => window.uploads[1].files), [
      {name:'first.txt',path:'Desktop folder/first.txt'},
      {name:'second.txt',path:'Desktop folder/Nested/second.txt'}
    ], 'directory drops preserve nested paths and drain every reader batch');
    const changedSourceError = await page.evaluate(async () => {
      window.currentSource = 'Other drive';
      try {
        await window.uploadDroppedFilesIntoFolder({files:[new File(['safe'],'safe.txt')]},
          {source:'Drive',path:'/Test/Archive'});
      } catch (error) { return error.message; }
    });
    assert.match(changedSourceError, /drive changed/);
    assert.equal(await page.evaluate(() => window.uploads.length), 2, 'navigation never redirects uploads to another drive');
    console.log('PASS: internal move mouse gestures; stable shared folder animation; multi-file desktop upload to child folder only; blank-area native upload; highlight cleanup; read-only guard; nested directory batches; drive-change guard; normal click.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
