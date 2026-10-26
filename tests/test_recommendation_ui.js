const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../docs/assets/app.js'), 'utf8');

function offer(tier, duration, priceRub, extra = {}) {
  return {
    tier, duration, priceRub, available: true, priceVerified: true, glitched: false,
    finalVerified: true, delivery: 'own_account', marketplace: 'plati',
    optionText: `${tier} ${duration}`, title: `${tier} listing`, url: 'https://example.test/offer',
    ...extra
  };
}

function product(id, offers, label = id) {
  return { id, label, description: `${label} offers`, metadata: { scanDate: '2026-10-23', listings: offers.length }, offers };
}

const registry = { families: {
  chatgpt: { sourceUrl: 'https://official.test/chatgpt', plans: [
    { planId: 'chatgpt.plus', canonicalTierAliases: ['Plus'], originalOfficialUnit: 'usage relative to Plus', originalOfficialQuantity: 1, originalOfficialPeriod: 'monthly', limitPoints: 1 },
    { planId: 'chatgpt.pro_100', canonicalTierAliases: ['Pro 100', 'Pro $100', 'Pro 5X', 'Pro 5x'], originalOfficialUnit: 'included usage; no stable current numeric allowance', originalOfficialQuantity: null, originalOfficialPeriod: 'monthly', limitPoints: null },
    { planId: 'chatgpt.pro_200', canonicalTierAliases: ['Pro 200', 'Pro $200', 'Pro 20X', 'Pro 20x'], originalOfficialUnit: 'usage', originalOfficialQuantity: null, originalOfficialPeriod: 'monthly', limitPoints: null },
    { planId: 'chatgpt.pro_500', canonicalTierAliases: ['Pro 500', 'Pro $500'], originalOfficialUnit: 'usage', originalOfficialQuantity: null, originalOfficialPeriod: 'monthly', limitPoints: null }
  ] },
  claude: { sourceUrl: 'https://official.test/claude', plans: [
    { planId: 'claude.pro', canonicalTierAliases: ['Pro'], originalOfficialUnit: 'usage relative to Pro', originalOfficialQuantity: 1, originalOfficialPeriod: 'monthly', limitPoints: 1 },
    { planId: 'claude.max_5x', canonicalTierAliases: ['Max 5X', 'Max 5x', 'Claude Max 5X', 'Claude Max 5x'], originalOfficialUnit: 'usage relative to Pro', originalOfficialQuantity: 5, originalOfficialPeriod: 'monthly', limitPoints: 5 },
    { planId: 'claude.max_20x', canonicalTierAliases: ['Max 20X', 'Max 20x', 'Claude Max 20X', 'Claude Max 20x'], originalOfficialUnit: 'usage relative to Pro', originalOfficialQuantity: 20, originalOfficialPeriod: 'monthly', limitPoints: 20 }
  ] },
  minimax: { plans: [
    { planId: 'minimax.global.plus', canonicalTierAliases: ['Plus', 'MiniMax Plus'], marketplaceRegionEvidence: ['global', 'international', 'global M Plan', 'global Token Plan'], marketRegion: 'global', originalOfficialUnit: 'estimated calls', originalOfficialQuantity: 34000, originalOfficialPeriod: 'per month', limitPoints: 1 },
    { planId: 'minimax.global.ultra', canonicalTierAliases: ['Ultra', 'MiniMax Ultra'], marketplaceRegionEvidence: ['global', 'international', 'global M Plan', 'global Token Plan'], marketRegion: 'global', originalOfficialUnit: 'estimated calls', originalOfficialQuantity: 250000, originalOfficialPeriod: 'per month', limitPoints: 7.35 },
    { planId: 'minimax.cn.plus', canonicalTierAliases: ['Plus', 'MiniMax Plus'], marketplaceRegionEvidence: ['China', 'CN', 'Chinese Token Plan', 'Token Plan China'], marketRegion: 'cn', originalOfficialUnit: 'estimated calls', originalOfficialQuantity: 12000, originalOfficialPeriod: 'per month', limitPoints: 1 },
    { planId: 'minimax.cn.ultra', canonicalTierAliases: ['Ultra', 'MiniMax Ultra'], marketplaceRegionEvidence: ['China', 'CN', 'Chinese Token Plan', 'Token Plan China'], marketRegion: 'cn', originalOfficialUnit: 'estimated calls', originalOfficialQuantity: 140000, originalOfficialPeriod: 'per month', limitPoints: 11.67 },
    { planId: 'minimax.ambiguous.plus', canonicalTierAliases: ['Plus', 'MiniMax Plus'], marketRegion: null, originalOfficialUnit: 'regional estimated calls differ', originalOfficialQuantity: null, originalOfficialPeriod: 'per month', limitPoints: 1 },
    { planId: 'minimax.ambiguous.max', canonicalTierAliases: ['Max', 'MiniMax Max'], marketRegion: null, originalOfficialUnit: 'regional estimated calls differ', originalOfficialQuantity: null, originalOfficialPeriod: 'per month', limitPoints: 3 },
    { planId: 'minimax.ambiguous.ultra', canonicalTierAliases: ['Ultra', 'MiniMax Ultra'], marketRegion: null, originalOfficialUnit: 'regional estimates diverge', originalOfficialQuantity: null, originalOfficialPeriod: 'per month', limitPoints: null }
  ] },
  zai_glm: { sourceUrl: 'https://official.test/glm', plans: [
    { planId: 'zai_glm.lite', canonicalTierAliases: ['Lite', 'GLM Lite', 'Z.ai Lite'], originalOfficialUnit: 'credits', originalOfficialQuantity: 10000, originalOfficialPeriod: 'per week', limitPoints: 1 },
    { planId: 'zai_glm.pro', canonicalTierAliases: ['Pro', 'GLM Pro', 'Z.ai Pro'], originalOfficialUnit: 'relative use', originalOfficialQuantity: 6, originalOfficialPeriod: 'per weekly cycle', limitPoints: 6 },
    { planId: 'zai_glm.max', canonicalTierAliases: ['Max', 'GLM Max', 'Z.ai Max'], originalOfficialUnit: 'relative use', originalOfficialQuantity: 14, originalOfficialPeriod: 'per weekly cycle', limitPoints: 14 }
  ] },
  kimi: { sourceUrl: 'https://official.test/kimi', plans: [
    { planId: 'kimi.plus', canonicalTierAliases: ['Plus'], marketplaceRegionEvidence: ['China', 'CN', '中国'], marketRegion: 'china', originalOfficialUnit: 'Agent credits', originalOfficialQuantity: 2, originalOfficialPeriod: 'monthly', limitPoints: 1 },
    { planId: 'kimi.pro', canonicalTierAliases: ['Pro'], marketplaceRegionEvidence: ['China', 'CN', '中国'], marketRegion: 'china', originalOfficialUnit: 'Agent credits', originalOfficialQuantity: 4, originalOfficialPeriod: 'monthly', limitPoints: 2 },
    { planId: 'kimi.max', canonicalTierAliases: ['Max'], marketplaceRegionEvidence: ['China', 'CN', '中国'], marketRegion: 'china', originalOfficialUnit: 'Agent credits', originalOfficialQuantity: 14, originalOfficialPeriod: 'monthly', limitPoints: 7 },
    { planId: 'kimi.ultra', canonicalTierAliases: ['Ultra'], marketplaceRegionEvidence: ['China', 'CN', '中国'], marketRegion: 'china', originalOfficialUnit: 'Agent credits', originalOfficialQuantity: 28, originalOfficialPeriod: 'monthly', limitPoints: 14 },
    { planId: 'kimi.legacy_andante', canonicalTierAliases: ['Andante'], originalOfficialUnit: 'legacy credits', originalOfficialQuantity: null, originalOfficialPeriod: 'monthly', limitPoints: null }
  ] }
} };

