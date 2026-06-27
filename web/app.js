// Zeek voice automation dashboard — vanilla JS, no build step, iOS-friendly.

const $ = (sel) => document.querySelector(sel);

const els = {
  talkBtn: $('#talk-btn'),
  talkLabel: $('#talk-label'),
  talkHint: $('#talk-hint'),
  heard: $('#heard'),
  response: $('#response'),
  repeatBtn: $('#repeat-btn'),
  typeForm: $('#type-form'),
  typeInput: $('#type-input'),
  commands: $('#commands'),
  history: $('#history'),
  settingsBtn: $('#settings-btn'),
  settingsPanel: $('#settings-panel'),
  settingsClose: $('#settings-close'),
  settingsSave: $('#settings-save'),
  settingsStatus: $('#settings-status'),
  serverUrl: $('#server-url'),
  accessToken: $('#access-token'),
  autospeak: $('#autospeak'),
  bigtext: $('#bigtext'),
  highcontrast: $('#highcontrast'),
};

// --- Settings -------------------------------------------------------------

const SETTINGS_KEY = 'zeek.settings.v1';
const defaultSettings = {
  serverUrl: '',
  token: '',
  autospeak: true,
  bigtext: false,
  highcontrast: false,
};

function loadSettings() {
  try {
    return { ...defaultSettings, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') };
  } catch {
    return { ...defaultSettings };
  }
}

function saveSettings(s) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
}

let settings = loadSettings();

function applyDisplaySettings() {
  document.body.classList.toggle('bigtext', settings.bigtext);
  document.body.classList.toggle('highcontrast', settings.highcontrast);
}

// --- API ------------------------------------------------------------------

function apiBase() {
  return (settings.serverUrl || '').replace(/\/+$/, '');
}

