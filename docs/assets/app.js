const labels = { own_account: 'На личный аккаунт', new_account: 'Отдельный аккаунт', shared_account: 'Общий аккаунт', unknown: 'Уточнить у продавца', '1m': '1 месяц', '3m': '3 месяца', '6m': '6 месяцев', '12m': '1 год' };
const ids = ['product','recommendations-list','recommendation-mode-price','recommendation-mode-value','search','tier','duration','delivery','marketplace','sort','hide-glitched','reset','offers','result','updated','offer-count','minimum-price','marketplace-count','product-kicker','product-title','product-description','source-note','gift-card-combo','gift-card-target','gift-card-combo-result'];
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
const denominationUnit = offer => offer.denominationCurrency === 'USD' ? '$1' : `1 ${offer.denominationCurrency || 'ед.'}`;
function resetOptions(id, initial) { els[id].innerHTML = `<option value="">${initial}</option>`; }
function addOptions(id, values) { [...values].sort().forEach(value => els[id].append(new Option(label(value), value))); }
function resetFilters() {
  const isGiftCard = active.kind === 'gift_card';
  els.search.value = '';
  resetOptions('tier', isGiftCard ? 'Любой номинал' : 'Все');
  resetOptions('duration', isGiftCard ? 'Любой регион' : 'Любой');
  resetOptions('delivery', 'Любая'); resetOptions('marketplace', 'Все');
  const tierLabel = els.tier.closest?.('label')?.querySelector?.('span');
  const durationLabel = els.duration.closest?.('label')?.querySelector?.('span');
  const headings = document.querySelectorAll?.('thead th') || [];
  if (tierLabel) tierLabel.textContent = isGiftCard ? 'Номинал' : 'Тариф';
  if (durationLabel) durationLabel.textContent = isGiftCard ? 'Регион' : 'Срок';
  if (headings[1]) headings[1].textContent = isGiftCard ? 'Номинал' : 'Тариф';
  if (headings[2]) headings[2].textContent = isGiftCard ? 'Регион' : 'Срок';
  const unitPriceSort = els.sort.querySelector?.('option[value="price-asc"]');
  if (unitPriceSort) unitPriceSort.textContent = isGiftCard ? `Цена за ${denominationUnit(offers[0] || {})} номинала` : 'Сначала дешевле';
  const durationSort = els.sort.querySelector?.('option[value="duration"]');
  if (durationSort) durationSort.textContent = isGiftCard ? 'По региону' : 'По сроку';
  if (isGiftCard) {
    addOptions('tier', new Set(offers.map(o => `${o.denomination} ${o.denominationCurrency}`)));
    addOptions('duration', new Set(offers.map(o => o.region)));
  } else {
    addOptions('tier', new Set(active.allowedTiers || offers.map(o => o.tier)));
    addOptions('duration', new Set(offers.map(o => o.duration)));
  }
  addOptions('delivery', new Set(offers.map(o => o.delivery))); addOptions('marketplace', new Set(offers.map(o => o.marketplace)));
  els.sort.value = 'price-asc'; els['hide-glitched'].checked = true;
}
function eligibleOffers(product) {
  return product.offers.filter(o => o.priceVerified !== false && !o.glitched && Number.isFinite(o.priceRub) && o.priceRub > 0);
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
function recommendationName(product, offer) {
  if (product.kind === 'gift_card') return `Apple Gift Card · ${offer.denomination} ${offer.denominationCurrency} · ${offer.region}`;
  const tier = recommendationTier(product, offer);
  if (product.id === 'zai') return `Z.ai GLM ${tier}`;
  if (product.id === 'minimax') return `MiniMax M Plan ${tier}`;
  return tier;
}
function recommendation(product, selection, mode) {
  const isGiftCard = product.kind === 'gift_card';
  const matching = eligibleOffers(product).filter(o => (!selection.tier || (isGiftCard ? `${o.denomination} ${o.denominationCurrency}` : recommendationTier(product, o)) === selection.tier)
    && (!selection.duration || (isGiftCard ? o.region : o.duration) === selection.duration));
  if (isGiftCard && mode === 'value') return null;
  if (mode === 'value') {
    const ranked = matching.map(offer => ({ offer, plan: planForOffer(product, offer), months: Number.parseInt(offer.duration, 10) }))
      .filter(item => Number.isFinite(item.months) && item.months > 0 && Number.isFinite(item.plan?.limitPoints) && item.plan.limitPoints > 0)
      .map(item => ({ ...item, score: item.plan.limitPoints * item.months / item.offer.priceRub * 1000 }));
    return ranked.sort((a,b) => b.score-a.score || a.offer.priceRub-b.offer.priceRub
      || Number(!a.offer.finalVerified)-Number(!b.offer.finalVerified)
      || Number(a.offer.delivery !== 'own_account')-Number(b.offer.delivery !== 'own_account'))[0] || null;
  }
  const unitPrice = offer => Number.isFinite(offer.pricePerUnit) ? offer.pricePerUnit : offer.priceRub / offer.denomination;
  const cheapest = [...matching].sort((a,b) => (isGiftCard ? unitPrice(a)-unitPrice(b) : a.priceRub-b.priceRub)
    || a.priceRub-b.priceRub
    || Number(!a.finalVerified)-Number(!b.finalVerified)
    || Number(a.delivery !== 'own_account')-Number(b.delivery !== 'own_account'))[0] || null;
  return cheapest ? { offer: cheapest, multiplier: null, score: null } : null;
}
function cheapestGiftCardCombo(product, targetCents, finalVerifiedOnly = false) {
  const options = new Map();
  for (const offer of product.offers) {
    if (offer.region !== 'US' || offer.denominationCurrency !== 'USD'
      || (finalVerifiedOnly && offer.finalVerified !== true)
      || offer.priceVerified !== true || offer.glitched
      || !Number.isFinite(offer.priceRub) || offer.priceRub <= 0) continue;
    const cents = Math.round(Number(offer.denomination) * 100);
    if (!Number.isInteger(cents) || cents <= 0 || Math.abs(cents - Number(offer.denomination) * 100) > 0.001) continue;
    const key = `${offer.marketplace}:${offer.pid}:${cents}`;
    const previous = options.get(key);
    if (!previous || offer.priceRub < previous.offer.priceRub) options.set(key, { offer, cents });
  }
  const choices = [...options.values()];
  const states = Array(targetCents + 1).fill(null);
  states[0] = { cost: 0, picks: [] };
  for (let total = 1; total <= targetCents; total++) {
    for (const { offer, cents } of choices) {
      if (cents > total || !states[total - cents]) continue;
      const candidate = { cost: states[total - cents].cost + offer.priceRub,
        picks: [...states[total - cents].picks, offer] };
      const previous = states[total];
      if (!previous || candidate.cost < previous.cost
        || (candidate.cost === previous.cost && candidate.picks.length < previous.picks.length)) states[total] = candidate;
    }
  }
  return states[targetCents] || null;
}
function renderGiftCardCombo(product) {
  const container = els['gift-card-combo'];
  if (!container) return;
  const isAppleUS = product?.kind === 'gift_card' && product.id === 'apple_us';
  container.hidden = !isAppleUS;
  if (!isAppleUS) return;
  const target = Number(els['gift-card-target']?.value || 50);
  if (!Number.isFinite(target) || target <= 0 || target > 1000) {
    els['gift-card-combo-result'].innerHTML = '<p class="combo-message">Введите сумму от $0,01 до $1 000.</p>';
    return;
  }
  const targetCents = Math.round(target * 100);
  if (Math.abs(targetCents - target * 100) > 0.001) {
    els['gift-card-combo-result'].innerHTML = '<p class="combo-message">Сумма должна быть указана с точностью до цента.</p>';
    return;
  }
  const currentCombo = cheapestGiftCardCombo(product, targetCents, true);
  const combo = currentCombo || cheapestGiftCardCombo(product, targetCents);
  if (!combo) {
    els['gift-card-combo-result'].innerHTML = `<p class="combo-message">Не нашёл комбинацию ровно на $${scoreFormat.format(target)} среди цен, подтверждённых в последнем скане.</p>`;
    return;
  }
  const rate = combo.cost / target;
  const grouped = new Map();
  for (const offer of combo.picks) {
    const key = `${offer.marketplace}:${offer.pid}:${offer.denomination}`;
    if (!grouped.has(key)) grouped.set(key, { offer, count: 0 });
    grouped.get(key).count++;
  }
  const lines = [...grouped.values()].map(({offer, count}) => `<li><span>${count} × $${scoreFormat.format(offer.denomination)} · ${rub.format(offer.priceRub)} ₽ за карту · ${offer.marketplace.toUpperCase()}${offer.optionText ? `<small>Выбрать на странице: ${esc(offer.optionText)}</small>` : ''}${offer.finalVerified ? '<small>Цена повторно проверена</small>' : ''}</span><a href="${esc(safeUrl(offer.url))}" target="_blank" rel="noopener noreferrer">Открыть лот</a></li>`).join('');
  const scannedAt = currentCombo ? product.metadata?.manualPriceChecksDate : product.metadata?.scanCompletedAt || product.metadata?.scanDate;
  const scanned = scannedAt ? (String(scannedAt).includes('T') ? new Date(scannedAt).toLocaleString('ru-RU') : new Date(`${scannedAt}T12:00:00`).toLocaleDateString('ru-RU')) : 'неизвестно';
  const count = combo.picks.length;
  const countLabel = count === 1 ? '1 карта' : count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 12 || count % 100 > 14) ? `${count} карты` : `${count} карт`;
  const checkScope = currentCombo
    ? `Это минимум среди ${Number(product.metadata?.manualPriceChecks || 0)} вариантов, чьи цены повторно проверены ${esc(scanned)}; другие лоты не входят в этот минимум.`
    : `Это минимум по подтверждённым ценам снимка от ${esc(scanned)}; цены продавцов могут измениться.`;
  els['gift-card-combo-result'].innerHTML = `<div class="combo-summary"><strong>${currentCombo ? 'Цена перепроверена:' : 'Оценка по скану:'} $${scoreFormat.format(target)} за ${rub.format(combo.cost)} ₽</strong><span>≈ ${scoreFormat.format(rate)} ₽ за $1 · ${countLabel}</span></div><ul class="combo-list">${lines}</ul><p class="combo-footnote">${checkScope} Оптимизация допускает повтор одного и того же лота; остатки не проверялись. Комиссии оплаты не учтены — перед оплатой проверьте выбранные варианты и итоговую сумму на странице продавца.</p>`;
}
function ordered(values, order) {
  return [...new Set(values)].sort((a,b) => {
    const ai = order.indexOf(a), bi = order.indexOf(b);
    return (ai < 0 ? -1 : ai) - (bi < 0 ? -1 : bi) || String(a).localeCompare(String(b));
  });
}
function renderRecommendation(product) {
  const eligible = eligibleOffers(product);
  const isGiftCard = product.kind === 'gift_card';
  const tierOrder = product.id === 'claude' ? ['Pro', 'Max 5X', 'Max 20X'] : tierRank[product.id] || [];
  const tiers = isGiftCard
    ? ordered(eligible.map(o => `${o.denomination} ${o.denominationCurrency}`), [])
    : ordered(eligible.map(o => recommendationTier(product, o)), tierOrder);
  const selection = recommendationSelection.get(product.id) || { tier: '', duration: '' };
  if (selection.tier && !tiers.includes(selection.tier)) selection.tier = '';
  const durationOffers = eligible.filter(o => !selection.tier || (isGiftCard ? `${o.denomination} ${o.denominationCurrency}` : recommendationTier(product, o)) === selection.tier);
  const durations = ordered(durationOffers.map(o => isGiftCard ? o.region : o.duration), isGiftCard ? [] : durationRank);
  if (selection.duration && !durations.includes(selection.duration)) selection.duration = '';
  recommendationSelection.set(product.id, selection);
  const chosen = recommendation(product, selection, recommendationMode);
  const offer = chosen?.offer;
  const id = esc(product.id);
  const tierOptions = [`<option value=""${selection.tier ? '' : ' selected'}>${isGiftCard ? 'Любой номинал' : 'Все уровни'}</option>`, ...tiers.map(tier => `<option value="${esc(tier)}"${tier === selection.tier ? ' selected' : ''}>${esc(tier)}</option>`)].join('');
  const durationOptions = [`<option value=""${selection.duration ? '' : ' selected'}>${isGiftCard ? 'Любой регион' : 'Любой срок'}</option>`, ...durations.map(duration => `<option value="${esc(duration)}"${duration === selection.duration ? ' selected' : ''}>${esc(isGiftCard ? duration : label(duration))}</option>`)].join('');
  const controls = `<div class="recommendation-controls">
      <label><span>${isGiftCard ? 'Номинал' : 'Уровень'}</span><select data-product="${id}" data-selection="tier">${tierOptions}</select></label>
      <label><span>${isGiftCard ? 'Регион' : 'Срок'}</span><select data-product="${id}" data-selection="duration">${durationOptions}</select></label>
    </div>`;
  if (!offer) return `<article class="recommendation-card">
    <span class="service">${esc(product.label)}</span>
    ${controls}
    <p class="unavailable">${isGiftCard && recommendationMode === 'value' ? 'Показатель лимита за рубль применяется к подпискам. Для gift cards используйте сортировку по цене.' : recommendationMode === 'value' ? 'Для выбранных условий нет подтверждённого числового лимита плана. Все предложения доступны в таблице.' : 'Нет проверенного предложения для выбранных условий. Все предложения доступны в таблице.'}</p>
    <a href="#offers" data-product="${id}" class="show-product-offers">Смотреть предложения</a>
  </article>`;
  const details = [label(offer.delivery), offer.seller, offer.marketplace.toUpperCase()].filter(Boolean).join(' · ');
  const planFamily = planRegistry?.families?.[product.id === 'zai' ? 'zai_glm' : product.id];
  const planSource = chosen?.plan?.sourceUrl || planFamily?.sourceUrl;
  const score = recommendationMode === 'value'
    ? `<span class="recommended-score">Официальный план: ${esc(chosen.plan.planId)}${chosen.plan.planProduct ? ` · ${esc(chosen.plan.planProduct)}` : ''} · ${esc(chosen.plan.originalOfficialUnit)} (${esc(chosen.plan.originalOfficialQuantity ?? 'нет числовой нормы')}; ${esc(chosen.plan.originalOfficialPeriod)}) · ${scoreFormat.format(chosen.plan.limitPoints)} × ${Number.parseInt(offer.duration, 10)} мес. × 1 000 / ${rub.format(offer.priceRub)} ₽ = ${scoreFormat.format(chosen.score)} условных пунктов лимита на 1 000 ₽ за срок подписки. <a href="${esc(safeUrl(planSource))}" target="_blank" rel="noopener noreferrer">Официальный источник</a></span>`
    : '';
  return `<article class="recommendation-card">
    <span class="service">${esc(product.label)}</span>
    <h3>${esc(recommendationName(product, offer))}${isGiftCard ? '' : ` · ${esc(label(offer.duration))}`}</h3>
    ${controls}
    ${score}
    <span class="recommended-price">Полная цена: ${rub.format(offer.priceRub)} ₽${isGiftCard ? ` · ${scoreFormat.format(offer.pricePerUnit ?? (offer.priceRub / offer.denomination))} ₽ за ${denominationUnit(offer)} номинала` : ''}</span>
    <span class="recommended-detail">${esc(offer.optionText || offer.title)}</span>
    ${offer.sellerNote ? `<span class="recommended-detail">Заметка продавца (не проверена): ${esc(offer.sellerNote)}</span>` : ''}
    <span class="recommended-meta">${esc(details)}${offer.finalVerified ? ' · цена повторно проверена' : ''}</span>
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
  els.updated.textContent = `Скан: ${finished ? new Date(finished).toLocaleString('ru-RU') : active.metadata.scanDate} · ${active.metadata.listings || '—'} уникальных объявлений`;
  els['source-note'].textContent = active.kind === 'gift_card'
    ? 'Регион Apple Account должен совпадать с регионом карты. Номинал — в валюте карты, цена продавца — в рублях. В каталоге проверяются цены; наличие и остатки не проверяются.'
    : `${active.metadata.detailLevel === 'summary' ? 'Это сохранённая итоговая сводка: полный raw/CSV этого исторического Z.ai-скана не был закоммичен. ' : 'Полный CSV и raw-снимок доступны в репозитории. '}Тип выдачи «не определён» требует ручной проверки условий продавца.`;
  if (active.metadata.coverageSummary) {
    els['source-note'].append(document.createTextNode(` Охват: ${active.metadata.coverageSummary}.`));
  }
  if (active.metadata.discoveryCoverage?.auditPath && /^audits\/[\w.-]+\.md$/.test(active.metadata.discoveryCoverage.auditPath)) {
    const link = document.createElement('a');
    link.href = active.metadata.discoveryCoverage.auditPath;
    link.textContent = 'Подробности поиска и его ограничения';
    els['source-note'].append(document.createTextNode(' '), link);
  }
  resetFilters(); render(); renderGiftCardCombo(active);
}
function filtered() {
  const query = els.search.value.trim().toLowerCase();
  const isGiftCard = active?.kind === 'gift_card';
  const unitPrice = offer => Number.isFinite(offer.pricePerUnit) ? offer.pricePerUnit : offer.priceRub / offer.denomination;
  return offers.filter(o => (!query || [o.title,o.optionText,o.marketplace,o.tier,o.region,o.denomination].join(' ').toLowerCase().includes(query))
    && (!els.tier.value || (isGiftCard ? `${o.denomination} ${o.denominationCurrency}` : o.tier) === els.tier.value)
    && (!els.duration.value || (isGiftCard ? o.region : o.duration) === els.duration.value)
    && (!els.delivery.value || o.delivery === els.delivery.value) && (!els.marketplace.value || o.marketplace === els.marketplace.value)
    && (!els['hide-glitched'].checked || !o.glitched))
    .sort((a,b) => els.sort.value === 'price-desc' ? b.priceRub-a.priceRub
      : els.sort.value === 'duration' ? (isGiftCard ? String(a.region).localeCompare(String(b.region)) : String(a.duration).localeCompare(String(b.duration))) || a.priceRub-b.priceRub
      : isGiftCard ? unitPrice(a)-unitPrice(b) || a.priceRub-b.priceRub : a.priceRub-b.priceRub);
}
function render() {
  renderGiftCardCombo(active);
  const rows = filtered(); els.result.textContent = `Показано ${rows.length} из ${offers.length} вариантов`;
  els['offer-count'].textContent = rows.length;
  const isGiftCard = active?.kind === 'gift_card';
  const metricLabel = els['minimum-price'].parentElement?.querySelector?.('span');
  if (metricLabel) metricLabel.textContent = isGiftCard ? `Минимум за ${denominationUnit(rows[0] || {})}` : 'Минимальная цена';
  if (isGiftCard) {
    const bestUnitPrice = rows.length ? Math.min(...rows.map(o => o.pricePerUnit ?? o.priceRub / o.denomination)) : null;
    els['minimum-price'].textContent = bestUnitPrice === null ? '—' : `${scoreFormat.format(bestUnitPrice)} ₽`;
  } else {
    const minimumPrice = rows.length ? Math.min(...rows.map(o => o.priceRub)) : null;
    els['minimum-price'].textContent = minimumPrice === null ? '—' : `${rub.format(minimumPrice)} ₽`;
  }
  els['marketplace-count'].textContent = new Set(rows.map(o => o.marketplace)).size;
  els.offers.innerHTML = rows.map(o => `<tr><td class="price">${rub.format(o.priceRub)} ₽${isGiftCard ? `<span class="sub">${scoreFormat.format(o.pricePerUnit ?? (o.priceRub / o.denomination))} ₽ за ${denominationUnit(o)} номинала</span>` : ''}${o.finalVerified ? '<span class="sub">повторно проверено</span>' : o.glitched ? '<span class="sub warning">нужна проверка</span>' : ''}</td><td><span class="tag">${esc(isGiftCard ? `${o.denomination} ${o.denominationCurrency}` : o.tier)}</span></td><td>${esc(isGiftCard ? o.region : label(o.duration))}</td><td>${esc(label(o.delivery))}</td><td>${esc(o.marketplace.toUpperCase())}</td><td class="title">${esc(o.title)}<span class="sub">${esc(o.optionText || 'Базовый вариант')}</span>${o.seller ? `<span class="sub">${esc(o.seller)}</span>` : ''}${o.sellerNote ? `<span class="sub">Заметка продавца (не проверена): ${esc(o.sellerNote)}</span>` : ''}</td><td><a href="${esc(safeUrl(o.url))}" target="_blank" rel="noopener noreferrer">Открыть</a></td></tr>`).join('') || '<tr><td colspan="7">Ничего не найдено: измените фильтры.</td></tr>';
}
async function init() {
  try {
    const [data, registry] = await Promise.all([
      fetch('data/latest.json?v=13').then(r => { if (!r.ok) throw new Error(); return r.json(); }),
      fetch('data/subscription-plan-limits.json').then(r => { if (!r.ok) throw new Error(); return r.json(); })
    ]);
    planRegistry = registry;
    products = [...(data.products || []), ...(data.giftCards || [])]; renderRecommendations(); els.product.innerHTML = ''; products.forEach(item => els.product.append(new Option(item.label, item.id))); chooseProduct(products[0]?.id);
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
    const durations = ordered(eligibleOffers(product).filter(o => !select.value || (product.kind === 'gift_card' ? `${o.denomination} ${o.denominationCurrency}` : recommendationTier(product, o)) === select.value).map(o => product.kind === 'gift_card' ? o.region : o.duration), product.kind === 'gift_card' ? [] : durationRank);
    if (selection.duration && !durations.includes(selection.duration)) selection.duration = '';
  }
  recommendationSelection.set(product.id, selection);
  renderRecommendations();
});
els['recommendation-mode-price'].addEventListener('click', () => { recommendationMode = 'price'; renderRecommendations(); });
els['recommendation-mode-value'].addEventListener('click', () => { recommendationMode = 'value'; renderRecommendations(); });
els['gift-card-target']?.addEventListener('input', () => renderGiftCardCombo(active));
els['recommendations-list'].addEventListener('click', event => {
  const link = event.target.closest?.('a.show-product-offers');
  if (!link) return;
  event.preventDefault();
  const product = products.find(item => item.id === link.dataset.product);
  if (!product) return;
  chooseProduct(product.id);
  els.offers.scrollIntoView({ block: 'start', behavior: 'smooth' });
});
