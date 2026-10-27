// Verifies the reader against a real parsed document (T2.6, acceptance B3).
//
// Opens the 541-page book in the reader, then checks the three things the
// card asks for that can be observed from the outside:
//
//   * the outline jumps: clicking a heading scrolls to its page;
//   * a citation marker jumps to its bibliography entry, and the entry's
//     "返回引用处" comes back to the marker;
//   * the first page paints inside two seconds.
//
// Run from frontend/ with both dev servers up:
//   node e2e/verify-reader.mjs [docId]

import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(here, "screenshots");
const base = process.argv[2] ?? "http://localhost:5173";
const api = "http://127.0.0.1:8000/api/v1";

const problems = [];
const fail = (message) => problems.push(message);
await mkdir(OUT, { recursive: true });

// Pick the longest parsed document: the book is what B3 is about.
const listing = await fetch(`${api}/documents?page_size=100`, {
  headers: { "X-User-Id": "default" },
}).then((r) => r.json());
const ready = (listing.items ?? []).filter((doc) => doc.status === "ready");
if (ready.length === 0) {
  console.error("no parsed document to open — parse one first");
  process.exit(1);
}
const doc = ready.sort((a, b) => b.page_count - a.page_count)[0];
console.log(`opening ${doc.title} (${doc.page_count} pages) ${doc.id}`);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("console", (m) => {
  if (m.type() === "error" || m.type() === "warning") fail(`console ${m.type()}: ${m.text()}`);
});
page.on("pageerror", (e) => fail(`pageerror: ${e.message}`));

const started = Date.now();
await page.goto(`${base}/reader/${doc.id}`, { waitUntil: "domcontentloaded" });
await page.locator("canvas").first().waitFor({ state: "visible", timeout: 60_000 });
const firstPaint = Date.now() - started;
console.log(`first page painted in ${String(firstPaint)} ms`);
if (firstPaint > 2000) fail(`first paint took ${String(firstPaint)} ms (limit 2000)`);

await page.screenshot({ path: path.join(OUT, "reader-open.png") });

// --- outline jump -------------------------------------------------------
const headings = page.locator("[data-outline-id]");
const count = await headings.count();
console.log(`outline rows: ${String(count)}`);
if (count === 0) fail("the outline rendered no headings");

const target = headings.nth(Math.min(12, count - 1));
const label = (await target.innerText()).replace(/\s+/g, " ").trim();
await target.click();
await page.waitForTimeout(1200);
const currentPage = await page.locator('[aria-label="跳转页码"]').inputValue();
console.log(`clicked "${label}" → page ${currentPage}`);
const shown = await page.locator(`[data-page="${currentPage}"]`).count();
if (shown === 0) fail(`jumping to "${label}" did not bring page ${currentPage} into view`);

// --- outline filter on a long book -------------------------------------
const filter = page.getByLabel("过滤标题");
await filter.fill("learning");
await page.waitForTimeout(300);
const filtered = await page.locator("[data-outline-id]").count();
console.log(`filtered rows for "learning": ${String(filtered)}`);
if (filtered === 0) fail('filtering the outline by "learning" matched nothing');
await filter.fill("");

// --- structure panel (on the book) --------------------------------------
// The book prints 272 figures and no tables, so the figure list is what can
// be checked here; the table check needs a document that has tables and runs
// further down.
await page.getByRole("tab", { name: /图表/ }).first().click();
await page.waitForTimeout(1200);
const figures = await page.locator('img[alt*="图 第"]').count();
console.log(`figure crops rendered: ${String(figures)}`);
if (figures === 0) fail("the book's 272 figures did not render in the structure panel");
await page.screenshot({ path: path.join(OUT, "reader-figures.png") });

