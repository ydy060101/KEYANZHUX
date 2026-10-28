// Verifies the QA page against the real API (T3.5, acceptance step 3).
//
// The checks are the ones the card names, observed through the UI:
//
//   * a question produces an answer whose claims carry anchor chips;
//   * clicking a chip opens the split reader on the anchor's page and draws
//     the bbox highlight, and the "阅读台" link carries the same page/bbox;
//   * an answer the library cannot support refuses instead of guessing;
//   * compare mode renders every cell with its evidence (grounded cells have
//     a chip, "未在原文找到" cells have none);
//   * the page fits 1440×900 and 1280×720 without horizontal overflow, with
//     zero console errors or warnings.
//
// Run from frontend/ with the API and dev server up:
//   node e2e/verify-qa.mjs [baseUrl]

import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(here, "screenshots");
const base = process.argv[2] ?? "http://localhost:5173";
const api = "http://127.0.0.1:8000/api/v1";
const NOT_FOUND = "未在原文找到";
const ASK_TIMEOUT = 240_000;

const problems = [];
const fail = (message) => problems.push(message);
await mkdir(OUT, { recursive: true });

const listing = await fetch(`${api}/documents?page_size=100`, {
  headers: { "X-User-Id": "default" },
}).then((r) => r.json());
const ready = (listing.items ?? [])
  .filter((doc) => doc.status === "ready")
  .sort((a, b) => (b.stats?.citations ?? 0) - (a.stats?.citations ?? 0));
if (ready.length === 0) {
  console.error("no parsed document to ask about — parse one first");
  process.exit(1);
}
console.log(`ready documents: ${String(ready.length)}; first: ${ready[0].title}`);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("console", (m) => {
  if (m.type() === "error" || m.type() === "warning") fail(`console ${m.type()}: ${m.text()}`);
});
page.on("pageerror", (e) => fail(`pageerror: ${e.message}`));

/** Fill the composer, send, and wait for the newest turn to settle. */
async function ask(question) {
  const before = await page.locator('[data-testid="qa-turn"]').count();
  await page.getByTestId("qa-input").fill(question);
  await page.getByRole("button", { name: "发送" }).click();
  await page.waitForFunction(
    (previous) => {
      const turns = document.querySelectorAll('[data-testid="qa-turn"]');
      if (turns.length <= previous) return false;
      const last = turns[turns.length - 1];
      return last instanceof HTMLElement && last.dataset.qaStatus !== "streaming";
    },
    before,
    { timeout: ASK_TIMEOUT },
  );
  const turn = page.locator('[data-testid="qa-turn"]').last();
  const status = await turn.getAttribute("data-qa-status");
  if (status === "error") {
    fail(`question "${question}" ended in an error: ${(await turn.innerText()).slice(0, 200)}`);
  }
  return turn;
}

async function newSession() {
  await page.getByRole("button", { name: "新建会话" }).first().click();
  await page.getByRole("button", { name: "发送" }).waitFor();
}

async function pickSingleDocument(doc) {
  await page.getByRole("group", { name: "检索范围" }).getByRole("button", { name: "单篇" }).click();
  await page.getByLabel("选择文献").selectOption(doc.id);
}

