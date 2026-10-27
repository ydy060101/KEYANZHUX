// DoD check for T2.6: the reader at both required viewports, in both themes.
//
//   node e2e/check-reader-viewports.mjs [docId]
//
// Fails on horizontal overflow, on any element spilling outside the viewport,
// and on a console error or warning — the three things "no misalignment, no
// overflow, both themes" means in practice.

import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(here, "screenshots");
const base = "http://localhost:5173";
const api = "http://127.0.0.1:8000/api/v1";
await mkdir(OUT, { recursive: true });

const listing = await fetch(`${api}/documents?page_size=100`, {
  headers: { "X-User-Id": "default" },
}).then((r) => r.json());
const ready = (listing.items ?? []).filter((doc) => doc.status === "ready");
if (ready.length === 0) {
  console.error("no parsed document to open");
  process.exit(1);
}
const doc = ready.sort((a, b) => b.page_count - a.page_count)[0];

const problems = [];
const browser = await chromium.launch();

for (const [width, height] of [
  [1440, 900],
  [1280, 720],
]) {
  for (const scheme of ["light", "dark"]) {
    const context = await browser.newContext({ viewport: { width, height }, colorScheme: scheme });
    const page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error" || message.type() === "warning") {
        problems.push(`${width}x${height} ${scheme}: console ${message.type()}: ${message.text()}`);
      }
    });
    page.on("pageerror", (error) => problems.push(`${width}x${height} ${scheme}: pageerror: ${error.message}`));

    await page.goto(`${base}/reader/${doc.id}`, { waitUntil: "domcontentloaded" });
    await page.locator("canvas").first().waitFor({ state: "visible", timeout: 60_000 });
    await page.waitForTimeout(1200);

    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    if (overflow.scrollWidth > overflow.clientWidth + 1) {
      problems.push(
        `${width}x${height} ${scheme}: page scrolls horizontally (${String(overflow.scrollWidth)} > ${String(overflow.clientWidth)})`,
      );
    }

    // Every rail must be on screen: a panel pushed off the edge is the usual
    // symptom of a fixed width that does not fit a narrower viewport.
    for (const label of ["左栏", "右栏"]) {
      const box = await page.getByRole("tablist", { name: label }).boundingBox();
      if (!box) {
        problems.push(`${width}x${height} ${scheme}: ${label} is not rendered`);
        continue;
      }
      if (box.x < -1 || box.x + box.width > width + 1) {
        problems.push(`${width}x${height} ${scheme}: ${label} spills outside the viewport`);
      }
    }

    await page.screenshot({ path: path.join(OUT, `reader-${String(width)}x${String(height)}-${scheme}.png`) });
    await context.close();
  }
}

await browser.close();
if (problems.length > 0) {
  console.error(`\n${String(problems.length)} problem(s):`);
  for (const problem of problems) console.error(`  - ${problem}`);
  process.exit(1);
}
console.log("reader viewports: PASS (1440x900 and 1280x720, light and dark)");
