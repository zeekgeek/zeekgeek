import express from 'express';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { config, tokenConfigured } from './config.js';
import { createStore } from './store.js';
import { route } from './router.js';
import { skills } from './skills.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const webDir = path.resolve(__dirname, '..', 'web');

/**
 * Build the Express app. Exported as a factory so tests can inject a custom
 * store (e.g. a temp directory) and so the server entry point stays tiny.
 */
export function createApp(options = {}) {
  const store = options.store || createStore();
  const app = express();

  app.disable('x-powered-by');
  app.use(express.json({ limit: '64kb' }));
  app.use(express.urlencoded({ extended: false }));

  // Permissive but configurable CORS for the PWA.
  app.use((req, res, next) => {
    const origin = req.headers.origin;
    const allowed = config.allowedOrigins;
    if (allowed.includes('*')) {
      res.setHeader('Access-Control-Allow-Origin', '*');
    } else if (origin && allowed.includes(origin)) {
      res.setHeader('Access-Control-Allow-Origin', origin);
      res.setHeader('Vary', 'Origin');
    }
    res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Access-Token');
    if (req.method === 'OPTIONS') return res.sendStatus(204);
    next();
  });

  function getProvidedToken(req) {
    const auth = req.headers.authorization || '';
    if (auth.toLowerCase().startsWith('bearer ')) return auth.slice(7).trim();
    if (req.headers['x-access-token']) return String(req.headers['x-access-token']).trim();
    if (req.query.token) return String(req.query.token).trim();
    if (req.body && req.body.token) return String(req.body.token).trim();
    return '';
  }

  function requireAuth(req, res, next) {
    // If no token is configured we run in "open" local mode but warn loudly.
    if (!tokenConfigured()) return next();
    const provided = getProvidedToken(req);
    if (provided && provided === config.accessToken) return next();
    return res.status(401).json({ ok: false, error: 'Unauthorized. Provide a valid access token.' });
  }

  // --- Public, unauthenticated endpoints -----------------------------------

  app.get('/api/health', (req, res) => {
    res.json({
      ok: true,
      assistant: config.assistantName,
      tokenConfigured: tokenConfigured(),
      time: new Date().toISOString(),
    });
  });

  // --- Authenticated automation endpoints ----------------------------------

  // The heart of the system: accept dictated text, return a spoken reply.
  app.post('/api/command', requireAuth, async (req, res) => {
    const text = req.body?.text ?? req.body?.command ?? req.query.text ?? '';
    try {
      const result = await route(text, { store, config });
      res.json({
        ok: true,
        matched: result.matched,
        intent: result.intent,
        // `speak` is the field the Apple Shortcut reads aloud with "Speak Text".
        speak: result.say,
        say: result.say,
        data: result.data || {},
      });
    } catch (err) {
      res.status(500).json({ ok: false, error: String(err?.message || err), speak: 'Sorry, something went wrong.' });
    }
  });

  // Convenience GET variant so a command can be triggered from a plain URL /
  // browser bookmark / NFC tag without a JSON body.
  app.get('/api/command', requireAuth, async (req, res) => {
    const text = req.query.text || req.query.command || '';
    try {
      const result = await route(text, { store, config });
      res.json({ ok: true, matched: result.matched, intent: result.intent, speak: result.say, say: result.say, data: result.data || {} });
    } catch (err) {
      res.status(500).json({ ok: false, error: String(err?.message || err), speak: 'Sorry, something went wrong.' });
    }
  });

  // List everything the assistant currently understands (built-ins + custom).
  app.get('/api/commands', requireAuth, (req, res) => {
    const builtins = skills.map((s) => ({ id: s.id, description: s.description, examples: s.examples, type: 'builtin' }));
    const custom = store.getCustomCommands().map((c) => ({
      id: c.id || (c.phrases && c.phrases[0]) || 'custom',
      description: c.description || c.say || '',
      examples: c.phrases || [],
      type: 'custom',
    }));
    res.json({ ok: true, commands: [...custom, ...builtins] });
  });

  app.get('/api/history', requireAuth, (req, res) => {
    res.json({ ok: true, history: store.getHistory() });
  });

  app.post('/api/history/clear', requireAuth, (req, res) => {
    store.clearHistory();
    res.json({ ok: true });
  });

  // --- Static PWA dashboard -------------------------------------------------

  app.use(
    express.static(webDir, {
      setHeaders(res, filePath) {
        if (filePath.endsWith('sw.js')) {
          res.setHeader('Cache-Control', 'no-cache');
        }
      },
    })
  );

  // SPA-ish fallback to the dashboard.
  app.get('*', (req, res, next) => {
    if (req.path.startsWith('/api/')) return next();
    res.sendFile(path.join(webDir, 'index.html'));
  });

  app.store = store;
  return app;
}
