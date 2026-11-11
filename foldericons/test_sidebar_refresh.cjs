// Behaviour tests for the native FileTree refresh adapter (no real files changed).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, 'client.js'), 'utf8');
const start = source.indexOf('/* Plexpoint sidebar refresh stability:');
assert(start > 0);
// Isolate this adapter; later independent client patches need their own DOM.
const end = source.indexOf('\n})();', start);
assert(end > start);
const patch = source.slice(start, end + '\n})();'.length);
const defer = () => { let resolve; const promise = new Promise(r => resolve = r); return {promise,resolve}; };
function fixture() {
  const data = new Map([['/', [{name:'Folder',path:'/Folder',type:'directory'}]],
    ['/Folder', [{name:'old.txt',path:'/Folder/old.txt',type:'text'}]]]);
  const stats = {loads:0, scrolls:0, toggles:0};
  const tree = {
    currentSource:'Drive',shareHash:null,rootPath:'/',showFiles:true,isRootInstance:true,
    rootLoaded:true,loading:false,isRefreshing:false,$el:{isConnected:true},
    fetchItems:async path => structuredClone(data.get(path) || []),
    createNode: item => ({...item,source:'Drive',isDir:item.type==='directory',
      expanded:false,loading:false,children:null,childrenCount:0,childrenError:null,dragOver:false}),
    async loadRoot() { stats.loads++; this.loading = true; this.rootNodes = (await this.fetchItems('/')).map(x => this.createNode(x)); this.loading = false; },
    async applyExpandedPaths(nodes, paths) { for (const node of nodes) if(paths.has(node.path)) { stats.toggles++; node.expanded = !node.expanded; } },
    async expandToPath() { this.scrollToCurrent(); },
    scrollToCurrent() { stats.scrolls++; },
    // Same call sequence as Quantum's native refresh; callers retain this
    // original bound method, so the adapter must work through dynamic methods.
    async refresh() {
      if(this.isRefreshing) return;
      this.isRefreshing = true;
      const expanded = new Set(this.rootNodes.filter(x => x.expanded).map(x => x.path));
      try { await this.loadRoot(); await this.applyExpandedPaths(this.rootNodes,expanded); await this.expandToPath(); this.scrollToCurrent(); }
      finally { this.isRefreshing = false; }
    },
  };
  tree.rootNodes = data.get('/').map(x => tree.createNode(x));
  tree.rootNodes[0].expanded = true;
  tree.rootNodes[0].children = data.get('/Folder').map(x => tree.createNode(x));
  const element = {__vue__:tree};
  vm.runInNewContext(patch, {console,document:{querySelectorAll:()=>[element],getElementById:()=>null},window:{setInterval(){}},MutationObserver:class{}});
  return {tree,data,stats};
}
(async () => {
  const {tree,data,stats} = fixture();
  const roots = tree.rootNodes, folder = roots[0], children = folder.children, file = children[0];
  for (let i=0;i<5;i++) {
    data.set('/Folder',[{name:'old.txt',path:'/Folder/old.txt',type:'text',size:i}, {name:'new.txt',path:'/Folder/new.txt',type:'text'}]);
    await tree.refresh();
    assert.equal(tree.rootNodes,roots); assert.equal(roots[0],folder); assert.equal(folder.children,children);
    assert.equal(children[0],file); assert.equal(file.size,i); assert.equal(folder.expanded,true);
  }
  assert.deepEqual(stats,{loads:0,scrolls:0,toggles:0});
  data.set('/Folder',[{name:'renamed.txt',path:'/Folder/renamed.txt',type:'text'}]);
  await tree.refresh(); assert.equal(folder.children.length,1); assert.equal(folder.children[0].name,'renamed.txt');
  const originalFetch = tree.fetchItems;
  tree.fetchItems = async () => {throw new Error('test offline')};
  await tree.refresh(); assert.equal(roots[0],folder); assert.equal(folder.children.length,1);
  tree.fetchItems = originalFetch;
  const gate = defer(); tree.fetchItems = async path => { if(path==='/') await gate.promise; return originalFetch(path); };
  const pending = tree.refresh(); folder.expanded = false; gate.resolve(); await pending;
  assert.equal(folder.expanded,false,'a user collapse during refresh is preserved');
  folder.expanded = true;
  const switchGate=defer(); tree.fetchItems=async () => {await switchGate.promise; return [{name:'Wrong',path:'/Wrong',type:'directory'}]};
  const switched=tree.refresh(); tree.currentSource='Other'; switchGate.resolve(); await switched;
  assert.equal(roots[0],folder,'old responses never replace a different drive');
  tree.fetchItems=originalFetch; await tree.loadRoot(); assert.equal(stats.loads,1,'source changes retain native loading');
  tree.scrollToCurrent(); assert.equal(stats.scrolls,1,'explicit navigation still scrolls');
  const moves = [];
  let rowBounds = {top:150,bottom:178};
  const scroller = {clientTop:0,clientHeight:400,scrollTop:90,scrollLeft:0,
    getBoundingClientRect:()=>({top:100,bottom:500}),scrollTo:options=>moves.push(options)};
  tree.$refs = {FileTree:{closest:()=>scroller,querySelector:()=>({getBoundingClientRect:()=>rowBounds})}};
  tree.scrollToCurrent();
  assert.equal(moves.length,0,'already-visible navigation rows never recenter');
  rowBounds = {top:510,bottom:538}; tree.scrollToCurrent();
  assert.equal(moves.at(-1).top,128,'only reveal the clipped bottom of a row');
  assert.equal(moves.at(-1).left,0,'never scroll the sidebar horizontally');
  assert.equal(moves.at(-1).behavior,'instant','no animated scroll/reset race');
  rowBounds = {top:72,bottom:100}; tree.scrollToCurrent();
  assert.equal(moves.at(-1).top,62,'reveal a row above the viewport');
  assert.equal(stats.scrolls,1,'sidebar navigation does not invoke scrollIntoView');
  console.log('PASS: stable nodes and expanded branches through edit/create/rename/delete; no refresh scrolling or loading flash; offline retention; collapse race; stale-drive rejection; native source navigation.');
})().catch(error=>{console.error(error);process.exitCode=1});
