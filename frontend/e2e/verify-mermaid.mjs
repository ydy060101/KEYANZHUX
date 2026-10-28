// T7.2 acceptance: prove that a generated Mermaid script renders in a real
// browser (jsdom has no SVG getBBox, so this cannot be a vitest check).
import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const file = process.argv[2];
if (!file) {
  console.error("usage: node e2e/verify-mermaid.mjs <figure-result.json>");
  process.exit(2);
}
const source = JSON.parse(readFileSync(file, "utf-8")).script;

const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.setContent("<!doctype html><html><body></body></html>");
  await page.addScriptTag({ path: resolve("node_modules/mermaid/dist/mermaid.min.js") });
  const svg = await page.evaluate(async (text) => {
    mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
    const result = await mermaid.render("figure-check", text);
    return result.svg;
  }, source);
  const ok = typeof svg === "string" && svg.trimStart().startsWith("<svg") && svg.includes("</svg>");
  console.log(JSON.stringify({ ok, svg_bytes: svg.length, console_errors: consoleErrors }));
  if (!ok || consoleErrors.length > 0) process.exit(1);
} finally {
  await browser.close();
}
