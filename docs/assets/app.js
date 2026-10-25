const labels = { own_account: 'На личный аккаунт', new_account: 'Отдельный аккаунт', shared_account: 'Общий аккаунт', unknown: 'Уточнить у продавца', '1m': '1 месяц', '3m': '3 месяца', '6m': '6 месяцев', '12m': '1 год' };
const ids = ['product','recommendations-list','recommendation-mode-price','recommendation-mode-value','search','tier','duration','delivery','marketplace','sort','hide-glitched','reset','offers','result','updated','offer-count','minimum-price','marketplace-count','product-kicker','product-title','product-description','source-note'];
const els = Object.fromEntries(ids.map(id => [id, document.getElementById(id)]));
const rub = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
const scoreFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
let products = [], active = null, offers = [], planRegistry = null;
const recommendationSelection = new Map();
let recommendationMode = 'price';
const tierRank = {
  minimax: ['Plus', 'Max', 'Ultra'],
  chatgpt: ['Plus', 'Max', 'Pro', 'Pro 5X', 'Pro 20X'],
  zai: ['Lite', 'Pro', 'Max'],
  kimi: ['Plus', 'Max', 'Pro', 'Pro+', 'Ultra'],
  claude: ['Pro', 'Max']
};
const durationRank = ['1m', '3m', '6m', '12m'];

