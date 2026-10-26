// Verifies the dedup dialog against real data (T1.6, acceptance case 3.1).
//
// Uploads v7 of the Transformer paper, then v1. The API flags the older one
// as the same paper and the library page opens the dialog with the real
// similarity, version and diff summary. Screenshots land in e2e/screenshots/.
//
//   node e2e/verify-dedup.mjs [url]

import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(here, "screenshots");
const url = process.argv[2] ?? "http://localhost:5173/";
const fixtures = path.resolve(here, "../../backend/fixtures/pdf");

const problems = [];
await mkdir(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("console", (m) => {
  if (m.type() === "error" || m.type() === "warning") problems.push(`console ${m.type()}: ${m.text()}`);
});
page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));

await page.goto(url, { waitUntil: "networkidle" });

// Upload v7 first so v1 is the one detected as an older version.
const input = page.locator('input[type="file"]');
await input.setInputFiles(path.join(fixtures, "1706.03762v7.pdf"));
await page.waitForTimeout(2500);

await input.setInputFiles(path.join(fixtures, "1706.03762v1.pdf"));
const dialog = page.getByRole("dialog");
await dialog.waitFor({ state: "visible", timeout: 120_000 });
console.log("dialog:", (await dialog.innerText()).split("\n").slice(0, 6).join(" | "));

await page.getByRole("button", { name: "查看修订摘要" }).click();
await page.waitForTimeout(4000);
await page.screenshot({ path: path.join(OUT, "dedup-dialog.png") });
console.log("captured dedup-dialog.png");

await page.getByRole("button", { name: "两者都保留" }).click();
await page.waitForTimeout(1500);
await page.screenshot({ path: path.join(OUT, "library-after-dedup.png") });
console.log("captured library-after-dedup.png");

await browser.close();

if (problems.length > 0) {
  console.log("\nPROBLEMS:");
  for (const p of [...new Set(problems)]) console.log(" -", p);
  process.exit(1);
}
console.log("\nDEDUP CHECK OK");