/** Opens the split pane through a chip and checks the highlight. */
async function openChipAndCheck(chip) {
  const label = await chip.getAttribute("aria-label");
  const pageNumber = Number(/第 (\d+) 页/.exec(label ?? "")?.[1] ?? 0);
  if (!pageNumber) fail(`chip has no page in its label: ${String(label)}`);

  await chip.click();
  const preview = page.getByTestId("qa-preview");
  await preview.waitFor({ state: "visible", timeout: 10_000 });

  const frame = page.frameLocator('[data-testid="qa-preview-frame"]');
  await frame.locator("canvas").first().waitFor({ state: "visible", timeout: 60_000 });
  const highlight = frame.locator(".bg-\\[var\\(--hl\\)\\]");
  await highlight.first().waitFor({ state: "visible", timeout: 30_000 });
  const box = await highlight.first().boundingBox();
  if (!box || box.width < 3 || box.height < 3) {
    fail(`the anchor highlight is too small to see: ${JSON.stringify(box)}`);
  }
  const shown = await frame.getByTestId("embed-page").innerText();
  console.log(`chip "${label}" → ${shown}, highlight ${JSON.stringify(box)}`);
  if (!shown.includes(`第 ${String(pageNumber)}`)) {
    fail(`the preview showed "${shown}" instead of page ${String(pageNumber)}`);
  }

  const href = await preview.getByRole("link", { name: "在阅读台打开" }).getAttribute("href");
  if (!href) {
    fail("the preview has no 阅读台 link");
    return;
  }
  const parsed = new URL(href, base);
  if (parsed.searchParams.get("page") !== String(pageNumber)) {
    fail(`阅读台 link page ${String(parsed.searchParams.get("page"))} != chip page ${String(pageNumber)}`);
  }
  if (!parsed.searchParams.get("bbox")) fail("阅读台 link lost the bbox");
  return { pageNumber, href: parsed };
}

// ---- single-document QA: answer → chip → highlight ----------------------
await page.goto(`${base}/qa`, { waitUntil: "domcontentloaded" });
await page.getByTestId("qa-input").waitFor({ state: "visible", timeout: 30_000 });

let chip = null;
let anchorDoc = null;
for (const doc of ready.slice(0, 2)) {
  await newSession();
  await pickSingleDocument(doc);
  console.log(`asking about ${doc.title}`);
  const turn = await ask("训练用了什么 GPU？");
  const chips = turn.locator("[data-anchor-chip]");
  const refused = await turn.getByTestId("qa-refusal").count();
  const count = await chips.count();
  console.log(`  refused=${String(refused > 0)} anchors=${String(count)}`);
  if (count > 0) {
    chip = chips.first();
    anchorDoc = doc;
    break;
  }
}
if (!chip) {
  fail("neither of the two most-cited papers produced an anchored answer");
} else {
  await page.screenshot({ path: path.join(OUT, "qa-answer.png") });
  const opened = await openChipAndCheck(chip);
  await page.screenshot({ path: path.join(OUT, "qa-preview.png") });
  console.log(`anchored answer from ${anchorDoc.title}, page ${String(opened?.pageNumber)}`);
}

// ---- unsupported question refuses --------------------------------------
await newSession();
const refusedTurn = await ask("企鹅在南极繁殖期最适宜的气温是多少摄氏度？");
const refusal = refusedTurn.getByTestId("qa-refusal");
if ((await refusal.count()) === 0) {
  const answer = (await refusedTurn.innerText()).replace(/\s+/g, " ").slice(0, 200);
  fail(`an unsupported question was not refused: ${answer}`);
} else {
  await page.screenshot({ path: path.join(OUT, "qa-refusal.png") });
  console.log("unsupported question refused");
}

// ---- compare table ------------------------------------------------------
const compareDocs = ready.slice(0, 2);
let compareChip = null;
if (compareDocs.length < 2) {
  fail("compare mode needs two ready documents");
} else {
  await newSession();
  await page.getByRole("group", { name: "模式" }).getByRole("button", { name: "对比" }).click();
  await page.getByRole("group", { name: "检索范围" }).getByRole("button", { name: "选集" }).click();
  await page.getByRole("button", { name: "选择文献" }).click();
  for (const doc of compareDocs) {
    await page.getByLabel("搜索文献").fill(doc.title);
    await page.locator('ul[role="listbox"] li button').first().click();
  }
  await page.getByRole("button", { name: "完成" }).click();
  console.log(`comparing ${compareDocs.map((doc) => doc.title).join(" vs ")}`);

  const turn = await ask("Compare the number of layers and the number of attention heads.");
  const table = turn.getByTestId("compare-table");
  await table.waitFor({ state: "visible", timeout: 240_000 });

  const rows = table.locator("tbody tr");
  const rowCount = await rows.count();
  let grounded = 0;
  let missing = 0;
  for (let rowIndex = 0; rowIndex < rowCount; rowIndex += 1) {
    const cells = rows.nth(rowIndex).locator("td");
    for (let cellIndex = 0; cellIndex < (await cells.count()); cellIndex += 1) {
      const cell = cells.nth(cellIndex);
      const content = (await cell.innerText()).trim();
      if (content === "" || content === "—") continue;
      const anchors = await cell.locator("[data-anchor-chip]").count();
      if (content.includes(NOT_FOUND)) {
        missing += 1;
        if (anchors > 0) fail(`an empty compare cell carries ${String(anchors)} anchors`);
      } else {
        grounded += 1;
        if (anchors === 0) fail(`grounded compare cell "${content.slice(0, 60)}" has no anchor (H01)`);
        if (!compareChip) compareChip = cell.locator("[data-anchor-chip]").first();
      }
    }
  }
  console.log(`compare rows=${String(rowCount)} grounded=${String(grounded)} missing=${String(missing)}`);
  if (rowCount === 0) fail("the compare table rendered no rows");
  if (grounded === 0) fail("no compare cell found evidence in the selected papers");
  if (missing === 0) fail("no cell reported 未在原文找到 — the empty path was not exercised");
  if ((await table.getByRole("button", { name: "导出 Markdown" }).count()) === 0) {
    fail("the compare table has no Markdown export");
  }
  await page.screenshot({ path: path.join(OUT, "qa-compare.png") });
}

