#!/usr/bin/env node
// Z.ai / GLM Coding variant price collector — Plati + GGSEL
// Pass 1: N parallel Playwright workers. Multi-template aware.
// Pass 2 (zai_analyze.py) interprets.
//
// Run:
//   node zai_price_scanner.js [--workers=6] [--out=/tmp/zai_raw.json]

const path = require('path');
const fs = require('fs');
const { chromium } = require(
  fs.existsSync(path.join(__dirname, 'ggsel_plati', 'node_modules', 'playwright'))
    ? path.join(__dirname, 'ggsel_plati', 'node_modules', 'playwright')
    : 'playwright',
);

const CHROME_PATH = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

// Populated via --plati-pids / --ggsel-ids CLI args. Empty defaults.
const PLATI_PIDS = [];
const GGSEL_IDS = [];
const PROXY_URLS = [];

// Parse --key=value OR --key value (next must not start with --)
const argv = process.argv.slice(2);
const args = {};
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (!a.startsWith('--')) continue;
  let key, value;
  const eq = a.indexOf('=');
  if (eq >= 0) {
    key = a.slice(2, eq);
    value = a.slice(eq + 1);
  } else {
    key = a.slice(2);
    const next = argv[i + 1];
    if (next !== undefined && !next.startsWith('--')) {
      value = next;
      i++;
    } else {
      value = true;
    }
  }
  args[key] = value;
}
// Merge --plati-pids / --ggsel-ids (comma-separated) into the empty defaults
if (args['plati-pids']) {
  for (const p of String(args['plati-pids']).split(',').map((s) => Number(s.trim())).filter(Boolean)) {
    if (!PLATI_PIDS.includes(p)) PLATI_PIDS.push(p);
  }
}
if (args['ggsel-ids']) {
  for (const id of String(args['ggsel-ids']).split(',').map((s) => s.trim()).filter(Boolean)) {
    if (!GGSEL_IDS.includes(id)) GGSEL_IDS.push(id);
  }
}
if (args['proxy-list-file']) {
  try {
    const list = JSON.parse(fs.readFileSync(String(args['proxy-list-file']), 'utf8'));
    if (!Array.isArray(list)) throw new Error('not an array');
    for (let i = 0; i < list.length; i++) {
      const value = list[i];
      const parsed = new URL(value);
      if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname || !parsed.port ||
          !['', '/'].includes(parsed.pathname) || parsed.search || parsed.hash) {
        throw new Error(`invalid entry ${i + 1}`);
      }
      PROXY_URLS.push(value);
    }
  } catch (e) {
    process.stderr.write('Invalid proxy-list file; expected HTTP(S) URLs, one per list item.\n');
    process.exit(2);
  }
}
const PROXY_REDACTIONS = PROXY_URLS.flatMap((proxyUrl) => {
  try {
    const parsed = new URL(proxyUrl);
    return [proxyUrl, parsed.host, parsed.hostname, decodeURIComponent(parsed.username), decodeURIComponent(parsed.password)]
      .filter(Boolean);
  } catch (_) {
    return [proxyUrl];
  }
});
const REUSE_ROTATING_PROXY = args['proxy-reuse'] === true || args['proxy-reuse'] === 'true';
if (REUSE_ROTATING_PROXY && PROXY_URLS.length !== 1) {
  process.stderr.write('Proxy reuse requires exactly one configured rotating HTTP proxy.\n');
  process.exit(2);
}
function redactProxyText(value) {
  let text = String(value || '');
  for (const secret of PROXY_REDACTIONS) text = text.split(secret).join('[proxy]');
  return text;
}
const WORKERS = Number(args.workers || 2);
if (!Number.isInteger(WORKERS) || WORKERS < 1 || WORKERS > 2) {
  process.stderr.write('Browser worker count must be between 1 and 2 for the reviewed Mac budget.\n');
  process.exit(2);
}
const MAX_CAPTURE_RETRIES = 4;
function parseCaptureRetries(value) {
  if (value === undefined) return 2;
  const text = String(value);
  if (!/^\d+$/.test(text)) {
    throw new Error(`--capture-retries must be an integer from 0 to ${MAX_CAPTURE_RETRIES} (default 2)`);
  }
  const retries = Number(text);
  if (!Number.isSafeInteger(retries) || retries > MAX_CAPTURE_RETRIES) {
    throw new Error(`--capture-retries must be an integer from 0 to ${MAX_CAPTURE_RETRIES} (default 2)`);
  }
  return retries;
}
let CAPTURE_RETRIES;
try {
  CAPTURE_RETRIES = parseCaptureRetries(args['capture-retries']);
} catch (e) {
  process.stderr.write(`error: ${e.message}\n`);
  process.exit(2);
}
const OUT_PATH = args.out || '/tmp/zai_raw.json';
const PAGE_TIMEOUT_MS = Number(args['page-timeout'] || 35000);
const CLICK_TIMEOUT_MS = Number(args['click-timeout'] || 8000);
const PRICE_SETTLE_TIMEOUT_MS = Number(args['price-settle-timeout'] || 5000);
// GGSEL's MUI product form applies variant changes in a regular browser but
// suppresses them in headless Chrome. Keep Plati-only runs headless, while a
// run containing GGSEL uses a visible guest browser by default. --headless
// remains available for diagnostics and CI.
const HEADLESS = args.headless === true || args.headless === 'true' || GGSEL_IDS.length === 0;
// Optional connection to an already-open, user-authenticated Chrome started
// with --remote-debugging-port. Useful when a marketplace disables reactive
// product controls in an isolated automation profile.
const CDP_URL = String(args['cdp-url'] || process.env.MARKETPLACE_CDP_URL || '').trim();

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

