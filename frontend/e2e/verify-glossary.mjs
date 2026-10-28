// Verifies the glossary and the translation cache against the real stack (T4.4).
//
//   * a fresh user has no glossary, so its blocks use the version-0 cache: two
//     translation jobs on an already translated paper must report zero model
//     work the second time (the card's "重复翻译命中缓存");
//   * the reader's translation tab shows the glossary, adding a term stores it,
//     the version advances, it survives a reload, and deleting it returns the
//     list to empty with another version.
//
// The glossary is reset before the UI test and the original list is restored
// afterwards, so running the script does not leave test terms behind.
//
// Run from frontend/ with both dev servers up:
//   node e2e/verify-glossary.mjs [docId]

import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(here, "screenshots");
const base = process.argv[2] ?? "http://localhost:5173";
const api = "http://127.0.0.1:8000/api/v1";
const defaultHeaders = { "X-User-Id": "default" };
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const problems = [];
const fail = (message) => problems.push(message);
await mkdir(OUT, { recursive: true });

async function call(pathname, init = {}, headers = defaultHeaders) {
  const response = await fetch(`${api}${pathname}`, {
    ...init,
    headers: {
      ...headers,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(`${pathname} → ${String(response.status)} ${JSON.stringify(payload)}`);
  }
  return payload;
}

function glossaryHead(payload) {
  return { version: Number(payload?.version ?? 0), entries: payload?.entries ?? [] };
}

async function putGlossary(entries, headers = defaultHeaders) {
  return glossaryHead(
    await call("/translate/glossary", { method: "PUT", body: JSON.stringify({ entries }) }, headers),
  );
}

async function translateOnce(docId, user) {
  const headers = { "X-User-Id": user };
  const started = await call(
    `/documents/${encodeURIComponent(docId)}/translate`,
    { method: "POST", body: JSON.stringify({ format: "md", direction: "en2zh" }) },
    headers,
  );
  const deadline = Date.now() + 5 * 60_000;
  for (;;) {
    if (Date.now() > deadline) throw new Error("translation job exceeded 5 minutes");
    const job = await call(`/jobs/${String(started.job_id)}`, {}, headers);
    if (job.status === "succeeded") return job.result ?? {};
    if (job.status === "failed" || job.status === "cancelled") {
      throw new Error(`translation job ${String(job.status)}: ${String(job.error ?? "")}`);
    }
    await sleep(1000);
  }
}

// ---- pick a document that already has translations ---------------------
const listing = await call("/documents?page_size=100");
const ready = (listing.items ?? [])
  .filter((doc) => doc.status === "ready" && doc.page_count > 0)
  .sort((a, b) => a.page_count - b.page_count);
let doc = process.argv[3] ? ready.find((item) => item.id === process.argv[3]) : undefined;
for (const candidate of ready) {
  if (doc) break;
  const translation = await call(
    `/documents/${encodeURIComponent(candidate.id)}/translation?direction=en2zh`,
  );
  if ((translation.blocks ?? []).length > 0) doc = candidate;
}
if (!doc) {
  console.error("no translated document — run e2e/verify-bilingual.mjs first");
  process.exit(1);
}
console.log(`${doc.title} (${String(doc.page_count)} pages)`);

// ---- repeated translation hits the cache -------------------------------
// A never-used user id has version 0 and no glossary file, which is exactly
// the key the existing translation rows were written under.
const cacheUser = `e2e-cache-${String(Date.now())}`;
const first = await translateOnce(doc.id, cacheUser);
const second = await translateOnce(doc.id, cacheUser);
console.log(
  `first: translated=${String(first.translated)} cached=${String(first.cached)} skipped=${String(first.skipped)} v=${String(first.glossary_version)}`,
);
console.log(
  `second: translated=${String(second.translated)} cached=${String(second.cached)} skipped=${String(second.skipped)} v=${String(second.glossary_version)}`,
);
if (second.translated !== 0) fail(`the second run translated ${String(second.translated)} blocks instead of using the cache`);
if ((second.cached ?? 0) + (second.skipped ?? 0) !== second.blocks) {
  fail(`the second run cached ${String(second.cached)} and skipped ${String(second.skipped)} of ${String(second.blocks)} blocks`);
}
if (second.glossary_version !== 0) fail(`a fresh user should use glossary version 0, got ${String(second.glossary_version)}`);
if ((second.cached ?? 0) === 0) fail("the second run reported no cached blocks");

const original = glossaryHead(await call("/translate/glossary"));
const cleared = await putGlossary([]);
console.log(`glossary reset: v${String(original.version)} → v${String(cleared.version)}`);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const consoleProblems = [];
page.on("console", (message) => {
  if (message.type() === "error" || message.type() === "warning") {
    consoleProblems.push(`console ${message.type()}: ${message.text()}`);
  }
});
page.on("pageerror", (error) => consoleProblems.push(`pageerror: ${error.message}`));

async function openGlossary() {
  await page.goto(`${base}/reader/${doc.id}`, { waitUntil: "domcontentloaded" });
  await page.locator("canvas").first().waitFor({ state: "visible", timeout: 60_000 });
  await page.getByRole("tab", { name: "翻译" }).click();
  const panel = page.getByTestId("glossary-panel");
  await panel.waitFor({ state: "visible", timeout: 20_000 });
  await panel.scrollIntoViewIfNeeded();
  return panel;
}

let addedVersion = null;
let deleteVersion = null;
try {
  const panel = await openGlossary();
  await page.getByTestId("glossary-empty").waitFor({ state: "visible", timeout: 10_000 });
  const before = await page.getByTestId("glossary-version").textContent();
  if (before?.trim() !== `v${String(cleared.version)}`) {
    fail(`the panel shows ${String(before)}, expected v${String(cleared.version)}`);
  }

  await page.getByLabel("原文术语").fill("attention");
  await page.getByLabel("译文术语").fill("注意力机制");
  await page.getByTestId("glossary-add").click();
  await page.locator('[data-glossary-entry="attention"]').waitFor({ state: "visible", timeout: 10_000 });
  addedVersion = Number((await page.getByTestId("glossary-version").textContent())?.replace("v", ""));
  console.log(`added term; glossary version ${String(cleared.version)} → ${String(addedVersion)}`);
  if (addedVersion !== cleared.version + 1) {
    fail(`adding a term changed the version to ${String(addedVersion)}, expected ${String(cleared.version + 1)}`);
  }
  const notice = await page.getByTestId("glossary-notice").textContent();
  if (!notice?.includes("重新翻译")) fail("the panel does not say that a retranslation is needed");

  await page.screenshot({ path: path.join(OUT, "glossary-1440-light.png") });
  const overflow1440 = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  console.log(`1440×900 horizontal overflow: ${String(overflow1440)} px`);
  if (overflow1440 > 1) fail(`page overflows horizontally by ${String(overflow1440)} px at 1440×900`);
  await page.getByLabel("切换到深色主题").click();
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(OUT, "glossary-1440-dark.png") });
  await page.getByLabel("切换到浅色主题").click();
  await page.waitForTimeout(200);

  // Persistence: the term is served by the API after a reload.
  await openGlossary();
  await page.locator('[data-glossary-entry="attention"]').waitFor({ state: "visible", timeout: 10_000 });
  const persisted = await page.getByTestId("glossary-version").textContent();
  if (persisted?.trim() !== `v${String(addedVersion)}`) {
    fail(`after reload the glossary shows ${String(persisted)}, expected v${String(addedVersion)}`);
  }

  await page.setViewportSize({ width: 1280, height: 720 });
  await page.waitForTimeout(300);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  console.log(`1280×720 horizontal overflow: ${String(overflow)} px`);
  if (overflow > 1) fail(`page overflows horizontally by ${String(overflow)} px at 1280×720`);
  await page.screenshot({ path: path.join(OUT, "glossary-1280-light.png") });
  await page.getByLabel("切换到深色主题").click();
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(OUT, "glossary-1280-dark.png") });
  await page.getByLabel("切换到浅色主题").click();
  await page.waitForTimeout(200);

  await page.getByRole("button", { name: "删除术语 attention" }).click();
  await page.getByTestId("glossary-empty").waitFor({ state: "visible", timeout: 10_000 });
  deleteVersion = Number((await page.getByTestId("glossary-version").textContent())?.replace("v", ""));
  console.log(`deleted term; glossary version ${String(addedVersion)} → ${String(deleteVersion)}`);
  if (deleteVersion !== addedVersion + 1) {
    fail(`deleting a term changed the version to ${String(deleteVersion)}, expected ${String(addedVersion + 1)}`);
  }
  const after = await call("/translate/glossary");
  if ((after.entries ?? []).length !== 0) fail("the API still serves terms after the UI deleted them");
} catch (error) {
  fail(error instanceof Error ? error.message : String(error));
} finally {
  await putGlossary(original.entries).catch((error) => {
    fail(`could not restore the original glossary: ${String(error)}`);
  });
  await browser.close();
}

for (const message of consoleProblems) fail(message);
if (problems.length > 0) {
  console.error(`\nFAIL\n- ${problems.join("\n- ")}`);
  process.exit(1);
}
console.log("\nPASS — repeated translation is cached, glossary add/delete/version works, both viewports/themes");