const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const label = value => labels[value] || value;
const safeUrl = value => /^https:\/\//.test(value) ? value : '#';
function resetOptions(id, initial) { els[id].innerHTML = `<option value="">${initial}</option>`; }
function addOptions(id, values) { [...values].sort().forEach(value => els[id].append(new Option(label(value), value))); }
function resetFilters() {
  els.search.value = ''; ['tier','duration','delivery','marketplace'].forEach(id => resetOptions(id, id === 'duration' ? 'Любой' : id === 'delivery' ? 'Любая' : 'Все'));
  addOptions('tier', new Set(active.allowedTiers || offers.map(o => o.tier))); addOptions('duration', new Set(offers.map(o => o.duration))); addOptions('delivery', new Set(offers.map(o => o.delivery))); addOptions('marketplace', new Set(offers.map(o => o.marketplace)));
  els.sort.value = 'price-asc'; els['hide-glitched'].checked = true;
}
function eligibleOffers(product) {
  return product.offers.filter(o => o.available !== false && o.priceVerified !== false && !o.glitched && Number.isFinite(o.priceRub) && o.priceRub > 0);
}
function normalizePlanAlias(value) { return String(value || '').toLowerCase().replace(/[^a-z0-9+]+/g, ' ').trim(); }
function planForOffer(product, offer) {
  const familyId = product.id === 'zai' ? 'zai_glm' : product.id;
  const family = planRegistry?.families?.[familyId];
  const plans = family?.plans || [];
  if (!plans.length) return null;
  // Tier and region mapping use selected-option evidence only. Seller titles do not
  // establish which regional product was selected or supply any plan limit.
  const selectedText = normalizePlanAlias(offer.optionText);
  const tierText = normalizePlanAlias(offer.tier);
  const aliasMatches = plans.flatMap(plan => (plan.canonicalTierAliases || []).flatMap(alias => {
    const needle = normalizePlanAlias(alias);
    return needle && (` ${selectedText} `).includes(` ${needle} `) ? [{ plan, alias: needle }] : [];
  }));
  const specificAliases = aliasMatches.filter(match => !aliasMatches.some(other => other.plan.planId !== match.plan.planId
    && other.alias !== match.alias && (` ${other.alias} `).includes(` ${match.alias} `)));
  const selectedMatches = [...new Map(specificAliases.map(match => [match.plan.planId, match.plan])).values()];
  const exactTierAliases = plans.flatMap(plan => (plan.canonicalTierAliases || [])
    .filter(alias => normalizePlanAlias(alias) === tierText).map(alias => ({ plan, length: normalizePlanAlias(alias).length })));
  const canonicalTierMatches = [...new Map(exactTierAliases.map(match => [match.plan.planId, match.plan])).values()];
  const canonicalTierSpecificity = Math.max(0, ...exactTierAliases.map(match => match.length));
  const selectedSpecificity = Math.max(0, ...specificAliases.map(match => match.alias.length));
  if (selectedMatches.length === 1 && canonicalTierMatches.length === 1
    && canonicalTierMatches[0].planId !== selectedMatches[0].planId
    && canonicalTierSpecificity >= selectedSpecificity) return null;
  const tierMatches = selectedMatches.length ? selectedMatches : canonicalTierMatches;
  const candidates = [...new Map(tierMatches.map(plan => [plan.planId, plan])).values()];
  const regionSource = String(offer.optionText || '').toLowerCase();
  const regionText = normalizePlanAlias(regionSource);
  const hasRegionEvidence = plan => (plan.marketplaceRegionEvidence || []).some(evidence => {
    const needle = normalizePlanAlias(evidence);
    const rawEvidence = String(evidence).toLowerCase();
    const unicodeEvidence = /[^\x00-\x7f]/.test(rawEvidence);
    return (needle && (` ${regionText} `).includes(` ${needle} `)) || (unicodeEvidence && regionSource.includes(rawEvidence));
  });
  if (candidates.length === 1) return candidates[0].marketplaceRegionEvidence && !hasRegionEvidence(candidates[0]) ? null : candidates[0];
  const regionMatches = candidates.filter(hasRegionEvidence);
  if (regionMatches.length === 1) return regionMatches[0];
  const shared = candidates.filter(plan => plan.marketRegion === null && plan.limitPoints !== null);
  return shared.length === 1 ? shared[0] : null;
}
function recommendationTier(product, offer) {
  if (product.id === 'claude' && offer.tier === 'Max') {
    const plan = planForOffer(product, offer);
    if (plan?.planId === 'claude.max_5x') return 'Max 5X';
    if (plan?.planId === 'claude.max_20x') return 'Max 20X';
  }
  return offer.tier;
}
function recommendation(product, selection, mode) {
  const matching = eligibleOffers(product).filter(o => (!selection.tier || recommendationTier(product, o) === selection.tier)
    && (!selection.duration || o.duration === selection.duration));
  if (mode === 'value') {
    const ranked = matching.map(offer => ({ offer, plan: planForOffer(product, offer), months: Number.parseInt(offer.duration, 10) }))
      .filter(item => Number.isFinite(item.months) && item.months > 0 && Number.isFinite(item.plan?.limitPoints) && item.plan.limitPoints > 0)
      .map(item => ({ ...item, score: item.plan.limitPoints * item.months / item.offer.priceRub * 1000 }));
    return ranked.sort((a,b) => b.score-a.score || a.offer.priceRub-b.offer.priceRub
      || Number(!a.offer.finalVerified)-Number(!b.offer.finalVerified)
      || Number(a.offer.delivery !== 'own_account')-Number(b.offer.delivery !== 'own_account'))[0] || null;
  }
  const cheapest = [...matching].sort((a,b) => a.priceRub-b.priceRub
    || Number(!a.finalVerified)-Number(!b.finalVerified)
    || Number(a.delivery !== 'own_account')-Number(b.delivery !== 'own_account'))[0] || null;
  return cheapest ? { offer: cheapest, multiplier: null, score: null } : null;
}
function ordered(values, order) {
  return [...new Set(values)].sort((a,b) => {
    const ai = order.indexOf(a), bi = order.indexOf(b);
    return (ai < 0 ? -1 : ai) - (bi < 0 ? -1 : bi) || String(a).localeCompare(String(b));
  });
}
function renderRecommendation(product) {
  const eligible = eligibleOffers(product);
  const tierOrder = product.id === 'claude' ? ['Pro', 'Max 5X', 'Max 20X'] : tierRank[product.id] || [];
  const tiers = ordered(eligible.map(o => recommendationTier(product, o)), tierOrder);
  const selection = recommendationSelection.get(product.id) || { tier: '', duration: '' };
  if (selection.tier && !tiers.includes(selection.tier)) selection.tier = '';
  const durationOffers = eligible.filter(o => !selection.tier || recommendationTier(product, o) === selection.tier);
  const durations = ordered(durationOffers.map(o => o.duration), durationRank);
  if (selection.duration && !durations.includes(selection.duration)) selection.duration = '';
  recommendationSelection.set(product.id, selection);
  const chosen = recommendation(product, selection, recommendationMode);
  const offer = chosen?.offer;
  const id = esc(product.id);
  const tierOptions = [`<option value=""${selection.tier ? '' : ' selected'}>Все уровни</option>`, ...tiers.map(tier => `<option value="${esc(tier)}"${tier === selection.tier ? ' selected' : ''}>${esc(tier)}</option>`)].join('');
  const durationOptions = [`<option value=""${selection.duration ? '' : ' selected'}>Любой срок</option>`, ...durations.map(duration => `<option value="${esc(duration)}"${duration === selection.duration ? ' selected' : ''}>${esc(label(duration))}</option>`)].join('');
  const controls = `<div class="recommendation-controls">
      <label><span>Уровень</span><select data-product="${id}" data-selection="tier">${tierOptions}</select></label>
      <label><span>Срок</span><select data-product="${id}" data-selection="duration">${durationOptions}</select></label>
    </div>`;
  if (!offer) return `<article class="recommendation-card">
    <span class="service">${esc(product.label)}</span>
    ${controls}
    <p class="unavailable">${recommendationMode === 'value' ? 'Для выбранных условий нет подтверждённого числового лимита плана. Все предложения доступны в таблице.' : 'Нет проверенного предложения для выбранных условий. Все предложения доступны в таблице.'}</p>
    <a href="#offers" data-product="${id}" class="show-product-offers">Смотреть предложения</a>
  </article>`;
  const details = [label(offer.delivery), offer.marketplace.toUpperCase()].filter(Boolean).join(' · ');
  const planFamily = planRegistry?.families?.[product.id === 'zai' ? 'zai_glm' : product.id];
  const planSource = chosen?.plan?.sourceUrl || planFamily?.sourceUrl;
  const score = recommendationMode === 'value'
    ? `<span class="recommended-score">Официальный план: ${esc(chosen.plan.planId)}${chosen.plan.planProduct ? ` · ${esc(chosen.plan.planProduct)}` : ''} · ${esc(chosen.plan.originalOfficialUnit)} (${esc(chosen.plan.originalOfficialQuantity ?? 'нет числовой нормы')}; ${esc(chosen.plan.originalOfficialPeriod)}) · ${scoreFormat.format(chosen.plan.limitPoints)} × ${Number.parseInt(offer.duration, 10)} мес. × 1 000 / ${rub.format(offer.priceRub)} ₽ = ${scoreFormat.format(chosen.score)} условных пунктов лимита на 1 000 ₽ за срок подписки. <a href="${esc(safeUrl(planSource))}" target="_blank" rel="noopener noreferrer">Официальный источник</a></span>`
    : '';
  return `<article class="recommendation-card">
    <span class="service">${esc(product.label)}</span>
    <h3>${esc(recommendationTier(product, offer))} · ${esc(label(offer.duration))}</h3>
    ${controls}
    ${score}
    <span class="recommended-price">Полная цена: ${rub.format(offer.priceRub)} ₽</span>
    <span class="recommended-detail">${esc(offer.optionText || offer.title)}</span>
    <span class="recommended-meta">${esc(details)}${offer.finalVerified ? ' · проверено в браузере' : ''}</span>
    <a href="${esc(safeUrl(offer.url))}" target="_blank" rel="noopener noreferrer">Смотреть предложение</a>
  </article>`;
}
function renderRecommendations() {
  els['recommendation-mode-price'].setAttribute('aria-selected', String(recommendationMode === 'price'));
  els['recommendation-mode-value'].setAttribute('aria-selected', String(recommendationMode === 'value'));
  const orderedProducts = recommendationMode === 'value'
    ? products.map((product, index) => ({ product, index, score: recommendation(product, recommendationSelection.get(product.id) || { tier: '', duration: '' }, 'value')?.score ?? null }))
      .sort((a,b) => a.score === null ? (b.score === null ? a.index-b.index : 1) : b.score === null ? -1 : b.score-a.score || a.index-b.index)
      .map(item => item.product)
    : products;
  els['recommendations-list'].innerHTML = orderedProducts.map(renderRecommendation).join('');
}
function chooseProduct(id) {
  active = products.find(item => item.id === id); if (!active) return;
  offers = active.offers; els.product.value = id;
  els['product-kicker'].textContent = `ПОСЛЕДНИЙ СКАН · ${active.metadata.scanDate}`;
  els['product-title'].textContent = active.label;
  els['product-description'].textContent = active.description;
  const finished = active.metadata.scanCompletedAt || active.metadata.scanStartedAt;
  els.updated.textContent = `Скан: ${finished ? new Date(finished).toLocaleString('ru-RU') : active.metadata.scanDate} · ${active.metadata.listings || '—'} карточек`;
  els['source-note'].textContent = `${active.metadata.detailLevel === 'summary' ? 'Это сохранённая итоговая сводка: полный raw/CSV этого исторического Z.ai-скана не был закоммичен. ' : 'Полный CSV и raw-снимок доступны в репозитории. '}Тип выдачи «не определён» требует ручной проверки условий продавца.`;
  resetFilters(); render();
}
function filtered() {
  const query = els.search.value.trim().toLowerCase();
  return offers.filter(o => (!query || [o.title,o.optionText,o.marketplace,o.tier].join(' ').toLowerCase().includes(query))
    && (!els.tier.value || o.tier === els.tier.value) && (!els.duration.value || o.duration === els.duration.value)
    && (!els.delivery.value || o.delivery === els.delivery.value) && (!els.marketplace.value || o.marketplace === els.marketplace.value)
    && (!els['hide-glitched'].checked || !o.glitched))
    .sort((a,b) => els.sort.value === 'price-desc' ? b.priceRub-a.priceRub : els.sort.value === 'duration' ? a.duration.localeCompare(b.duration) || a.priceRub-b.priceRub : a.priceRub-b.priceRub);
}
function render() {
  const rows = filtered(); els.result.textContent = `Показано ${rows.length} из ${offers.length} вариантов`;
  els['offer-count'].textContent = rows.length; els['minimum-price'].textContent = rows.length ? `${rub.format(rows[0].priceRub)} ₽` : '—'; els['marketplace-count'].textContent = new Set(rows.map(o => o.marketplace)).size;
  els.offers.innerHTML = rows.map(o => `<tr><td class="price">${rub.format(o.priceRub)} ₽${o.finalVerified ? '<span class="sub">повторно проверено</span>' : o.glitched ? '<span class="sub warning">нужна проверка</span>' : ''}</td><td><span class="tag">${esc(o.tier)}</span></td><td>${esc(label(o.duration))}</td><td>${esc(label(o.delivery))}</td><td>${esc(o.marketplace.toUpperCase())}</td><td class="title">${esc(o.title)}<span class="sub">${esc(o.optionText || 'Базовый вариант')}</span></td><td><a href="${esc(safeUrl(o.url))}" target="_blank" rel="noopener noreferrer">Открыть</a></td></tr>`).join('') || '<tr><td colspan="7">Ничего не найдено: измените фильтры.</td></tr>';
}
async function init() {
  try {
    const [data, registry] = await Promise.all([
      fetch('data/latest.json?v=7').then(r => { if (!r.ok) throw new Error(); return r.json(); }),
      fetch('data/subscription-plan-limits.json').then(r => { if (!r.ok) throw new Error(); return r.json(); })
    ]);
    planRegistry = registry;
    products = data.products; renderRecommendations(); els.product.innerHTML = ''; products.forEach(item => els.product.append(new Option(item.label, item.id))); chooseProduct(products[0]?.id);
  } catch { els.result.textContent = 'Не удалось загрузить каталог снимков.'; }
}
['search','tier','duration','delivery','marketplace','sort','hide-glitched'].forEach(id => els[id].addEventListener(id === 'search' ? 'input' : 'change', render));
els.product.addEventListener('change', event => chooseProduct(event.target.value)); els.reset.addEventListener('click', () => { resetFilters(); render(); }); init();
els['recommendations-list'].addEventListener('change', event => {
  const select = event.target;
  const product = products.find(item => item.id === select.dataset.product);
  if (!product || !select.dataset.selection) return;
  const selection = recommendationSelection.get(product.id) || { tier: '', duration: '' };
  selection[select.dataset.selection] = select.value;
  if (select.dataset.selection === 'tier') {
    const durations = ordered(eligibleOffers(product).filter(o => !select.value || recommendationTier(product, o) === select.value).map(o => o.duration), durationRank);
    if (selection.duration && !durations.includes(selection.duration)) selection.duration = '';
  }
  recommendationSelection.set(product.id, selection);
  renderRecommendations();
});
els['recommendation-mode-price'].addEventListener('click', () => { recommendationMode = 'price'; renderRecommendations(); });
els['recommendation-mode-value'].addEventListener('click', () => { recommendationMode = 'value'; renderRecommendations(); });
els['recommendations-list'].addEventListener('click', event => {
  const link = event.target.closest?.('a.show-product-offers');
  if (!link) return;
  event.preventDefault();
  const product = products.find(item => item.id === link.dataset.product);
  if (!product) return;
  chooseProduct(product.id);
  els.offers.scrollIntoView({ block: 'start', behavior: 'smooth' });
});
