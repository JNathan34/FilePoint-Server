/* Live portable-storage cards. Native FileBrowser still performs file operations. */
(() => {
  'use strict';
  let devices = [], busy = false, timer = 0, frame = 0;
  let topology = '';
  const groupIcon = '/__foldericons/device-icon?kind=device';
  const style = document.createElement('style');
  style.textContent = `
    #filepoint-connected-storage { margin:10px 8px 8px; }
    #filepoint-connected-storage h3 { font:600 11px/1.5 "Segoe UI",sans-serif; color:var(--plexpoint-explorer-muted); margin:10px 12px 5px; }
    #filepoint-connected-storage h3 { display:flex; align-items:center; gap:6px; }
    #filepoint-connected-storage h3 img { width:16px; height:16px; flex:0 0 16px; }
    #filepoint-connected-storage a { display:flex; align-items:center; gap:8px; padding:6px 10px; border-radius:5px; color:var(--plexpoint-explorer-text); text-decoration:none; font-size:13px; }
    #filepoint-connected-storage a:hover { background:var(--plexpoint-explorer-hover); }
    #filepoint-connected-storage a[aria-current=page] { background:var(--primaryColor,#2196f3); color:white; }
    #filepoint-connected-storage a[aria-disabled=true] { opacity:.55; }
    #filepoint-connected-storage .material-symbols { font-size:21px; color:var(--primaryColor,#2196f3); }
    #filepoint-connected-storage img { width:24px; height:24px; object-fit:contain; flex:0 0 24px; }
    #filepoint-connected-storage a[aria-current=page] .material-symbols { color:white; }
    #filepoint-connected-storage .filepoint-device-label { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .filepoint-connected-drive .filepoint-device-symbol { font-size:40px!important; color:var(--primaryColor,#2196f3)!important; }
    .filepoint-connected-drive .filepoint-device-detail { font-size:12px; color:var(--plexpoint-explorer-muted); margin-top:5px; }
    .filepoint-connected-drive[aria-disabled=true] { opacity:.6; }
    body.plexpoint-home-dashboard #app .folder-items > .plexpoint-home-section {
      height:auto!important; min-height:0!important;
      padding:4px 4px 0!important; margin-top:0!important; margin-bottom:-8px!important;
    }
    #filepoint-connected-heading { order:-1600!important; flex:0 0 calc(100% - 1rem)!important; width:calc(100% - 1rem)!important; max-width:calc(100% - 1rem)!important; margin:0 0 .25rem!important; box-sizing:border-box!important; }
    .filepoint-connected-drive { order:-1500!important; border:3px solid var(--divider)!important; border-radius:.95rem!important; box-sizing:border-box; }
    .filepoint-connected-drive .filepoint-device-preview {
      display:grid;
      place-items:center;
      width:48px;
      height:48px;
      padding:2px;
      box-sizing:border-box;
    }
    .filepoint-connected-drive .filepoint-device-art {
      display:block;
      width:100%;
      height:100%;
      object-fit:contain;
    }
    .filepoint-connected-drive .plexpoint-space-bar[aria-disabled=true] { opacity:.45; }
    html body #sidebar .tree-node[data-filepoint-device-kind]:has(> .filepoint-device-native-icon[data-ready]) > :is(.node-icon,.plexpoint-v65-sidebar-icon,.plexpoint-v177-sidebar-root-icon) { display:none!important; }
    #sidebar .tree-node > .filepoint-device-native-icon { display:inline-flex!important; flex:0 0 24px; align-items:center; justify-content:center; color:var(--primaryColor,#2196f3); font-size:22px; }
    #sidebar .tree-node > .filepoint-device-native-icon:not([data-ready]) { display:none!important; }
    #sidebar .tree-node[data-filepoint-device-kind="group"] > .filepoint-device-native-icon { flex-basis:26px; width:26px; margin-right:3px; }
    @media (min-width:600px) and (max-width:768px) and (pointer:fine) {
      #sidebar .tree-node[data-filepoint-device-kind="group"] > .filepoint-device-native-icon { flex-basis:20px; width:20px; margin-right:2px; }
      #sidebar .tree-node[data-filepoint-device-kind="group"] > .filepoint-device-native-icon img { width:20px!important; height:20px!important; }
    }
    #sidebar .tree-node.current-item > .filepoint-device-native-icon { color:white; }
    #sidebar .filepoint-device-native-icon img { width:24px!important; height:24px!important; object-fit:contain; }
  `;
  document.head.appendChild(style);
  const href = d => '/files/Home/' + d.path.split('/').map(encodeURIComponent).join('/') + '/';
  const bytes = n => {
    if (!Number.isFinite(n) || n < 0) return '';
    if (n === 0) return '0 B';
    const unit = Math.min(4,Math.floor(Math.log(n)/Math.log(1024)));
    return (n / 1024 ** unit).toFixed(unit >= 2 && n / 1024 ** unit < 100 ? 1 : 0) + ' ' + ['B','KB','MB','GB','TB'][unit];
  };
  function navigate(d) {
    if (d.status !== 'ready') return;
    const router = document.getElementById('app')?.__vue_app__?.config?.globalProperties?.$router;
    if (router) router.push(href(d));
    else location.assign(href(d));
  }
  function makeLink(d, card) {
    const link = document.createElement('a');
    link.dataset.filepointDevice = d.id;
    link.href = href(d);
    if (card) {
      link.className = 'listing-item clickable no-select plexpoint-home-card filepoint-connected-drive';
      link.dataset.dir = 'true'; link.dataset.type = 'directory';
      link.dataset.name = d.label; link.dataset.plexpointHomeCategory = 'drive';
      link.setAttribute('role','button');
      const iconWrap = document.createElement('div'), preview = document.createElement('span');
      preview.className = 'filepoint-device-preview';
      const icon = document.createElement('img'); icon.className = 'filepoint-device-art'; icon.alt = ''; icon.draggable = false;
      preview.append(icon); iconWrap.append(preview);
      const text = document.createElement('div'); text.className = 'text';
      const name = document.createElement('p'); name.className = 'name';
      const label = document.createElement('span'); label.className = 'filepoint-device-label'; name.append(label);
      const detail = document.createElement('div'); detail.className = 'plexpoint-home-detail';
      const bar = document.createElement('div'); bar.className = 'plexpoint-space-bar';
      const used = document.createElement('div'); used.className = 'plexpoint-space-used'; bar.append(used);
      const usageLabel = document.createElement('span'); usageLabel.className = 'plexpoint-space-label';
      detail.append(bar,usageLabel);
      text.append(name,detail); link.append(iconWrap,text);
    } else {
      const icon = document.createElement('img'); icon.alt = ''; icon.draggable = false;
      const label = document.createElement('span'); label.className = 'filepoint-device-label';
      link.append(icon,label);
    }
    return link;
  }
  function reconcile(container, card) {
    const ids = new Set(devices.map(d => d.id));
    for (const node of container.querySelectorAll(':scope > [data-filepoint-device]')) {
      if (!ids.has(node.dataset.filepointDevice)) node.remove();
    }
    for (const d of devices) {
      let node = [...container.children].find(n => n.dataset.filepointDevice === d.id);
      if (!node) { node = makeLink(d,card); container.append(node); }
      const current = location.pathname.startsWith(href(d));
      const detail = d.status === 'ready' ? (d.readOnly ? 'Read only · ' : '') + (d.total ? `${bytes(d.free)} free of ${bytes(d.total)}` : 'Storage information unavailable') : d.status === 'locked' ? 'Locked — unlock on the server' : d.status === 'waiting-for-mount' ? 'Waiting for server to mount' : 'Device unavailable';
      const signature = JSON.stringify([d.label,d.iconUrl,detail,current]);
      if (node.dataset.deviceSignature === signature) continue;
      node.dataset.deviceSignature = signature;
      node.querySelector('.filepoint-device-label').textContent = d.label;
      const image = node.querySelector('img');
      if (image.getAttribute('src') !== d.iconUrl) image.src = d.iconUrl;
      node.querySelector('.plexpoint-space-label')?.replaceChildren(document.createTextNode(detail));
      const bar = node.querySelector('.plexpoint-space-bar');
      if (bar) {
        const valid = d.status === 'ready' && d.total > 0 && Number.isFinite(d.free);
        const percent = valid ? Math.max(0,Math.min(100,100*(d.total-d.free)/d.total)) : 0;
        bar.querySelector('.plexpoint-space-used').style.width = percent.toFixed(1)+'%';
        bar.setAttribute('aria-label',valid ? percent.toFixed(0)+' percent used' : detail);
        bar.setAttribute('aria-disabled',String(!valid));
      }
      node.title = d.label + ' — ' + detail;
      node.setAttribute('aria-label',d.label);
      node.setAttribute('aria-disabled',String(d.status !== 'ready'));
      if (current) node.setAttribute('aria-current','page'); else node.removeAttribute('aria-current');
    }
  }
  function render() {
    frame = 0;
    const sidebar = document.querySelector('#sidebar .sidebar-links-content');
    const rows = [...document.querySelectorAll('#sidebar .tree-node')];
    const isDevicesRoot = row => {
      const identity = row.dataset.plexpointSidebarHiddenIdentity || '';
      return identity.startsWith('Home\nConnected devices\n') || identity.startsWith('Connected devices\n\n');
    };
    const nativeRoot = rows.some(isDevicesRoot);
    for (const row of rows) {
      const identity = row.dataset.plexpointSidebarHiddenIdentity || '';
      const device = isDevicesRoot(row) ? {kind:'group',iconUrl:groupIcon} :
        devices.find(d => identity.startsWith('Home\n' + d.path + '\n') || identity.startsWith('Connected devices\n' + d.name + '\n'));
      let icon = row.querySelector(':scope > .filepoint-device-native-icon');
      if (!device?.iconUrl) {
        delete row.dataset.filepointDeviceKind;
        icon?.remove();
        continue;
      }
      if (row.dataset.filepointDeviceKind !== device.kind) row.dataset.filepointDeviceKind = device.kind;
      if (!icon) {
        icon = document.createElement('span');
        icon.className = 'filepoint-device-native-icon';
        icon.setAttribute('aria-hidden','true');
        const image = document.createElement('img');
        image.alt = '';
        image.draggable = false;
        image.addEventListener('load', () => icon.setAttribute('data-ready',''));
        image.addEventListener('error', () => icon.removeAttribute('data-ready'));
        icon.append(image);
        row.querySelector('.node-name')?.before(icon);
      }
      const image = icon.querySelector('img');
      if (image && image.getAttribute('src') !== device.iconUrl) {
        icon.removeAttribute('data-ready');
        image.src = device.iconUrl;
      }
    }
    let group = document.getElementById('filepoint-connected-storage');
    if (!devices.length || nativeRoot) group?.remove();
    else if (sidebar) {
      if (!group) {
        group = document.createElement('div'); group.id = 'filepoint-connected-storage';
        const title = document.createElement('h3');
        const icon = document.createElement('img');
        icon.alt = '';
        icon.src = groupIcon;
        title.append(icon,'Connected devices');
        group.append(title);
        sidebar.append(group);
      }
      reconcile(group,false);
    }
    const home = /^\/files\/Home\/?$/.test(location.pathname);
    const container = home && document.querySelector('.folder-items[aria-label="Folder Items"]');
    let heading = document.getElementById('filepoint-connected-heading');
    if (container && devices.length) {
      if (!heading) {
        heading = document.createElement('div');
        heading.id = 'filepoint-connected-heading';
        heading.className = 'plexpoint-home-section';
        heading.dataset.category = 'connected';
        const title = document.createElement('h2');
        title.textContent = 'Connected devices';
        heading.append(title);
        container.append(heading);
      }
    } else heading?.remove();
    if (container) reconcile(container,true);
    else document.querySelectorAll('.filepoint-connected-drive').forEach(n => n.remove());
  }
  function schedule() { if (!frame) frame = requestAnimationFrame(render); }
  function refreshTrees() {
    for (const root of document.querySelectorAll('#sidebar .file-tree-root')) {
      let instance = root.__vueParentComponent;
      for (let depth=0; instance && depth<20; depth++,instance=instance.parent) {
        if (String(instance.type?.name || instance.type?.__name).toLowerCase() === 'filetree') {
          const tree = instance.proxy;
          if (typeof tree?.refresh === 'function') Promise.resolve(tree.refresh()).catch(() => {});
          break;
        }
      }
    }
  }
  async function refresh() {
    clearTimeout(timer);
    if (busy || document.hidden) { timer = setTimeout(refresh,3000); return; }
    busy = true;
    try {
      const response = await fetch('/__foldericons/devices',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(8000)});
      if (response.ok) {
        const data = await response.json();
        devices = Array.isArray(data.devices) ? data.devices.slice(0,64).filter((d,i,all) => all.findIndex(other => other.id === d.id) === i).slice(0,64) : [];
        const next = JSON.stringify(devices.map(d => [d.id,d.status]));
        if (topology && topology !== next) refreshTrees();
        topology = next;
      } else if (response.status === 401 || response.status === 403) devices = [];
      else devices = devices.map(d => ({...d,status:'unavailable'}));
      schedule();
    } catch (_) { devices = devices.map(d => ({...d,status:'unavailable'})); schedule(); }
    finally { busy = false; timer = setTimeout(refresh,3000); }
  }
  // These are drive shortcuts, not native file rows: route them before native
  // selection/context handlers can infer the wrong source from the current view.
  for (const type of ['click','dblclick','contextmenu','keydown']) window.addEventListener(type,event => {
    const link = event.target instanceof Element && event.target.closest('[data-filepoint-device]');
    if (!link) return;
    if (type === 'keydown' && !['Enter',' '].includes(event.key)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    const d = devices.find(d => d.id === link.dataset.filepointDevice);
    if (d && (type === 'keydown' || type === 'dblclick' || (type === 'click' && !link.classList.contains('filepoint-connected-drive')))) navigate(d);
  },true);
  new MutationObserver(schedule).observe(document.body,{childList:true,subtree:true,attributes:true,
    attributeFilter:['data-plexpoint-sidebar-hidden-identity']});
  window.addEventListener('popstate',schedule);
  document.addEventListener('visibilitychange',refresh);
  refresh();
})();