// --- table rendering (02 §4.2) -----------------------------------------
// A table is shown as its extracted HTML with the page crop one click away.
// Only some tables expose a structure — a borderless table set as one column
// of text has no cells to detect — so this looks for a document that has one
// rather than assuming every table does.
async function structureOf(id) {
  return fetch(`${api}/documents/${id}/structure`, { headers: { "X-User-Id": "default" } }).then((r) => r.json());
}
const withTables = (listing.items ?? []).filter((item) => item.status === "ready" && (item.stats?.tables ?? 0) > 0);
let htmlDoc = null;
let htmlTable = null;
for (const candidate of withTables) {
  const structure = await structureOf(candidate.id);
  const table = (structure.assets ?? []).find((asset) => asset.kind === "table" && asset.html);
  if (table) {
    htmlDoc = candidate;
    htmlTable = table;
    break;
  }
}
if (!htmlDoc) {
  fail(`none of the ${String(withTables.length)} documents with tables exposes table HTML`);
} else {
  console.log(`table HTML check on ${htmlDoc.title} (${String(htmlDoc.stats.tables)} tables)`);
  await page.goto(`${base}/reader/${htmlDoc.id}`, { waitUntil: "domcontentloaded" });
  await page.locator("canvas").first().waitFor({ state: "visible", timeout: 60_000 });
  await page.waitForTimeout(1000);
  await page.getByRole("tab", { name: "表格" }).click();
  await page.waitForTimeout(1200);
  const rows = await page.locator("table").count();
  const toggles = await page.getByRole("button", { name: "查看原图" }).count();
  console.log(`tables: ${String(rows)} rendered as HTML, ${String(toggles)} with a crop toggle`);
  if (rows === 0) fail(`${htmlDoc.title} has table HTML (${htmlTable.id}) but the panel rendered none`);
  if (toggles === 0) fail("the HTML table offered no 查看原图 toggle");
  await page.getByRole("button", { name: "查看原图" }).first().click();
  await page.waitForTimeout(500);
  const back = await page.getByRole("button", { name: "查看 HTML" }).count();
  if (back === 0) fail("查看原图 did not switch the table to its crop");
  await page.screenshot({ path: path.join(OUT, "reader-tables.png") });
}

// --- citation hover card and bidirectional jump ------------------------
// The longest document is a book with author-year references and no link
// annotations, so it has no numeric markers to hover. The marker checks run
// on the document that has the most citations, which is what the feature is
// for; the book's own checks (speed, outline, figures) have already run above.
const cited = (listing.items ?? [])
  .filter((item) => item.status === "ready" && item.id !== doc.id)
  .sort((a, b) => (b.stats?.citations ?? 0) - (a.stats?.citations ?? 0))[0];
if (cited) {
  console.log(`citation checks on ${cited.title} (${String(cited.stats?.citations ?? 0)} markers)`);
  await page.goto(`${base}/reader/${cited.id}`, { waitUntil: "domcontentloaded" });
  await page.locator("canvas").first().waitFor({ state: "visible", timeout: 60_000 });
  await page.waitForTimeout(1500);

  // A paper's markers start where its body does — this one's first marker is
  // on page 34 — so jumping to page 1 would look for one on pages that have
  // none. The reader's own page box is used, which is the same path a reader
  // takes.
  const citations = await fetch(`${api}/documents/${cited.id}/citations`, {
    headers: { "X-User-Id": "default" },
  }).then((r) => r.json());
  const firstPage = (citations ?? [])
    .map((c) => c.page)
    .filter((p) => typeof p === "number")
    .sort((a, b) => a - b)[0];
  if (firstPage) {
    console.log(`jumping to page ${String(firstPage)}, where the first marker sits`);
    const box = page.locator('[aria-label="跳转页码"]');
    await box.fill(String(firstPage));
    await box.press("Enter");
    await page.waitForTimeout(2000);
  }
}
const marker = page.locator("[data-citation]").first();
if ((await marker.count()) === 0) {
  fail("no citation markers were drawn on the pages in view");
} else {
  await marker.scrollIntoViewIfNeeded();
  await page.waitForTimeout(600);
  await marker.hover();
  const card = page.getByRole("dialog", { name: /引用/ });
  await card.waitFor({ state: "visible", timeout: 5000 });
  const cardText = (await card.innerText()).split("\n").slice(0, 3).join(" | ");
  console.log(`citation card: ${cardText}`);
  await page.screenshot({ path: path.join(OUT, "reader-citation-card.png") });

  // A marker may name several entries ("[MCCD13, PSM14]"), and the card lists
  // one row each; the first row's jump is the one this check follows.
  await card.getByRole("button", { name: "跳转" }).first().click();
  await page.waitForTimeout(900);
  const back = page.getByRole("button", { name: /返回引用处/ }).first();
  if ((await back.count()) === 0) fail("the bibliography entry offered no 返回引用处 button");
  else {
    await back.click();
    await page.waitForTimeout(700);
    const highlight = await page.locator(".bg-\\[var\\(--hl\\)\\]").count();
    console.log(`highlights after returning: ${String(highlight)}`);
    if (highlight === 0) fail("returning to the marker drew no anchor highlight");
    await page.screenshot({ path: path.join(OUT, "reader-returned.png") });
  }
}

await browser.close();

if (problems.length > 0) {
  console.error(`\n${String(problems.length)} problem(s):`);
  for (const problem of problems) console.error(`  - ${problem}`);
  process.exit(1);
}
console.log("\nreader: PASS");
