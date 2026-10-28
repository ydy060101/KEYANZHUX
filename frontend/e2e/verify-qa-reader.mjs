// Verifies the QA → reader half of T3.5 against the real API.
//
// `verify-qa.mjs` covers the same steps after a compare table; this script
// reaches them from a single-document answer instead, so the reader jump can
// be checked on its own when a full compare run is not affordable.
//
//   * a chip opens the split preview on the anchor page with its bbox drawn;
//   * the "在阅读台打开" link carries page + bbox into the full reader, which
//     lands on that page and draws the highlight;
//   * the reader's 问答 rail is the shared chat, scoped to the open paper;
//   * the QA page fits 1280×720 with the preview open, zero console errors.
//
// Run from frontend/ with the API and dev server up:
//   node e2e/verify-qa-reader.mjs [baseUrl]

import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(here, "screenshots");
const base = process.argv[2] ?? "http://localhost:5173";
const api = "http://127.0.0.1:8000/api/v1";
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

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("console", (m) => {
  if (m.type() === "error" || m.type() === "warning") fail(`console ${m.type()}: ${m.text()}`);
});
page.on("pageerror", (e) => fail(`pageerror: ${e.message}`));

await page.goto(`${base}/qa`, { waitUntil: "domcontentloaded" });
await page.getByTestId("qa-input").waitFor({ state: "visible", timeout: 30_000 });

let chip = null;
let anchorDoc = null;
for (const doc of ready.slice(0, 2)) {
  await page.getByRole("button", { name: "新建会话" }).first().click();
  await page.getByRole("group", { name: "检索范围" }).getByRole("button", { name: "单篇" }).click();
  await page.getByLabel("选择文献").selectOption(doc.id);
  const before = await page.locator('[data-testid="qa-turn"]').count();
  await page.getByTestId("qa-input").fill("训练用了什么 GPU？");
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
  const count = await turn.locator("[data-anchor-chip]").count();
  console.log(`${doc.title}: anchors=${String(count)}`);
  if (count > 0) {
    chip = turn.locator("[data-anchor-chip]").first();
    anchorDoc = doc;
    break;
  }
}

if (!chip) {
  fail("neither of the two most-cited papers produced an anchored answer");
} else {
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
  await page.screenshot({ path: path.join(OUT, "qa-preview-single.png") });

  const href = await preview.getByRole("link", { name: "在阅读台打开" }).getAttribute("href");
  if (!href) {
    fail("the preview has no 阅读台 link");
  } else {
    const parsed = new URL(href, base);
    if (parsed.searchParams.get("page") !== String(pageNumber)) {
      fail(`阅读台 link page ${String(parsed.searchParams.get("page"))} != chip page ${String(pageNumber)}`);
    }
    if (!parsed.searchParams.get("bbox")) fail("阅读台 link lost the bbox");

    await page.setViewportSize({ width: 1280, height: 720 });
    await page.waitForTimeout(400);
    const overflow = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    console.log(`1280×720 scrollWidth=${String(overflow.scroll)} clientWidth=${String(overflow.client)}`);
    if (overflow.scroll > overflow.client + 1) fail("the QA page overflows horizontally at 1280×720");
    if (!(await preview.isVisible())) fail("the split preview is not visible at 1280×720");
    await page.screenshot({ path: path.join(OUT, "qa-preview-1280.png") });

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(parsed.href, { waitUntil: "domcontentloaded" });
    await page.locator("canvas").first().waitFor({ state: "visible", timeout: 60_000 });
    await page.waitForFunction(
      () => document.querySelector(".bg-\\[var\\(--hl\\)\\]") !== null,
      null,
      { timeout: 20_000 },
    );
    await page.waitForFunction(
      (expected) => {
        const input = document.querySelector('[aria-label="跳转页码"]');
        return input instanceof HTMLInputElement && Number(input.value) === expected;
      },
      pageNumber,
      { timeout: 10_000 },
    );
    const current = await page.locator('[aria-label="跳转页码"]').inputValue();
    if (Number(current) !== pageNumber) {
      fail(`the full reader opened page ${current}, not ${String(pageNumber)}`);
    }
    console.log(`full reader highlighted page ${current} (${anchorDoc.title})`);
    await page.screenshot({ path: path.join(OUT, "qa-reader-highlight.png") });

    await page.getByRole("tab", { name: "问答" }).click();
    await page.getByPlaceholder("就这篇文献提问…").waitFor({ state: "visible", timeout: 10_000 });
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
console.log("\nqa-reader: PASS");
