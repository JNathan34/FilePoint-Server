// Exercise production planners without touching real files.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(require('node:path').join(__dirname, 'client.js'), 'utf8');
const context = vm.createContext({TextEncoder});
for (const [start,end] of [['  function bulkRenamePlan(', '  function restoreBulkRenameSelection(']]) {
  const a=source.indexOf(start),b=source.indexOf(end,a);assert(a>0&&b>a);
  vm.runInContext(source.slice(a,b),context);
}
const items=['Photo.JPG','Report.docx'].map(name=>({source:'Drive',path:'/Folder/'+name,name,isDir:false}));
const opts={mode:'number',name:'Trip',start:'1',digits:'2',find:'',replace:'',prefix:'',suffix:''};
const plan=(options=opts,list=items,existing=list)=>context.bulkRenamePlan(list,options,existing);
assert.deepEqual(Array.from(plan(),p=>p.name),['Trip 01.JPG','Trip 02.docx']);
assert(plan().every(p=>!p.error));
assert.deepEqual(Array.from(plan({...opts,mode:'replace',find:'o',replace:'O'}),p=>p.name),['PhOtO.JPG','RepOrt.docx']);
assert.equal(plan({...opts,mode:'text',prefix:'Done ',suffix:' final'})[0].name,'Done Photo final.JPG');
assert(plan(opts,items,[...items,{name:'TRIP 01.JPG'}])[0].error);
assert(plan({...opts,name:'../escape'}).every(p=>p.error));
assert(plan({...opts,start:'1.2'}).every(p=>p.error));
assert(plan({...opts,digits:'999'}).every(p=>p.error));
assert(plan({...opts,name:'x'.repeat(256)}).every(p=>p.error));
const sameExt=['one.txt','two.txt'].map(name=>({source:'Drive',path:'/Folder/'+name,name}));
assert(plan({...opts,mode:'replace',find:'two',replace:'one'},sameExt).some(p=>p.error));
assert(plan({...opts,mode:'replace',find:'',replace:'x'}).every(p=>p.error));
assert(plan({...opts,mode:'text'}).every(p=>!p.changed));
assert.equal(plan(opts,[{name:'Folder.ext',source:'Drive',path:'/Folder.ext',isDir:true}])[0].name,'Trip 01');
assert.equal(plan(opts,[{name:'.env',source:'Drive',path:'/.env'}])[0].name,'Trip 01');
assert(plan({...opts,mode:'replace',find:'Photo',replace:'CON'})[0].error);
console.log('PASS: numbering; replace; prefix/suffix; extension preservation; collisions; invalid/reserved names; folders; dotfiles; unchanged names.');
