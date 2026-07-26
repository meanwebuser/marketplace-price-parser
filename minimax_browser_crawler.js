#!/usr/bin/env node
const path = require('path');
const fs = require('fs');
const http = require('http');
const https = require('https');
const playwrightPackage = path.join(__dirname, 'ggsel_plati', 'node_modules', 'playwright');
const { chromium } = require(fs.existsSync(playwrightPackage) ? playwrightPackage : 'playwright');

function argValues(name) {
  const values = [];
  for (let i = 0; i < process.argv.length; i += 1) {
    if (process.argv[i] === name && process.argv[i + 1]) values.push(process.argv[i + 1]);
  }
  return values;
}

function argValue(name, fallback) {
  const values = argValues(name);
  return values.length ? values[0] : fallback;
}

function clean(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function normalise(value) {
  return clean(value).toLowerCase().replace(/ё/g, 'е');
}

function numberFromPrice(value) {
  const match = String(value || '').replace(/\s/g, '').match(/-?\d+(?:[.,]\d+)?/);
  return match ? Number.parseFloat(match[0].replace(',', '.')) : 0;
}

const GGSEL_CATEGORY_URL = process.env.MINIMAX_GGSEL_CATEGORY_URL || 'https://ggsel.net/catalog/minimaxhailuo';
const PLATI_API_URL = process.env.MINIMAX_PLATI_API_URL || 'https://api.digiseller.com/api/cataloguer/front/products';
const PLATI_BASE_URL = process.env.MINIMAX_PLATI_BASE_URL || 'https://plati.market';

function requestJson(url) {
  return new Promise((resolve, reject) => {
    const client = url.startsWith('https:') ? https : http;
    const request = client.get(url, {headers: {'User-Agent': 'Mozilla/5.0', Accept: 'application/json'}}, (response) => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => { body += chunk; });
      response.on('end', () => {
        if (response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error(`HTTP ${response.statusCode}`));
          return;
        }
        try {
          resolve(JSON.parse(body));
        } catch (error) {
          reject(new Error(`invalid JSON: ${error.message}`));
        }
      });
    });
    request.setTimeout(30000, () => request.destroy(new Error('request timeout')));
    request.on('error', reject);
  });
}

function isLikelyMinimaxCandidate(text) {
  const value = normalise(text);
  if (!/minimax|mini\s*max/.test(value)) return false;
  if (/audio|agent|credit|кредит|top\s*-?up|попол\w*|api\s*key|\bm[23](?:\.\d+)?\b/.test(value)) return false;
  const hasPlan = /max|макс|plus|плюс|plan|тариф|подпис\w*|platform|api/.test(value);
  const hasTermOrSubscription = /1\s*(?:month|месяц|мес)|1m\b|подпис\w*|plan|тариф|platform|api/.test(value);
  return hasPlan && hasTermOrSubscription;
}

function listingPrice(text) {
  const match = String(text || '').match(/\d[\d\s\u00a0]*(?:[.,]\d+)?\s*(?:₽|руб|\$|usd)/i);
  return match ? numberFromPrice(match[0]) : null;
}

async function discoverGgsel(page) {
  await page.goto(GGSEL_CATEGORY_URL, {waitUntil: 'domcontentloaded', timeout: 60000});
  await page.waitForTimeout(1800);
  const rows = await page.evaluate(() => [...document.querySelectorAll('a[data-testid="card-link"][href*="/catalog/product/"]')]
    .map((link) => {
      const card = link.closest('div[class*="ProductCard"][class*="card"]') || link.parentElement;
      const text = (card?.innerText || '').replace(/\s+/g, ' ').trim();
      const lines = (card?.innerText || '').split(/\r?\n/).map((line) => line.replace(/\s+/g, ' ').trim()).filter(Boolean);
      const title = lines.find((line) => /minimax|hailuo/i.test(line)) || link.getAttribute('title') || text;
      return {url: link.href, title, text, price: text};
    }));
  const seen = new Set();
  return rows.filter((row) => {
    if (!row.url || seen.has(row.url) || !isLikelyMinimaxCandidate(row.title + ' ' + row.text)) return false;
    seen.add(row.url);
    return true;
  }).map((row) => ({
    source: 'ggsel',
    label: row.title,
    url: row.url,
    native_id: row.url.match(/(\d+)(?:\?|$)/)?.[1] || row.url,
    catalog_price_rub: listingPrice(row.text),
  }));
}

function platiName(item) {
  const names = Array.isArray(item?.name) ? item.name : [];
  return names.find((name) => name.locale === 'ru-RU')?.value
    || names.find((name) => name.value)?.value
    || '';
}

