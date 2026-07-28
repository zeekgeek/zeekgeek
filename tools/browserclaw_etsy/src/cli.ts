#!/usr/bin/env node
import { writeFile } from "node:fs/promises";
import { researchCompetitors } from "./browserclaw_etsy.js";

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const checkOnly = args.includes("--check");

  if (checkOnly) {
    const { BrowserClaw } = await import("browserclaw");
    try {
      const browser = await BrowserClaw.connect();
      console.log(JSON.stringify({ ok: true, cdpUrl: browser.url }, null, 2));
      return;
    } catch (error) {
      console.error(
        JSON.stringify(
          {
            ok: false,
            error: String(error),
            hint: "Start Chrome: scripts/mac-start-chrome-cdp.sh or BrowserClaw.waiting session",
          },
          null,
          2,
        ),
      );
      process.exit(1);
    }
  }

  const query = args.find((arg) => !arg.startsWith("--")) || "recovery definition shirt";
  const cdpIdx = args.indexOf("--cdp");
  const cdpUrl = cdpIdx >= 0 ? args[cdpIdx + 1] : process.env.BROWSERCLAW_CDP_URL;
  const outIdx = args.indexOf("--out");
  const outPath = outIdx >= 0 ? args[outIdx + 1] : undefined;
  const shotIdx = args.indexOf("--screenshot");
  const screenshotPath = shotIdx >= 0 ? args[shotIdx + 1] : "etsy_search.png";

  const result = await researchCompetitors(query, {
    cdpUrl,
    screenshotPath,
    maxResults: 24,
  });

  const json = JSON.stringify(result, null, 2);
  if (outPath) {
    await writeFile(outPath, json, "utf8");
    console.log(`Wrote ${outPath}`);
  } else {
    console.log(json);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
