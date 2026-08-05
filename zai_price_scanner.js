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

const PLATI_PIDS = [
  5619379, 5523111, 5971847, 5840436, 5997168, 5585825, 5893342, 5450549,
  5918664, 5955197, 6002805, 5526305, 5377500, 5885298,
];
const GGSEL_IDS = [
  'apgreid-z-ai-lite-pro-max-glm-5-2-1-12-mesiaca-f-a-s-t-full-warranty-102109731',
  'z-ai-glm-coding-plan-lite-pro-max-fast-activation-full-warranty-102458121',
  'z-ai-glm-lite-pro-max-coding-plan-glm-5-2-licnaia-podpiska-polnaia-102610634',
  'z-ai-glm-lite-pro-max-coding-plan-1-3-12-mesiacev-personalnaia-podpiska-polnaia-102438864',
  'z-ai-podpiska-glm-coding-lite-pro-max-1-3-12-mesiacev-102010339',
  'z-ai-z-ai-glm-coding-lite-pro-max-1-month-super-fast-zai-102358846',
  'z-ai-glm-lite-pro-max-coding-plan-glm-5-2-personalnaia-podpiska-polnaia-102495696',
  'upgrade-z-ai-glm-5-1-12m-f-a-s-t-full-warranty-102483517',
  'z-ai-lite-pro-max-gotovyi-akkaunt-dostavka-v-tecenie-neskolkix-casov-102644827',
  'z-ai-z-ai-podpiska-glm-coding-lite-pro-na-1-mesiac-5327293',
  'z-ai-z-ai-podpiska-glm-coding-lite-pro-max-na-1-mesiac-102185754',
  'z-ai-z-ai-podpiska-glm-coding-lite-pro-na-1-3-12-mesiacev-102234852',
  'podpiska-z-ai-lite-pro-max-1-mesiac-na-vas-akkaunt-102584986',
  'z-ai-z-ai-glm-coding-lite-pro-max-1-month-super-fast-zai-102662846',
  'obnovlenie-z-ai-1-3-12m-podpiska-glm-coding-lite-pro-max-g-arantiia-102303683',
  'obnovlenie-z-ai-1-3-12m-podpiska-glm-coding-lite-pro-max-g-arantiia-102618255',
  'z-ai-z-ai-podpiska-glm-coding-lite-pro-max-1-12-mesiacev-102113607',
  'z-ai-z-ai-podpiska-na-1-mesiac-lite-pro-max-dlia-programmirovaniia-zai-zai-5413116',
  'z-ai-z-ai-pokupka-podpiski-1-3-12m-popolnit-balansa-kredity-102169054',
  'podpiska-z-ai-na-vas-akkaunt-102651023',
  'podpiska-z-ai-z-ai-oficialnaia-oplata-1-3-12-mesiacev-102583131',
  'podpiska-z-ai-glm-coding-plan-1-12m-fast-delivery-full-warranty-102457859',
  'oficialnaia-1-3-12-mes-podpiska-z-ai-z-ai-liubye-e-oformlenie-polnaia-g-arantiia-102296362',
  'z-ai-lite-pro-max-1-mesiac-mgnovennyi-dostup-podderzka-24-7-i-102495673',
  'z-ai-z-ai-lite-pro-max-1-3-12-mesiaca-vas-akkaunt-102104408',
  'z-ai-lite-pro-max-premium-dostup-k-ii-1-mesiac-mgnovennaia-aktivaciia-102528209',
  'z-ai-lite-pro-max-podpiska-na-1-mesiac-operativnaia-podderzka-i-garantiinoe-obsluzivanie-102528064',
  'z-ai-podpiska-coding-lite-na-1-mesiac-102611308',
];

const args = Object.fromEntries(
  process.argv.slice(2).filter((a) => a.startsWith('--')).map((a) => {
    const [k, ...rest] = a.replace(/^--/, '').split('=');
    return [k, rest.length ? rest.join('=') : true];
  }),
);
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

const collectVariantControls = () => {
  const controls = [];
  const seen = new Set();
  const record = (kind, text, meta) => {
    const k = (text || '').trim();
    if (!k || k.length > 250 || seen.has(k)) return;
    seen.add(k);
    controls.push({ kind, text: k, ...(meta || {}) });
  };
  document.querySelectorAll('button').forEach(b => {
    const t = (b.innerText || '').trim();
    if (/Max|Pro|Lite|Месяц|Год|month|year|Первая|Продление/i.test(t)) record('button', t);
  });
  document.querySelectorAll('label').forEach(l => {
    const t = (l.innerText || '').trim();
    if (/Max|Pro|Lite|Месяц|Год|месяц|год|Subscription|Продление|Случайный|Требуется/i.test(t)) record('label', t);
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
    record('radio', text, { inputId: i.id, inputName: i.name });
  });
  document.querySelectorAll('[role="radio"]').forEach(el => record('role-radio', (el.innerText || '').trim()));
  document.querySelectorAll('select').forEach(s => {
    Array.from(s.options).forEach(o => record('select-option', (o.textContent || '').trim(), { value: o.value }));
  });
  return controls;
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
  const out = { marketplace, pid, url, title: '', template: '', initialPrices: [], options: [], error: null };
  try {
    await withTimeout(page.goto(url, { waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS }), PAGE_TIMEOUT_MS + 5000, 'goto');
    await sleep(2500);
    out.title = await page.title();
    out.template = await detectTemplate(page);
    out.initialPrices = await snapshotPrices(page);
    const ctrls = await collectVariantControls(page);
    for (const ctrl of ctrls) {
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
    out.controlCount = ctrls.length;
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
