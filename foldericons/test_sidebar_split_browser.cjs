// Exercise responsive CSS against the deployed FileBrowser sidebar rules.
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, 'client.js'), 'utf8');
const sheets = [...source.matchAll(/style\.textContent\s*=\s*`([\s\S]*?)`;/g)]
  .map(match => match[1]).filter(css => !css.includes('${'));
const mobileIndex = sheets.findIndex(css => css.includes('--plexpoint-mobile-header-row'));
const mobile = sheets.splice(mobileIndex, 1)[0];
// Recycle Bin uses its own style variable rather than the generic style sheets.
const recycle = source.match(/recycleStyle\.textContent\s*=\s*`([\s\S]*?)`;/)[1];
sheets.push(recycle);
(async () => {
  const native = await (await fetch('https://files.plexpoint.uk/public/static/assets/index-CWvpHkA4.css')).text();
  const browser = await chromium.launch({headless:true, channel:'msedge'});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:800}});
    await page.setContent(`<style>:root{--plexpoint-explorer-content-top:111px;--safe-area-top:0px;--safe-area-bottom:0px}${native}\n${sheets.join('\n')}\n${mobile}</style>
      <body class="plexpoint-explorer-layout"><div id="app">
      <nav id="sidebar" class="active" style="width:20em;left:0">
      <div class="sidebar-links"><div class="sidebar-links-header">Navigation</div>
      <div class="sidebar-links-content"><div class="file-tree-root"><div class="tree-list">
      <div class="tree-item"><div class="tree-node"><span class="node-name">Documents</span></div>
      <div class="file-tree"><div class="tree-list"><div class="tree-item"><div class="tree-node">College</div></div></div></div>
      </div></div></div></div></div></nav></div></body>`);
    const sidebar = page.locator('#sidebar');
    // This fails before the fix: native transition: .4s ease animates every
    // geometry/paint change as a snapped window or native sidebar width changes.
    assert.equal(await sidebar.evaluate(el => getComputedStyle(el).transitionDuration), '0s',
      'desktop sidebar geometry must not animate behind window resizing');
    for (const width of [1440,960,800,769,768,765,761,760,600,390,768,769,960,1440]) {
      await page.setViewportSize({width,height:800});
      const state = await sidebar.evaluate(el => {
        const css = getComputedStyle(el);
        return {mobileShell:css.getPropertyValue('--plexpoint-mobile-header-row').trim(),
          transition:css.transitionDuration, left:el.getBoundingClientRect().left,
          width:el.getBoundingClientRect().width, animations:el.getAnimations().length};
      });
      assert.equal(Boolean(state.mobileShell), width <= 768, `custom shell agrees with native mobile state at ${width}`);
      assert.equal(state.transition, '0s', `no sidebar transition at ${width}`);
      assert.equal(state.left, 0, `open sidebar stays anchored at ${width}`);
      assert.equal(state.animations, 0, `no stale resize animation at ${width}`);
      if (width <= 768) assert(state.width <= 320, `mobile drawer fits at ${width}`);
      await sidebar.evaluate(el => { el.classList.remove('active'); el.style.left='-20em'; });
      assert((await sidebar.boundingBox()).x <= -300, `closed sidebar immediately leaves screen at ${width}`);
      await sidebar.evaluate(el => { el.classList.add('active'); el.style.left='0'; });
    }
    assert.equal(await page.locator('.file-tree .tree-node').textContent(), 'College', 'expanded navigation survives resizing');
    await page.evaluate(() => {
      const row=name=>`<div class="tree-node"><span class="expand-icon">⌄</span><span class="node-icon">▣</span><span class="node-name">${name}</span></div>`;
      let branch=`<div class="tree-item">${row('Exemplar')}</div>`;
      for(const name of ['Past Examination Paper','U03 Using Social Media in a Business','ICT LEVEL 3','College','Documents','ZimaOS HDD'].reverse())
        branch=`<div class="tree-item">${row(name)}<div class="file-tree"><div class="tree-list">${branch}</div></div></div>`;
      document.querySelector('#sidebar').innerHTML=`<div class="sidebar-links"><div class="sidebar-links-header"><button class="mode-toggle">Navigation</button></div><div class="sidebar-links-content"><div class="file-tree-container"><div class="file-tree file-tree-root"><div class="tree-list">${branch}${Array.from({length:25},(_,i)=>`<div class="tree-item">${row('Folder '+i)}</div>`).join('')}</div></div></div></div></div><div class="buffer"></div><div class="credits">FilePoint</div>`;
      document.querySelectorAll('.sidebar-links,.sidebar-links *').forEach(el=>el.setAttribute('data-v-97ca25da',''));
      document.querySelectorAll('.file-tree,.file-tree *').forEach(el=>el.setAttribute('data-v-ffa0a7d3',''));
    });
    for(const width of [730,768,769,1440,960,600,390,730,960]){
      await page.setViewportSize({width,height:850});
      await page.locator('.node-name').filter({hasText:'Exemplar'}).evaluate(el=>el.scrollIntoView({block:'nearest'}));
      const metrics=await page.evaluate(()=>{
        const sidebar=document.querySelector('#sidebar'),scroller=sidebar.querySelector('.sidebar-links-content');
        return {sidebarHeight:sidebar.clientHeight,height:scroller.clientHeight,width:scroller.clientWidth,scrollWidth:scroller.scrollWidth,left:scroller.scrollLeft};
      });
      assert(metrics.height>metrics.sidebarHeight*.65,`tree fills sidebar after snap at ${width}: ${JSON.stringify(metrics)}`);
      assert(metrics.scrollWidth<=metrics.width+1,`deep tree has no horizontal scroll after snap at ${width}: ${JSON.stringify(metrics)}`);
      assert.equal(metrics.left,0,`selected folder does not push tree sideways at ${width}`);
      const guides=await page.locator('#sidebar .tree-list .tree-list').evaluateAll(branches=>branches.map(el=>{
        const css=getComputedStyle(el);return {border:css.borderLeftWidth,indent:css.marginLeft};
      }));
      assert(guides.length>=6,'fixture contains multiple expanded levels');
      for(const guide of guides){
        assert.equal(guide.border,'0px',`no dotted tree guides at ${width}px`);
        assert.equal(guide.indent,'12px',`expanded folder indentation stays intact at ${width}px`);
      }
    }
    await page.setViewportSize({width:730,height:850});
    await page.evaluate(()=>{
      document.documentElement.classList.add('plexpoint-transparent-effects');
      document.documentElement.style.setProperty('--plexpoint-v168-blur','blur(16px) saturate(1.45)');
      const content=document.querySelector('.sidebar-links-content');
      content.insertAdjacentHTML('afterbegin','<div class="source-card-container"><button class="plexpoint-v35-source-selector-button">Home</button></div>');
      content.insertAdjacentHTML('beforeend','<button id="plexpoint-recycle-bin-link"><span class="plexpoint-recycle-expand-placeholder"></span><span class="plexpoint-recycle-node-icon">♲</span><span class="node-name">Recycle Bin</span></button>');
      document.querySelectorAll('.tree-node').forEach(el=>el.querySelector('.node-icon')?.classList.add('plexpoint-v65-sidebar-icon'));
    });
    for(const width of [320,481,730]){
      await page.setViewportSize({width,height:850});
      const geometry=await page.evaluate(()=>{
        const side=document.querySelector('#sidebar'),content=side.querySelector('.sidebar-links-content');
        const first=side.querySelector('.tree-node'),recycle=side.querySelector('#plexpoint-recycle-bin-link');
        return {inset:content.getBoundingClientRect().left-side.getBoundingClientRect().left,
          row:first.getBoundingClientRect().height,bin:recycle.getBoundingClientRect().height,
          label:first.querySelector('.node-name').getBoundingClientRect().left,
          binLabel:recycle.querySelector('.node-name').getBoundingClientRect().left,
          source:side.querySelector('.plexpoint-v35-source-selector-button').getBoundingClientRect().height,
          blur:getComputedStyle(side).backdropFilter,background:getComputedStyle(side).backgroundColor};
      });
      const compact=width>=600;
      assert.equal(geometry.inset,compact?8:12,`one sidebar inset at ${width}`);
      assert.equal(geometry.row,compact?32:44);assert.equal(geometry.bin,compact?32:44);assert.equal(geometry.source,compact?34:44);
      assert(Math.abs(geometry.label-geometry.binLabel)<1,`Recycle Bin label aligns with folders at ${width}: ${JSON.stringify(geometry)}`);
      assert.equal(geometry.background,'rgba(8, 15, 21, 0.44)');assert.match(geometry.blur,/blur\(16px\)/);
    }
    await page.evaluate(()=>document.querySelector('#app').insertAdjacentHTML('beforeend',
      '<main id="main"><div class="listing-view-root"><div class="listing-items"><div class="file-items"><div class="listing-item"><div><div class="image-preview"><i>folder</i></div></div><div class="text"><span class="name">Project file</span><span class="modified">2 weeks ago</span><span class="size">4 KB</span></div></div></div></div></div></main>'));
    for(const width of [600,720,768,720]){
      await page.setViewportSize({width,height:850});
      const measure=()=>page.evaluate(()=>{
        const side=document.querySelector('#sidebar').getBoundingClientRect(),main=document.querySelector('#main').getBoundingClientRect();
        const row=document.querySelector('#main .listing-item').getBoundingClientRect();
        return {sideRight:side.right,mainLeft:main.left,mainRight:main.right,rowLeft:row.left,rowRight:row.right,rowHeight:row.height,
          shell:getComputedStyle(document.documentElement).getPropertyValue('--plexpoint-mobile-header-row').trim()};
      });
      const open=await measure();
      assert.equal(open.mainLeft,open.sideRight,`file pane starts beside open sidebar at ${width}`);
      assert(open.rowLeft>=open.sideRight,`file rows never extend behind sidebar at ${width}`);
      assert(open.rowRight<=width&&open.mainRight<=width,`file pane fits remaining width at ${width}`);
      assert(open.rowHeight<=56,`compact file rows at ${width}: ${JSON.stringify(open)}`);
      assert.equal(open.shell,'44px');
      await sidebar.evaluate(el=>{el.classList.remove('active');el.style.left='-20em';});
      assert.equal((await measure()).mainLeft,0,'closing sidebar returns full file pane width');
      await sidebar.evaluate(el=>{el.classList.add('active');el.style.left='0';});
    }
    await page.setViewportSize({width:730,height:850});
    await page.addStyleTag({content:'body {background:#111d25;color:#edf3f7;font-family:Arial} :root{--primaryColor:#2196f3;--textPrimary:#edf3f7;--plexpoint-explorer-base:#111d25}'});
    await sidebar.screenshot({path:path.join(__dirname,'sidebar-snapped-tree-preview.png')});
    const touch=await browser.newPage({viewport:{width:720,height:850},hasTouch:true});
    await touch.setContent(await page.content());
    assert.equal(await touch.locator('#sidebar').evaluate(el=>el.getBoundingClientRect().width),320,'touch screens retain the mobile drawer width');
    assert.equal(await touch.locator('#main').evaluate(el=>el.getBoundingClientRect().left),0,'touch layout retains the native drawer behavior');
    assert.equal(await touch.locator('#sidebar .tree-node').first().evaluate(el=>el.getBoundingClientRect().height),44,'touch layout retains large tap targets');
    await touch.close();
    console.log('PASS: split-screen resize 390–1440px, native/custom breakpoint agreement, immediate sidebar open/close, no resize animations, deep native tree retains full-height scrolling without horizontal overflow or selected-row scroll drift.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
