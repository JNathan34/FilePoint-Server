// Reproduce Vue replacing a selected tree row's class attribute during navigation.
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, 'client.js'), 'utf8');
function styles(marker, constants) {
  const section = source.slice(source.indexOf(marker));
  const css = section.match(/style\.textContent = `([\s\S]*?)`;/)[1];
  return css.replace(/\$\{(\w+)\}/g, (_, name) => constants[name]);
}
const primary = styles('/* === Plexpoint Explorer V65:', {
  ACTIVE_CLASS:'plexpoint-v65-sidebar-icon-active', ICON_CLASS:'plexpoint-v65-sidebar-icon',
  OFFICE_CLASS:'plexpoint-v65-sidebar-office-icon', SIDEBAR_HIDDEN_CLASS:'plexpoint-sidebar-hidden-entry',
  SIDEBAR_HIDDEN_PENDING_CLASS:'plexpoint-sidebar-hidden-pending',
});
const recovery = styles('* Plexpoint Explorer V177', {
  ACTIVE_CLASS:'plexpoint-v177-sidebar-root-icon-active', ICON_CLASS:'plexpoint-v177-sidebar-root-icon',
  PRIMARY_ACTIVE_CLASS:'plexpoint-v65-sidebar-icon-active', PRIMARY_ICON_CLASS:'plexpoint-v65-sidebar-icon',
});
(async () => {
  const browser = await chromium.launch({headless:true, channel:'msedge'});
  try {
    const page = await browser.newPage({viewport:{width:1100,height:800}});
    await page.setContent(`<style>
      .tree-node {display:flex} .node-icon {display:flex;width:24px}
      ${primary}\n${recovery}
      </style><body class="plexpoint-explorer-layout"><nav id="sidebar">
      <div class="tree-node plexpoint-v65-sidebar-icon-active">
        <span class="plexpoint-v65-sidebar-icon" data-plexpoint-icon-ready="true"><i>folder</i></span>
        <span class="node-icon">folder</span><span class="node-name">College</span>
      </div></nav></body>`);
    const before = await page.locator('.node-name').boundingBox();
    for (const classes of ['tree-node current-item', 'tree-node has-children', 'tree-node']) {
      await page.locator('.tree-node').evaluate((el, cls) => {el.className=cls}, classes);
      assert.equal(await page.locator('.node-icon').evaluate(el=>getComputedStyle(el).display), 'none',
        'native icon must stay hidden when Vue replaces the row classes');
      assert.equal((await page.locator('.node-name').boundingBox()).x, before.x, 'navigation must not shift the label');
    }
    await page.locator('.tree-node').evaluate(el => {
      const recovery = document.createElement('span');
      recovery.className='plexpoint-v177-sidebar-root-icon'; recovery.innerHTML='<i>folder</i>';
      el.prepend(recovery);
    });
    assert.equal(await page.locator('.plexpoint-v177-sidebar-root-icon').evaluate(el=>getComputedStyle(el).display),'none',
      'recovery icon must not duplicate an installed primary icon');
    await page.locator('.plexpoint-v65-sidebar-icon').evaluate(el=>el.remove());
    assert.equal(await page.locator('.node-icon').evaluate(el=>getComputedStyle(el).display),'none',
      'a recovery icon also survives row class updates');
    await page.locator('.plexpoint-v177-sidebar-root-icon').evaluate(el=>el.remove());
    assert.notEqual(await page.locator('.node-icon').evaluate(el=>getComputedStyle(el).display),'none',
      'native fallback remains visible when there is no custom icon');
    await page.locator('.tree-node').evaluate(el=>el.insertAdjacentHTML('afterbegin',
      '<span class="plexpoint-v65-sidebar-icon"><img></span>'));
    assert.notEqual(await page.locator('.node-icon').evaluate(el=>getComputedStyle(el).display),'none',
      'an unready image must not hide the fallback');
    console.log('PASS: navigation class replacement preserves icon visibility and label position; recovery deduplication and missing/unready icon fallbacks.');
  } finally {await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
