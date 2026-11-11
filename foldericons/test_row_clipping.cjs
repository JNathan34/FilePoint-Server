const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'client.js'),'utf8');
const marker=source.indexOf('const STYLE_ID = "plexpoint-v171-list-chrome-clip-style"');
const code=source.slice(source.lastIndexOf('(() => {',marker),source.indexOf('\n})();',marker)+6);
class Style {constructor(){this.values={};} set cssText(v){this.values={};} get cssText(){return JSON.stringify(this.values);} setProperty(k,v){this.values[k]=v;}}
class Element {constructor(id,y=0,h=100){this.id=id;this.y=y;this.h=h;this.isConnected=true;this.scrollTop=0;this.listeners={};this.classList={contains:()=>true,add(){},remove(){}};}getBoundingClientRect(){return {top:this.y,bottom:this.y+this.h,height:this.h,width:800};}removeAttribute(){}setAttribute(){}addEventListener(k,f){this.listeners[k]=f;}removeEventListener(k){delete this.listeners[k];}}
const host=new Element('main',0,1000),header=new Element('header',0,111),shelf=new Element('shelf',111,49),root=new Element('root'),listing=new Element('listing');listing.parentElement=root;
const rows=[new Element('one',0,65),new Element('two',65,65),new Element('three',130,65)];
const styles={},frames=[];let observer;let resizeObservations=0;
const document={readyState:'complete',body:new Element('body'),documentElement:new Element('html'),head:{appendChild(e){styles[e.id]=e;}},createElement(){return {sheet:{cssRules:[],deleteRule(i){this.cssRules.splice(i,1);},insertRule(text,i){this.cssRules.splice(i,0,{style:new Style()});}}};},getElementById(id){return {main:host,shelf}[id]||styles[id];},querySelector(sel){return sel==='header.flexbar'?header:sel.includes('listing-items')?listing:null;},querySelectorAll(){return rows;},addEventListener(){}};
const window={innerWidth:1440,addEventListener(k,f){this[k]=f;},setInterval(){}};
class ResizeObserver {constructor(fn){this.fn=fn;observer=this;}observe(){resizeObservations++;}disconnect(){}}
const context={document,window,HTMLElement:Element,Element,ResizeObserver,MutationObserver:class{constructor(fn){this.fn=fn;}observe(){}disconnect(){}},getComputedStyle(){return {display:'block',visibility:'visible',opacity:'1'};},requestAnimationFrame(fn){frames.push(fn);return frames.length;},location:{pathname:'/files/source/folder/',href:'https://example.test/files/source/folder/',origin:'https://example.test',search:'',hash:''},history:{pushState(){},replaceState(){}},CSS:{escape:x=>x},URL,queueMicrotask};
function flush(){let count=0;while(frames.length){assert.ok(++count<10,'geometry refresh loop');frames.shift()();}}
function states(){return styles['plexpoint-v171-list-chrome-clip-style'].sheet.cssRules.map(r=>r.style.values);}
vm.runInNewContext(code,context);
assert.equal(states()[0].visibility,'hidden');assert.equal(states()[1].visibility,'hidden');
assert.ok(observer,'layout geometry must be observed');assert.equal(resizeObservations,6);
rows.forEach((r,i)=>r.y=162+65*i);observer.fn();flush();assert.ok(states().every(s=>!s.visibility&&!s['clip-path']),'settled desktop rows must recover');
const observations=resizeObservations;observer.fn();flush();assert.equal(resizeObservations,observations,'unchanged targets must not be re-observed in a loop');
host.scrollTop=100;host.listeners.scroll();assert.equal(states()[0].visibility,'hidden');assert.equal(states()[1]['clip-path'],'inset(33px 0 0 0)');assert.equal(states()[2].visibility,undefined);
window.innerWidth=390;window.resize();flush();assert.equal(states().length,0,'mobile must clear desktop clipping');
window.innerWidth=1440;host.scrollTop=0;window.resize();flush();assert.ok(states().every(s=>!s.visibility&&!s['clip-path']));
console.log('Row clipping: delayed layout, resize recovery, scroll clipping, mobile reset and observer stability passed.');
