import fs from 'node:fs';
import path from 'node:path';
import { config } from './config.js';

/**
 * Tiny JSON-file backed store. No database required so Andrew (or a caregiver)
 * can run this on anything: a Raspberry Pi, an old laptop, or a cheap VPS.
 */

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return fallback;
  }
}

function writeJson(file, value) {
  ensureDir(path.dirname(file));
  fs.writeFileSync(file, JSON.stringify(value, null, 2));
}

const HISTORY_LIMIT = 200;

export function createStore(options = {}) {
  const dataDir = options.dataDir || config.dataDir;
  const runtimeDir = options.runtimeDir || config.runtimeDir;
  const historyFile = path.join(runtimeDir, 'history.json');
  const customCommandsFile = path.join(dataDir, 'commands.json');
  const exampleCommandsFile = path.join(dataDir, 'commands.example.json');

  ensureDir(dataDir);
  ensureDir(runtimeDir);

  function getCustomCommands() {
    if (fs.existsSync(customCommandsFile)) {
      return readJson(customCommandsFile, []);
    }
    // Fall back to the bundled examples so the system works out of the box.
    return readJson(exampleCommandsFile, []);
  }

  function getHistory() {
    return readJson(historyFile, []);
  }

  function addHistory(entry) {
    const history = getHistory();
    history.unshift({ ...entry, at: new Date().toISOString() });
    writeJson(historyFile, history.slice(0, HISTORY_LIMIT));
    return entry;
  }

  function clearHistory() {
    writeJson(historyFile, []);
  }

  return { getCustomCommands, getHistory, addHistory, clearHistory, customCommandsFile };
}
