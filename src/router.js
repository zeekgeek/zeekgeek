import { skills } from './skills.js';

/**
 * Normalize spoken/dictated text so matching is forgiving:
 * lowercase, collapse whitespace, and strip trailing punctuation that
 * dictation engines love to add ("turn on the lights." -> "turn on the lights").
 */
export function normalize(text) {
  return String(text || '')
    .toLowerCase()
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/[.!?,;:]+$/g, '')
    .trim();
}

/**
 * Try to match a single custom command against the normalized text.
 * A command matches if any of its phrases is contained in the text, OR
 * matches its optional `pattern` (a RegExp source string).
 */
function matchCustomCommand(command, normalized) {
  if (command.pattern) {
    try {
      const re = new RegExp(command.pattern, 'i');
      const m = normalized.match(re);
      if (m) return { groups: m.slice(1) };
    } catch {
      /* ignore invalid user-supplied pattern */
    }
  }
  const phrases = command.phrases || [];
  for (const phrase of phrases) {
    const p = normalize(phrase);
    if (p && (normalized === p || normalized.includes(p))) {
      return { groups: [] };
    }
  }
  return null;
}

async function runWebhook(webhook, context) {
  const fetchImpl = context.fetchImpl || globalThis.fetch;
  const method = (webhook.method || 'POST').toUpperCase();
  const headers = { 'Content-Type': 'application/json', ...(webhook.headers || {}) };
  const init = { method, headers };
  if (method !== 'GET' && method !== 'HEAD') {
    init.body = JSON.stringify(webhook.body ?? { text: context.text });
  }
  const res = await fetchImpl(webhook.url, init);
  return { ok: res.ok, status: res.status };
}

/**
 * Route a piece of text to either a user-defined command or a built-in skill.
 * Returns { matched, intent, say, data }.
 */
export async function route(rawText, ctx) {
  const text = String(rawText || '');
  const normalized = normalize(text);

  if (!normalized) {
    return {
      matched: false,
      intent: 'empty',
      say: `I didn't hear anything. Please try again.`,
    };
  }

  // 1) User-defined commands win, so a caregiver can override or extend behavior.
  for (const command of ctx.store.getCustomCommands()) {
    const m = matchCustomCommand(command, normalized);
    if (!m) continue;

    let say = command.say || `Done.`;
    const data = { command: command.id || command.phrases?.[0] };

    if (command.webhook) {
      try {
        const result = await runWebhook(command.webhook, { ...ctx, text });
        data.webhook = result;
        if (!result.ok) {
          say = command.errorSay || `I tried, but that automation didn't respond correctly.`;
        }
      } catch (err) {
        data.webhook = { ok: false, error: String(err?.message || err) };
        say = command.errorSay || `I couldn't reach that automation right now.`;
      }
    }

    ctx.store.addHistory({ type: 'command', intent: command.id || 'custom', text, say, source: 'custom' });
    return { matched: true, intent: command.id || 'custom', say, data };
  }

  // 2) Built-in skills.
  for (const skill of skills) {
    const match = skill.test(normalized);
    if (!match) continue;
    const result = await skill.run({ text, normalized, match: match === true ? {} : match, ctx });
    if (skill.id !== 'reminder' && skill.id !== 'note') {
      // reminder/note already log themselves with the saved item text
      ctx.store.addHistory({ type: 'skill', intent: skill.id, text, say: result.say, source: 'skill' });
    }
    return { matched: true, intent: skill.id, say: result.say, data: result.data || {} };
  }

  // 3) Nothing matched.
  ctx.store.addHistory({ type: 'unmatched', intent: 'unknown', text, source: 'skill' });
  return {
    matched: false,
    intent: 'unknown',
    say: `I'm not sure how to help with that yet. Say "help" to hear what I can do, or a caregiver can add it as a new command.`,
  };
}
