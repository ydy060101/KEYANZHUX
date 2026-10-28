// T7.5 acceptance: walk the writing studio against the real API.
//
//   * 论文框架: generate an outline over SSE, verify the KaTeX preview and the
//     reference panel (verified cards, [待补充] for unmatched cite keys);
//   * 图表工坊: generate a Mermaid figure and wait for the browser-rendered SVG;
//   * 数据工坊: upload a CSV, generate a chart, check the caption/stats panel;
//   * 学术翻译: translate a Chinese abstract and require an English-only result;
//   * every workspace fits 1440×900 and 1280×720 in both themes with no
//     console errors or warnings and no horizontal overflow (H16).
//
// Run from frontend/ with the API, worker and dev server up:
//   node e2e/verify-writing.mjs [baseUrl]

import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(here, "screenshots");
const base = process.argv[2] ?? "http://127.0.0.1:5173";

const problems = [];
const fail = (message) => problems.push(message);
await mkdir(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("console", (message) => {
  if (message.type() === "error" || message.type() === "warning") {
    fail(`console ${message.type()}: ${message.text()}`);
  }
});
page.on("pageerror", (error) => {
  fail(`pageerror: ${error.message}`);
});

async function setTheme(target) {
  for (let index = 0; index < 4; index += 1) {
    const current = await page.evaluate(() => document.documentElement.dataset["theme"]);
    if (current === target) return;
    await page.getByRole("button", { name: /切换主题/ }).click();
    await page.waitForTimeout(180);
  }
  const current = await page.evaluate(() => document.documentElement.dataset["theme"]);
  if (current !== target) fail(`could not switch to the ${target} theme (got ${String(current)})`);
}

async function checkLayout(label) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  if (overflow > 1) fail(`${label}: horizontal overflow ${String(overflow)}px`);
}