process.on('uncaughtException', (e) => process.stderr.write(`UNCAUGHT: ${e.stack || e}\n`));
process.on('unhandledRejection', (e) => process.stderr.write(`UNHANDLED: ${e?.stack || e}\n`));

// ---- Output file management (incremental writes) ------------------------

fs.writeFileSync(OUT_PATH, JSON.stringify({
  schemaVersion: 2,
  startedAt: new Date().toISOString(),
  note: 'Pass 1 raw. zai_analyze.py interprets.',
  config: {
    workers: WORKERS,
    pageTimeoutMs: PAGE_TIMEOUT_MS,
    clickTimeoutMs: CLICK_TIMEOUT_MS,
    priceSettleTimeoutMs: PRICE_SETTLE_TIMEOUT_MS,
    captureRetries: CAPTURE_RETRIES,
    proxyMode: PROXY_URLS.length ? 'configured' : 'direct',
    proxyCount: PROXY_URLS.length,
  },
  listings: [],
}, null, 2));

const appendListing = (r) => {
  const cur = JSON.parse(fs.readFileSync(OUT_PATH, 'utf8'));
  cur.listings.push(r);
  cur.lastUpdate = new Date().toISOString();
  fs.writeFileSync(OUT_PATH, JSON.stringify(cur, null, 2));
};

// ---- All page-evaluate bodies share these helpers (scoped inside the fn) -

