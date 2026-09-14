#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { chromium } = require(
  fs.existsSync(path.join(__dirname, "ggsel_plati", "node_modules", "playwright"))
    ? path.join(__dirname, "ggsel_plati", "node_modules", "playwright")
    : "playwright"
);

const argv = process.argv.slice(2);
const args = {};
for (let i = 0; i < argv.length; i++) {
  if (!argv[i].startsWith("--")) continue;
  const key = argv[i].slice(2);
  args[key] = argv[i + 1];
  i += 1;
}
if (!args.input || !args.out) throw new Error("--input and --out are required");

const CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
// Variant labels may embed a live surcharge.  It is page state, not part of
// the variant identity; tier/duration/delivery text must still match exactly.
const controlKey = (value) => normalize(value)
  .replace(/[+-]?\s*\d[\d\s\u00a0]*(?:[.,]\d+)?\s*(?:₽|руб|RUB)(?:\s+за\s+.+)?$/i, "")
  .trim();
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function parseRub(text) {
  const match = normalize(text).match(/(\d[\d\s\u00a0]*)\s*(?:₽|руб|RUB)/i);
  return match ? Number(match[1].replace(/[\s\u00a0]/g, "")) : null;
}

async function primaryPrice(page) {
  return page.evaluate(() => {
    const visible = (el) => {
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    };
    const selectors = [
      '[class*="id_product_price"]',
      '[id*="id_product_price"]',
      '[class*="ProductBuyBlock"] [class*="amount"]',
      '[class*="ProductBuyBlock"] [class*="Amount"]',
    ];
    for (const selector of selectors) {
      for (const el of document.querySelectorAll(selector)) {
        const text = (el.innerText || el.textContent || "").trim();
        if (visible(el) && /\d[\d\s\u00a0]*\s*(?:₽|руб|RUB)/i.test(text)) return text;
      }
    }
    return null;
  });
}

async function locateExact(page, offer) {
  const selectors = {
    button: "button", label: "label", radio: 'input[type="radio"]',
    "role-radio": '[role="radio"]', "select-option": "select option",
  };
  const preferred = selectors[offer.controlKind];
  const candidates = preferred ? [preferred] : Object.values(selectors);
  const wanted = controlKey(offer.optionText);
  for (const selector of candidates) {
    const locator = page.locator(selector);
    const count = await locator.count();
    for (let index = 0; index < count; index++) {
      const item = locator.nth(index);
      const text = await item.evaluate((el) => {
        if (el.matches('input[type="radio"]')) {
          const label = el.closest("label") || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`));
          return (label && (label.innerText || label.textContent)) || el.value || el.name || "";
        }
        return el.innerText || el.textContent || "";
      });
      if (controlKey(text) === wanted) return { locator: item, selector, index };
    }
  }
  return null;
}

async function selectedState(locator) {
  return locator.evaluate((el) => {
    const input = el.matches("input,option") ? el : el.querySelector('input[type="radio"],input[type="checkbox"],option');
    const nodes = [el, input].filter(Boolean);
    const aria = nodes.some((node) => ["aria-checked", "aria-selected", "aria-pressed"].some((name) => node.getAttribute(name) === "true"));
    const classes = nodes.flatMap((node) => String(node.className || "").split(/\s+/));
    const strictClass = classes.some((name) => /^(?:selected|checked|chosen|is-selected|is-checked)$/i.test(name));
    const text = (el.innerText || el.textContent || "").trim();
    return Boolean(el.checked || el.selected || (input && (input.checked || input.selected)) || aria || strictClass || /(?:^|\s)(?:выбран(?:о|а)?|selected)(?:\s|$)/i.test(text));
  });
}

async function verifyOne(browser, offer) {
  const result = { ...offer, observedPrice: null, selected: false, stable: false, verified: false, verifiedAt: new Date().toISOString(), error: null };
  const context = await browser.newContext({
    locale: "ru-RU",
    userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
  });
  const page = await context.newPage();
  page.setDefaultTimeout(12000);
  try {
    await page.goto(offer.url, { waitUntil: "domcontentloaded", timeout: 35000 });
    await sleep(2200);
    const target = await locateExact(page, offer);
    if (!target) {
      const nearby = await page.locator('label,button,[role="radio"]').evaluateAll((nodes) => nodes
        .map((el) => (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim())
        .filter((text) => /pro|20x|20х|месяц/i.test(text)).slice(0, 8));
      throw new Error(`exact variant control not found; nearby=${JSON.stringify(nearby)}`);
    }
    if (target.selector === "select option") {
      const value = await target.locator.getAttribute("value");
      await target.locator.locator("xpath=..").selectOption(value);
    } else {
      await target.locator.click({ timeout: 12000 });
    }
    await sleep(400);
    result.selected = await selectedState(target.locator);
    if (!result.selected) throw new Error("variant click has no selected-state proof");
    let previous = null;
    let stableSamples = 0;
    const deadline = Date.now() + 8000;
    while (Date.now() < deadline) {
      const text = await primaryPrice(page);
      const price = text ? parseRub(text) : null;
      stableSamples = price !== null && price === previous ? stableSamples + 1 : 0;
      previous = price;
      if (stableSamples >= 2) { result.stable = true; break; }
      await sleep(350);
    }
    result.observedPrice = previous;
    if (!result.stable || result.observedPrice === null) throw new Error("primary price did not become stable");
    if (Number(result.observedPrice) !== Number(offer.expectedPrice)) {
      throw new Error(`price mismatch: expected ${offer.expectedPrice}, observed ${result.observedPrice}`);
    }
    result.verified = true;
  } catch (error) {
    result.error = String(error && error.message || error);
  } finally {
    await context.close();
  }
  return result;
}

(async () => {
  const input = JSON.parse(fs.readFileSync(args.input, "utf8"));
  const browser = await chromium.launch({
    headless: true,
    executablePath: CHROME_PATH,
    args: ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
  });
  const results = [];
  try {
    for (const offer of input.offers || []) results.push(await verifyOne(browser, offer));
  } finally {
    await browser.close();
  }
  const report = { schemaVersion: 1, verifiedAt: new Date().toISOString(), results };
  fs.writeFileSync(args.out, JSON.stringify(report, null, 2));
  process.exitCode = results.every((item) => item.verified) ? 0 : 1;
})().catch((error) => {
  fs.writeFileSync(args.out, JSON.stringify({ schemaVersion: 1, results: [], error: String(error && error.stack || error) }, null, 2));
  process.exitCode = 2;
});
