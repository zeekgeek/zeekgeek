# Accessibility notes

This project is built for someone with a disability who relies on voice. The
design choices below are intentional. Please keep them if you extend the code.

## Principles

1. **Voice first, but never voice only.** Every action can be done by voice
   (Siri), by a big tap target, or by typing. If one input method is hard on a
   given day, another always works.
2. **Lean on native iOS accessibility.** Siri, Voice Control, Back Tap, the
   Action Button, AssistiveTouch, and Dictation are mature, well-supported, and
   already tuned for assistive use. We route through them instead of trying to
   reinvent speech recognition in a browser (which is unreliable on iOS).
3. **Short, spoken-friendly replies.** The server returns a single `speak`
   sentence designed to be read aloud — no jargon, no long lists.
4. **Forgiving input.** Dictation adds punctuation, changes case, and mishears
   small words. The router normalizes text and matches on contained phrases, so
   "Lights on!!" and "turn the lights on" both work.

## In the web dashboard (PWA)

- **Large tap targets** — minimum 64px (76px in large-text mode), well above the 44px guideline.
- **High-contrast mode** and **extra-large text** toggles in Settings.
- **Respects `prefers-reduced-motion`** — animations are disabled for users who need that.
- **Screen-reader support** — semantic landmarks, `aria-live` regions for spoken replies, descriptive labels, and a skip link.
- **Keyboard accessible** — visible focus outlines, Escape closes dialogs.
- **Speech synthesis** reads replies aloud (with a "Say that again" button).
- **Offline shell** — the interface still opens without a connection (service worker), so the UI is always there.
- **Emergency command** is visually distinct (red border) and is the first thing wired for one-tap use.

## Things to keep in mind when adding features

- Don't remove the typed and tap fallbacks.
- Keep new spoken responses to one clear sentence.
- Keep color contrast high; test with high-contrast mode on.
- Make new buttons at least `var(--tap-min)` tall.
- Put any new important alerts in an `aria-live` region.