const PAGE_FN = `
const findElement = (tag, text, exact) => {
  let pool;
  if (tag === 'button') pool = document.querySelectorAll('button');
  else if (tag === 'label') pool = document.querySelectorAll('label');
  else if (tag === 'radio') pool = document.querySelectorAll('input[type="radio"]');
  else if (tag === 'role-radio') pool = document.querySelectorAll('[role="radio"]');
  else if (tag === 'select-option') pool = document.querySelectorAll('select option');
  else return null;
  for (const el of pool) {
    const t = (tag === 'select-option') ? (el.textContent || '').trim() : (el.innerText || '').trim();
    if (exact ? t === text : t.startsWith(text)) {
      if (tag === 'radio') {
        const lab = el.closest('label');
        return lab || el;
      }
      return el;
    }
  }
  return null;
};

const findElementByIndex = (tag, index) => {
  if (!Number.isInteger(index) || index < 0) return null;
  let pool;
  if (tag === 'button') pool = document.querySelectorAll('button');
  else if (tag === 'label') pool = document.querySelectorAll('label');
  else if (tag === 'radio') pool = document.querySelectorAll('input[type="radio"]');
  else if (tag === 'role-radio') pool = document.querySelectorAll('[role="radio"]');
  else if (tag === 'select-option') pool = document.querySelectorAll('select option');
  else return null;
  return pool[index] || null;
};

const fireClick = (el) => {
  if (!el) return;
  el.scrollIntoView({ block: 'center' });
  const rect = el.getBoundingClientRect();
  for (const ev of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
    el.dispatchEvent(new MouseEvent(ev, {
      bubbles: true, cancelable: true, view: window,
      clientX: rect.x + rect.width / 2, clientY: rect.y + rect.height / 2, button: 0,
    }));
  }
  // Also dispatch a change event on any associated input — required by
  // Plati single-select accordion: radios do not fire change automatically
  // when the wrapping label is clicked programmatically.
  const input = (el.tagName === 'LABEL') ? el.querySelector('input[type="radio"], input[type="checkbox"]') : null;
  const target = input || el.querySelector('input[type="radio"]');
  if (target) {
    target.dispatchEvent(new Event('change', { bubbles: true }));
    target.dispatchEvent(new Event('input', { bubbles: true }));
    if (target.checked !== true && target.type === 'radio') target.checked = true;
  }
};

const isSelectedElement = (el, text) => {
  if (!el) return false;
  const input = el.matches && el.matches('input, option')
    ? el
    : el.querySelector && el.querySelector('input[type="radio"], input[type="checkbox"], option');
  const attrs = ['aria-checked', 'aria-selected', 'aria-pressed'];
  const ariaSelected = attrs.some((name) =>
    (el.getAttribute && el.getAttribute(name) === 'true') ||
    (input && input.getAttribute && input.getAttribute(name) === 'true')
  );
  const className = (el.className || '').toString() + ' ' + ((input && input.className) || '').toString();
  const selectedClass = /(?:^|[\\s_-])(?:active|selected|checked|chosen)(?:$|[\\s_-])/i.test(className);
  const selectedText = /(?:^|\\s)(?:выбран(?:о|а)?|selected)(?:\\s|$)/i.test(text || '');
  return Boolean(
    el.checked || el.selected || (input && (input.checked || input.selected)) ||
    ariaSelected || selectedClass || selectedText
  );
};

const snapshotPrices = () => {
  const els = Array.from(document.querySelectorAll('*')).filter(el => {
    if (el.children.length !== 0) return false;
    const t = (el.innerText || '').trim();
    return /^\\d[\\d\\s\\u00a0]*\\s*(?:₽|руб|RUB)\\s*$/.test(t) && t.length < 30;
  });
  return els.map(p => ({
    text: p.innerText.trim(),
    cls: (p.className || '').toString().slice(0, 100),
    id: p.id || ''
  })).filter(p => !/Steam RUB|Steam KZT|Steam UAH|USD\\s*=/.test(p.text));
};

// Read only the displayed storefront currency. Do not inspect stock or purchase
// button state; price collection must not become an availability check.
const snapshotPurchaseState = () => {
  const currencies = new Set();
  document.querySelectorAll('button, [role="button"], select option:checked').forEach(control => {
    if (!control.getClientRects().length) return;
    const label = (control.innerText || control.textContent || '').trim();
    const currency = label.match(/^(?:Dollars?|Доллары?|Рубли|Rubles?)\\s*\\((USD|RUB)\\)$/i);
    if (currency) currencies.add(currency[1].toUpperCase());
  });
  return {
    storeCurrency: currencies.size === 1 ? Array.from(currencies)[0] : null,
  };
};

const detectTemplate = () => {
  if (document.querySelector('[class*="ProductBuyBlock"]')) return 'ggsel';
  if (!document.querySelector('[class*="id_product_price"]')) return 'unknown';
  if (Array.from(document.querySelectorAll('label')).some(l => /Требуется Вход|Случайный Email/i.test(l.innerText || ''))) return 'plati-A';
  if (Array.from(document.querySelectorAll('label')).some(l => /Subscription.*\\+|Subscription.*Месяц|Subscription.*Month/i.test(l.innerText || ''))) return 'plati-B';
  if (document.querySelectorAll('input[type="radio"]').length > 0) return 'plati-C';
  return 'plati-A';
};

const grabPageText = () => {
  const t = (document.body && document.body.innerText) || '';
  return t.replace(/[ \\t]+/g, ' ').replace(/\\n{3,}/g, '\\n\\n').trim().slice(0, 6000);
};

// Seller description is often collapsed behind a "Показать ещё" expander,
// so innerText misses it; textContent of description containers still has it.
const grabDescText = () => {
  const sels = ['[itemprop="description"]', '[class*="escription"]', '[id*="escription"]', '[class*="desc"]'];
  const parts = [];
  for (const sel of sels) {
    document.querySelectorAll(sel).forEach((el) => {
      const t = (el.textContent || '').replace(/\\s+/g, ' ').trim();
      if (t.length > 40 && parts.indexOf(t) === -1) parts.push(t);
    });
  }
  return parts.slice(0, 5).join('\\n---\\n').slice(0, 5000);
};

const collectVariantControls = () => {
  const controls = [];
  const skipped = [];
  const seen = new Set();
  const seenSkipped = new Set();
  // Keyword gate decides WHICH controls we click; everything else that
  // looks like a variant control is still recorded into "skipped" so a
  // manual audit can see variants the filter silently rejected.
  const KEY = /Max|Pro|Lite|Plus|Ultra|Explore|Build|Плюс|GO|Токен|Месяц|Год|month|year|Первая|Продление|Subscription|Случайный|Требуется|месяц|год|нов(?:ый|ая)\s+(?:аккаунт|учетн)|предоставлю|свой\s+аккаунт|account/i;
  const appleGiftCard = /\\b(?:apple|itunes)\\b/i.test(document.title || '') &&
    /gift|подарочн|itunes/i.test(document.title || '');
  const denominationControl = text => appleGiftCard &&
    /^(?:[$₺]\\s*\\d+(?:[.,]\\d+)?|\\d+(?:[.,]\\d+)?\\s*(?:[$₺]|USD\\b|TRY\\b|TL\\b))/i.test(text);
  const selectedMeta = (el, text) => {
    const input = el && (el.matches && el.matches('input, option')
      ? el
      : el.querySelector && el.querySelector('input[type="radio"], input[type="checkbox"], option'));
    return { selected: isSelectedElement(el, text) };
  };
  const record = (kind, text, meta, el) => {
    const k = (text || '').trim();
    if (!k || k.length > 250 || seen.has(k)) return;
    if (!KEY.test(k) && !denominationControl(k)) {
      if (k.length >= 3 && !seenSkipped.has(k) && skipped.length < 80) {
        seenSkipped.add(k);
        skipped.push({ kind, text: k });
      }
      return;
    }
    seen.add(k);
    let domIndex = -1;
    if (kind === 'button') domIndex = Array.from(document.querySelectorAll('button')).indexOf(el);
    else if (kind === 'label') domIndex = Array.from(document.querySelectorAll('label')).indexOf(el);
    else if (kind === 'radio') domIndex = Array.from(document.querySelectorAll('input[type="radio"]')).indexOf(el);
    else if (kind === 'role-radio') domIndex = Array.from(document.querySelectorAll('[role="radio"]')).indexOf(el);
    else if (kind === 'select-option') domIndex = Array.from(document.querySelectorAll('select option')).indexOf(el);
    controls.push({ kind, text: k, domIndex, ...(meta || {}), ...selectedMeta(el, k) });
  };
  document.querySelectorAll('button').forEach(b => record('button', b.innerText || '', null, b));
  document.querySelectorAll('label').forEach(l => {
    const nested = l.querySelector('input[type="radio"], input[type="checkbox"]');
    const labelled = l.htmlFor && document.getElementById(l.htmlFor);
    const associated = nested || (labelled && /^(?:radio|checkbox)$/i.test(labelled.type || ''));
    const explicitlyInteractive = l.getAttribute('role') || l.tabIndex >= 0;
    if (associated || explicitlyInteractive) record('label', l.innerText || '', null, l);
  });
  document.querySelectorAll('input[type="radio"]').forEach(i => {
    const lab = i.closest('label');
    let text = '';
    if (lab) text = (lab.innerText || '').trim();
    else {
      const parent = i.closest('div, li, span');
      if (parent) text = (parent.innerText || '').trim().slice(0, 200);
    }
    if (!text) text = i.value || i.name || ('radio:' + i.id);
    record('radio', text, { inputId: i.id, inputName: i.name }, i);
  });
  document.querySelectorAll('[role="radio"]').forEach(el => record('role-radio', (el.innerText || '').trim(), null, el));
  document.querySelectorAll('select').forEach(s => {
    Array.from(s.options).forEach(o => record('select-option', (o.textContent || '').trim(), { value: o.value }, o));
  });
  const variantControlCount = document.querySelectorAll('input[type="radio"], [role="radio"], select').length;
  return { controls, skipped, variantControlCount };
};

const resolveControl = (ctrl) => {
  let el = findElement(ctrl.kind, ctrl.text, true);
  if (!el) el = findElementByIndex(ctrl.kind, ctrl.domIndex);
  if (!el) {
    const prefix = (ctrl.text || '').split('\\n')[0].slice(0, 25);
    if (prefix.length > 5) el = findElement(ctrl.kind, prefix, false);
  }
  if (!el && ctrl.kind === 'radio' && ctrl.inputId) {
    const i = document.getElementById(ctrl.inputId);
    if (i) el = i.closest('label') || i;
  }
  return el;
};

const clickControl = (ctrl) => {
  const el = resolveControl(ctrl);
  if (!el) return false;
  fireClick(el);
  return true;
};

const controlIsSelected = (ctrl) => {
  const el = resolveControl(ctrl);
  return isSelectedElement(el, (el && (el.innerText || el.textContent)) || ctrl.text || '');
};
`;

