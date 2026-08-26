const labels = { own_account: 'Свой аккаунт', new_account: 'Новый аккаунт', unknown: 'Не определён', '1m': '1 месяц', '3m': '3 месяца', '6m': '6 месяцев', '12m': '1 год' };
const els = Object.fromEntries(['search','tier','duration','delivery','marketplace','sort','hide-glitched','reset','offers','result','updated','offer-count','minimum-price','marketplace-count'].map(id => [id, document.getElementById(id)]));
const rub = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
let offers = [];

function valueLabel(value) { return labels[value] || value; }
function addOptions(id, values) { [...values].sort().forEach(value => els[id].append(new Option(valueLabel(value), value))); }
function filtered() {
  const query = els.search.value.trim().toLowerCase();
  const rows = offers.filter(o => (!query || [o.title,o.optionText,o.marketplace,o.tier].join(' ').toLowerCase().includes(query))
    && (!els.tier.value || o.tier === els.tier.value) && (!els.duration.value || o.duration === els.duration.value)
    && (!els.delivery.value || o.delivery === els.delivery.value) && (!els.marketplace.value || o.marketplace === els.marketplace.value)
    && (!els['hide-glitched'].checked || !o.glitched));
  return rows.sort((a,b) => els.sort.value === 'price-desc' ? b.priceRub-a.priceRub : els.sort.value === 'duration' ? a.duration.localeCompare(b.duration) || a.priceRub-b.priceRub : a.priceRub-b.priceRub);
}
function render() {
  const rows = filtered();
  els.result.textContent = `Показано ${rows.length} из ${offers.length} вариантов`;
  els['offer-count'].textContent = rows.length;
  els['minimum-price'].textContent = rows.length ? `${rub.format(rows[0].priceRub)} ₽` : '—';
  els['marketplace-count'].textContent = new Set(rows.map(o => o.marketplace)).size;
  els.offers.innerHTML = rows.map(o => `<tr><td class="price">${rub.format(o.priceRub)} ₽${o.glitched ? '<span class="sub warning">нужна проверка</span>' : ''}</td><td><span class="tag">${o.tier}</span></td><td>${valueLabel(o.duration)}</td><td>${valueLabel(o.delivery)}</td><td>${o.marketplace.toUpperCase()}</td><td class="title">${o.title}<span class="sub">${o.optionText || 'Базовый вариант'}</span></td><td><a href="${o.url}" target="_blank" rel="noopener noreferrer">Открыть</a></td></tr>`).join('') || '<tr><td colspan="7">Ничего не найдено: измените фильтры.</td></tr>';
}
async function init() {
  try {
    const data = await fetch('data/latest.json').then(r => { if (!r.ok) throw new Error(); return r.json(); });
    offers = data.offers;
    addOptions('tier', new Set(offers.map(o => o.tier))); addOptions('duration', new Set(offers.map(o => o.duration))); addOptions('delivery', new Set(offers.map(o => o.delivery))); addOptions('marketplace', new Set(offers.map(o => o.marketplace)));
    const completed = data.metadata.scanCompletedAt || data.metadata.generatedAt;
    els.updated.textContent = `Снимок: ${new Date(completed).toLocaleString('ru-RU')} · ${data.metadata.listings || '—'} карточек`; render();
  } catch { els.result.textContent = 'Не удалось загрузить снимок цен.'; }
}
['search','tier','duration','delivery','marketplace','sort','hide-glitched'].forEach(id => els[id].addEventListener(id === 'search' ? 'input' : 'change', render));
els.reset.addEventListener('click', () => { els.search.value = ''; ['tier','duration','delivery','marketplace'].forEach(id => els[id].value=''); els.sort.value='price-asc'; els['hide-glitched'].checked=true; render(); });
init();
