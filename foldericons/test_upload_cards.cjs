// Per-file notification regression coverage with a small DOM double.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(`${__dirname}/client.js`, 'utf8');
const start = source.indexOf('Plexpoint Explorer V96 — DOM-DRIVEN');
function extract(name) {
  const begin = source.indexOf(`  function ${name}(`, start);
  const end = source.indexOf('\n  function ', begin + 1);
  assert(begin > start && end > begin, name);
  return source.slice(begin, end);
}
class Element {
  constructor(){ this.children=[]; this.dataset={}; this.style={setProperty(k,v){this[k]=v;}}; this.attrs={}; this.events={}; this.disabled=false; }
  append(...nodes){ for (const node of nodes) this.appendChild(node); }
  appendChild(node){ if(node.parent) node.remove(); this.children.push(node); node.parent=this; node.parentElement=this; return node; }
  setAttribute(key,value){ this.attrs[key]=value; }
  addEventListener(key,fn){ this.events[key]=fn; }
  click(){ this.events.click?.({preventDefault(){},stopPropagation(){}}); }
  remove(){ this.parent.children=this.parent.children.filter(node=>node!==this); }
}
class Button extends Element {}
let now=1000;
const context={HTMLElement:Element,HTMLButtonElement:Button, rowMemory:new WeakMap(), state:{sample:null},
  performance:{now:()=>now}, document:{createElement:tag=>tag==='button'?new Button():new Element(),createTextNode:value=>({nodeValue:value})}};
vm.createContext(context);
vm.runInContext(['textNode','setText','createUploadCard','realRowButton','clickRealRowButton','updateRowControls','parseByteValue','rowProgress','rowName','summarizeRows','formatBytes','formatRemaining','updateSpeed','uploadQueueForRow','uploadRowInfo','updateUploadIcon','prepareUploadGroups','renderUploadCards'].map(extract).join('\n'),context);
function row(name,text,actions){
  const row=new Element(); row.name=name; row.text=text; row.buttons={}; row.calls=[];
  for(const action of actions){const button=new Button();button.events.click=()=>row.calls.push(action);row.buttons[action]=button;}
  row.querySelector=selector=>{
    if(selector.includes('file-name')) return {textContent:row.name};
    if(selector.includes('status-label')||selector.includes('vue-simple-progress-text')) return {textContent:row.text};
    return row.buttons[selector.match(/aria-label="([^"]+)"/)?.[1]] || null;
  };
  return row;
}
const a=row('Report.txt','2 MB / 10 MB',['Pause','Cancel']);
const b=row('Photo.png','6 MB / 20 MB',['Resume','Cancel']);
const c=row('Report.txt','Completed',[]); // same filename is still a separate upload
const ui={cards:new Map(),list:new Element()};
function render(rows){context.renderUploadCards(context.summarizeRows(rows),ui);}
render([a,b,c]);
assert.equal(ui.cards.size,3);
assert.equal(ui.cards.get(a).fill.style.width,'20%');
assert.equal(ui.cards.get(b).fill.style.width,'30%');
assert.equal(ui.cards.get(c).card.dataset.mode,'complete');
assert.equal(ui.cards.get(c).metaText.nodeValue,'Successful');
assert.equal(ui.cards.get(c).rowActions.hidden,true);
assert.match(ui.cards.get(b).metaText.nodeValue,/Paused/);
ui.cards.get(a).pauseResume.click();ui.cards.get(b).pauseResume.click();ui.cards.get(b).cancelOne.click();
assert.deepEqual(a.calls,['Pause']);assert.deepEqual(b.calls,['Resume','Cancel']);assert.deepEqual(c.calls,[]);
const originalCard=ui.cards.get(a).card;
now=2000;a.text='4 MB / 10 MB';render([a,b,c]);
assert.equal(ui.cards.get(a).card,originalCard,'progress keeps card and focused buttons mounted');
assert.match(ui.cards.get(a).speedText.nodeValue,/2.00 MB\/s/);
assert.equal(ui.cards.get(b).speedText.nodeValue,'','paused files never inherit batch speed');
assert.equal(ui.cards.get(a).bar.attrs['aria-valuenow'],'40');
a.text='10 MB / 10 MB';render([a,b,c]);assert.match(ui.cards.get(a).metaText.nodeValue,/Finishing upload/);
a.text='Completed';a.buttons={};render([a,b,c]);assert.equal(ui.cards.get(a).card.dataset.mode,'complete');
b.text='Conflict';b.buttons={Replace:new Button()};render([a,b,c]);assert.equal(ui.cards.get(b).card.dataset.mode,'error');assert.equal(ui.cards.get(a).card.dataset.mode,'complete');
render([b,c]);assert.equal(ui.cards.size,2);assert.equal(ui.list.children.length,2);
console.log('PASS: independent file cards, duplicate names, progress/speed/status, targeted pause/resume/cancel, stable controls, errors and row removal.');
