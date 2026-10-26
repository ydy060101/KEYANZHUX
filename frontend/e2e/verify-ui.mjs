// DoD screenshot check: 1440x900 and 1280x720, light and dark (H16, T1.6).
//
// Run from frontend/ with the dev servers up:
//   node e2e/verify-ui.mjs [url]
// Screenshots land in e2e/screenshots/. Exits non-zero on horizontal
// overflow or on any console error/warning, which the DoD requires to be zero.

import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(here, "screenshots");
const VIEWPORTS = [
  [1440, 900],
  [1280, 720],
];
const THEMES = ["light", "dark"];

const url = process.argv[2] ?? "http://localhost:5173/";
const problems = [];

await mkdir(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage();

page.on("console", (message) => {
  if (message.type() === "error" || message.type() === "warning") {
    problems.push(`console ${message.type()}: ${message.text()}`);
  }
});
page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));

for (const [width, height] of VIEWPORTS) {
  for (const theme of THEMES) {
    await page.setViewportSize({ width, height });
    await page.goto(url, { waitUntil: "networkidle" });
    await page.evaluate((value) => localStorage.setItem("ra-theme", value), theme);
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(600);

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    if (overflow) problems.push(`${width}x${height} ${theme}: horizontal overflow`);

    const name = `library-${width}x${height}-${theme}.png`;
    await page.screenshot({ path: path.join(OUT, name) });
    console.log("captured", name);
  }
}

await browser.close();

if (problems.length > 0) {
  console.log("\nPROBLEMS:");
  for (const item of [...new Set(problems)]) console.log(" -", item);
  process.exit(1);
}
console.log("\nUI CHECK OK");
