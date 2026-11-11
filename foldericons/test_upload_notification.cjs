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
class Element {}
class Button extends Element { disabled = false; click() { closes++; } }
let closes = 0, removed = 0, reset = 0, hidden = 0;
let rows = [], callbacks = [], cleared = [];
const prompt = new Element();
prompt.querySelector = () => new Button();
const state = { prompt, completeTimer: null, userOpened: false };
const textFields = Object.fromEntries(['headingText','actionText','nameText','metaText','speedText'].map(k=>[k,{}]));
const notice = { dataset:{}, _ppV96:{...textFields,fill:{style:{}}} };
const context = {
  HTMLElement: Element, HTMLButtonElement: Button, rowMemory: new WeakMap(),
  state, uploadPrompt:()=>prompt, uploadRows:()=>rows, hideUploadPrompt:()=>hidden++,
  renderUploadCards:()=>{}, ensureNotice:()=>notice, setText:(node,value)=>node.text=value, updateRowControls:()=>{},
  formatBytes:String, formatRemaining:String, removeNotice:()=>removed++, resetSession:()=>reset++,
  window:{setTimeout:fn=>{callbacks.push(fn);return callbacks.length;}},
  clearTimeout:id=>cleared.push(id),
};
vm.createContext(context);
vm.runInContext(['parseByteValue','rowProgress','rowName','summarizeRows','closeUploadPrompt','render'].map(extract).join('\n'), context);
function row(text, actions = [], directory = false) {
  const result = new Element();
  result.querySelector = selector => {
    if (selector === '.file-name') return {textContent:'Test upload'};
    if (selector === '.vue-simple-progress-text') return directory ? null : {textContent:text};
    if (selector === '.vue-simple-progress-text, .status-label') return {textContent:text};
    const action = selector.match(/aria-label="([^"]+)"/);
    return action && actions.includes(action[1]) ? new Button() : null;
  };
  return result;
}
rows = [row('128 MB / 128 MB',['Pause','Cancel'])];
let summary = context.summarizeRows(rows);
assert.equal(summary.percent,100);
assert.equal(summary.complete,false,'100% sent is not a server-confirmed completion');
assert.equal(context.closeUploadPrompt(),false);
assert.equal(closes,0);
context.render(summary,{speed:0});
assert.equal(notice._ppV96.headingText.text,'Finishing upload');
assert.equal(callbacks.length,0);

for (const actions of [['Resume'],['Retry'],['Replace']]) {
  rows = [row('128 MB / 128 MB',actions)];
  assert.equal(context.summarizeRows(rows).complete,false);
}
rows = [row('Conflict',['Replace'])];
assert.equal(context.summarizeRows(rows).errors,1);
rows = [row('Completed'),row('pending',[],true)];
assert.equal(context.summarizeRows(rows).files,2,'directories count toward queue completion');
assert.equal(context.summarizeRows(rows).complete,false);

rows = [row('Completed')];
summary = context.summarizeRows(rows);
assert.equal(summary.complete,true);
context.render(summary,{speed:0});
assert.equal(callbacks.length,1);
rows = [row('1 MB / 128 MB',['Pause'])];
context.render(context.summarizeRows(rows),{speed:0});
assert.deepEqual(cleared,[1],'new work disarms completion timeout');
callbacks[0]();
assert.equal(closes,0,'even an already-dispatched stale timeout cannot close an active queue');
assert.equal(removed,0);
assert.equal(reset,0);
assert(hidden>0);

rows = [row('Completed')];
context.render(context.summarizeRows(rows),{speed:0});
callbacks[1]();
assert.equal(closes,1,'a confirmed completed queue can close normally');
assert.equal(removed,1);
console.log('PASS: upload finalisation, pause/error/conflict/directory states and completion-timer races.');