async function renderFixture(productOrProducts, planMetadata = registry) {
  const catalogue = Array.isArray(productOrProducts) ? { products: productOrProducts }
    : Array.isArray(productOrProducts?.products) ? productOrProducts : { products: [productOrProducts] };
  const products = [...(catalogue.products || []), ...(catalogue.giftCards || [])];
  const elements = new Map();
  const getElement = id => {
    if (!elements.has(id)) elements.set(id, {
      value: '', checked: false, textContent: '', innerHTML: '', options: [], listeners: {}, attributes: {}, scrollCount: 0,
      append(option) { this.options.push(option); },
      scrollIntoView() { this.scrollCount += 1; },
      setAttribute(name, value) { this.attributes[name] = value; },
      addEventListener(type, callback) { this.listeners[type] = callback; }
    });
    return elements.get(id);
  };
  const context = {
    document: { getElementById: getElement },
    Option: function Option(text, value) { this.text = text; this.value = value; },
    fetch: async url => ({ ok: true, json: async () => String(url).includes('subscription-plan-limits') ? planMetadata : catalogue }),
    Intl, Date, Set, Map, Number, String, Object, Array, Math
  };
  vm.runInNewContext(script, context);
  await new Promise(resolve => setImmediate(resolve));
  return { elements, getElement };
}