// ---- Each page.evaluate call wraps PAGE_FN + a small body that returns ---

async function detectTemplate(page) {
  return await page.evaluate(new Function(PAGE_FN + '\nreturn detectTemplate();'));
}
async function collectVariantControls(page) {
  return await page.evaluate(new Function(PAGE_FN + '\nreturn collectVariantControls();'));
}
async function grabPageText(page) {
  try {
    return await page.evaluate(new Function(PAGE_FN + '\nreturn grabPageText();'));
  } catch (e) { return ''; }
}
async function grabDescText(page) {
  try {
    return await page.evaluate(new Function(PAGE_FN + '\nreturn grabDescText();'));
  } catch (e) { return ''; }
}
async function snapshotPrices(page) {
  try {
    return await page.evaluate(new Function(PAGE_FN + '\nreturn snapshotPrices();'));
  } catch (e) { return []; }
}
async function snapshotPurchaseState(page) {
  try {
    return await page.evaluate(new Function(PAGE_FN + '\nreturn snapshotPurchaseState();'));
  } catch (e) { return { storeCurrency: null }; }
}

const priceFingerprint = (prices) => {
  const all = prices || [];
  const primary = all.filter((p) => {
    const cls = (p.cls || '').toLowerCase();
    return cls.includes('id_product_price') || (cls.includes('buyblock') && cls.includes('amount'));
  });
  const basis = primary.length > 0 ? primary : all;
  return JSON.stringify(basis.map((p) => [p.text || '', p.cls || '', p.id || '']));
};

