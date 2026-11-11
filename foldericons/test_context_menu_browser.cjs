// Browser geometry/interaction regression fixture; does not touch real files.
const { chromium } = require('playwright');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const source = readFileSync(join(__dirname, 'client.js'), 'utf8');
  const start = source.indexOf('(() => {', source.indexOf('Plexpoint Explorer V189'));
  const end = source.indexOf('/* ============================================================================', start);
  assert(start > 0 && end > start);
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  try {
    const page = await browser.newPage({ viewport: { width: 1000, height: 700 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent(`<style>
      body { margin:0; background:#152630; color:#e7edf1; font:14px system-ui; }
      #file { margin:48px; padding:18px; background:#284351; }
      .overlay { position:fixed; inset:0; }
      #context-menu { position:fixed; width:360px; padding:12px; background:#202e38;
        border:1px solid #607480; border-radius:14px; z-index:10; }
      #context-menu button.action { display:flex; min-height:2.05rem!important;
        height:auto!important; padding:.26rem .56rem!important; width:100%;
        color:inherit; background:transparent; border:0; font:inherit; }
      #context-menu button.action:hover { background:#38586b; }
      /* Native icons carry padding; clipboard icons have a separate old width.
         The screenshot regression only appears with both styles present. */
      .action i { padding:.4em; }
      .action:hover { transform:scale(1.02); }
      #context-menu button.action[data-plexpoint-clipboard-action] > i {
        display:inline-flex!important; min-width:1.45rem!important; padding:0!important;
      }
      #context-menu button.action[data-plexpoint-clipboard-action] { padding-left:1.26rem!important; }
      #context-menu .context-menu-header { padding:0 .5em; }
      #context-menu .action span { margin-left:4px; }
      #context-menu i { font-style:normal; }
      .plexpoint-context-divider { height:1px; background:#52616b; margin:3px 6px; }
      #context-menu.plexpoint-home-compact-menu { width:14rem!important; min-width:14rem!important; max-height:none!important; }
      @media(max-width:760px) {
        body.plexpoint-explorer-layout #context-menu.centered { top:auto!important; right:8px!important;
          bottom:8px!important; left:8px!important; width:auto!important; max-height:70dvh!important;
          padding:8px!important; transform:translateY(-10px)!important; }
        body.plexpoint-explorer-layout #context-menu > button.action { min-height:48px!important; }
      }
    </style><body class="plexpoint-explorer-layout"><div id="file" tabindex="0">Example report.docx</div></body>`);
    await page.addScriptTag({ content: source.slice(start, end) });
    await page.addScriptTag({ content: `
      window.actions = 0;
      window.showMenu = (x,y, home = false) => {
        const overlay = document.createElement('div'); overlay.className = 'overlay';
        const menu = document.createElement('div'); menu.id = 'context-menu';
        menu.className = 'centered' + (home ? ' plexpoint-home-compact-menu' : '');
        menu.style.cssText = 'left:'+x+'px;top:'+y+'px';
        menu.dataset.plexpointContextMenuStable = 'true';
        const labels = ['Download','Share','Pin to Home','Cut','Copy','Paste','Copy path',
          'Open in Microsoft Word','Save back to Files','New','Delete','Rename','Properties'];
        labels.forEach((label,i) => {
          if ([3,7,10,12].includes(i)) { const divider = document.createElement('div');
            divider.className='plexpoint-context-divider'; menu.append(divider); }
          const button=document.createElement('button'); button.className='action';
          button.innerHTML='<i>◇</i><span>'+label+'</span>';
          if (['Cut','Copy','Paste'].includes(label)) button.dataset.plexpointClipboardAction=label.toLowerCase();
          button.addEventListener('click', () => window.actions++);
          if (label==='New') {
            button.classList.add('context-menu-create-toggle');
            button.querySelector('span').className='plexpoint-new-label';
            button.insertAdjacentHTML('beforeend','<i class="plexpoint-new-chevron">›</i>');
            const header=document.createElement('div'); header.className='context-menu-header';
            header.append(button); menu.append(header);
          } else menu.append(button);
        });
        overlay.onclick = () => { menu.remove(); overlay.remove(); };
        document.body.append(overlay, menu);
      };
      document.getElementById('file').addEventListener('contextmenu', event => {
        event.preventDefault(); window.showMenu(event.clientX,event.clientY);
      });
    ` });

    async function fits(noScroll = true) {
      await page.waitForFunction(() => {
        const menu = document.getElementById('context-menu');
        if (!menu?.hasAttribute('data-plexpoint-fitted-menu')) return false;
        const r = menu.getBoundingClientRect();
        return r.left >= 7.9 && r.top >= 7.9 && r.right <= innerWidth-7.9 && r.bottom <= innerHeight-7.9;
      });
      const geometry = await page.locator('#context-menu').evaluate(menu => ({
        width: menu.getBoundingClientRect().width,
        height: menu.getBoundingClientRect().height,
        overflow: menu.scrollHeight - menu.clientHeight,
        row: menu.querySelector('button').getBoundingClientRect().height,
        documentOverflow: document.documentElement.scrollHeight > innerHeight,
      }));
      assert(geometry.width <= 260, JSON.stringify(geometry));
      if (noScroll) assert(geometry.overflow <= 1, JSON.stringify(geometry));
      assert(!geometry.documentOverflow, 'popup must not make the page scroll');
      const rows = await page.locator('#context-menu button.action').evaluateAll(buttons => buttons.map(button => {
        const row = button.getBoundingClientRect();
        const icon = button.querySelector('i').getBoundingClientRect();
        const label = button.querySelector('span').getBoundingClientRect();
        return { x:icon.x, width:icon.width, height:icon.height, labelX:label.x,
          iconOffset: icon.y + icon.height/2 - row.y - row.height/2,
          labelOffset: label.y + label.height/2 - row.y - row.height/2 };
      }));
      for (const row of rows) {
        assert.equal(row.width,20,'icon width includes native padding');
        assert.equal(row.height,20,'icon height includes native padding');
        assert.equal(row.x,rows[0].x,'all icons share one column');
        assert.equal(row.labelX,rows[0].labelX,'all labels share one column');
        assert(Math.abs(row.iconOffset)<0.1,'icon must be vertically centered');
        assert(Math.abs(row.labelOffset)<0.1,'label must be vertically centered');
      }
      return geometry;
    }
    for (const [width,height] of [[1000,700],[700,500],[900,400]]) {
      await page.setViewportSize({width,height});
      for (const [x,y] of [[1,1],[width-2,1],[1,height-2],[width-2,height-2]]) {
        await page.evaluate(({x,y}) => window.showMenu(x,y), {x,y});
        await fits();
        await page.locator('#context-menu button').last().click();
        await page.locator('.overlay').click({position:{x:width/2,y:4}});
        assert.equal(await page.locator('#context-menu').count(),0);
      }
    }
    assert.equal(await page.evaluate(() => window.actions),12, 'actions remain clickable');
    await page.setViewportSize({width:900,height:600});
    await page.locator('#file').click({button:'right'});
    await fits();
    await page.evaluate(() => {
      const late = document.createElement('button'); late.className='action';
      late.innerHTML='<i>◇</i><span>Late Microsoft action</span>';
      document.getElementById('context-menu').append(late);
    });
    await fits();
    await page.setViewportSize({width:700,height:440});
    await fits();
    await page.locator('#context-menu').evaluate(menu => menu.classList.add('plexpoint-home-compact-menu'));
    await fits();
    // No perpetual layout/mutation loop after settling.
    await page.waitForTimeout(100);
    await page.evaluate(() => {
      window.layoutChanges=0;
      new MutationObserver(records => window.layoutChanges+=records.length)
        .observe(document.getElementById('context-menu'),{attributes:true});
    });
    await page.waitForTimeout(200);
    assert.equal(await page.evaluate(() => window.layoutChanges),0);
    await page.screenshot({path:join(__dirname,'context-menu-browser-preview.png')});
    // Extreme viewport: fallback stays inside the popup, never page scrolling.
    await page.setViewportSize({width:320,height:240});
    await fits(false);
    assert.deepEqual(errors,[]);
    console.log('PASS: compact menu, 12 edge cases, short/narrow windows, late actions, resizing, native clicks/dismissal, no idle mutation loop.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode=1; });