test('current catalogue renders with the canonical registry without inventing an X-derived score', async () => {
  const current = JSON.parse(fs.readFileSync(path.join(__dirname, '../docs/data/latest.json'), 'utf8'));
  const officialPlans = JSON.parse(fs.readFileSync(path.join(__dirname, '../docs/data/subscription-plan-limits.json'), 'utf8'));
  const { getElement } = await renderFixture(current.products, officialPlans);
  getElement('recommendation-mode-value').listeners.click();
  const html = getElement('recommendations-list').innerHTML;
  assert.equal((html.match(/class="recommendation-card"/g) || []).length, current.products.length);
  assert.match(html, /Официальный план:/);
  assert.doesNotMatch(html, /undefined|null ×/);
  // This date's live marketplace scan did not rediscover a Pro 20X offer.
  // The canonical registry and X-value handling are covered by the fixture tests below.
  assert.match(html, /Plus/);
});

test('separate Apple giftCards collection appears in the product picker and ranks by RUB per USD', async () => {
  const current = JSON.parse(fs.readFileSync(path.join(__dirname, '../docs/data/latest.json'), 'utf8'));
  const officialPlans = JSON.parse(fs.readFileSync(path.join(__dirname, '../docs/data/subscription-plan-limits.json'), 'utf8'));
  const apple = current.giftCards.find(item => item.id === 'apple_us');
  const eligible = apple.offers.filter(item => item.available !== false && item.priceVerified);
  const best = [...eligible].sort((a, b) => a.pricePerUnit - b.pricePerUnit || a.priceRub - b.priceRub)[0];
  const denomination = String(best.denomination) + ' ' + best.denominationCurrency;
  const unitRate = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(best.pricePerUnit);
  assert.ok(Array.isArray(current.giftCards));
  assert.equal(current.products.some(product => product.id === 'apple_us'), false);
  assert.ok(apple.offers.length > 0);
  assert.equal(apple.offers.some(item => String(item.pid) === '102829897' && item.optionText === '15 USD'), false);
  const { getElement } = await renderFixture(current, officialPlans);

  assert.ok(getElement('product').options.some(option => option.value === 'apple_us'));
  getElement('product').listeners.change({ target: { value: 'apple_us' } });
  assert.ok(getElement('recommendations-list').innerHTML.includes('Apple Gift Card · ' + denomination + ' · US'));
  assert.ok(getElement('recommendations-list').innerHTML.includes(unitRate + ' ₽ за $1 номинала'));
  assert.match(getElement('recommendations-list').innerHTML, /Наличие:/);
  assert.ok(getElement('offers').innerHTML.includes(String(best.priceRub) + ' ₽'));
  assert.match(getElement('offers').innerHTML, /50 USD/);
});

test('actual MiniMax M Plan tiers map separately from legacy Token Plan tiers', async () => {
  const officialPlans = JSON.parse(fs.readFileSync(path.join(__dirname, '../docs/data/subscription-plan-limits.json'), 'utf8'));
  const items = [
    product('minimax', [offer('GO', '1m', 1000, { optionText: 'GO (Subscription Renewal)' })], 'M Plan Go fixture'),
    product('minimax', [offer('Explore', '1m', 3000, { optionText: 'M Plan Explore · 1 month' })], 'M Plan Explore fixture'),
    product('minimax', [offer('Build', '12m', 10000, { optionText: 'Build - 1 год' })], 'M Plan Build fixture'),
    product('minimax', [offer('Max', '1m', 3000, { optionText: 'Max · 1 month' })], 'Legacy Max fixture'),
    product('minimax', [offer('GO', '1m', 100, { optionText: 'Go / Explore / Build · 1 month' })], 'Ambiguous M Plan fixture')
  ];
  const { getElement } = await renderFixture(items, officialPlans);
  getElement('recommendation-mode-value').listeners.click();
  const cards = getElement('recommendations-list').innerHTML.match(/<article class="recommendation-card">[\s\S]*?<\/article>/g);
  const card = label => cards.find(html => html.includes(label));
  for (const [label, planId, points] of [
    ['M Plan Go fixture', 'minimax.m_plan.go', 1],
    ['M Plan Explore fixture', 'minimax.m_plan.explore', 3],
    ['M Plan Build fixture', 'minimax.m_plan.build', 7.5]
  ]) {
    const plan = officialPlans.families.minimax.plans.find(plan => plan.planId === planId);
    assert.equal(plan.limitPoints, points);
    assert.equal(plan.sourceUrl, 'https://www.minimax.io/m-plan');
    assert.ok(card(label).includes(planId));
  }
  assert.match(card('Legacy Max fixture'), /minimax\.ambiguous\.max/);
  assert.match(card('Ambiguous M Plan fixture'), /нет подтверждённого числового лимита плана/);
});