async function api(path, { method = 'GET', body } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (settings.token) headers['X-Access-Token'] = settings.token;
  const res = await fetch(apiBase() + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Request failed (${res.status})`);
  }
  return res.json();
}

// --- Speech output --------------------------------------------------------

let lastSpoken = '';

function speak(text) {
  lastSpoken = text;
  els.repeatBtn.hidden = !text;
  if (!settings.autospeak) return;
  if (!('speechSynthesis' in window)) return;
  try {
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1;
    u.pitch = 1;
    window.speechSynthesis.speak(u);
  } catch {
    /* speech synthesis is best-effort */
  }
}

// --- Speech input (progressive enhancement) -------------------------------

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let listening = false;

function setupRecognition() {
  if (!SpeechRecognition) {
    els.talkHint.textContent =
      'Voice input is best through "Hey Siri". Tap a command below, or type one.';
    els.talkLabel.textContent = 'Use Siri or tap';
    return;
  }
  recognition = new SpeechRecognition();
  recognition.lang = 'en-US';
  recognition.interimResults = true;
  recognition.continuous = false;

  recognition.onresult = (event) => {
    let transcript = '';
    for (const result of event.results) transcript += result[0].transcript;
    els.heard.textContent = `You: ${transcript}`;
    if (event.results[event.results.length - 1].isFinal) {
      sendCommand(transcript);
    }
  };
  recognition.onerror = () => stopListening();
  recognition.onend = () => stopListening();
}

function startListening() {
  if (!recognition) return;
  try {
    // A spoken utterance here also "unlocks" speechSynthesis on iOS.
    speak('');
    recognition.start();
    listening = true;
    els.talkBtn.classList.add('listening');
    els.talkLabel.textContent = 'Listening…';
  } catch {
    stopListening();
  }
}

function stopListening() {
  listening = false;
  els.talkBtn.classList.remove('listening');
  els.talkLabel.textContent = SpeechRecognition ? 'Tap to talk' : 'Use Siri or tap';
  if (recognition) {
    try { recognition.stop(); } catch { /* noop */ }
  }
}

// --- Core actions ---------------------------------------------------------

async function sendCommand(text) {
  const trimmed = (text || '').trim();
  if (!trimmed) return;
  els.heard.textContent = `You: ${trimmed}`;
  els.response.textContent = '…';
  try {
    const result = await api('/api/command', { method: 'POST', body: { text: trimmed } });
    const reply = result.speak || result.say || 'Done.';
    els.response.textContent = reply;
    speak(reply);
    loadHistory();
  } catch (err) {
    const msg =
      'I could not reach the server. Open Settings and check the server address and access token.';
    els.response.textContent = `${msg} (${err.message})`;
    speak(msg);
  }
}

async function loadCommands() {
  try {
    const { commands } = await api('/api/commands');
    renderCommands(commands);
  } catch (err) {
    els.commands.innerHTML = '';
    els.commands.setAttribute('aria-busy', 'false');
    const p = document.createElement('p');
    p.className = 'muted';
    p.textContent = 'Connect to your server in Settings to load commands.';
    els.commands.appendChild(p);
  }
}

function renderCommands(commands) {
  els.commands.innerHTML = '';
  els.commands.setAttribute('aria-busy', 'false');
  const dangerIds = new Set(['i_need_help', 'emergency']);
  for (const cmd of commands) {
    const phrase = (cmd.examples && cmd.examples[0]) || cmd.id;
    const btn = document.createElement('button');
    btn.className = 'command-card' + (dangerIds.has(cmd.id) ? ' danger' : '');
    btn.setAttribute('role', 'listitem');
    btn.type = 'button';

    const name = document.createElement('span');
    name.className = 'cmd-name';
    name.textContent = humanize(cmd.id);
    const desc = document.createElement('span');
    desc.className = 'cmd-desc';
    desc.textContent = cmd.description || `Say: "${phrase}"`;

    btn.append(name, desc);
    btn.setAttribute('aria-label', `${humanize(cmd.id)}. ${cmd.description || ''}`.trim());
    btn.addEventListener('click', () => sendCommand(phrase));
    els.commands.appendChild(btn);
  }
}

function humanize(id) {
  return String(id || '')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

async function loadHistory() {
  try {
    const { history } = await api('/api/history');
    els.history.innerHTML = '';
    for (const item of history.slice(0, 12)) {
      const li = document.createElement('li');
      const time = document.createElement('span');
      time.className = 'h-time';
      time.textContent = new Date(item.at).toLocaleString();
      const body = document.createElement('span');
      body.textContent = item.text || item.intent || item.type;
      li.append(time, body);
      els.history.appendChild(li);
    }
  } catch {
    /* history is non-critical */
  }
}

// --- Settings drawer ------------------------------------------------------

function openSettings() {
  els.serverUrl.value = settings.serverUrl;
  els.accessToken.value = settings.token;
  els.autospeak.checked = settings.autospeak;
  els.bigtext.checked = settings.bigtext;
  els.highcontrast.checked = settings.highcontrast;
  els.settingsPanel.hidden = false;
  els.settingsBtn.setAttribute('aria-expanded', 'true');
  els.serverUrl.focus();
}

function closeSettings() {
  els.settingsPanel.hidden = true;
  els.settingsBtn.setAttribute('aria-expanded', 'false');
  els.settingsBtn.focus();
}

function persistSettings() {
  settings = {
    serverUrl: els.serverUrl.value.trim(),
    token: els.accessToken.value.trim(),
    autospeak: els.autospeak.checked,
    bigtext: els.bigtext.checked,
    highcontrast: els.highcontrast.checked,
  };
  saveSettings(settings);
  applyDisplaySettings();
  els.settingsStatus.textContent = 'Saved.';
  loadCommands();
  loadHistory();
  setTimeout(() => (els.settingsStatus.textContent = ''), 1500);
}

// --- Wire up --------------------------------------------------------------

function init() {
  applyDisplaySettings();
  setupRecognition();
  setupRecognition.done = true;

  els.talkBtn.addEventListener('click', () => {
    if (!SpeechRecognition) {
      els.response.textContent =
        'For full hands-free voice, use "Hey Siri, Zeek" with the Shortcut. Here you can tap a command or type one.';
      speak('For full hands free voice, use Hey Siri with the shortcut. Here you can tap a command or type one.');
      return;
    }
    listening ? stopListening() : startListening();
  });

  els.repeatBtn.addEventListener('click', () => {
    settings.autospeak = true;
    speak(lastSpoken);
  });

  els.typeForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = els.typeInput.value;
    els.typeInput.value = '';
    sendCommand(text);
  });

  els.settingsBtn.addEventListener('click', openSettings);
  els.settingsClose.addEventListener('click', closeSettings);
  els.settingsSave.addEventListener('click', persistSettings);
  els.settingsPanel.addEventListener('click', (e) => {
    if (e.target === els.settingsPanel) closeSettings();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !els.settingsPanel.hidden) closeSettings();
  });

  loadCommands();
  loadHistory();

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('./sw.js').catch(() => {});
  }
}

init();
