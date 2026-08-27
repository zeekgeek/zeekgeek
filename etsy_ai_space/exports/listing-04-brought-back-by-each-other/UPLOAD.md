# Listing #4 — Brought Back By Each Other

## Design
`images/01-printify-print.png` — clasped hands, snapped chains, cream typography on black.

## BrowserClaw → Printify (local Mac)

1. Start Chrome/BrowserClaw with CDP and log into Printify (Etsy channel connected):

```bash
mkdir -p ~/chrome-cdp-profile
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/chrome-cdp-profile" \
  --no-first-run
```

2. From the repo root:

```bash
source .venv/bin/activate
pip install -e ".[etsy]"

# Preview
python3 -m etsy_ai_space browserclaw-printify \
  --package etsy_ai_space/exports/listing-04-brought-back-by-each-other \
  --dry-run

# Stage draft in Printify (does NOT publish to Etsy)
python3 -m etsy_ai_space browserclaw-printify \
  --package etsy_ai_space/exports/listing-04-brought-back-by-each-other \
  --cdp-url 9222 \
  --reuse-tab \
  --wait
```

Or:

```bash
./scripts/local-browserclaw-printify.sh . listing-04-brought-back-by-each-other
```

3. In Printify: finish mockups/colors → **Publish to Etsy**.

4. Mark done:

```bash
python3 -m etsy_ai_space printify mark-submitted --all
```

## Product defaults
- Comfort Colors 1717
- Price: $26.99
- Colors: Black, Pepper, Charcoal, Navy
- Sizes: S–2XL