test('fresh MiniMax catalogue uses the current headless GGSEL snapshot', async () => {
  const current = JSON.parse(fs.readFileSync(path.join(__dirname, '../docs/data/latest.json'), 'utf8'));
  const item = current.products.find(product => product.id === 'minimax');
  assert.equal(item.metadata.scanDate, '2026-10-25');
  assert.equal(item.metadata.listings, 12);
  const ggsel = { ...item, offers: item.offers.filter(offer => offer.marketplace === 'ggsel') };
  assert.equal(ggsel.offers.length, 28);
  assert.ok(ggsel.offers.some(offer => offer.pid === '102443754' && offer.tier === 'Ultra'));
});

test('actual registry aliases resolve Claude variants specifically and keep Kimi Pro+ separate from Pro', async () => {
  const officialPlans = JSON.parse(fs.readFileSync(path.join(__dirname, '../docs/data/subscription-plan-limits.json'), 'utf8'));
  const items = [
    product('claude', [offer('Max', '1m', 5000, { optionText: 'Claude Max 5X · 1 month' })], 'Claude 5X'),
    product('claude', [offer('Max', '1m', 8000, { optionText: 'Claude Max 20X · 1 month' })], 'Claude 20X'),
    product('claude', [offer('Max', '1m', 900, { optionText: 'Claude Max · 1 month' })], 'Claude generic Max'),
    product('kimi', [offer('Pro', '1m', 1000, { optionText: 'CN Pro selected' })], 'Kimi Pro CN'),
    product('kimi', [offer('Pro+', '1m', 1000, { optionText: 'CN Pro+ selected' })], 'Kimi Pro+ CN'),
    product('kimi', [offer('Ultra', '1m', 1000, { optionText: 'Ultra selected', title: 'Kimi China membership' })], 'Kimi China title-only'),
    product('kimi', [offer('Ultra', '1m', 1000, { optionText: 'Ultra selected', title: 'Kimi CN membership' })], 'Kimi CN title-only'),
    product('kimi', [offer('Ultra', '1m', 1000, { optionText: 'China Ultra selected' })], 'Kimi selected China')
  ];
  const { getElement } = await renderFixture(items, officialPlans);
  getElement('recommendation-mode-value').listeners.click();
  const html = getElement('recommendations-list').innerHTML;
  assert.match(html, /Claude 5X[\s\S]*claude\.max_5x/);
  assert.match(html, /Claude 20X[\s\S]*claude\.max_20x/);
  assert.match(html, /Claude generic Max[\s\S]*Для выбранных условий нет подтверждённого числового лимита плана/);
  assert.match(html, /Kimi Pro CN[\s\S]*kimi\.pro/);
  assert.match(html, /Kimi Pro\+ CN[\s\S]*Для выбранных условий нет подтверждённого числового лимита плана/);
  assert.match(html, /Kimi China title-only[\s\S]*Для выбранных условий нет подтверждённого числового лимита плана/);
  assert.match(html, /Kimi CN title-only[\s\S]*Для выбранных условий нет подтверждённого числового лимита плана/);
  assert.match(html, /Kimi selected China[\s\S]*kimi\.ultra/);
});

function selectTier(handler, productId, value) {
  handler({ target: { dataset: { product: productId, selection: 'tier' }, value } });
}

test('Z.ai GLM Max static offer stays eligible with an unverified seller note and explicit family', async () => {
  const current = JSON.parse(fs.readFileSync(path.join(__dirname, '../docs/data/latest.json'), 'utf8'));
  const zai = current.products.find(item => item.id === 'zai');
  const item = zai.offers.find(item => item.pid === '102331610');
  assert.ok(item, 'saved static Z.ai GLM Max row is present');
  assert.equal(item.delivery, 'unknown');
  assert.equal(item.sellerNoteVerified, false);
  const { getElement } = await renderFixture([
    product('zai', [item], 'Z.ai GLM Coding'),
    product('minimax', [offer('Max', '1m', 5000)], 'MiniMax')
  ]);
  const html = getElement('recommendations-list').innerHTML;
  assert.match(html, /<h3>Z\.ai GLM Max · 3 месяца<\/h3>/);
  assert.match(html, /<h3>MiniMax M Plan Max · 1 месяц<\/h3>/);
  assert.match(html, /Полная цена: 37(?:\s|&nbsp;|\u00a0)000 ₽/);
  assert.match(html, /Заметка продавца \(не проверена\): Доступен только 1 аккаунт/);
  assert.doesNotMatch(html, /<h3>Max ·/);
});

