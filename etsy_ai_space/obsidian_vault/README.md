# Etsy AI Space — archives room

This folder is the agent memory vault. Creative briefs are written here automatically
when you run:

```bash
python3 -m etsy_ai_space pipeline "retro cat shirt" --demo
```

Subfolders:
- `briefs/` — trend-informed creative briefs (Markdown)
- `exports/` — symlink or copy target for JSON/CSV upload bundles (also under `../exports/`)

Do not commit shop credentials or OAuth tokens here.