// ---- 1280×720 layout ----------------------------------------------------
await page.setViewportSize({ width: 1280, height: 720 });
await page.waitForTimeout(500);
if (compareChip) await openChipAndCheck(compareChip);
const overflow = await page.evaluate(() => ({
  scroll: document.documentElement.scrollWidth,
  client: document.documentElement.clientWidth,
}));
console.log(`1280×720 scrollWidth=${String(overflow.scroll)} clientWidth=${String(overflow.client)}`);
if (overflow.scroll > overflow.client + 1) fail("the QA page overflows horizontally at 1280×720");
if (!(await page.getByTestId("qa-preview").isVisible())) {
  fail("the split preview is not visible at 1280×720");
}
await page.screenshot({ path: path.join(OUT, "qa-1280.png") });

// ---- the same anchor in the full reader ---------------------------------
if (compareChip) {
  const opened = await openChipAndCheck(compareChip);
  if (opened) {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(new URL(opened.href, base).href, { waitUntil: "domcontentloaded" });
    await page.locator("canvas").first().waitFor({ state: "visible", timeout: 60_000 });
    await page.waitForFunction(
      () => document.querySelector(".bg-\\[var\\(--hl\\)\\]") !== null,
      null,
      { timeout: 20_000 },
    );
    // The scroll is instant, but the observer that drives the page box
    // reports on its next frame; give it that frame before reading the box.
    await page.waitForFunction(
      (expected) => {
        const input = document.querySelector('[aria-label="跳转页码"]');
        return input instanceof HTMLInputElement && Number(input.value) === expected;
      },
      opened.pageNumber,
      { timeout: 10_000 },
    );
    const current = await page.locator('[aria-label="跳转页码"]').inputValue();
    if (Number(current) !== opened.pageNumber) {
      fail(`the full reader opened page ${current}, not ${String(opened.pageNumber)}`);
    }
    console.log(`full reader highlighted page ${current} from the URL query`);
    await page.screenshot({ path: path.join(OUT, "qa-reader-highlight.png") });

    // The reader's 问答 tab is the same chat, scoped to the open paper.
    await page.getByRole("tab", { name: "问答" }).click();
    const panel = page.getByPlaceholder("就这篇文献提问…");
    await panel.waitFor({ state: "visible", timeout: 10_000 });
    if ((await page.getByRole("tab", { name: "问答" }).count()) === 0) {
      fail("the reader has no QA rail tab");
    }
    console.log("reader QA rail rendered the shared chat");
    await page.screenshot({ path: path.join(OUT, "qa-reader-rail.png") });
  }
}

await browser.close();

if (problems.length > 0) {
  console.error(`\n${String(problems.length)} problem(s):`);
  for (const problem of problems) console.error(`  - ${problem}`);
  process.exit(1);
}
console.log("\nqa: PASS");
