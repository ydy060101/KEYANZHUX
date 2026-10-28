// Verifies the citation graph (T6.1–T6.3) against the real API.
//
//   * the selection page lists the library, refuses fewer than two parsed
//     documents, and follows the build job to the graph;
//   * the graph page renders the stored graph: summary, rankings, node detail,
//     layout switch and both exports;
//   * the page fits 1440×900 and 1280×720 with no horizontal overflow and no
//     console errors or warnings (H16).
//
// Run from frontend/ with the API, worker and dev server up:
//   node e2e/verify-graph.mjs [baseUrl] [apiUrl]

import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(here, "screenshots");
const base = process.argv[2] ?? "http://localhost:5173";
const api = process.argv[3] ?? "http://127.0.0.1:8000/api/v1";

const problems = [];
const fail = (message) => problems.push(message);
await mkdir(OUT, { recursive: true });

// The three classic papers are linked in this library (GPT-3 cites BERT and
// Attention). Real documents are preferred over the check-* fixtures left by
// acceptance scripts, but any copy with the same arXiv id matches.
const documents = await (await fetch(`${api}/documents?page_size=100`)).json();
const pick = (arxiv) =>
  documents.items.find(
    (doc) => doc.status === "ready" && doc.arxiv_id === arxiv && !doc.id.startsWith("check-"),
  );
const chosen = ["2005.14165", "1810.04805", "1706.03762"].map(pick).filter(Boolean);
if (chosen.length < 2) {
  console.error("graph-e2e: SKIP — the library has no ready GPT-3/BERT/Attention documents");
  process.exit(2);
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
page.on("console", (message) => {
  if (message.type() === "error" || message.type() === "warning") fail(`console ${message.type()}: ${message.text()}`);
});
page.on("pageerror", (error) => fail(`pageerror: ${error.message}`));

await page.goto(`${base}/graph`, { waitUntil: "domcontentloaded" });
await page.getByTestId("graph-doc").first().waitFor({ state: "visible", timeout: 30_000 });

// --- selection -----------------------------------------------------------
const build = page.getByTestId("graph-build");
if (!(await build.isDisabled())) fail("the build button is enabled before any selection");
for (const doc of chosen) {
  await page.locator(`[data-doc-id="${doc.id}"]`).check();
}
await page.waitForFunction(() => {
  const button = document.querySelector('[data-testid="graph-build"]');
  return button instanceof HTMLButtonElement && !button.disabled;
}, { timeout: 10_000 });
console.log(`selection: ${String(chosen.length)} documents chosen`);
await page.screenshot({ path: path.join(OUT, "graph-selection-1440.png") });

await build.click();
await page.waitForURL(/\/graph\/[0-9a-f-]{36}/, { timeout: 120_000 });
const graphUrl = page.url();
console.log(`job: navigated to ${graphUrl}`);

// --- the graph -----------------------------------------------------------
await page.getByTestId("graph-summary").waitFor({ state: "visible", timeout: 30_000 });
const summary = (await page.getByTestId("graph-summary").textContent()) ?? "";
console.log(`summary: ${summary.trim()}`);
const counts = /(\d+) 节点 · (\d+) 边/.exec(summary);
if (!counts) fail(`unreadable summary: ${summary}`);
else if (Number(counts[1]) < 2 || Number(counts[2]) < 1) fail(`expected at least 2 nodes and 1 edge, got ${summary}`);

const visibleCount = (await page.getByTestId("graph-visible-count").textContent()) ?? "";
console.log(`filters: ${visibleCount.trim()}`);
if (!visibleCount.includes("显示")) fail("the filter count is missing");

const row = page
  .getByTestId("graph-metrics-row")
  .or(page.getByTestId("graph-node-row"))
  .first();
await row.waitFor({ state: "visible", timeout: 10_000 });
await row.click();
const detail = page.getByTestId("graph-detail");
await detail.waitFor({ state: "visible", timeout: 10_000 });
const detailText = (await detail.textContent()) ?? "";
if (!detailText.includes("入度") || !detailText.includes("PageRank") || !detailText.includes("介数")) {
  fail("the node detail lacks one of 入度 / PageRank / 介数");
}
if (!detailText.includes("判定依据")) fail("the node detail does not explain the role");
await page.screenshot({ path: path.join(OUT, "graph-view-1440.png") });

// timeline layout must keep the canvas alive and every node on screen
await page.getByTestId("graph-layout").getByRole("button", { name: "时间轴" }).click();
await page.waitForTimeout(700);
if (!(await page.getByTestId("graph-canvas").isVisible())) fail("the canvas disappeared after switching to the timeline layout");
const canvasCheck = await page.evaluate(() => {
  const element = document.querySelector('[data-testid="graph-canvas"]');
  const cy = element?.__cy;
  if (!cy) return { error: "no Cytoscape instance" };
  const width = cy.width();
  const height = cy.height();
  const visible = cy.nodes(":visible");
  const outside = visible.filter((node) => {
    const point = node.renderedPosition();
    return point.x < 0 || point.y < 0 || point.x > width || point.y > height;
  }).length;
  return { nodes: visible.length, outside, zoom: Number(cy.zoom().toFixed(2)) };
});
if (canvasCheck.error) fail(canvasCheck.error);
else {
  console.log(`canvas: ${String(canvasCheck.nodes)} nodes, ${String(canvasCheck.outside)} outside, zoom ${String(canvasCheck.zoom)}`);
  if (canvasCheck.nodes < 2) fail("the canvas rendered fewer than two nodes");
  if (canvasCheck.outside > 0) fail(`${String(canvasCheck.outside)} node(s) fall outside the canvas`);
}

// exports
const [jsonDownload] = await Promise.all([
  page.waitForEvent("download", { timeout: 10_000 }),
  page.getByTestId("graph-export-json").click(),
]);
if (!jsonDownload.suggestedFilename().endsWith(".json")) fail("the JSON export has the wrong filename");
const [pngDownload] = await Promise.all([
  page.waitForEvent("download", { timeout: 10_000 }),
  page.getByTestId("graph-export-png").click(),
]);
if (!pngDownload.suggestedFilename().endsWith(".png")) fail("the PNG export has the wrong filename");

// --- dark theme ----------------------------------------------------------
for (let index = 0; index < 3; index += 1) {
  const theme = await page.evaluate(() => document.documentElement.dataset["theme"]);
  if (theme === "dark") break;
  await page.getByRole("button", { name: /切换主题/ }).click();
}
const theme = await page.evaluate(() => document.documentElement.dataset["theme"]);
if (theme !== "dark") fail(`could not switch to the dark theme (got ${String(theme)})`);
await page.waitForTimeout(400);
await page.screenshot({ path: path.join(OUT, "graph-view-dark-1440.png") });

// --- the narrow viewport -------------------------------------------------
await page.setViewportSize({ width: 1280, height: 720 });
await page.waitForTimeout(300);
const overflow = await page.evaluate(
  () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
);
if (overflow > 1) fail(`horizontal overflow at 1280×720: ${String(overflow)}px`);
await page.screenshot({ path: path.join(OUT, "graph-view-1280.png") });

await browser.close();
if (problems.length > 0) {
  for (const problem of problems) console.error(`FAIL ${problem}`);
  console.error("graph-e2e: FAIL");
  process.exit(1);
}
console.log("graph-e2e: PASS");