/** Screenshot the active workspace in both themes at both card viewports. */
async function audit(label) {
  for (const [width, height] of [
    [1440, 900],
    [1280, 720],
  ]) {
    await page.setViewportSize({ width, height });
    for (const theme of ["light", "dark"]) {
      await setTheme(theme);
      await page.waitForTimeout(350);
      await checkLayout(`${label} ${String(width)}×${String(height)} ${theme}`);
      await page.screenshot({ path: path.join(OUT, `${label}-${String(width)}x${String(height)}-${theme}.png`) });
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await setTheme("light");
}

async function openTab(key, readyTestId) {
  const tab = page.getByTestId(`writing-tab-${key}`);
  await tab.click();
  // A dev server may still re-optimise a dependency and reload the page; the
  // second click lands on the same tab after the reload and is a no-op when
  // the first load was already stable.
  await page.waitForTimeout(1500);
  await tab.click();
  await page.getByTestId(readyTestId).waitFor({ state: "visible", timeout: 120_000 });
  await page.waitForTimeout(250);
}

await page.goto(`${base}/writing`, { waitUntil: "domcontentloaded" });
await page.getByTestId("writing-idea").waitFor({ state: "visible", timeout: 30_000 });

// --- 论文框架 --------------------------------------------------------------
await page.getByTestId("writing-idea").fill(
  "一种面向长文档的可溯源检索增强问答方法：解析版面与公式，按证据块回答，每条结论附原文锚点，依据不足时明确拒答。",
);
await page.getByTestId("writing-generate").click();
await page.getByTestId("outline-preview").waitFor({ state: "visible", timeout: 240_000 });
const preview = (await page.getByTestId("outline-preview").textContent()) ?? "";
const citations = await page.locator("[data-citation-key]").count();
const references = await page.getByTestId("writing-reference").count();
const missing = await page.getByTestId("writing-reference-missing").count();
console.log(
  `outline: ${String(preview.trim().length)} chars, ${String(citations)} citation chips, ` +
    `${String(references)} verified cards, ${String(missing)} [待补充]`,
);
if (preview.trim().length < 200) fail(`the outline preview is suspiciously short (${String(preview.trim().length)} chars)`);
if (citations === 0) fail("the outline contains no clickable citation");
if (references === 0 && missing === 0) fail("the reference panel is empty");
if (await page.getByTestId("writing-bibtex").isDisabled()) fail("the BibTeX export is disabled");
if (citations > 0) {
  const chip = page.locator("[data-citation-key]").first();
  const key = await chip.getAttribute("data-citation-key");
  await chip.click();
  const card = page.locator(`[data-reference-key="${String(key)}"]`);
  if ((await card.count()) === 0 && (await page.getByTestId("writing-reference-missing").count()) === 0) {
    fail(`citation ${String(key)} is not represented in the reference panel`);
  }
}
await audit("writing-outline");

// --- 图表工坊 --------------------------------------------------------------
await openTab("figures", "figure-description");
await page.getByTestId("figure-description").fill(
  "画一个三阶段流程图：文献解析 → 证据检索 → 带锚点回答，每个阶段一个方框并用箭头串联。",
);
await page.getByTestId("figure-generate").click();
await page.getByTestId("figure-svg").waitFor({ state: "visible", timeout: 240_000 });
const figureErrors = page.getByTestId("figure-errors");
if ((await figureErrors.count()) > 0) {
  fail(`figure generation reported errors: ${(await figureErrors.textContent()) ?? ""}`);
}
const svgBox = await page.getByTestId("figure-svg").boundingBox();
if (!svgBox || svgBox.width < 40 || svgBox.height < 40) fail("the rendered Mermaid SVG is too small");
if (await page.getByTestId("figure-export-png").isDisabled()) fail("the figure PNG export is disabled");
console.log(`figure: SVG ${String(Math.round(svgBox?.width ?? 0))}×${String(Math.round(svgBox?.height ?? 0))}`);
await audit("writing-figure");

// --- 数据工坊 --------------------------------------------------------------
const csv = ["year,accuracy,tokens", "2018,71.2,120", "2019,74.8,180", "2020,79.3,260", "2021,82.1,390", "2022,86.4,540", "2023,89.8,720"].join("\n");
await openTab("data", "data-file");
await page.getByTestId("data-file").setInputFiles({
  name: "accuracy.csv",
  mimeType: "text/csv",
  buffer: Buffer.from(csv, "utf-8"),
});
await page.getByTestId("data-meta").waitFor({ state: "visible", timeout: 60_000 });
const meta = (await page.getByTestId("data-meta").textContent()) ?? "";
if (!meta.includes("accuracy.csv")) fail(`the dataset panel does not name the file: ${meta}`);
await page.getByTestId("data-generate").click();
await page.getByTestId("data-caption").waitFor({ state: "visible", timeout: 240_000 });
const caption = await page.getByTestId("data-caption").inputValue();
const stats = (await page.getByTestId("data-stats").textContent()) ?? "";
if (caption.trim().length < 10) fail("the generated caption is empty");
if (!/\d/.test(stats)) fail("the statistics panel has no numbers");
if (await page.getByTestId("data-chart").count() === 0) fail("the ECharts canvas is missing");
if (await page.getByTestId("data-export-png").isDisabled()) fail("the chart PNG export is disabled");
console.log(`data: caption ${String(caption.length)} chars, stats ${String(stats.length)} chars`);
await audit("writing-data");

// --- 学术翻译 --------------------------------------------------------------
await openTab("translate", "translate-source");
const abstract =
  "本文提出一种可溯源的检索增强问答方法。我们把 PDF 按版面块切分并建立向量索引，使用 RRF 融合向量与 BM25 的召回结果。实验表明，该方法在三个长文档数据集上将引用准确率提高到 91.4%。";
await page.getByTestId("translate-source").fill(abstract);
await page.getByTestId("translate-run").click();
await page.getByTestId("translate-target").waitFor({ state: "visible", timeout: 240_000 });
const english = (await page.getByTestId("translate-target").textContent()) ?? "";
if (/[一-鿿]/.test(english)) fail("the translation still contains Chinese characters");
if (english.trim().length < 80) fail(`the translation is suspiciously short (${String(english.trim().length)} chars)`);
if (await page.getByTestId("translate-copy").isDisabled()) fail("the translation copy button is disabled");
console.log(`translation: ${String(english.trim().length)} chars, no CJK`);
await audit("writing-translate");

await browser.close();
if (problems.length > 0) {
  for (const problem of problems) console.error(`FAIL ${problem}`);
  console.error("writing-e2e: FAIL");
  process.exit(1);
}
console.log("writing-e2e: PASS");