test('default price recommendation includes every eligible tier and term and chooses the lowest total price', async () => {
  const item = product('chatgpt', [
    offer('Plus', '12m', 500),
    offer('Pro 20X', '1m', 20000),
    offer('Plus', '1m', 900, { delivery: 'shared_account' }),
    offer('Plus', '3m', 100, { priceVerified: false })
  ], 'ChatGPT');
  const { getElement } = await renderFixture(item);
  const html = getElement('recommendations-list').innerHTML;
  assert.match(html, /<h3>Plus · 1 год<\/h3>/);
  assert.match(html, /Полная цена: 500 ₽/);
  assert.match(html, /<option value="" selected>Все уровни<\/option>/);
  assert.match(html, /<option value="" selected>Любой срок<\/option>/);
  assert.equal(getElement('tier').value, '');
  assert.equal(getElement('duration').value, '');
  assert.match(html, /value="Pro 20X"/);
});

test('Apple gift-card recommendation chooses lowest RUB per face-value USD and shows total plus unit price', async () => {
  const apple = {
    ...product('apple_us', [], 'Apple Gift Card · США'),
    kind: 'gift_card', region: 'US', allowedTiers: null,
    offers: [
      { marketplace: 'ggsel', pid: '2', url: 'https://example.test/2', title: 'Apple Gift Card USA', optionText: '$2 USD', region: 'US', denomination: 2, denominationCurrency: 'USD', priceRub: 159, pricePerUnit: 79.5, delivery: 'instant digital code', available: true, priceVerified: true, glitched: false },
      { marketplace: 'ggsel', pid: '100', url: 'https://example.test/100', title: 'Apple Gift Card USA', optionText: '$100 USD', region: 'US', denomination: 100, denominationCurrency: 'USD', priceRub: 6000, pricePerUnit: 60, delivery: 'instant digital code', available: true, priceVerified: true, glitched: false }
    ]
  };
  const { getElement } = await renderFixture(apple);
  const recommendation = getElement('recommendations-list').innerHTML;
  const offers = getElement('offers').innerHTML;

  assert.match(recommendation, /Apple Gift Card · 100 USD · US/);
  assert.match(recommendation, /Полная цена: 6\s?000 ₽ · 60 ₽ за \$1 номинала/);
  assert.match(offers, /6\s?000 ₽<span class="sub">60 ₽ за \$1 номинала<\/span>/);
  assert.ok(offers.indexOf('100 USD') < offers.indexOf('2 USD'));
});

test('gift-card stock stays separate from price: unknown can be ranked, out-of-stock cannot be recommended', async () => {
  const apple = {
    ...product('apple_us', [], 'Apple Gift Card · США'),
    kind: 'gift_card', region: 'US', allowedTiers: null,
    offers: [
      { marketplace: 'ggsel', pid: '50', url: 'https://example.test/50', title: 'Apple Gift Card USA', optionText: '$50 (USDT)', region: 'US', denomination: 50, denominationCurrency: 'USD', priceRub: 500, pricePerUnit: 10, delivery: 'unknown', seller: 'FiatPay', available: false, availabilityStatus: 'out_of_stock', priceVerified: true, glitched: false },
      { marketplace: 'ggsel', pid: '5-unknown', url: 'https://example.test/5', title: 'Apple Gift Card USA', optionText: '$5 USD', region: 'US', denomination: 5, denominationCurrency: 'USD', priceRub: 289, pricePerUnit: 57.8, delivery: 'unknown', seller: 'FiatPay', available: null, availabilityStatus: 'unknown', priceVerified: true, glitched: false },
      { marketplace: 'ggsel', pid: '10', url: 'https://example.test/10', title: 'Apple Gift Card USA', optionText: '$10 USD', region: 'US', denomination: 10, denominationCurrency: 'USD', priceRub: 600, pricePerUnit: 60, delivery: 'unknown', seller: 'Other', available: true, availabilityStatus: 'in_stock', priceVerified: true, glitched: false }
    ]
  };
  const { getElement } = await renderFixture(apple);
  const recommendation = getElement('recommendations-list').innerHTML;
  const offers = getElement('offers').innerHTML;

  assert.match(recommendation, /Apple Gift Card · 5 USD · US/);
  assert.match(recommendation, /Наличие: Наличие не проверено/);
  assert.doesNotMatch(recommendation, /Apple Gift Card · 50 USD/);
  assert.match(offers, /Нет в наличии/);
  assert.match(offers, /Наличие не проверено/);
});

