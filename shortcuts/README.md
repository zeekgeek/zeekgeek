# Apple Shortcuts kit

The full, illustrated walkthrough lives in [`../docs/SETUP-IOS.md`](../docs/SETUP-IOS.md).
This folder is a quick reference plus a machine-readable description of the
shortcut so it can be rebuilt or automated later.

## The one shortcut that does everything

Name it **Zeek** (the name becomes the "Hey Siri" phrase). It dictates speech,
posts it to the server, and speaks the reply.

```
Hey Siri, Zeek
  → Dictate Text            (captures what Andrew says)
  → Get Contents of URL     (POST https://YOUR-SERVER/api/command)
        Header: Content-Type: application/json
        Header: X-Access-Token: <your ACCESS_TOKEN>
        Body (JSON): { "text": <Dictated Text> }
  → Get Dictionary Value    (key: speak)
  → Speak Text              (reads the answer aloud)
```

## Reference definition

`zeek-shortcut.json` describes the same flow in a readable structure. It is a
specification you (or a script) can follow when building the shortcut in the
Shortcuts app — it is **not** an importable `.shortcut` binary, because those
are signed, device-specific files.

## Why a single dictation shortcut?

Because the server understands free-form text, one shortcut becomes unlimited
commands. Add a new phrase on the server (`data/commands.json`) and it instantly
works by voice — no need to touch the phone again.

## Handy extra shortcuts

| Shortcut name | Body to send | Good for |
|---|---|---|
| Help | `{ "text": "i need help" }` | Lock Screen / Back Tap emergency button |
| Lights | `{ "text": "turn on the lights" }` | One-tap home control |
| Morning | `{ "text": "morning routine" }` | Start-of-day scene |
| Goodnight | `{ "text": "good night" }` | End-of-day scene |

Assign these to the **Action Button**, **Back Tap**, **AssistiveTouch**, or a
Lock Screen widget for one-press access.
