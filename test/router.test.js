import { test } from 'node:test';
import assert from 'node:assert/strict';
import { route, normalize } from '../src/router.js';

function makeCtx(customCommands = []) {
  const history = [];
  return {
    config: { assistantName: 'Zeek', userName: 'Andrew' },
    store: {
      getCustomCommands: () => customCommands,
      getHistory: () => history,
      addHistory: (e) => history.push(e),
    },
    _history: history,
  };
}

test('normalize lowercases, trims, and strips trailing punctuation', () => {
  assert.equal(normalize('  Turn ON the Lights!! '), 'turn on the lights');
  assert.equal(normalize('What time is it?'), 'what time is it');
});

test('empty input is handled gracefully', async () => {
  const res = await route('   ', makeCtx());
  assert.equal(res.matched, false);
  assert.equal(res.intent, 'empty');
});

test('built-in time skill matches', async () => {
  const res = await route('what time is it', makeCtx());
  assert.equal(res.matched, true);
  assert.equal(res.intent, 'time');
  assert.match(res.say, /It's/);
});

test('reminder skill captures the task and logs it', async () => {
  const ctx = makeCtx();
  const res = await route('remind me to take my medication', ctx);
  assert.equal(res.intent, 'reminder');
  assert.equal(res.data.reminder, 'take my medication');
  assert.equal(ctx._history.at(-1).type, 'reminder');
});

test('note skill captures the note text', async () => {
  const res = await route('take a note that the nurse visits friday', makeCtx());
  assert.equal(res.intent, 'note');
  assert.equal(res.data.note, 'the nurse visits friday');
});

test('custom command matches by phrase and wins over built-ins', async () => {
  const ctx = makeCtx([
    { id: 'lights_on', phrases: ['turn on the lights', 'lights on'], say: 'Turning the lights on.' },
  ]);
  const res = await route('Lights on!', ctx);
  assert.equal(res.matched, true);
  assert.equal(res.intent, 'lights_on');
  assert.equal(res.say, 'Turning the lights on.');
});

test('custom command supports a regex pattern', async () => {
  const ctx = makeCtx([
    { id: 'set_temp', pattern: 'set (?:the )?temperature to (\\d+)', say: 'Adjusting the temperature.' },
  ]);
  const res = await route('set the temperature to 72', ctx);
  assert.equal(res.intent, 'set_temp');
});

test('custom command fires a webhook and reports failure with errorSay', async () => {
  let called = null;
  const ctx = makeCtx([
    {
      id: 'help',
      phrases: ['i need help'],
      say: 'Calling your caregiver.',
      errorSay: 'I could not reach your caregiver.',
      webhook: { url: 'https://example.com/hook', method: 'POST', body: { a: 1 } },
    },
  ]);
  ctx.fetchImpl = async (url, init) => {
    called = { url, init };
    return { ok: false, status: 500 };
  };
  const res = await route('i need help', ctx);
  assert.equal(called.url, 'https://example.com/hook');
  assert.equal(res.say, 'I could not reach your caregiver.');
});

test('custom webhook success keeps the normal say', async () => {
  const ctx = makeCtx([
    { id: 'morning', phrases: ['morning routine'], say: 'Starting your morning.', webhook: { url: 'https://x/y' } },
  ]);
  ctx.fetchImpl = async () => ({ ok: true, status: 200 });
  const res = await route('morning routine', ctx);
  assert.equal(res.say, 'Starting your morning.');
  assert.equal(res.data.webhook.ok, true);
});

test('unknown input returns a helpful fallback', async () => {
  const res = await route('flibbertigibbet zorp', makeCtx());
  assert.equal(res.matched, false);
  assert.equal(res.intent, 'unknown');
  assert.match(res.say, /help/i);
});