async function waitForSettledPrices(page, beforePrices, selectedBefore) {
  const started = Date.now();
  const before = priceFingerprint(beforePrices);
  let previous = '';
  let stableSamples = 0;
  let latest = beforePrices;
  let changed = false;
  while (Date.now() - started < PRICE_SETTLE_TIMEOUT_MS) {
    await sleep(200);
    latest = await snapshotPrices(page);
    const current = priceFingerprint(latest);
    changed = changed || current !== before;
    stableSamples = current === previous ? stableSamples + 1 : 0;
    previous = current;
    if (stableSamples >= 2 && (changed || (selectedBefore && Date.now() - started >= 800))) {
      return { prices: latest, changed, stable: true, elapsedMs: Date.now() - started };
    }
  }
  // An unchanged snapshot can still be stable.  It becomes verified only if
  // the control is independently observed as selected after the click.
  return { prices: latest, changed, stable: stableSamples >= 2, elapsedMs: Date.now() - started };
}
async function clickControl(page, ctrl) {
  const selectors = {
    button: 'button',
    label: 'label',
    radio: 'input[type="radio"]',
    'role-radio': '[role="radio"]',
    'select-option': 'select option',
  };
  const selector = selectors[ctrl.kind];
  let target = null;
  // Product forms re-render after a selection. A stable, exact option name is
  // safer than an index among unrelated navigation buttons.
  if (ctrl.kind === 'button' && ctrl.text) {
    const byText = page.getByRole('button', { name: ctrl.text, exact: true });
    if (await byText.count() === 1) target = byText;
  }
  if (!target && selector && Number.isInteger(ctrl.domIndex) && ctrl.domIndex >= 0) {
    target = page.locator(selector).nth(ctrl.domIndex);
  }
  if (target) {
    if (await target.count()) {
      if (ctrl.kind === 'select-option') {
        await target.evaluate((option) => {
          option.selected = true;
          option.parentElement.dispatchEvent(new Event('change', { bubbles: true }));
        });
      } else {
        // Playwright performs the browser's native pointer action and waits
        // for actionability.  Synthetic MouseEvent chains can toggle styling
        // without triggering the marketplace's dependent price request.
        await target.click({ timeout: CLICK_TIMEOUT_MS });
      }
      return true;
    }
  }
  return await page.evaluate(new Function(PAGE_FN + `
    return clickControl(${JSON.stringify(ctrl)});
  `));
}
async function controlIsSelected(page, ctrl) {
  try {
    return await page.evaluate(new Function(PAGE_FN + `
      return controlIsSelected(${JSON.stringify(ctrl)});
    `));
  } catch (e) { return false; }
}

