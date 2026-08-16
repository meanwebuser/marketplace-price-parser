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
const WORKERS = Number(args.workers || 6);
const OUT_PATH = args.out || '/tmp/zai_raw.json';
const PAGE_TIMEOUT_MS = Number(args['page-timeout'] || 35000);
const CLICK_TIMEOUT_MS = Number(args['click-timeout'] || 8000);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

process.on('uncaughtException', (e) => process.stderr.write(`UNCAUGHT: ${e.stack || e}\n`));
process.on('unhandledRejection', (e) => process.stderr.write(`UNHANDLED: ${e?.stack || e}\n`));

// ---- Output file management (incremental writes) ------------------------

fs.writeFileSync(OUT_PATH, JSON.stringify({
  startedAt: new Date().toISOString(),
  note: 'Pass 1 raw. zai_analyze.py interprets.',
  config: { workers: WORKERS, pageTimeoutMs: PAGE_TIMEOUT_MS, clickTimeoutMs: CLICK_TIMEOUT_MS },
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
  const KEY = /Max|Pro|Lite|Plus|Плюс|GO|Токен|Месяц|Год|month|year|Первая|Продление|Subscription|Случайный|Требуется|месяц|год/i;
  const record = (kind, text, meta) => {
    const k = (text || '').trim();
    if (!k || k.length > 250 || seen.has(k)) return;
    if (!KEY.test(k)) {
      if (k.length >= 3 && !seenSkipped.has(k) && skipped.length < 80) {
        seenSkipped.add(k);
        skipped.push({ kind, text: k });
      }
      return;
    }
    seen.add(k);
    controls.push({ kind, text: k, ...(meta || {}) });
  };
  document.querySelectorAll('button').forEach(b => record('button', b.innerText || ''));
  document.querySelectorAll('label').forEach(l => record('label', l.innerText || ''));
  document.querySelectorAll('input[type="radio"]').forEach(i => {
    const lab = i.closest('label');
    let text = '';
    if (lab) text = (lab.innerText || '').trim();
    else {
      const parent = i.closest('div, li, span');
      if (parent) text = (parent.innerText || '').trim().slice(0, 200);
    }
    if (!text) text = i.value || i.name || ('radio:' + i.id);
    record('radio', text, { inputId: i.id, inputName: i.name });
  });
  document.querySelectorAll('[role="radio"]').forEach(el => record('role-radio', (el.innerText || '').trim()));
  document.querySelectorAll('select').forEach(s => {
    Array.from(s.options).forEach(o => record('select-option', (o.textContent || '').trim(), { value: o.value }));
  });
  return { controls, skipped };
};

const clickControl = (ctrl) => {
  let el = findElement(ctrl.kind, ctrl.text, true);
  if (!el) {
    const prefix = (ctrl.text || '').split('\\n')[0].slice(0, 25);
    if (prefix.length > 5) el = findElement(ctrl.kind, prefix, false);
  }
  if (!el && ctrl.kind === 'radio' && ctrl.inputId) {
    const i = document.getElementById(ctrl.inputId);
    if (i) el = i.closest('label') || i;
  }
  if (!el) return false;
  fireClick(el);
  return true;
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
async function clickControl(page, ctrl) {
  return await page.evaluate(new Function(PAGE_FN + `
    return clickControl(${JSON.stringify(ctrl)});
  `));
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
  const out = { marketplace, pid, url, title: '', template: '', initialPrices: [], pageText: '', descText: '', skippedControls: [], options: [], error: null };
  try {
    await withTimeout(page.goto(url, { waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS }), PAGE_TIMEOUT_MS + 5000, 'goto');
    await sleep(2500);
    out.title = await page.title();
    out.template = await detectTemplate(page);
    out.initialPrices = await snapshotPrices(page);
    out.pageText = await grabPageText(page);
    out.descText = await grabDescText(page);
    const { controls, skipped } = await collectVariantControls(page);
    out.skippedControls = skipped;
    for (const ctrl of controls) {
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
      await sleep(850);
      const prices = await snapshotPrices(page);
      out.options.push(Object.assign({}, ctrl, { clicked: true, prices }));
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

async function runWorker(workerId, queue, context, onDone) {
  while (queue.length > 0) {
    const job = queue.shift();
    if (!job) break;
    const t0 = Date.now();
    process.stderr.write(`[w${workerId}] ${job.marketplace} ${String(job.pid).slice(0, 50)}...\n`);
    try {
      const result = await collectListing(context, job.marketplace, job.pid, job.urlBuilder);
      onDone(result);
      process.stderr.write(`[w${workerId}] ${job.marketplace} ${String(job.pid).slice(0, 50)} — ${result.controlsClicked || 0}/${result.controlCount || 0} clicked in ${Date.now() - t0}ms\n`);
    } catch (e) {
      onDone({ marketplace: job.marketplace, pid: job.pid, url: job.urlBuilder(job.pid), error: String(e.message || e) });
      process.stderr.write(`[w${workerId}] ${job.marketplace} ${String(job.pid).slice(0, 50)} — FAIL in ${Date.now() - t0}ms: ${e.message}\n`);
    }
  }
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-blink-features=AutomationControlled'],
  });
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
  const workers = [];
  for (let i = 0; i < WORKERS; i++) {
    const ctx = await browser.newContext({
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
      locale: 'ru-RU',
    });
    workers.push(runWorker(i, queue, ctx, appendListing));
  }
  await Promise.all(workers);
  const final = JSON.parse(fs.readFileSync(OUT_PATH, 'utf8'));
  final.finishedAt = new Date().toISOString();
  fs.writeFileSync(OUT_PATH, JSON.stringify(final, null, 2));
  process.stderr.write(`DONE: ${final.listings.length} listings → ${OUT_PATH}\n`);
  await browser.close();
  process.exit(0);
})().catch((e) => {
  process.stderr.write(`FATAL: ${e.stack || e}\n`);
  process.exit(1);
});