test('card-level filters can select a tier, and an incompatible term resets to Any instead of falling back', async () => {
  const item = product('chatgpt', [offer('Plus', '12m', 500), offer('Pro 20X', '1m', 20000)], 'ChatGPT');
  const { getElement } = await renderFixture(item);
  const handler = getElement('recommendations-list').listeners.change;
  selectTier(handler, 'chatgpt', 'Pro 20X');
  let html = getElement('recommendations-list').innerHTML;
  assert.match(html, /<h3>Pro 20X · 1 месяц<\/h3>/);
  assert.match(html, /<option value="1m">1 месяц<\/option>/);
  handler({ target: { dataset: { product: 'chatgpt', selection: 'duration' }, value: '1m' } });
  selectTier(handler, 'chatgpt', 'Plus');
  html = getElement('recommendations-list').innerHTML;
  assert.match(html, /<h3>Plus · 1 год<\/h3>/);
  assert.match(html, /<option value="" selected>Любой срок<\/option>/);
  assert.doesNotMatch(html, /<option value="1m"/);
});

test('ChatGPT value mode ignores seller X; current Pro variants have no stable numeric score', async () => {
  const item = product('chatgpt', [
    offer('Pro', '1m', 5000, { optionText: 'Pro 10X · 1 месяц', title: 'ChatGPT 100X listing' }),
    offer('Pro 20X', '1m', 20000, { optionText: 'Pro 20X · 1 месяц' }),
    offer('Pro 5X', '1m', 3500, { optionText: 'Pro 5X · 1 месяц' }),
    offer('Plus', '1m', 1000, { optionText: 'Plus · 1 месяц', title: 'ChatGPT 100X limited offer' })
  ], 'ChatGPT');
  const { getElement } = await renderFixture(item);
  getElement('recommendation-mode-value').listeners.click();
  const html = getElement('recommendations-list').innerHTML;
  assert.match(html, /<h3>Plus · 1 месяц<\/h3>/);
  assert.match(html, /Официальный план: chatgpt\.plus/);
  assert.match(html, /Официальный источник/);
  assert.doesNotMatch(html, /10X/);
  assert.doesNotMatch(html, /100X/);
  selectTier(getElement('recommendations-list').listeners.change, 'chatgpt', 'Pro 5X');
  assert.match(getElement('recommendations-list').innerHTML, /Для выбранных условий нет подтверждённого числового лимита плана/);
  selectTier(getElement('recommendations-list').listeners.change, 'chatgpt', 'Pro 20X');
  assert.match(getElement('recommendations-list').innerHTML, /Для выбранных условий нет подтверждённого числового лимита плана/);
});

test('Claude value mode uses selected canonical Max option; generic titles never establish a plan', async () => {
  const item = product('claude', [
    offer('Pro', '1m', 1000, { optionText: 'Claude Pro · 1 месяц', title: 'Claude Pro, also mentions Max 20X and Max 5X' }),
    offer('Max', '1m', 4000, { optionText: 'Claude Max 5X · 1 месяц' }),
    offer('Max', '1m', 25000, { optionText: 'Claude Max 20X · 1 месяц' })
  ], 'Claude');
  const { getElement } = await renderFixture(item);
  getElement('recommendation-mode-value').listeners.click();
  let html = getElement('recommendations-list').innerHTML;
  assert.match(html, /<h3>Max 5X · 1 месяц<\/h3>/);
  assert.match(html, /claude\.max_5x/);
  assert.doesNotMatch(html, /<h3>Pro ·/);

  selectTier(getElement('recommendations-list').listeners.change, 'claude', 'Max 20X');
  html = getElement('recommendations-list').innerHTML;
  assert.match(html, /<h3>Max 20X · 1 месяц<\/h3>/);
  assert.match(html, /claude\.max_20x/);
});

test('value mode ranks official canonical plan points across services and puts unknown plans last', async () => {
  const items = [
    product('chatgpt', [offer('Plus', '1m', 5000, { optionText: 'Plus · 1 месяц' })], 'ChatGPT'),
    product('claude', [offer('Max', '1m', 1000, { optionText: 'Claude Max 5X · 1 месяц' })], 'Claude'),
    product('minimax', [offer('Ultra', '1m', 500, { optionText: 'Global M Plan Ultra · 1 месяц', title: 'seller title' })], 'MiniMax')
  ];
  const { getElement } = await renderFixture(items);
  getElement('recommendation-mode-value').listeners.click();
  const html = getElement('recommendations-list').innerHTML;
  assert.ok(html.indexOf('>MiniMax<') < html.indexOf('>Claude<'));
  assert.ok(html.indexOf('>Claude<') < html.indexOf('>ChatGPT<'));
  assert.match(html, /5 × 1 мес\. × 1 000 \/ 1\s*000 ₽ = 5 условных пунктов лимита/);
  assert.match(html, /1 × 1 мес\. × 1 000 \/ 5\s*000 ₽ = 0,2 условных пунктов лимита/);
  assert.match(html, /Официальный план: minimax\.global\.ultra/);
});

