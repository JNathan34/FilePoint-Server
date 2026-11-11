const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'client.js'),'utf8');
const start=source.indexOf('  async function applySidebarHiddenState(');
const end=source.indexOf('  function scheduleApply()',start);
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try {
  const page=await browser.newPage();
  await page.setContent('<style>.pending > .tree-node{visibility:hidden}.hidden{display:none}</style><div class="tree-item"><div class="tree-node">Folder</div></div>');
  await page.addScriptTag({content:`
    let generation=0;
    const hiddenChecks=new WeakMap();
    const SIDEBAR_HIDDEN_CLASS='hidden',SIDEBAR_HIDDEN_PENDING_CLASS='pending';
    const treeItemForNode=node=>node.parentElement;
    let identity='Drive\\nFolder';
    const currentFolderContextIdentity=()=>identity;
    let hidden=false, gate=null;
    async function loadManifest(){if(gate) await gate; return {hidden:new Set(hidden?['Folder']:[])};}
    ${source.slice(start,end)}
    const node=document.querySelector('.tree-node');
    window.checkHidden=()=>applySidebarHiddenState(node,{kind:'folder',source:'Drive',parentPath:'',folderName:'Folder'},generation);
    window.beginRevalidation=(hide=false)=>{generation++;hidden=hide;gate=new Promise(resolve=>window.release=()=>{gate=null;resolve()});return window.checkHidden();};
    window.changes=0;
    new MutationObserver(records=>window.changes+=records.length).observe(node.parentElement,{attributes:true,subtree:true});
  `});
  await page.evaluate(()=>window.checkHidden());
  await page.evaluate(()=>window.changes=0);
  await page.evaluate(async()=>{for(let i=0;i<25;i++) await window.checkHidden()});
  assert.equal(await page.evaluate(()=>window.changes),0,'settled sidebar rows do not churn on icon/layout updates');
  await page.evaluate(()=>{window.revalidation=window.beginRevalidation()});
  assert.equal(await page.locator('.tree-node').evaluate(el=>getComputedStyle(el).visibility),'visible','row remains visible during metadata refresh');
  await page.evaluate(async()=>{window.release();await window.revalidation});
  await page.evaluate(()=>{window.revalidation=window.beginRevalidation(true)});
  await page.evaluate(async()=>{window.release();await window.revalidation});
  assert.equal(await page.locator('.tree-item').evaluate(el=>getComputedStyle(el).display),'none','updated hidden metadata is still respected');
  console.log('PASS: settled sidebar rows produce zero repeated DOM mutations; metadata revalidation has no conceal/reveal flash; hidden changes still apply.');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
