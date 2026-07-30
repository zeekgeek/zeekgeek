/**
 * BrowserClaw-powered Etsy competitor research.
 *
 * API notes (your sketch vs real BrowserClaw):
 *   - BrowserClaw.launch() / connect() returns a browser handle (not claw.goto)
 *   - browser.open(url) navigates; page = await browser.currentPage()
 *   - page.snapshot() → { snapshot, refs } for agent click loops
 *   - page.evaluate() / playwrightPage() → bulk DOM extraction
 */
import { BrowserClaw } from "browserclaw";

export type EtsyListing = {
  etsyListingId: string | null;
  title: string;
  url: string;
  priceAmount: number | null;
  shopName: string | null;
  reviewCount: number | null;
  rating: number | null;
};

export type ResearchResult = {
  query: string;
  source: "browserclaw";
  scrapedAt: string;
  listings: EtsyListing[];
  snapshotPreview: string;
  screenshotPath?: string;
};

export type ResearchOptions = {
  cdpUrl?: string;
  headless?: boolean;
  maxResults?: number;
  screenshotPath?: string;
  saveSnapshotPath?: string;
};

type BrowserHandle = Awaited<ReturnType<typeof BrowserClaw.connect>>;
type PageHandle = Awaited<ReturnType<BrowserHandle["open"]>>;

async function naturalScroll(page: PageHandle): Promise<void> {
  const pw = await page.playwrightPage();
  for (let i = 0; i < 5; i += 1) {
    const delta = 350 + Math.floor(Math.random() * 450);
    await pw.mouse.wheel(0, i % 4 === 0 ? -Math.floor(delta / 3) : delta);
    await pw.waitForTimeout(600 + Math.floor(Math.random() * 900));
  }
}

async function extractListings(page: PageHandle, maxResults: number): Promise<EtsyListing[]> {
  const pw = await page.playwrightPage();
  return pw.evaluate((limit) => {
    const cards = Array.from(
      document.querySelectorAll("[data-listing-id], a.listing-link, div[data-listing-card-v2]"),
    );
    const seen = new Set<string>();
    const rows: EtsyListing[] = [];

    for (const card of cards) {
      if (rows.length >= limit) break;
      const element = card as HTMLElement;
      const listingId =
        element.getAttribute("data-listing-id") ||
        (element.getAttribute("href") || "").match(/\/listing\/(\d+)/)?.[1] ||
        null;
      const href = element instanceof HTMLAnchorElement ? element.href : element.querySelector("a")?.href || "";
      const key = listingId || href;
      if (!key || seen.has(key)) continue;
      seen.add(key);

      const text = (element.innerText || "").trim();
      const title =
        element.querySelector("h3, [data-listing-card-title], .v2-listing-card__title")?.textContent?.trim() ||
        text.split("\n")[0]?.trim() ||
        "";
      if (!title) continue;

      const priceText =
        element.querySelector(".currency-value, [data-price], .lc-price")?.textContent?.trim() || text;
      const shopName =
        element.querySelector(".shop-name, [data-shop-name], .v2-listing-card__shop")?.textContent?.trim() ||
        null;

      const ratingMatch = text.match(/(\d\.\d)\s*\(\s*(\d[\d,]*)/);
      const reviewMatch = text.match(/(\d[\d,]*)\s*reviews?/i);

      const row: EtsyListing = {
        etsyListingId: listingId,
        title: title.slice(0, 240),
        url: href.startsWith("http") ? href : listingId ? `https://www.etsy.com/listing/${listingId}` : "",
        priceAmount: null,
        shopName,
        reviewCount: reviewMatch ? Number.parseInt(reviewMatch[1].replace(/,/g, ""), 10) : null,
        rating: ratingMatch ? Number.parseFloat(ratingMatch[1]) : null,
      };

      const price = priceText.match(/\$?\s*(\d[\d,]*(?:\.\d{2})?)/);
      if (price) {
        row.priceAmount = Number.parseFloat(price[1].replace(/,/g, ""));
      }
      rows.push(row);
    }
    return rows;
  }, maxResults);
}

function searchUrlFor(query: string): string {
  return `https://www.etsy.com/search?q=${encodeURIComponent(query)}&explicit=1`;
}

async function attachBrowser(options: ResearchOptions): Promise<{ browser: BrowserHandle; launched: boolean }> {
  if (options.cdpUrl) {
    return { browser: await BrowserClaw.connect(options.cdpUrl, { stealth: true }), launched: false };
  }
  try {
    return { browser: await BrowserClaw.connect(), launched: false };
  } catch {
    const browser = await BrowserClaw.launch({
      headless: options.headless ?? false,
      cdpPort: 9222,
    });
    return { browser, launched: true };
  }
}

export async function researchCompetitors(
  query: string,
  options: ResearchOptions = {},
): Promise<ResearchResult> {
  const maxResults = options.maxResults ?? 24;
  const searchUrl = searchUrlFor(query);
  const { browser, launched } = await attachBrowser(options);

  try {
    const page = await browser.open(searchUrl);

    const challenge = await page.detectChallenge();
    if (challenge?.kind === "cloudflare-js") {
      await page.waitForChallenge({ timeoutMs: 20000 });
    }

    await naturalScroll(page);

    const { snapshot } = await page.snapshot({ maxChars: 12000 });
    const listings = await extractListings(page, maxResults);

    let screenshotPath: string | undefined;
    if (options.screenshotPath) {
      const fs = await import("node:fs/promises");
      await fs.writeFile(options.screenshotPath, await page.screenshot({ fullPage: false }));
      screenshotPath = options.screenshotPath;
    }

    if (options.saveSnapshotPath) {
      const fs = await import("node:fs/promises");
      await fs.writeFile(options.saveSnapshotPath, snapshot, "utf8");
    }

    return {
      query,
      source: "browserclaw",
      scrapedAt: new Date().toISOString(),
      listings,
      snapshotPreview: snapshot.slice(0, 2000),
      screenshotPath,
    };
  } finally {
    if (launched) {
      await browser.stop("success");
    }
  }
}