test('switching from selected 12-month price to value mode keeps term and scores canonical monthly plan', async () => {
  const item = product('claude', [
    offer('Max', '12m', 1000, { optionText: 'Claude Max 5X · 12 месяцев' }),
    offer('Max', '1m', 20000, { optionText: 'Claude Max 5X · 1 месяц' })
  ], 'ChatGPT');
  const { getElement } = await renderFixture(item);
  getElement('recommendations-list').listeners.change({ target: { dataset: { product: 'claude', selection: 'duration' }, value: '12m' } });
  assert.match(getElement('recommendations-list').innerHTML, /<h3>Max 5X · 1 год<\/h3>/);
  getElement('recommendation-mode-value').listeners.click();
  const html = getElement('recommendations-list').innerHTML;
  assert.match(html, /<h3>Max 5X · 1 год<\/h3>/);
  assert.match(html, /<option value="12m" selected>1 год<\/option>/);
  assert.match(html, /5 × 12 мес\. × 1 000 \/ 1\s*000 ₽ = 60 условных пунктов лимита/);
});

test('term normalization table uses canonical monthly points times months over full upfront price', async () => {
  for (const [duration, price, expected] of [['1m', 5000, '1'], ['3m', 5000, '3'], ['12m', 10000, '6']]) {
    const item = product('claude', [offer('Max', duration, price, { optionText: 'Claude Max 5X · selected plan' })], 'Claude');
    const { getElement } = await renderFixture(item);
    getElement('recommendation-mode-value').listeners.click();
    assert.match(getElement('recommendations-list').innerHTML, new RegExp(`= ${expected} условных пунктов лимита`));
    assert.match(getElement('recommendations-list').innerHTML, new RegExp(`Полная цена: ${price.toLocaleString('ru-RU')} ₽`));
  }
});

test('value mode scores official plan aliases and leaves ambiguous or unregistered offers visible without score', async () => {
  const items = [
    product('minimax', [offer('Unknown', '1m', 800, { optionText: 'regional plan unknown' })], 'MiniMax'),
    product('zai', [offer('Legacy', '1m', 900)], 'GLM'),
    product('kimi', [offer('Andante', '1m', 700)], 'Kimi'),
    product('chatgpt', [offer('Pro', '1m', 1000, { optionText: 'Pro 10X / Pro 20X selected menu' })], 'ChatGPT'),
    product('claude', [offer('Max', '1m', 1100, { optionText: 'Claude Max 5X / Max 20X' })], 'Claude')
  ];
  const { getElement } = await renderFixture(items);
  getElement('recommendation-mode-value').listeners.click();
  let html = getElement('recommendations-list').innerHTML;
  assert.equal((html.match(/Для выбранных условий нет подтверждённого числового лимита плана/g) || []).length, 5, html);
  assert.match(html, /Все предложения доступны в таблице/);

  getElement('recommendation-mode-price').listeners.click();
  html = getElement('recommendations-list').innerHTML;
  assert.match(html, /MiniMax/);
  assert.match(html, /Полная цена: 800 ₽/);
  assert.match(html, /ChatGPT/);
  assert.match(html, /Claude/);
});

test('MiniMax regional Ultra score requires explicit product/region evidence; generic Plus/Max keep shared ratios', async () => {
  const items = [
    product('minimax', [offer('Ultra', '1m', 500, { optionText: 'Ultra plan' })], 'MiniMax Ultra'),
    product('minimax', [offer('Ultra', '1m', 500, { optionText: 'Global M Plan Ultra' })], 'MiniMax Global'),
    product('minimax', [offer('Ultra', '1m', 500, { optionText: 'Ultra plan', title: 'MiniMax Global M Plan subscription' })], 'MiniMax title-only Global'),
    product('minimax', [offer('Max', '1m', 300, { optionText: 'Max plan' })], 'MiniMax Max'),
    product('minimax', [offer('Ultra', '1m', 500, { optionText: 'Ultra plan', title: '469 CNY promotion' })], 'MiniMax CNY'),
    product('minimax', [offer('Ultra', '1m', 500, { optionText: 'Ultra plan', title: 'unknowncn promotion' })], 'MiniMax embedded cn'),
    product('minimax', [offer('Ultra', '1m', 500, { optionText: 'CN Token Plan Ultra' })], 'MiniMax CN'),
    product('minimax', [offer('Ultra', '1m', 500, { optionText: 'Ultra plan', title: 'MiniMax CN Token Plan' })], 'MiniMax title-only CN')
  ];
  const { getElement } = await renderFixture(items);
  getElement('recommendation-mode-value').listeners.click();
  const html = getElement('recommendations-list').innerHTML;
  assert.match(html, /MiniMax Ultra[\s\S]*Для выбранных условий нет подтверждённого числового лимита плана/);
  assert.match(html, /MiniMax Global[\s\S]*minimax\.global\.ultra/);
  assert.match(html, /MiniMax title-only Global[\s\S]*Для выбранных условий нет подтверждённого числового лимита плана/);
  assert.match(html, /MiniMax Max[\s\S]*minimax\.ambiguous\.max/);
  assert.match(html, /MiniMax CNY[\s\S]*Для выбранных условий нет подтверждённого числового лимита плана/);
  assert.match(html, /MiniMax embedded cn[\s\S]*Для выбранных условий нет подтверждённого числового лимита плана/);
  assert.match(html, /MiniMax CN[\s\S]*minimax\.cn\.ultra/);
  assert.match(html, /MiniMax title-only CN[\s\S]*Для выбранных условий нет подтверждённого числового лимита плана/);
});

