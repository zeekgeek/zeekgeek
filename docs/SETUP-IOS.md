# iPhone & iPad setup (the hands-free "Hey Siri" way)

This is the most important guide. It gives Andrew **fully hands-free voice
automation** using the part of iOS that is already the most accessible: **Siri**.

The idea is simple and powerful:

> One Apple Shortcut named **"Zeek"** listens to whatever you say, sends it to
> your server, and reads the answer back to you. Because it accepts *anything*
> you dictate, a single shortcut becomes unlimited voice commands.

You only have to set this up **once**.

---

## What you need

- An iPhone 16 Pro Max / iPad (any modern iOS 16+ device works) — Andrew's device.
- The Zeek server running somewhere the phone can reach (see the main `README.md`).
  - For testing on the same Wi-Fi: `http://<your-computer-ip>:3000`
  - For anywhere access: a small VPS, or a tunnel like Cloudflare Tunnel / Tailscale.
- The **access token** you put in the server's `.env` file.

---

## Step 1 — Create the "Zeek" shortcut

1. Open the **Shortcuts** app (built into iOS).
2. Tap **+** (top right) to create a new shortcut.
3. Tap the name at the top and rename it to **Zeek** (this becomes the Siri phrase).
4. Add these actions in order (tap **Add Action** and search for each):

   | # | Action | What to set |
   |---|--------|-------------|
   | 1 | **Dictate Text** | Language: English. (This is what captures Andrew's voice.) |
   | 2 | **Text** | Paste your **access token** here. Name this variable later if you like. |
   | 3 | **Get Contents of URL** | See settings below. |
   | 4 | **Get Dictionary Value** | Key: `speak`. Input: the result of step 3. |
   | 5 | **Speak Text** | Input: the value from step 4. |

5. Configure **Get Contents of URL** (step 3):
   - **URL:** `https://YOUR-SERVER/api/command`
   - Tap **Show More**.
   - **Method:** `POST`
   - **Headers:** add two:
     - `Content-Type` = `application/json`
     - `X-Access-Token` = *(the Text from step 2 — tap the field and pick the token variable)*
   - **Request Body:** `JSON`
     - Add field **`text`** (type *Text*) = the **Dictated Text** variable from step 1.

6. Tap **Done**.

That's it. The shortcut now: hears you → asks the server → speaks the reply.

---

## Step 2 — Use it hands-free

Just say:

> **"Hey Siri, Zeek"**

Siri runs the shortcut, plays the listening tone, and you say what you want:

- *"Turn on the lights"*
- *"Remind me to take my medication"*
- *"Run my morning routine"*
- *"I need help"*

The server replies and Siri reads the answer out loud. No tapping required.

> Tip: You can also rename the shortcut to a phrase that's easy for Andrew to
> say, like **"Assistant"** or **"Computer"**. The shortcut's name *is* the
> trigger phrase.

---

## Step 3 (optional) — Even faster triggers

iOS gives Andrew several ways to fire the shortcut, pick whatever suits him:

- **Back Tap:** Settings → Accessibility → Touch → Back Tap → Double Tap → choose the **Zeek** shortcut. Now a double-tap on the back of the phone starts it.
- **Action Button** (iPhone 15/16 Pro): Settings → Action Button → Shortcut → **Zeek**. One press to talk.
- **Home Screen / Lock Screen widget:** Add a Shortcuts widget so there's a big button to tap.
- **AssistiveTouch:** assign the shortcut to the floating button for users who can't use the side buttons.
- **Voice Control** (fully hands-free, no "Hey Siri" needed): Settings → Accessibility → Voice Control. Create a custom command that runs the **Zeek** shortcut on a phrase Andrew chooses.

---

## Step 4 (optional) — Dedicated one-tap shortcuts

For the most important or hardest-to-say commands, make extra shortcuts that
skip dictation entirely. Example: an **"I need help"** shortcut that sends a
fixed command.

1. New shortcut → name it **Help**.
2. **Get Contents of URL** → same URL/headers as above, body `{"text": "i need help"}`.
3. **Get Dictionary Value** (`speak`) → **Speak Text**.
4. Add it to the Lock Screen, set it as the Action Button, or a Back Tap.

Now help is one press away even if Andrew can't speak a full sentence.

---

## Troubleshooting

- **"Unauthorized"** spoken or no reply → the `X-Access-Token` header doesn't match the server's `ACCESS_TOKEN`. Re-check both.
- **Nothing happens** → confirm the phone can open `https://YOUR-SERVER/api/health` in Safari and shows `{"ok":true}`.
- **It hears but does the wrong thing** → add or adjust phrases in `data/commands.json` on the server (see the main README). Custom commands always win.
- **Siri won't recognize the name** → rename the shortcut to something distinct and easy to pronounce.