async function discoverPlati(query) {
  const params = new URLSearchParams({
    categoryId: '',
    getProductsRecursive: 'true',
    sellerCategoryId: '',
    productId: '',
    productName: query,
    ownerId: 'plati',
    ownerCategoryId: '',
    sellerId: '',
    sellerName: '',
    currency: 'RUB',
    page: '1',
    count: '100',
    individual: 'false',
    video: 'false',
    image: 'false',
    attributes: '',
    sortBy: 'price-asc',
    priceFrom: '',
    priceTo: '',
    includeAggregations: 'true',
    fuzzy: 'false',
    lang: 'ru-RU',
  });
  const payload = await requestJson(`${PLATI_API_URL}?${params.toString()}`);
  const items = Array.isArray(payload?.content?.items) ? payload.content.items : [];
  const seen = new Set();
  return items.filter((item) => {
    const name = platiName(item);
    const id = String(item?.product_id || '');
    if (!id || seen.has(id) || !isLikelyMinimaxCandidate(name)) return false;
    seen.add(id);
    return true;
  }).map((item) => {
    const name = platiName(item);
    const slug = item.name_url || name.toLowerCase().replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '');
    return {
      source: 'plati',
      label: name,
      url: `${PLATI_BASE_URL}/itm/${slug}/${item.product_id}`,
      native_id: String(item.product_id),
      catalog_price_rub: Number(item.price) || null,
      seller: item.seller_name || null,
      sales: item.total_sales ?? null,
    };
  });
}

async function discoverCandidates(page, query, maxDiscovered) {
  const discovery = {
    query,
    ggsel_category: GGSEL_CATEGORY_URL,
    plati_api: PLATI_API_URL,
    ggsel_found: 0,
    plati_found: 0,
    candidates: 0,
    errors: [],
  };
  let ggsel = [];
  let plati = [];
  try {
    ggsel = await discoverGgsel(page);
    discovery.ggsel_found = ggsel.length;
  } catch (error) {
    discovery.errors.push(`ggsel: ${String(error?.message || error)}`);
  }
  try {
    plati = await discoverPlati(query);
    discovery.plati_found = plati.length;
  } catch (error) {
    discovery.errors.push(`plati: ${String(error?.message || error)}`);
  }
  const byUrl = new Map();
  for (const candidate of [...ggsel, ...plati]) byUrl.set(candidate.url, candidate);
  const candidates = [...byUrl.values()]
    .sort((left, right) => (left.catalog_price_rub ?? Number.POSITIVE_INFINITY) - (right.catalog_price_rub ?? Number.POSITIVE_INFINITY))
    .slice(0, maxDiscovered);
  discovery.candidates = candidates.length;
  return {candidates, discovery};
}

function classifyDelivery(text) {
  const value = normalise(text);
  if (/общ(ий|ая|ее)?\s*(аккаунт|доступ)|shared\s*account/.test(value)) return 'shared-account';
  if (/готов\w*\s*аккаунт|new account|our mail|наш\w*\s*аккаунт/.test(value)) return 'ready-account';
  if (/свой\s*аккаунт|личн\w*\s*аккаунт|ваш\w*\s*аккаунт|активир\w*|activated\s+on\s+your\s+account|on\s+your\s+account|продл\w*\s*свою\s*учетн|existing account|personal account|login|required login|парол/.test(value)) return 'own-login';
  if (/без\s*(входа|логина)|по\s*(ссылке|токену)|token|link/.test(value)) return 'own-no-login';
  return 'unknown';
}

