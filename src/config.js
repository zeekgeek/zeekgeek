import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, '..');

/**
 * Minimal .env loader so we don't need an extra dependency.
 * Only sets variables that are not already present in the environment.
 */
function loadDotEnv() {
  const envPath = path.join(rootDir, '.env');
  if (!fs.existsSync(envPath)) return;
  const text = fs.readFileSync(envPath, 'utf8');
  for (const rawLine of text.split('\n')) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (!(key in process.env)) {
      process.env[key] = value;
    }
  }
}

loadDotEnv();

export const config = {
  rootDir,
  port: Number(process.env.PORT) || 3000,
  accessToken: process.env.ACCESS_TOKEN || '',
  allowedOrigins: (process.env.ALLOWED_ORIGINS || '*')
    .split(',')
    .map((o) => o.trim())
    .filter(Boolean),
  assistantName: process.env.ASSISTANT_NAME || 'Zeek',
  userName: process.env.USER_NAME || 'Andrew',
  dataDir: path.join(rootDir, 'data'),
  runtimeDir: path.join(rootDir, 'data', 'runtime'),
};

export function tokenConfigured() {
  return Boolean(config.accessToken && config.accessToken !== 'change-me-to-a-long-random-secret');
}
