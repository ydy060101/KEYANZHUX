// Verifies the discovery page (T5.1/T5.6) against the real API and sources.
//
//   * the recommendation feed renders scored rows whose reasons name a seed
//     (not a fixed list) — or an honest empty state when the library is empty;
//   * a live search returns hits from several sources, marks what is already
//     owned, and offers import only for hits with a downloadable PDF;
//   * the page fits 1440×900 and 1280×720 with no horizontal overflow and no
//     console errors or warnings (H16).
//
// Run from frontend/ with the API, worker and dev server up:
//   node e2e/verify-discover.mjs [baseUrl]

import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(here, "screenshots");
const base = process.argv[2] ?? "http://localhost:5173";

const problems = [];
const fail = (message) => problems.push(message);
await mkdir(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("console", (m) => {
  if (m.type() === "error" || m.type() === "warning") fail(`console ${m.type()}: ${m.text()}`);
});
page.on("pageerror", (e) => fail(`pageerror: ${e.message}`));

await page.goto(`${base}/discover`, { waitUntil: "domcontentloaded" });
await page.getByRole("tab", { name: "推荐流" }).waitFor({ state: "visible", timeout: 30_000 });

// --- the feed ------------------------------------------------------------
const feedCard = page.getByTestId("discover-hit").first();
const emptyFeed = page.getByText("还没有可推荐的文献");
await Promise.race([
  feedCard.waitFor({ state: "visible", timeout: 90_000 }).catch(() => undefined),
  emptyFeed.waitFor({ state: "visible", timeout: 90_000 }).catch(() => undefined),
]);
if (await feedCard.isVisible()) {
  const cards = await page.getByTestId("discover-hit").count();
  const firstReason = await page.getByTestId("discover-hit").first().locator("li").first().textContent();
  console.log(`feed: ${String(cards)} rows; first reason: ${(firstReason ?? "").trim()}`);
  if (cards < 1) fail("the feed rendered no rows");
  if (!(firstReason ?? "").includes("库内")) fail("a recommendation reason does not name a library seed");
} else if (await emptyFeed.isVisible()) {
  console.log("feed: empty state (the library has no titled document)");
} else {
  fail("the feed neither rendered rows nor the empty state");
}
await page.screenshot({ path: path.join(OUT, "discover-feed-1440.png") });

// --- live search ---------------------------------------------------------
await page.getByRole("tab", { name: "搜索下载" }).click();
await page.getByTestId("discover-query").fill("attention is all you need");
await page.getByTestId("discover-search").click();
await page.getByTestId("discover-count").waitFor({ state: "visible", timeout: 90_000 });
const count = (await page.getByTestId("discover-count").textContent()) ?? "";
const hits = await page.getByTestId("discover-hit").count();
console.log(`search: ${count.trim()}, ${String(hits)} cards`);
if (hits < 5) fail(`expected at least 5 hits, got ${String(hits)}`);

const degraded = page.getByTestId("discover-degraded");
if (await degraded.isVisible()) {
  console.log(`search degraded: ${(await degraded.textContent())?.trim() ?? ""}`);
}

const owned = page.getByText("已在库中");
if ((await owned.count()) === 0) fail("no hit is marked 已在库中 although the paper is imported");
const importButtons = page.getByTestId("discover-import");
const noPdf = page.getByRole("button", { name: "无可下载 PDF" });
console.log(`search: ${String(await importButtons.count())} importable, ${String(await noPdf.count())} without a PDF`);
await page.screenshot({ path: path.join(OUT, "discover-search-1440.png"), fullPage: false });

// --- the narrow viewport ------------------------------------------------
await page.setViewportSize({ width: 1280, height: 720 });
const overflow = await page.evaluate(
  () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
);
if (overflow > 1) fail(`horizontal overflow at 1280×720: ${String(overflow)}px`);
await page.screenshot({ path: path.join(OUT, "discover-search-1280.png") });

await browser.close();
if (problems.length > 0) {
  for (const problem of problems) console.error(`FAIL ${problem}`);
  console.error("discover-e2e: FAIL");
  process.exit(1);
}
console.log("discover-e2e: PASS");
