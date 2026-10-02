const labels = { own_account: 'На личный аккаунт', new_account: 'Отдельный аккаунт', shared_account: 'Общий аккаунт', unknown: 'Уточнить у продавца', '1m': '1 месяц', '3m': '3 месяца', '6m': '6 месяцев', '12m': '1 год' };
const ids = ['product','recommendations-list','search','tier','duration','delivery','marketplace','sort','hide-glitched','reset','offers','result','updated','offer-count','minimum-price','marketplace-count','product-kicker','product-title','product-description','source-note'];
const els = Object.fromEntries(ids.map(id => [id, document.getElementById(id)]));
const rub = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
let products = [], active = null, offers = [];

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
function recommendation(product) {
  const verified = product.offers.filter(o => o.available !== false && o.priceVerified !== false && !o.glitched);
  return [...verified].sort((a,b) => a.priceRub-b.priceRub
    || Number(!a.finalVerified)-Number(!b.finalVerified)
    || Number(a.delivery !== 'own_account')-Number(b.delivery !== 'own_account'))[0] || null;
}
function renderRecommendations() {
  els['recommendations-list'].innerHTML = products.map(product => {
    const offer = recommendation(product);
    if (!offer) return '';
    const details = [label(offer.duration), label(offer.delivery), offer.marketplace.toUpperCase()].filter(Boolean).join(' · ');
    return `<article class="recommendation-card">
      <span class="service">${esc(product.label)}</span>
      <h3>${esc(offer.tier)}</h3>
      <span class="recommended-price">${rub.format(offer.priceRub)} ₽</span>
      <span class="recommended-detail">${esc(offer.optionText || offer.title)}</span>
      <span class="recommended-meta">${esc(details)}${offer.finalVerified ? ' · проверено в браузере' : ''}</span>
      <a href="${esc(safeUrl(offer.url))}" target="_blank" rel="noopener noreferrer">Смотреть предложение</a>
    </article>`;
  }).join('');
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
    const data = await fetch('data/latest.json?v=7').then(r => { if (!r.ok) throw new Error(); return r.json(); });
    products = data.products; renderRecommendations(); els.product.innerHTML = ''; products.forEach(item => els.product.append(new Option(item.label, item.id))); chooseProduct(products[0]?.id);
  } catch { els.result.textContent = 'Не удалось загрузить каталог снимков.'; }
}
['search','tier','duration','delivery','marketplace','sort','hide-glitched'].forEach(id => els[id].addEventListener(id === 'search' ? 'input' : 'change', render));
els.product.addEventListener('change', event => chooseProduct(event.target.value)); els.reset.addEventListener('click', () => { resetFilters(); render(); }); init();
