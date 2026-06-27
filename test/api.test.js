import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createApp } from '../src/app.js';
import { createStore } from '../src/store.js';

let server;
let baseUrl;
let tmp;

before(async () => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'zeek-test-'));
  const dataDir = path.join(tmp, 'data');
  const runtimeDir = path.join(dataDir, 'runtime');
  fs.mkdirSync(runtimeDir, { recursive: true });
  fs.writeFileSync(
    path.join(dataDir, 'commands.json'),
    JSON.stringify([{ id: 'lights_on', phrases: ['lights on'], say: 'Turning the lights on.' }])
  );

  const store = createStore({ dataDir, runtimeDir });
  const app = createApp({ store });
  await new Promise((resolve) => {
    server = app.listen(0, () => {
      baseUrl = `http://127.0.0.1:${server.address().port}`;
      resolve();
    });
  });
});

after(() => {
  server?.close();
  if (tmp) fs.rmSync(tmp, { recursive: true, force: true });
});

test('GET /api/health reports ok', async () => {
  const res = await fetch(`${baseUrl}/api/health`);
  const json = await res.json();
  assert.equal(res.status, 200);
  assert.equal(json.ok, true);
});

test('POST /api/command returns a spoken reply', async () => {
  const res = await fetch(`${baseUrl}/api/command`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: 'what time is it' }),
  });
  const json = await res.json();
  assert.equal(json.ok, true);
  assert.equal(json.intent, 'time');
  assert.ok(json.speak && json.speak.length > 0);
});

test('custom command from data file is used', async () => {
  const res = await fetch(`${baseUrl}/api/command`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: 'lights on' }),
  });
  const json = await res.json();
  assert.equal(json.intent, 'lights_on');
  assert.equal(json.speak, 'Turning the lights on.');
});

test('GET /api/commands lists custom and built-in commands', async () => {
  const res = await fetch(`${baseUrl}/api/commands`);
  const json = await res.json();
  assert.equal(json.ok, true);
  const ids = json.commands.map((c) => c.id);
  assert.ok(ids.includes('lights_on'));
  assert.ok(ids.includes('time'));
});

test('history records issued commands', async () => {
  const res = await fetch(`${baseUrl}/api/history`);
  const json = await res.json();
  assert.equal(json.ok, true);
  assert.ok(json.history.length >= 1);
});

test('command via GET query string works (for NFC tags / bookmarks)', async () => {
  const res = await fetch(`${baseUrl}/api/command?text=${encodeURIComponent('hello')}`);
  const json = await res.json();
  assert.equal(json.intent, 'greeting');
});

test('the dashboard HTML is served at the root', async () => {
  const res = await fetch(`${baseUrl}/`);
  const html = await res.text();
  assert.match(html, /Tap to talk/);
});