test('Kimi China-only plan registry requires matching regional evidence', async () => {
  const items = [
    product('kimi', [offer('Pro', '1m', 1000, { optionText: 'Pro selected' })], 'Kimi unknown region'),
    product('kimi', [offer('Pro', '1m', 1000, { optionText: 'China Pro selected' })], 'Kimi China'),
    product('kimi', [offer('Ultra', '1m', 1000, { optionText: 'Ultra selected', title: 'Kimi China Ultra' })], 'Kimi title-only China'),
    product('kimi', [offer('Ultra', '1m', 1000, { optionText: 'CN Ultra selected' })], 'Kimi selected CN'),
    product('kimi', [offer('Pro', '1m', 1000, { optionText: 'Pro selected', title: 'Kimi CNY membership' })], 'Kimi CNY')
  ];
  const { getElement } = await renderFixture(items);
  getElement('recommendation-mode-value').listeners.click();
  const html = getElement('recommendations-list').innerHTML;
  assert.match(html, /Kimi unknown region[\s\S]*Для выбранных условий нет подтверждённого числового лимита плана/);
  assert.match(html, /Kimi China[\s\S]*kimi\.pro/);
  assert.match(html, /Kimi title-only China[\s\S]*Для выбранных условий нет подтверждённого числового лимита плана/);
  assert.match(html, /Kimi selected CN[\s\S]*kimi\.ultra/);
  assert.match(html, /Kimi CNY[\s\S]*Для выбранных условий нет подтверждённого числового лимита плана/);
  assert.match(html, /2 × 1 мес\. × 1 000 \/ 1\s*000 ₽ = 2 условных пунктов лимита/);
});

test('recommendation tabs have explicit scope and do not change detailed table filters', async () => {
  const item = product('chatgpt', [
    offer('Pro', '1m', 5000, { optionText: 'Pro 10X · 1 месяц' }),
    offer('Plus', '12m', 1000, { optionText: 'Plus · 1 год' })
  ], 'ChatGPT');
  const { getElement } = await renderFixture(item);
  const initialTable = getElement('offers').innerHTML;
  assert.equal(getElement('recommendation-mode-price').attributes['aria-selected'], 'true');
  assert.equal(getElement('recommendation-mode-value').attributes['aria-selected'], 'false');
  getElement('recommendation-mode-value').listeners.click();
  assert.equal(getElement('recommendation-mode-price').attributes['aria-selected'], 'false');
  assert.equal(getElement('recommendation-mode-value').attributes['aria-selected'], 'true');
  assert.equal(getElement('offers').innerHTML, initialTable);
  assert.equal(getElement('product').value, 'chatgpt');
  assert.equal(getElement('tier').value, '');
  assert.equal(getElement('duration').value, '');
  assert.match(getElement('recommendations-list').innerHTML, /chatgpt\.plus/);
});

test('unavailable product link switches the offers table to that product', async () => {
  const items = [
    product('kimi', [offer('Plus', '1m', 1000)], 'Kimi'),
    product('claude', [offer('Max', '1m', 100, { title: 'Claude unavailable listing', priceVerified: false })], 'Claude')
  ];
  const { getElement } = await renderFixture(items);
  const handler = getElement('recommendations-list').listeners.click;
  const link = { dataset: { product: 'claude' } };
  let prevented = false;
  handler({ preventDefault() { prevented = true; }, target: { closest: selector => selector === 'a.show-product-offers' ? link : null } });
  assert.equal(getElement('product').value, 'claude');
  assert.match(getElement('offers').innerHTML, /Claude unavailable listing/);
  assert.equal(prevented, true);
  assert.equal(getElement('offers').scrollCount, 1);
});