async function withTimeout(p, ms, label) {
  let to;
  const t = new Promise((_, rej) => { to = setTimeout(() => rej(new Error(label + ' timeout')), ms); });
  try { return await Promise.race([p, t]); } finally { clearTimeout(to); }
}

async function collectListing(context, marketplace, pid, urlBuilder) {
  const url = urlBuilder(pid);
  const page = await context.newPage();
  page.setDefaultTimeout(PAGE_TIMEOUT_MS);
  const out = { marketplace, pid, url, title: '', template: '', initialPrices: [], pageText: '', descText: '', skippedControls: [], options: [], storeCurrency: null, variantControlCount: null, error: null };
  try {
    const response = await withTimeout(page.goto(url, { waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS }), PAGE_TIMEOUT_MS + 5000, 'goto');
    if (response && [401, 403, 429, 503].includes(response.status())) {
      out.error = `marketplace blocked page (HTTP ${response.status()})`;
      return out;
    }
    await sleep(2500);
    out.title = await page.title();
    if (/DDoS[- ]Guard|Access Denied|Attention Required|Just a moment|Checking your browser/i.test(out.title)) {
      out.error = 'marketplace anti-bot challenge page';
      return out;
    }
    out.template = await detectTemplate(page);
    out.initialPrices = await snapshotPrices(page);
    Object.assign(out, await snapshotPurchaseState(page));
    out.pageText = await grabPageText(page);
    out.descText = await grabDescText(page);
    const { controls, skipped, variantControlCount } = await collectVariantControls(page);
    out.skippedControls = skipped;
    out.variantControlCount = variantControlCount;
    // Defer the initially selected control.  Some reactive buy blocks do not
    // render any price until another variant is selected; returning to the
    // default afterwards produces an auditable snapshot for both variants.
    const orderedControls = controls.slice().sort((a, b) => Number(a.selected) - Number(b.selected));
    for (const ctrl of orderedControls) {
      const beforePrices = await snapshotPrices(page);
      let clicked = false;
      try {
        clicked = await withTimeout(clickControl(page, ctrl), CLICK_TIMEOUT_MS, 'click');
      } catch (e) {
        out.options.push(Object.assign({}, ctrl, { clicked: false, err: String(e.message || e) }));
        continue;
      }
      if (!clicked) {
        out.options.push(Object.assign({}, ctrl, { clicked: false }));
        continue;
      }
      const settled = await waitForSettledPrices(page, beforePrices, Boolean(ctrl.selected));
      const selectedAfter = await controlIsSelected(page, ctrl);
      out.options.push(Object.assign({}, ctrl, {
        ...await snapshotPurchaseState(page),
        clicked: true,
        beforePrices,
        prices: settled.prices,
        priceChanged: settled.changed,
        priceStable: settled.stable,
        selectedAfter,
        // The initial default is clicked last. Its page-load selection is
        // historical: require the live selected state for every option so a
        // failed return click cannot inherit the previous variant's price.
        priceVerified: settled.prices.length > 0 && settled.stable && selectedAfter &&
          (Boolean(ctrl.selected) || settled.changed),
        priceSettleMs: settled.elapsedMs,
      }));
    }
    out.controlCount = controls.length;
    out.controlsClicked = out.options.filter((o) => o.clicked).length;
  } catch (e) {
    out.error = String(e.message || e);
  } finally {
    try { await page.close(); } catch (e) {}
  }
  return out;
}