function isOneMonthMax(label) {
  const value = normalise(label);
  const isMax = /\bmax\b|макс/.test(value);
  const isOneMonth = /1\s*(?:месяц|мес|month)|\[\s*1\s*(?:месяц|мес)|1m\b/.test(value);
  const isLonger = /3\s*(?:месяц|мес|month)|год|year|12\s*(?:месяц|мес|month)/.test(value);
  return isMax && isOneMonth && !isLonger;
}

async function pageOptions(page) {
  return page.evaluate(() => {
    const inputs = Array.from(document.querySelectorAll('input[type="radio"]')).map((input) => {
      const label = input.closest('label') || document.querySelector(`label[for="${input.id}"]`);
      const text = (label?.innerText || input.parentElement?.innerText || '').replace(/\s+/g, ' ').trim();
      return {
        kind: 'input',
        id: input.id,
        value: input.value || '',
        group: input.name || '',
        delta: input.getAttribute('data-delta-price') || '',
        checked: input.checked,
        text,
      };
    });
    const buttons = Array.from(document.querySelectorAll('button[value]')).map((button) => ({
      kind: 'button',
      id: button.id || '',
      value: button.value || '',
      group: '',
      delta: button.getAttribute('data-delta-price') || '',
      checked: button.getAttribute('aria-pressed') === 'true',
      text: (button.innerText || '').replace(/\s+/g, ' ').trim(),
    }));
    return [...inputs, ...buttons].filter((option) => option.text);
  });
}

async function clickOption(page, option) {
  if (option.kind === 'button') {
    await page.locator(`button[value="${option.value}"]`).first().click({force: true});
  } else {
    await page.evaluate((optionId) => {
      const input = document.getElementById(optionId);
      if (!input) return;
      input.click();
      input.checked = true;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      if (typeof window.optionChanged === 'function') window.optionChanged(input);
    }, option.id);
  }
  // GGSEL recalculates the price asynchronously after a toggle.  A short fixed
  // delay used to capture the previous option's price (and sometimes the base
  // Plus price), so give the page time to settle before reading it.
  await page.waitForTimeout(1200);
}

async function readPrice(page) {
  return page.evaluate(() => {
    const element = document.querySelector(
      '#product_price2, #product_price1, .id_product_price, [class*="ProductBuyBlock"][class*="amount"]',
    );
    return (element?.innerText || '').replace(/\s+/g, ' ').trim();
  });
}

async function safeEvidence(page, options, priceText) {
  const accessibility = await readAccessibilityTree(page);
  return page.evaluate(({pageOptions, selectedPrice, axTree}) => ({
    body_text: (document.body.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 2500),
    controls: pageOptions.slice(0, 80).map((option) => ({
      kind: option.kind,
      group: option.group,
      delta: option.delta,
      checked: option.checked,
      text: option.text,
    })),
    visible_price: selectedPrice,
    accessibility_tree: axTree,
  }), {pageOptions: options, selectedPrice: priceText, axTree: accessibility});
}

async function readAccessibilityTree(page) {
  try {
    const session = await page.context().newCDPSession(page);
    const tree = await session.send('Accessibility.getFullAXTree');
    return (tree.nodes || [])
      .map((node) => ({
        role: node.role?.value || '',
        name: String(node.name?.value || '').slice(0, 160),
      }))
      .filter((node) => (
        /button|radio|checkbox|heading|textbox|link|combobox/i.test(node.role)
        || /max|plus|ultra|месяц|month|аккаунт|account|цена|price|купить|buy/i.test(node.name)
      ))
      .slice(0, 80);
  } catch (error) {
    return [{role: 'a11y-error', name: String(error?.message || error)}];
  }
}

function browserPath() {
  if (process.platform === 'darwin') return '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  if (process.platform === 'win32') return 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
  return '/usr/bin/google-chrome';
}

async function scrape(page, candidate) {
  const result = {
    source: candidate.source,
    label: candidate.label,
    url: candidate.url,
    price: null,
    currency: 'RUB',
    delivery: 'unknown',
    plan_label: '',
    product_family: 'unknown',
    title: '',
    sales: null,
    reviews: null,
    status: 'error',
    error: '',
    evidence: null,
  };

  try {
    await page.goto(candidate.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(1800);
    result.title = await page.title();
    const body = await page.locator('body').innerText().catch(() => '');
    const currentUrl = page.url();
    if (/\/search\/?$/.test(currentUrl) || /ничего не нашлось|nothing found|нет в наличии|out of stock|sold out/i.test(body)) {
      result.status = 'unavailable';
      result.error = `redirected or unavailable: ${currentUrl}`;
      return result;
    }
    const productText = `${result.title} ${body}`;
    result.product_family = /token\s*plan|m3|m2\.7|\bminimax\s*(?:ai\s*)?(?:platform|api)\b/i.test(productText)
      ? 'minimax-token-plan'
      : /hailuo|video/i.test(productText) ? 'hailuo-minimax-legacy' : 'unknown';
    const salesMatch = body.match(/(?:Продано|Sold)\s*([\d\s+.,]+|<10)/i);
    result.sales = salesMatch ? clean(salesMatch[1]) : null;
    const reviewsMatch = body.match(/(?:Отзывы|Reviews)\s*(\d[\d\s]*)/i);
    result.reviews = reviewsMatch ? numberFromPrice(reviewsMatch[1]) : null;

    const options = await pageOptions(page);
    const oneMonthContext = `${result.title} ${body}`;
    const planOptions = options.filter((option) => (
      isOneMonthMax(option.text) || (
        /\bmax\b|макс/i.test(option.text)
        && /1\s*(?:месяц|мес|month)|1m\b/i.test(oneMonthContext)
        && !/3\s*(?:месяц|мес|month)|год|year|12\s*(?:месяц|мес|month)/i.test(option.text)
      )
    ));
    const deliveryOptions = options.filter((option) => {
      const delivery = classifyDelivery(option.text);
      return delivery === 'own-login' || delivery === 'own-no-login';
    });
    const deliveryChoices = deliveryOptions.length ? deliveryOptions : [{kind: 'fallback', id: '', text: body, delta: ''}];
    if (!planOptions.length) {
      result.error = 'no Max one-month option';
      return result;
    }

    let best = null;
    for (const deliveryOption of deliveryChoices) {
      if (deliveryOption.id || deliveryOption.value) await clickOption(page, deliveryOption);
      for (const planOption of planOptions) {
        await clickOption(page, planOption);
        const priceText = await readPrice(page);
        const price = numberFromPrice(priceText);
        if (!price) continue;
        const delivery = classifyDelivery(deliveryOption.text || body);
        const offer = {
          price,
          currency: /\$|usd/i.test(priceText) ? 'USD' : 'RUB',
          delivery,
          plan_label: planOption.text,
          delivery_label: deliveryOption.id || deliveryOption.value ? clean(deliveryOption.text) : `inferred: ${delivery}`,
          price_text: priceText,
          selection: {deliveryOption, planOption},
        };
        if (!best || offer.price < best.price) best = offer;
      }
    }
    if (!best) {
      result.error = 'Max option price was empty';
      return result;
    }
    // Re-select the winning pair before taking evidence.  This keeps the
    // accessibility tree, controls, and final price from describing different
    // variants when a card has several account/plan combinations.
    await clickOption(page, best.selection.deliveryOption);
    await clickOption(page, best.selection.planOption);
    best.price_text = await readPrice(page);
    best.price = numberFromPrice(best.price_text) || best.price;
    const finalOptions = await pageOptions(page);
    result.evidence = await safeEvidence(page, finalOptions, best.price_text);
    delete best.selection;
    Object.assign(result, best, {status: 'ok'});
  } catch (error) {
    result.error = String(error?.stack || error);
  }
  return result;
}

(async () => {
  const urls = argValues('--url');
  const autoDiscover = process.argv.includes('--discover');
  let candidates = urls.map((url) => ({source: 'marketplace', label: url, url}));
  let discovery = null;
  const browserOptions = {headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage']};
  if (process.env.MINIMAX_BROWSER_PATH) browserOptions.executablePath = process.env.MINIMAX_BROWSER_PATH;
  else if (fs.existsSync(browserPath())) browserOptions.executablePath = browserPath();
  const browser = await chromium.launch(browserOptions);
  const context = await browser.newContext({locale: 'ru-RU', timezoneId: 'Europe/Moscow'});
  if (autoDiscover) {
    const discoveryPage = await context.newPage();
    const discovered = await discoverCandidates(
      discoveryPage,
      argValue('--query', 'MiniMax'),
      Number.parseInt(argValue('--max-discovered', '30'), 10) || 30,
    );
    candidates = discovered.candidates;
    discovery = discovered.discovery;
    await discoveryPage.close();
  }
  if (process.argv.includes('--discover-ggsel')) {
    const discoveryPage = await context.newPage();
    let discovered = [];
    const errors = [];
    try {
      discovered = await discoverGgsel(discoveryPage);
    } catch (error) {
      errors.push(String(error?.message || error));
    }
    await discoveryPage.close();
    await browser.close();
    process.stdout.write(`${JSON.stringify({
      discovery: {ggsel_category: GGSEL_CATEGORY_URL, ggsel_found: discovered.length, errors},
      candidates: discovered,
    })}\n`);
    return;
  }
  if (!candidates.length && !autoDiscover) throw new Error('at least one --url or --discover is required');
  const results = [];
  for (const candidate of candidates) {
    let page = await context.newPage();
    let result = await scrape(page, candidate);
    await page.close();
    if (result.status === 'error' && /page\.goto|navigation|ERR_NAME_NOT_RESOLVED/i.test(result.error)) {
      page = await context.newPage();
      result = await scrape(page, candidate);
      await page.close();
    }
    results.push(result);
  }
  await browser.close();
  process.stdout.write(`${JSON.stringify({crawled_at_epoch: Date.now() / 1000, discovery, items: results})}\n`);
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
