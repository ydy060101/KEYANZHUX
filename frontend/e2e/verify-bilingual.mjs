// Verifies the bilingual reader against a real translated document (T4.3).
//
// The card asks for block-aligned columns, linked scrolling from either side,
// no pixel-ratio sync and no scroll loop. This script:
//   1. picks a ready paper, translating it first when no translation exists;
//   2. scrolls the PDF column and checks the matching translation block is in
//      the viewport (the block is recomputed independently from page boxes,
//      bboxes and the exposed scale);
//   3. scrolls the translation column and checks the PDF lands on that block,
//      not at a proportional offset;
//   4. waits for the scroll to settle and asserts nothing keeps moving;
//   5. checks both viewports and themes and the zero-console rule.
//
// Run from frontend/ with both dev servers up:
//   node e2e/verify-bilingual.mjs [docId]

import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(here, "screenshots");
const base = process.argv[2] ?? "http://localhost:5173";
const api = "http://127.0.0.1:8000/api/v1";
const headers = { "X-User-Id": "default" };

const problems = [];
const fail = (message) => problems.push(message);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
await mkdir(OUT, { recursive: true });

async function call(pathname, init = {}) {
  const response = await fetch(`${api}${pathname}`, {
    ...init,
    headers: { ...headers, ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(`${pathname} → ${String(response.status)} ${JSON.stringify(payload)}`);
  return payload;
}

async function translationOf(id) {
  return call(`/documents/${encodeURIComponent(id)}/translation?direction=en2zh`);
}

async function ensureTranslation(doc) {
  const current = await translationOf(doc.id);
  if ((current.blocks ?? []).length > 0) return current.blocks;
  console.log(`translating ${doc.title} …`);
  const started = await call(`/documents/${encodeURIComponent(doc.id)}/translate`, {
    method: "POST",
    body: JSON.stringify({ format: "md", direction: "en2zh" }),
  });
  const deadline = Date.now() + 10 * 60_000;
  for (;;) {
    if (Date.now() > deadline) throw new Error("translation job exceeded 10 minutes");
    const job = await call(`/jobs/${String(started.job_id)}`);
    if (job.status === "succeeded") break;
    if (job.status === "failed" || job.status === "cancelled") {
      throw new Error(`translation job ${String(job.status)}: ${String(job.error ?? "")}`);
    }
    await sleep(3000);
  }
  const done = await translationOf(doc.id);
  if ((done.blocks ?? []).length === 0) throw new Error("translation job succeeded but returned no blocks");
  return done.blocks;
}

// A short paper is enough to exercise alignment; a book would take minutes to
// translate and its 10k rows are not what this card is about.
const listing = await call("/documents?page_size=100");
const ready = (listing.items ?? [])
  .filter((doc) => doc.status === "ready" && doc.page_count > 0 && doc.page_count <= 30)
  .sort((a, b) => a.page_count - b.page_count);
if (ready.length === 0) {
  console.error("no parsed short paper — parse one first");
  process.exit(1);
}

const requested = process.argv[3];
let doc = requested ? ready.find((item) => item.id === requested) : undefined;
let blocks = null;
if (doc) blocks = await ensureTranslation(doc);
for (const candidate of ready) {
  if (blocks) break;
  const existing = await translationOf(candidate.id);
  if ((existing.blocks ?? []).length > 0) {
    doc = candidate;
    blocks = existing.blocks;
  }
}
if (!doc) {
  doc = ready[0];
  blocks = await ensureTranslation(doc);
}
console.log(`${doc.title} (${String(doc.page_count)} pages, ${String(blocks.length)} translated blocks)`);
if (blocks.length < 3) fail("fewer than three translated blocks — alignment cannot be observed");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("console", (message) => {
  if (message.type() === "error" || message.type() === "warning") {
    fail(`console ${message.type()}: ${message.text()}`);
  }
});
page.on("pageerror", (error) => fail(`pageerror: ${error.message}`));

await page.goto(`${base}/reader/${doc.id}`, { waitUntil: "domcontentloaded" });
await page.locator("canvas").first().waitFor({ state: "visible", timeout: 60_000 });
await page.waitForTimeout(800);

await page.getByRole("button", { name: "中英对照" }).click();
const pane = page.locator('[data-testid="bilingual-pane"]');
await pane.waitFor({ state: "visible", timeout: 20_000 });
const rows = page.locator("[data-bilingual-row]");
await rows.first().waitFor({ state: "visible", timeout: 20_000 });
await page.waitForTimeout(600);
const rowCount = await rows.count();
console.log(`rendered translation rows: ${String(rowCount)}`);
if (rowCount !== blocks.length) fail(`${String(blocks.length)} blocks from the API rendered as ${String(rowCount)} rows`);

const pdf = page.locator("[data-reader-scroll]");
const scroll = page.locator("[data-bilingual-scroll]");

// Recompute the block at the PDF reading line from the DOM and the exposed
// scale; this is the same block identity the pane must choose, but it is not
// read from the component's state.
async function expectedPdfBlock() {
  return page.evaluate(() => {
    const host = document.querySelector("[data-reader-scroll]");
    const aside = document.querySelector('[data-testid="bilingual-pane"]');
    if (!(host instanceof HTMLElement) || !(aside instanceof HTMLElement)) return null;
    const scale = Number(aside.dataset.scale);
    const line = host.scrollTop + Math.min(180, Math.max(48, host.clientHeight * 0.22));
    let before = null;
    let after = null;
    for (const row of aside.querySelectorAll("[data-bilingual-row]")) {
      if (!(row instanceof HTMLElement)) continue;
      const pageBox = host.querySelector(`[data-page="${row.dataset.page ?? ""}"]`);
      if (!(pageBox instanceof HTMLElement)) continue;
      const bbox = (row.dataset.bbox ?? "").split(",").map(Number);
      if (bbox.length !== 4 || bbox.some((value) => !Number.isFinite(value))) continue;
      const top =
        pageBox.getBoundingClientRect().top -
        host.getBoundingClientRect().top +
        host.scrollTop +
        bbox[1] * scale;
      const item = { id: row.dataset.bilingualRow, top };
      if (top <= line) {
        if (!before || top >= before.top) before = item;
      } else if (!after || top < after.top) {
        after = item;
      }
    }
    return (before ?? after)?.id ?? null;
  });
}

// ---- left column drives the right --------------------------------------
const beforePdf = await pdf.evaluate((node) => node.scrollTop);
const beforeCurrent = await pane.getAttribute("data-current-block");
await pdf.hover();
await page.mouse.wheel(0, 1200);
await page.waitForTimeout(700);
const afterPdf = await pdf.evaluate((node) => node.scrollTop);
const current = await pane.getAttribute("data-current-block");
console.log(`PDF ${String(Math.round(beforePdf))} → ${String(Math.round(afterPdf))} px, current=${String(current)}`);
if (afterPdf <= beforePdf) fail("wheel scrolling moved the PDF column by 0 px");
if (!current) fail("scrolling the PDF selected no translation block");
if (current && current === beforeCurrent) fail("the PDF scrolled but the current block did not change");
const expected = await expectedPdfBlock();
if (current && expected !== current) fail(`PDF shows block ${String(expected)}, pane marked ${String(current)}`);

const row = page.locator(`[data-bilingual-row="${String(current)}"]`);
const rowBox = await row.boundingBox();
const paneBox = await pane.boundingBox();
if (!rowBox || !paneBox) fail("could not measure the current row or the translation pane");
else {
  const visible = rowBox.y < paneBox.y + paneBox.height && rowBox.y + rowBox.height > paneBox.y;
  console.log(`current row y=${String(Math.round(rowBox.y))}, pane ${String(Math.round(paneBox.y))}–${String(Math.round(paneBox.y + paneBox.height))}`);
  if (!visible) fail("the matching translation block is outside the translation viewport");
}

// ---- no scroll loop ----------------------------------------------------
const pdfSettled = await pdf.evaluate((node) => node.scrollTop);
const paneSettled = await scroll.evaluate((node) => node.scrollTop);
await page.waitForTimeout(700);
const pdfLater = await pdf.evaluate((node) => node.scrollTop);
const paneLater = await scroll.evaluate((node) => node.scrollTop);
if (Math.abs(pdfLater - pdfSettled) > 1 || Math.abs(paneLater - paneSettled) > 1) {
  fail(`scroll positions kept moving after 700 ms (pdf ${String(pdfSettled)}→${String(pdfLater)}, pane ${String(paneSettled)}→${String(paneLater)})`);
}

// ---- right column drives the left --------------------------------------
const pdfBeforePaneWheel = await pdf.evaluate((node) => node.scrollTop);
const paneBefore = await scroll.evaluate((node) => node.scrollTop);
await scroll.hover();
await page.mouse.wheel(0, 900);
await page.waitForTimeout(700);
const paneAfter = await scroll.evaluate((node) => node.scrollTop);
const pdfAfterPaneWheel = await pdf.evaluate((node) => node.scrollTop);
const paneCurrent = await pane.getAttribute("data-current-block");
console.log(`pane ${String(Math.round(paneBefore))} → ${String(Math.round(paneAfter))} px, PDF ${String(Math.round(pdfBeforePaneWheel))} → ${String(Math.round(pdfAfterPaneWheel))} px, current=${String(paneCurrent)}`);
if (paneAfter <= paneBefore) fail("wheel scrolling moved the translation column by 0 px");
if (pdfAfterPaneWheel === pdfBeforePaneWheel) fail("scrolling the translation column did not move the PDF");
if (!paneCurrent) fail("scrolling the translation column selected no PDF block");

const expectedRow = await page.evaluate(() => {
  const pane = document.querySelector("[data-bilingual-scroll]");
  if (!(pane instanceof HTMLElement)) return null;
  const line = pane.scrollTop + Math.min(120, Math.max(36, pane.clientHeight * 0.18));
  let before = null;
  let after = null;
  for (const row of pane.querySelectorAll("[data-bilingual-row]")) {
    if (!(row instanceof HTMLElement)) continue;
    const top = row.getBoundingClientRect().top - pane.getBoundingClientRect().top + pane.scrollTop;
    const item = { id: row.dataset.bilingualRow, top };
    if (top <= line) {
      if (!before || top >= before.top) before = item;
    } else if (!after || top < after.top) {
      after = item;
    }
  }
  return (before ?? after)?.id ?? null;
});
if (paneCurrent && expectedRow !== paneCurrent) {
  fail(`pane shows block ${String(expectedRow)}, reader marked ${String(paneCurrent)}`);
}

const landing = await page.evaluate((id) => {
  const host = document.querySelector("[data-reader-scroll]");
  const aside = document.querySelector('[data-testid="bilingual-pane"]');
  const row = document.querySelector(`[data-bilingual-row="${id}"]`);
  if (!(host instanceof HTMLElement) || !(aside instanceof HTMLElement) || !(row instanceof HTMLElement)) return null;
  const pageBox = host.querySelector(`[data-page="${row.dataset.page ?? ""}"]`);
  if (!(pageBox instanceof HTMLElement)) return null;
  const bbox = (row.dataset.bbox ?? "").split(",").map(Number);
  const scale = Number(aside.dataset.scale);
  const target =
    pageBox.getBoundingClientRect().top -
    host.getBoundingClientRect().top +
    host.scrollTop +
    bbox[1] * scale -
    8;
  return { target, actual: host.scrollTop };
}, paneCurrent);
if (!landing) fail("could not measure the PDF landing position");
else {
  const expectedTop = Math.max(0, landing.target);
  console.log(`PDF landed at ${String(Math.round(landing.actual))} px, block target ${String(Math.round(expectedTop))} px`);
  if (Math.abs(landing.actual - expectedTop) > 2) {
    fail(`PDF did not land on the block's top (${String(Math.round(landing.actual))} vs ${String(Math.round(expectedTop))})`);
  }
}

// ---- independent font size ---------------------------------------------
const text = page.locator(`[data-bilingual-row="${String(paneCurrent)}"] p`).first();
const sizeBefore = await text.evaluate((node) => parseFloat(getComputedStyle(node).fontSize));
await page.getByLabel("增大译文字号").click();
const sizeAfter = await text.evaluate((node) => parseFloat(getComputedStyle(node).fontSize));
console.log(`translation font ${String(sizeBefore)} → ${String(sizeAfter)} px`);
if (sizeAfter <= sizeBefore) fail("increasing the translation font changed nothing");

// ---- theme and viewport screenshots ------------------------------------
await page.screenshot({ path: path.join(OUT, "bilingual-1440-light.png") });
await page.getByLabel("切换到深色主题").click();
await page.waitForTimeout(400);
await page.screenshot({ path: path.join(OUT, "bilingual-1440-dark.png") });
await page.getByLabel("切换到浅色主题").click();
await page.waitForTimeout(300);

await page.getByLabel("退出对照模式").click();
if ((await pane.count()) !== 0) fail("退出对照模式 did not close the translation column");
await page.setViewportSize({ width: 1280, height: 720 });
await page.getByRole("button", { name: "中英对照" }).click();
await pane.waitFor({ state: "visible" });
await page.waitForTimeout(700);
const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
console.log(`1280×720 horizontal overflow: ${String(overflow)} px`);
if (overflow > 1) fail(`page overflows horizontally by ${String(overflow)} px at 1280×720`);
const paneAt1280 = await pane.boundingBox();
if (!paneAt1280 || paneAt1280.width < 280) fail(`translation column is ${String(paneAt1280?.width ?? 0)} px wide at 1280`);
await page.screenshot({ path: path.join(OUT, "bilingual-1280-light.png") });
await page.getByLabel("切换到深色主题").click();
await page.waitForTimeout(400);
await page.screenshot({ path: path.join(OUT, "bilingual-1280-dark.png") });

await browser.close();

if (problems.length > 0) {
  console.error(`\nFAIL\n- ${problems.join("\n- ")}`);
  process.exit(1);
}
console.log("\nPASS — block-aligned linked scrolling, both directions, no loop, both viewports/themes");