function playwrightProxyOptions(proxyUrl) {
  const parsed = new URL(proxyUrl);
  const host = parsed.hostname.includes(':') ? `[${parsed.hostname}]` : parsed.hostname;
  const options = { server: `${parsed.protocol}//${host}:${parsed.port}` };
  if (parsed.username) options.username = decodeURIComponent(parsed.username);
  if (parsed.password) options.password = decodeURIComponent(parsed.password);
  return options;
}

let proxyCursor = 0;
const activeProxyIndexes = new Set();

async function acquireProxyIndex(excluded = new Set()) {
  if (REUSE_ROTATING_PROXY) return PROXY_URLS.length ? 0 : null;
  while (true) {
    for (let offset = 0; offset < PROXY_URLS.length; offset++) {
      const index = (proxyCursor + offset) % PROXY_URLS.length;
      if (!activeProxyIndexes.has(index) && !excluded.has(index)) {
        activeProxyIndexes.add(index);
        proxyCursor = (index + 1) % PROXY_URLS.length;
        return index;
      }
    }
    if (excluded.size >= PROXY_URLS.length) return null;
    await sleep(25);
  }
}

async function runWorker(workerId, queue, browser, sharedContext, contextOptions, onDone) {
  while (queue.length > 0) {
    const job = queue.shift();
    if (!job) break;
    const t0 = Date.now();
    process.stderr.write(`[w${workerId}] ${job.marketplace} ${String(job.pid).slice(0, 50)}...\n`);
    let finalResult = null;
    const allRetryReasons = [];
    const failedProxyIndexes = new Set();
    let captureAttempts = 0;
    try {
      for (let attempt = 0; attempt <= CAPTURE_RETRIES; attempt++) {
        let context = sharedContext;
        let transientContext = false;
        let proxyLease = null;
        let result;
        try {
          if (PROXY_URLS.length) {
            proxyLease = await acquireProxyIndex(failedProxyIndexes);
            if (proxyLease === null) break;
            context = await browser.newContext({
              ...contextOptions,
              proxy: playwrightProxyOptions(PROXY_URLS[proxyLease]),
            });
            await context.addInitScript(() => {
              Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            });
            transientContext = true;
          }
          captureAttempts = attempt + 1;
          result = await collectListing(context, job.marketplace, job.pid, job.urlBuilder);
        } catch (error) {
          result = {
            marketplace: job.marketplace,
            pid: job.pid,
            url: job.urlBuilder(job.pid),
            error: redactProxyText(error.message || error),
          };
        } finally {
          if (transientContext && context) await context.close().catch(() => {});
          if (proxyLease !== null) {
            if (!REUSE_ROTATING_PROXY) {
              activeProxyIndexes.delete(proxyLease);
              failedProxyIndexes.add(proxyLease);
            }
          }
        }

        finalResult = result;
        const reasons = [];
        if (result.error) reasons.push('listing error');
        for (const option of result.options || []) {
          if (option.clicked !== true) reasons.push('option control not clicked');
          if (option.clicked && (!option.prices || option.prices.length === 0)) reasons.push('missing price snapshot');
          if (option.priceChanged && !option.priceStable) reasons.push('unstable changed price');
        }
        if (reasons.length === 0 || attempt === CAPTURE_RETRIES) break;
        // Reopening a listing through more proxies cannot recover a route
        // that returned an explicit marketplace block. Preserve the failure
        // and move on instead of spending the full retry budget.
        if (/marketplace blocked page \(HTTP (?:401|403)\)/i.test(result.error || '')) break;
        allRetryReasons.push(...reasons);
        process.stderr.write(`[w${workerId}] ${job.marketplace} ${String(job.pid).slice(0, 50)} — retry ${attempt + 1}/${CAPTURE_RETRIES}: ${[...new Set(reasons)].join(', ')}\n`);
      }
    } catch (e) {
      const safeError = redactProxyText(e.message || e);
      finalResult = { marketplace: job.marketplace, pid: job.pid, url: job.urlBuilder(job.pid), error: safeError };
    }
    if (!finalResult) finalResult = { marketplace: job.marketplace, pid: job.pid, url: job.urlBuilder(job.pid), error: 'no proxy available' };
    finalResult.captureAttempts = captureAttempts;
    finalResult.captureRetryReasons = [...new Set(allRetryReasons)];
    onDone(finalResult);
    if (finalResult.error) {
      process.stderr.write(`[w${workerId}] ${job.marketplace} ${String(job.pid).slice(0, 50)} — FAIL in ${Date.now() - t0}ms: ${redactProxyText(finalResult.error)}\n`);
    } else {
      process.stderr.write(`[w${workerId}] ${job.marketplace} ${String(job.pid).slice(0, 50)} — ${finalResult.controlsClicked || 0}/${finalResult.controlCount || 0} clicked in ${Date.now() - t0}ms\n`);
    }
  }
}

