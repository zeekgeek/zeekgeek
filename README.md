# zeekgeek — Zeek Voice Automation Hub

A small, accessibility-first **voice automation hub** built for someone who
relies on voice to control their world from an **iPhone 16 Pro Max** or **iPad**.

It turns a single **"Hey Siri"** phrase into **unlimited, configurable
automations** — turn on lights, run a morning routine, set reminders, or call
for help — and reads a friendly answer back out loud. When voice isn't an
option, there's a big-button, high-contrast web dashboard that does everything
by tap or type instead.

> Built for Andrew. Voice-first, but never voice-only.

---

## Why this is a *better* way

Most "voice automation" projects try to do speech recognition in the browser,
which is unreliable on iOS and a poor fit for assistive use. Instead, Zeek
leans on the parts of iOS that are already the most accessible and dependable:

- **Siri + Dictation** handle the listening (works with Voice Control, Back Tap, the Action Button, AssistiveTouch, etc.).
- **One Apple Shortcut** sends whatever you say to a tiny server you control.
- **The server understands free-form speech** and replies with one clear spoken sentence.
- **A caregiver can add new commands** by editing a plain JSON file — no coding.
- **A web dashboard** provides large tap targets, high-contrast/large-text modes, and read-aloud responses for the moments speaking is hard.

The result: say *"Hey Siri, Zeek"* → *"turn on the lights"* → it happens, and
Zeek tells you it's done. Add a new phrase on the server and it instantly works
by voice, no changes needed on the phone.

---

## What's in the box

```
src/            The automation server (Node + Express, zero database)
  server.js     Entry point
  app.js        Routes + auth + static dashboard hosting
  router.js     Forgiving natural-language matcher
  skills.js     Built-in skills (time, reminders, notes, greeting, help…)
  store.js      JSON-file storage for history + custom commands
  config.js     Env/.env loading
web/            The accessible PWA dashboard (installable to the Home Screen)
data/           commands.example.json — copy to commands.json and customize
shortcuts/      The Apple Shortcuts kit + reference definition
docs/           SETUP-IOS.md (the important one) and ACCESSIBILITY.md
test/           Unit + API tests (run with `npm test`)
```

---

## Quick start

Requirements: **Node.js 20+**.

```bash
# 1. Install
npm install

# 2. Configure
cp .env.example .env
#   then edit .env and set a long random ACCESS_TOKEN:
node -e "console.log(require('crypto').randomBytes(24).toString('hex'))"

# 3. (optional) Add your own commands
cp data/commands.example.json data/commands.json

# 4. Run
npm start
```

Then open the dashboard at **http://localhost:3000** and verify health at
**http://localhost:3000/api/health**.

Try it from the command line:

```bash
curl -s -X POST http://localhost:3000/api/command \
  -H 'Content-Type: application/json' \
  -H 'X-Access-Token: YOUR_TOKEN' \
  -d '{"text":"what time is it"}'
```

---

## Connect Andrew's iPhone / iPad

Follow **[`docs/SETUP-IOS.md`](docs/SETUP-IOS.md)** — it walks through creating
the one **"Zeek"** Apple Shortcut (a one-time, ~5-action setup). After that:

> **"Hey Siri, Zeek"** → say anything → Zeek does it and speaks the answer.

You can also trigger it with **Back Tap**, the **Action Button**, **Voice
Control**, **AssistiveTouch**, or a Lock Screen widget for fully hands-free use.

To install the dashboard as an app: open the server URL in Safari → **Share** →
**Add to Home Screen**.

---

## Adding your own voice commands (no coding)

Edit `data/commands.json`. Each entry maps spoken phrases to a spoken reply and,
optionally, a webhook that performs the real action (smart-home scene, send a
message, alert a caregiver — anything that accepts an HTTP request).

```json
[
  {
    "id": "lights_on",
    "description": "Turn the lights on.",
    "phrases": ["turn on the lights", "lights on"],
    "say": "Turning the lights on.",
    "webhook": { "url": "https://your-home-hub/lights", "method": "POST", "body": { "state": "on" } }
  },
  {
    "id": "set_temp",
    "pattern": "set (?:the )?temperature to (\\d+)",
    "say": "Adjusting the temperature now."
  }
]
```

- `phrases` — match if the dictated text contains any of them (case/punctuation insensitive).
- `pattern` — optional regular expression for flexible matching (e.g. capturing a number).
- `say` — the sentence Zeek speaks back.
- `webhook` — optional HTTP call that does the real-world action.
- `errorSay` — optional sentence spoken if the webhook fails.

Custom commands always take priority over the built-ins, so you can override
anything. See `data/commands.example.json` for a full set, including an
**"I need help"** caregiver alert.

---

## Built-in skills (work out of the box)

| Say | Zeek does |
|---|---|
| "hello" / "good morning" | Friendly greeting + check-in |
| "what time is it" / "what's the date" | Tells time / date |
| "remind me to …" | Saves a reminder |
| "take a note that …" | Saves a note |
| "how are things" | Quick status with recent activity |
| "help" / "what can you do" | Lists available commands |

---

## API reference

All `/api` routes (except `/api/health`) require the token via an
`X-Access-Token` header, `Authorization: Bearer …`, or a `token` query/body
field. If no `ACCESS_TOKEN` is configured the server runs in open local mode and
warns loudly.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Liveness + whether a token is configured |
| `POST` | `/api/command` | Body `{ "text": "…" }` → `{ speak, intent, data }` |
| `GET` | `/api/command?text=…` | Same, for NFC tags / bookmarks |
| `GET` | `/api/commands` | List built-in + custom commands |
| `GET` | `/api/history` | Recent activity |
| `POST` | `/api/history/clear` | Clear history |

The response field used by the Apple Shortcut is **`speak`** — the single
sentence to read aloud.

---

## Security

- Set a long random `ACCESS_TOKEN` before exposing the server beyond localhost.
- Put it behind HTTPS (a reverse proxy, Cloudflare Tunnel, or Tailscale).
- Restrict browser origins with `ALLOWED_ORIGINS` in production.

---

## Development & tests

```bash
npm run dev    # auto-reloading server
npm test       # unit + API tests (Node's built-in test runner)
```

The test suite covers the natural-language router, custom-command precedence,
webhook handling, and the HTTP API.

---

## License

MIT.
