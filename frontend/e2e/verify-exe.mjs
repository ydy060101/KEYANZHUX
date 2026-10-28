// Smoke-checks the packaged launcher: the API serves the built SPA at :8000,
// every module route renders the app shell, and the page has no console
// errors, failed requests or horizontal overflow at the two DoD viewports.
//
// Run after `release/ResearchAssistant.exe` is already serving:
//   node e2e/verify-exe.mjs [http://127.0.0.1:8000]

import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(here, "screenshots");
const base = process.argv[2] ?? "http://127.0.0.1:8000";
const routes = ["/", "/library", "/qa", "/discover", "/graph", "/writing"];
const problems = [];

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch();

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
]) {
  const page = await browser.newPage({ viewport });
  const consoleProblems = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => {
    consoleProblems.push(`pageerror: ${error.message}`);
  });
  page.on("requestfailed", (request) => {
    consoleProblems.push(`requestfailed: ${request.url()} ${request.failure()?.errorText ?? ""}`);
  });

  for (const route of routes) {
    const response = await page.goto(`${base}${route}`, { waitUntil: "domcontentloaded" });
    if (!response || response.status() !== 200) {
      problems.push(`${route}: HTTP ${response?.status() ?? "none"}`);
      continue;
    }
    await page.waitForTimeout(900);
    const shell = await page.getByRole("navigation").count();
    if (shell === 0) problems.push(`${route}: navigation shell missing`);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    if (overflow > 1) problems.push(`${route}: horizontal overflow ${String(overflow)}px @${viewport.width}`);
  }

  if (consoleProblems.length > 0) {
    problems.push(...consoleProblems.map((item) => `${String(viewport.width)}px ${item}`));
  }
  if (viewport.width === 1440) {
    await page.goto(base, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(OUT, "exe-home.png"), fullPage: false });
  }
  await page.close();
}

await browser.close();
if (problems.length > 0) {
  console.error("EXE SMOKE: FAIL");
  for (const problem of problems) console.error(` - ${problem}`);
  process.exit(1);
}
console.log(`EXE SMOKE: PASS — ${String(routes.length)} routes at 1440x900 and 1280x720`);
