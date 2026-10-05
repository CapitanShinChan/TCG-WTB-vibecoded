const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('catalogue warning distinguishes stale, unavailable, and healthy data', async () => {
  const source = fs.readFileSync(path.join(__dirname, '../app/static/catalogue.js'), 'utf8');
  const cases = [
    [{ available: true, stale: true, version: '5.2.3' }, false, /cached catalogue 5.2.3/i],
    [{ available: true, stale: false, persistent: false }, false, /could not be saved/i],
    [{ available: false, error: 'offline' }, false, /unavailable/i],
    [{ available: true, stale: false }, true, /^$/],
    [{ available: false, error: null }, true, /^$/],
  ];
  for (const [status, expectedHidden, text] of cases) {
    let hidden = true;
    const element = { textContent: '', classList: { toggle: (_, value) => { hidden = value; } } };
    const context = { window: {}, document: { getElementById: () => element },
      fetch: async () => ({ ok: true, json: async () => status }) };
    vm.runInNewContext(source, context);
    await context.window.refreshCatalogueStatus();
    assert.equal(hidden, expectedHidden);
    assert.match(element.textContent, text);
  }
});
