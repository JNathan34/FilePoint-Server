const fs = require('node:fs');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, 'client.js'), 'utf8');
const start = source.indexOf('/* Office documents open in independent browser windows');
const code = source.slice(start, source.indexOf('/* FilePoint folder navigation:', start));
const folder = '/files/ZimaOS%20HDD/Documents/';
function run({ blocked=false, closed=false, search='', native=true, app=false, folders=[] }={}) {
  const calls=[], panels=[], listeners={}; let guard;
  const router={beforeEach(fn){guard=fn;}};
  const popup={opener:{},closed,focus(){}};
  class Element {closest(selector){return selector==='.floating-close' ? this.closeButton : null;}}
  function element(tag) {return {tag,children:[],setAttribute(){},append(...children){this.children.push(...children);},remove(){}};}
  const document={
    documentElement:{dataset:{}},body:{append(p){panels.push(p);}},
    getElementById(id){return id==='app' && app ? {__vue_app__:{config:{globalProperties:{$router:router}}}} : null;},
    querySelectorAll(selector){return selector.includes('data-dir') ? folders.map(name=>({dataset:{name}})) : native ? [{__vue__:{$parent:{$router:router}}}] : [{__vueParentComponent:{proxy:{$router:router}}}];},
    createElement:element
  };
  vm.runInNewContext(code,{document,Element,URL,URLSearchParams,location:{origin:'https://files.plexpoint.uk',search},screen:{availWidth:1920,availHeight:1080},window:{open(...args){calls.push(args);return blocked?null:popup;},addEventListener(name,fn){listeners[name]=fn;},close(){calls.push('close');}},setInterval(){throw Error('Router was not detected');},setTimeout(){},clearInterval(){}});
  return {navigate(path,from=folder){return guard({path,fullPath:path+'?test=1'},{path:from});},calls,panels,popup,guard,listeners,Element};
}
for(const ext of ['docx','pptx','xlsx','pdf','PDF']){
  const env=run();assert.equal(env.navigate(folder+'Example.'+ext),false);
  const [url,target,features]=env.calls[0];assert.equal(target,'_blank');assert.match(features,/popup=yes/);assert.equal(new URL(url).searchParams.get('officeWindow'),'1');assert.equal(env.popup.opener,null);
}
const many=run();many.navigate(folder+'One.docx');many.navigate(folder+'Two.xlsx');assert.equal(many.calls.length,2);assert.notEqual(many.calls[0][0],many.calls[1][0]);
for(const path of [folder+'Subfolder/',folder+'photo.jpg',folder+'note.txt']){const e=run();assert.equal(e.navigate(path),true);assert.equal(e.calls.length,0);}
const initial=run();assert.equal(initial.navigate(folder+'Test.docx','/'),true);assert.equal(initial.calls.length,0);
const documentNamedFolder=run({folders:['Archive.docx']});assert.equal(documentNamedFolder.navigate(folder+'Archive.docx'),true);assert.equal(documentNamedFolder.calls.length,0);
const pdfNamedFolder=run({folders:['Archive.pdf']});assert.equal(pdfNamedFolder.navigate(folder+'Archive.pdf'),true);assert.equal(pdfNamedFolder.calls.length,0);
const pdfDirect=run();assert.equal(pdfDirect.navigate(folder+'Report.pdf','/'),true);assert.equal(pdfDirect.calls.length,0);
const pdfBlocked=run({blocked:true});assert.equal(pdfBlocked.navigate(folder+'Report%20final.pdf'),false);assert.equal(pdfBlocked.panels.length,1);assert.match(pdfBlocked.panels[0].children.find(el=>el.tag==='a').href,/Report%20final\.pdf/);
const pdfConcurrent=run();pdfConcurrent.navigate(folder+'One.pdf');pdfConcurrent.navigate(folder+'Two.pdf');assert.equal(pdfConcurrent.calls.length,2);assert.notEqual(pdfConcurrent.calls[0][0],pdfConcurrent.calls[1][0]);
const blocked=run({blocked:true});assert.equal(blocked.navigate(folder+'Test.docx'),false);assert.equal(blocked.panels.length,1);const link=blocked.panels[0].children.find(el=>el.tag==='a');assert.equal(link.target,'_blank');assert.equal(link.rel,'noopener');assert.equal(new URL(link.href).searchParams.get('officeWindow'),'1');
const closed=run({closed:true});assert.equal(closed.navigate(folder+'Closed.docx'),false);assert.equal(closed.panels.length,1);
for(const opts of [{app:true,native:false},{native:false}]){const e=run(opts);assert.equal(e.navigate(folder+'Test.docx'),false);}
const child=run({search:'?officeWindow=1'});assert.equal(child.guard,undefined);const target=new child.Element();target.closeButton=true;let prevented=false;child.listeners.click({target,preventDefault(){prevented=true;},stopImmediatePropagation(){}});assert.ok(prevented);assert.equal(child.calls[0],'close');
console.log('Document windows: Word/Excel/PowerPoint/PDF, uppercase PDF, concurrent windows, PDF-named folders, direct routes, blocked popup, router variants and close passed.');