(async () => {
  const remoteBrowser = Boolean(CDP_URL);
  if (remoteBrowser && PROXY_URLS.length) {
    throw new Error('Proxy lists require isolated browser mode; configured CDP mode was not changed.');
  }
  const browser = remoteBrowser
    ? await chromium.connectOverCDP(CDP_URL)
    : await chromium.launch({
      headless: HEADLESS,
      executablePath: CHROME_PATH,
      args: ['--no-sandbox', '--disable-blink-features=AutomationControlled'],
    });
  const remoteContexts = remoteBrowser ? browser.contexts() : [];
  if (remoteBrowser && remoteContexts.length === 0) {
    throw new Error('CDP browser has no usable context');
  }
  const queue = [
    ...[...new Set(PLATI_PIDS)].map((pid) => ({
      marketplace: 'plati', pid,
      urlBuilder: (p) => `https://plati.market/itm/${p}`,
    })),
    ...[...new Set(GGSEL_IDS)].map((id) => ({
      marketplace: 'ggsel', pid: id,
      urlBuilder: (p) => `https://ggsel.net/catalog/product/${p}`,
    })),
  ];
  // A real browser context owns live user tabs, so keep CDP collection
  // sequential. Isolated collection remains parallel.
  const workerCount = remoteBrowser ? 1 : PROXY_URLS.length
    ? (REUSE_ROTATING_PROXY ? WORKERS : Math.min(WORKERS, PROXY_URLS.length))
    : WORKERS;
  const contextOptions = {
    locale: 'ru-RU',
    userAgent: `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${browser.version()} Safari/537.36`,
  };
  const workers = [];
  for (let i = 0; i < workerCount; i++) {
    const ctx = remoteBrowser ? remoteContexts[0] : PROXY_URLS.length ? null : await browser.newContext(contextOptions);
    if (!remoteBrowser && ctx) {
      await ctx.addInitScript(() => {
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
      });
    }
    workers.push(runWorker(i, queue, browser, ctx, contextOptions, appendListing));
  }
  await Promise.all(workers);
  const final = JSON.parse(fs.readFileSync(OUT_PATH, 'utf8'));
  final.finishedAt = new Date().toISOString();
  fs.writeFileSync(OUT_PATH, JSON.stringify(final, null, 2));
  process.stderr.write(`DONE: ${final.listings.length} listings → ${OUT_PATH}\n`);
  if (!remoteBrowser) await browser.close();
  process.exit(0);
})().catch((e) => {
  process.stderr.write(`FATAL: ${e.stack || e}\n`);
  process.exit(1);
});
