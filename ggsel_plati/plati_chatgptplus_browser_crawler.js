#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');
function getArg(name, def) { const i = process.argv.indexOf(name); return (i >= 0 && i + 1 < process.argv.length) ? process.argv[i + 1] : def; }
const catalog = getArg('--catalog', 'https://plati.market/games/chatgpt/1267/?id_c=7396');
const plan = String(getArg('--plan', 'plus')).toLowerCase();
const detailLimit = parseInt(getArg('--detail-limit', '80'), 10);
const outJson = getArg('--out-json', '/tmp/best_price_helpers/chatgptplus/plati_results.json');
const outCsv = getArg('--out-csv', '/tmp/best_price_helpers/chatgptplus/plati_results.csv');
function clean(s) { return String(s || '').replace(/\s+/g, ' ').trim(); }
function priceNum(s) { const m = String(s || '').replace(/\s/g, '').match(/\d+(?:[.,]\d+)?/); return m ? parseFloat(m[0].replace(',', '.')) : 0; }
function norm(s) { return String(s || '').toLowerCase().replace(/ё/g, 'е'); }
function matchesPlan(text, plan) {
  const t = norm(text);
  if (plan === 'plus' || plan === 'плюс') return (t.includes('plus') || t.includes('плюс')) && !(/\bgo\b|\bpro\b|\bпро\b/.test(t));
  if (plan === 'go') return /\bgo\b|\bго\b/.test(t);
  if (plan === 'pro' || plan === 'про') return /\bpro\b|\bпро\b/.test(t);
  return t.includes(plan);
}
function csvCell(v) {
  const q = String.fromCharCode(34);
  return q + String(v == null ? '' : v).split(q).join(q + q).replace(/\r?\n/g, ' ') + q;
}
async function readPrice(page) {
  for (let i = 0; i < 25; i++) {
    const p = await page.evaluate(function () {
      const el = document.querySelector('#product_price2,#product_price1,.id_product_price');
      return (el && el.innerText || '').replace(/\s+/g, ' ').trim();
    }).catch(function () { return ''; });
    if (p.indexOf('₽') >= 0 && !/^0\s*000/.test(p)) return p;
    await page.waitForTimeout(300);
  }
  return await page.evaluate(function () {
    const el = document.querySelector('#product_price2,#product_price1,.id_product_price');
    return (el && el.innerText || '').replace(/\s+/g, ' ').trim();
  }).catch(function () { return ''; });
}
async function extractCards(page) {
  await page.goto(catalog, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(3000);
  return await page.evaluate(function () {
    function cleanLocal(s) { return String(s || '').replace(/\s+/g, ' ').trim(); }
    function priceLocal(s) { const m = String(s || '').replace(/\s/g, '').match(/\d+(?:[.,]\d+)?/); return m ? parseFloat(m[0].replace(',', '.')) : 0; }
    const rows = [];
    const seen = new Set();
    const cards = Array.from(document.querySelectorAll('a.card[href]'));
    for (const a of cards) {
      const href = new URL(a.getAttribute('href'), location.href).href;
      const idMatch = href.match(/\/(\d+)(?:\?|$)/);
      const id = a.getAttribute('product_id') || (idMatch ? idMatch[1] : href);
      if (seen.has(id)) continue;
      seen.add(id);
      const titleEl = a.querySelector('.card-title,.title');
      const priceEl = a.querySelector('.title-bold,.price');
      const sellerEl = a.querySelector('.text-truncate');
      const name = a.getAttribute('title') || cleanLocal((titleEl && titleEl.innerText) || a.innerText).slice(0, 200);
      const priceText = cleanLocal((priceEl && priceEl.innerText) || '');
      const salesMatch = cleanLocal(a.innerText).match(/Продано\s*([^\s]+)/i);
      rows.push({source:'plati', id:id, name:name, seller:cleanLocal((sellerEl && sellerEl.innerText) || ''), sales:salesMatch ? salesMatch[1] : null, rating:null, catalog_price_rub:priceLocal(priceText), price_rub:priceLocal(priceText), url:href, description:'', error:'', plan_price_source:'catalog_min'});
    }
    return rows;
  });
}
async function extractCards(page) {
  await page.goto(catalog, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(3000);
  return await page.evaluate(function () {
    function cleanLocal(s) { return String(s || '').replace(/\s+/g, ' ').trim(); }
    function priceLocal(s) { const m = String(s || '').replace(/\s/g, '').match(/\d+(?:[.,]\d+)?/); return m ? parseFloat(m[0].replace(',', '.')) : 0; }
    const rows = [];
    const seen = new Set();
    const cards = Array.from(document.querySelectorAll('a.card[href]'));
    for (const a of cards) {
      const href = new URL(a.getAttribute('href'), location.href).href;
      const idMatch = href.match(/\/(\d+)(?:\?|$)/);
      const id = a.getAttribute('product_id') || (idMatch ? idMatch[1] : href);
      if (seen.has(id)) continue;
      seen.add(id);
      const titleEl = a.querySelector('.card-title,.title');
      const priceEl = a.querySelector('.title-bold,.price');
      const sellerEl = a.querySelector('.text-truncate');
      const name = a.getAttribute('title') || cleanLocal((titleEl && titleEl.innerText) || a.innerText).slice(0, 200);
      const priceText = cleanLocal((priceEl && priceEl.innerText) || '');
      const salesMatch = cleanLocal(a.innerText).match(/Продано\s*([^\s]+)/i);
      rows.push({source:'plati', id:id, name:name, seller:cleanLocal((sellerEl && sellerEl.innerText) || ''), sales:salesMatch ? salesMatch[1] : null, rating:null, catalog_price_rub:priceLocal(priceText), price_rub:priceLocal(priceText), url:href, description:'', error:'', plan_price_source:'catalog_min'});
    }
    return rows;
  });
}
async function selectOption(page, id) {
  await page.evaluate(function (id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.checked = true;
    el.dispatchEvent(new Event('change', { bubbles: true }));
    if (typeof window.optionChanged === 'function') window.optionChanged(el);
  }, id);
  await page.waitForTimeout(900);
}

function classifyDelivery(row) {
  const label = norm(row.matched_plan_label || '');
  const name = norm(row.name || '');
  const text = label + ' ' + name;
  if (/готов(ый|ые)|персональн(ый|ого) аккаунт|аккаунт \+ почта|с почт(ой|а)|полный доступ к почте|личный аккаунт/.test(label)) return 'ready-account';
  if (/без входа|без логина|по ссылке|токен/.test(label)) return 'own-no-login';
  if (/со входом|с входом|почта от аккаунта|пароль от аккаунта|на ваш аккаунт|продление|продлевается/.test(label)) return 'own-login';
  if (/готов(ый|ые)|персональн(ый|ого) аккаунт|аккаунт \+ почта|с почт(ой|а)|полный доступ к почте|личный аккаунт/.test(text)) return 'ready-account';
  if (/без входа|без логина|по ссылке|токен/.test(text)) return 'own-no-login';
  if (/со входом|с входом|почта от аккаунта|пароль от аккаунта|на ваш аккаунт|продление|продлевается/.test(text)) return 'own-login';
  return 'unknown';
}
function deliveryRisk(delivery) {
  if (delivery === 'own-login') return 'нужен логин/пароль от вашего аккаунта';
  if (delivery === 'own-no-login') return 'без входа; обычно ссылка/токен, но всё равно сторонний продавец';
  if (delivery === 'ready-account') return 'готовый/чужой аккаунт; не ваш профиль и история';
  return 'тип выдачи не распознан автоматически';
}

async function enrich(page, row) {
  try {
    await page.goto(row.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(2500);
    const basePriceText = await readPrice(page);
    const basePrice = priceNum(basePriceText) || row.price_rub;
    const title = await page.title();
    const options = await page.evaluate(function () {
      return Array.from(document.querySelectorAll('input[data-delta-price]')).map(function (inp) {
        const label = document.querySelector('label[for="' + inp.id + '"]');
        return {id:inp.id, checked:!!inp.checked, delta:inp.getAttribute('data-delta-price') || '', text:((label && label.innerText) || '').replace(/\s+/g, ' ').trim()};
      });
    });
    const candidates = options.filter(function (o) { return matchesPlan(o.text, plan); });
    let best = null;
    const variants = [];
    for (const c0 of candidates) {
      await selectOption(page, c0.id);
      const ptxt = await readPrice(page);
      let p = priceNum(ptxt) || basePrice;
      const deltaRub = priceNum(c0.delta);
      if (deltaRub > 0 && p <= basePrice) { p = Math.round((basePrice + deltaRub) * 100) / 100; ptxt = String(p) + ' ₽ (base + option delta)'; }
      const checked = await page.evaluate(function () {
        return Array.from(document.querySelectorAll('input[data-delta-price]')).filter(function (i) { return i.checked; }).map(function (i) {
          const label = document.querySelector('label[for="' + i.id + '"]');
          return {id:i.id, delta:i.getAttribute('data-delta-price') || '', text:((label && label.innerText) || '').replace(/\s+/g, ' ').trim()};
        });
      });
      const cand = Object.assign({}, c0, {browser_price_text:ptxt, browser_price_rub:p, checked_after_select:checked});
      const variant = Object.assign({}, row, {price_rub:p, browser_price_text:ptxt, matched_plan_label:c0.text, checked_after_select:checked, options:options, plan_price_source:'browser_option_click'});
      variant.delivery = classifyDelivery(variant);
      variant.risk_note = deliveryRisk(variant.delivery);
      variants.push(variant);
      if (!best || cand.browser_price_rub < best.browser_price_rub) best = cand;
    }
    row.options = options;
    row.plan_variants = variants;
    if (best) {
      row.price_rub = best.browser_price_rub;
      row.browser_price_text = best.browser_price_text;
      row.matched_plan_label = best.text;
      row.checked_after_select = best.checked_after_select;
      row.plan_price_source = 'browser_option_click';
    } else if (options.length === 0 && matchesPlan(title, plan)) {
      row.price_rub = basePrice;
      row.browser_price_text = basePriceText;
      row.matched_plan_label = title;
      row.plan_price_source = 'browser_title_no_options';
    } else {
      row.error = 'no matching plan option: ' + plan;
    }
  } catch (e) {
    row.error = String((e && e.stack) || e);
  }
  row.delivery = classifyDelivery(row);
  row.risk_note = deliveryRisk(row.delivery);
  return row;
}
(async function main() {
 const browser = await chromium.launch({
  headless: true,
  executablePath: '/usr/bin/google-chrome',
  args: [
    '--no-sandbox', '--disable-dev-shm-usage',
    '--disable-blink-features=AutomationControlled',
    '--disable-features=IsolateOrigins,site-per-process',
    '--disable-web-security',
  ],
  ignoreDefaultArgs: ['--enable-automation'],
 });
 const ctx = await browser.newContext({
   locale: 'ru-RU',
   userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
   viewport: { width: 1440, height: 900 },
   timezoneId: 'Europe/Moscow',
 });
 const page = await ctx.newPage();
 await page.addInitScript(() => {
   Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
 });
 let rows = await extractCards(page);
  const enriched = [];
  for (const r of rows.slice(0, detailLimit)) enriched.push(await enrich(page, r));
  for (const r of rows.slice(detailLimit)) { r.error = 'not enriched: over detail limit'; enriched.push(r); }
  let flatRows = [];
  enriched.forEach(function (r) {
    if (!r.error && Array.isArray(r.plan_variants) && r.plan_variants.length) flatRows = flatRows.concat(r.plan_variants);
    else flatRows.push(r);
  });
  rows = flatRows.filter(function (r) { return !r.error && r.price_rub > 0; }).sort(function (a, b) { return a.price_rub - b.price_rub; });
  const result = { catalog: catalog, plan: plan, count: rows.length, crawled_at_epoch: Date.now() / 1000, note: 'Prices verified in browser by selecting target plan option and reading buy price.', items: rows };
  fs.mkdirSync(path.dirname(outJson), { recursive: true });
  fs.writeFileSync(outJson, JSON.stringify(result, null, 2), 'utf8');
  const fields = ['source','id','price_rub','catalog_price_rub','name','seller','sales','rating','url','delivery','risk_note','matched_plan_label','browser_price_text','plan_price_source','error'];
  fs.writeFileSync(outCsv, fields.join(',') + '\n' + rows.map(function (r) { return fields.map(function (f) { return csvCell(r[f]); }).join(','); }).join('\n'), 'utf8');
  console.log('items: ' + rows.length + ' plan: ' + plan);
  rows.slice(0, 10).forEach(function (r) { console.log(r.price_rub + ' RUB | ' + r.seller + ' | sales=' + r.sales + ' | ' + r.name + ' | plan=' + String(r.matched_plan_label || '').slice(0, 100)); });
  console.log('json: ' + outJson);
  console.log('csv: ' + outCsv);
  await browser.close();
})().catch(function (e) { console.error(e.stack || e); process.exit(1); });
