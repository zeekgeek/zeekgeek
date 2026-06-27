/**
 * Built-in skills.
 *
 * Each skill is an intent with:
 *   - id: stable identifier
 *   - description: human readable, shown in the dashboard + "what can you do"
 *   - examples: phrases a person might say (also used to build help)
 *   - test(text): returns a match object (truthy) or null
 *   - run({ text, match, ctx }): returns { say, data? }  (say = words spoken back)
 *
 * Skills are intentionally simple and dependency-free. Anything that needs to
 * touch the real world (lights, messages, etc.) is delivered through a webhook
 * defined in data/commands.json so non-developers can wire it up.
 */

function spokenList(items) {
  if (items.length === 0) return 'nothing yet';
  if (items.length === 1) return items[0];
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

function timeOfDayGreeting(date = new Date()) {
  const h = date.getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

export const skills = [
  {
    id: 'greeting',
    description: 'Friendly greeting and check-in.',
    examples: ['hello', 'hi', 'good morning', 'hey there'],
    test: (t) => /\b(hello|hi|hey|good morning|good afternoon|good evening|howdy)\b/.test(t),
    run: ({ ctx }) =>
      ({ say: `${timeOfDayGreeting()}, ${ctx.config.userName}. I'm here and listening. What would you like to do?` }),
  },

  {
    id: 'help',
    description: 'Lists what you can ask for.',
    examples: ['help', 'what can you do', 'what can i say', 'commands'],
    test: (t) => /\b(help|what can (you|i) (do|say)|commands|options)\b/.test(t),
    run: ({ ctx }) => {
      const builtin = ['set a reminder', 'take a note', 'what time is it', 'run my morning routine'];
      const custom = ctx.store.getCustomCommands().map((c) => (c.phrases && c.phrases[0]) || c.id).filter(Boolean);
      const all = [...builtin, ...custom].slice(0, 8);
      return { say: `You can say things like: ${spokenList(all)}. You can also just tell me what you need.` };
    },
  },

  {
    id: 'time',
    description: 'Tells the current time.',
    examples: ['what time is it', 'tell me the time', 'current time'],
    test: (t) => /\b(what(?:'s| is)? the time|what time is it|current time|tell me the time)\b/.test(t),
    run: () => {
      const now = new Date();
      const time = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
      return { say: `It's ${time}.`, data: { time: now.toISOString() } };
    },
  },

  {
    id: 'date',
    description: 'Tells the current date.',
    examples: ["what's the date", 'what day is it', "today's date"],
    test: (t) => /\b(what(?:'s| is)? the date|what day is it|today'?s date)\b/.test(t),
    run: () => {
      const now = new Date();
      const date = now.toLocaleDateString([], {
        weekday: 'long',
        month: 'long',
        day: 'numeric',
        year: 'numeric',
      });
      return { say: `Today is ${date}.`, data: { date: now.toISOString() } };
    },
  },

  {
    id: 'reminder',
    description: 'Saves a reminder.',
    examples: ['remind me to take my medication at 8', 'set a reminder to call mom', 'reminder: stretch'],
    test: (t) => {
      const m = t.match(/\b(?:remind me to|set a reminder(?: to)?|reminder:?)\s+(.+)/);
      return m ? { what: m[1].trim() } : null;
    },
    run: ({ match, ctx }) => {
      ctx.store.addHistory({ type: 'reminder', text: match.what, source: 'skill' });
      return { say: `Okay, I'll remind you to ${match.what}.`, data: { reminder: match.what } };
    },
  },

  {
    id: 'note',
    description: 'Saves a quick note.',
    examples: ['take a note that the nurse visits friday', 'note: the front door code changed', 'make a note to reorder gloves'],
    test: (t) => {
      const m = t.match(/\b(?:take a note(?: that)?|make a note(?: to)?|note:?)\s+(.+)/);
      return m ? { what: m[1].trim() } : null;
    },
    run: ({ match, ctx }) => {
      ctx.store.addHistory({ type: 'note', text: match.what, source: 'skill' });
      return { say: `Got it. I saved a note: ${match.what}.`, data: { note: match.what } };
    },
  },

  {
    id: 'status',
    description: 'A quick well-being / system check-in.',
    examples: ['how are things', 'status', 'everything okay'],
    test: (t) => /\b(how are things|status|everything ok(?:ay)?|all good)\b/.test(t),
    run: ({ ctx }) => {
      const recent = ctx.store.getHistory().slice(0, 3).map((h) => h.text || h.intent).filter(Boolean);
      const tail = recent.length ? ` Recently you asked about: ${spokenList(recent)}.` : '';
      return { say: `Everything is running smoothly and I'm ready to help.${tail}` };
    },
  },
];

export { spokenList, timeOfDayGreeting };
