const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, 'client.js'), 'utf8');
const start = source.indexOf('  function dismissMicrosoftPanels(event) {');
const end = source.indexOf('\n  async function showMicrosoftVersions(', start);
assert.ok(start > 0 && end > start);
let panels = [];
const dismiss = vm.runInNewContext(source.slice(start, end) + '\ndismissMicrosoftPanels', {
  document: {querySelectorAll: selector => {
    assert.equal(selector, '[data-plexpoint-ms-dismissible]');
    return panels;
  }},
});
const inside = {};
let removed = 0;
panels = [{contains: target => target === inside, remove: () => removed++}];
dismiss({type: 'pointerdown', target: inside});
assert.equal(removed, 0, 'inside clicks must leave panel open');
dismiss({type: 'keydown', key: 'Enter'});
assert.equal(removed, 0, 'other keys must not close panel');
dismiss({type: 'pointerdown', target: {}});
assert.equal(removed, 1, 'outside pointer must close panel');
dismiss({type: 'keydown', key: 'Escape'});
assert.equal(removed, 2, 'Escape must close panel');
panels = [];
assert.doesNotThrow(() => dismiss({type: 'pointerdown', target: {}}));
for (const name of ['showMicrosoftVersions', 'showMicrosoftSessions', 'showSaved', 'showSession']) {
  const body = source.split(`function ${name}(`)[1].split('\n  function ')[0].split('\n  async function ')[0];
  assert.ok(body.includes('panel.setAttribute("data-plexpoint-ms-dismissible", "true")'), name);
}
const choice = source.split('function showMicrosoftChoice(')[1].split('\n  function ')[0];
assert.ok(!choice.includes('data-plexpoint-ms-dismissible'), 'confirmation prompts must not be silently accepted/dismissed');
assert.ok(source.includes('document.addEventListener("pointerdown", dismissMicrosoftPanels, true)'));
console.log('Microsoft panel dismissal: inside/outside clicks, keyboard, empty state and four panel registrations passed.');
