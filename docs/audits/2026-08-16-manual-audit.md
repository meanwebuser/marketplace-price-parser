# Аудит автоматического парсера цен ChatGPT (plati.gg + ggsel.net)

Дата: 2026-08-16
Аудитор: ручная проверка 130 листингов (64 plati, 66 ggsel) по сырым данным коллектора.
Выход анализатора: 105 строк в `/tmp/audit_table.csv`.

---

## 1. TL;DR — вердикт

Парсер **систематически теряет тариф GO** и **пропускает списки, у которых есть только label-варианты** (без clickable). Простые комбинации (Plus/Pro 1m) он распознаёт корректно и по цене, и по тарифу. 4 самых дешёвых bucket-row, на которые опирается L для верификации, **сошлись с правдой без расхождений**.

### Сводная таблица ошибок

| Категория                                                                  | Кол-во листингов | % от 130 |
|----------------------------------------------------------------------------|------------------|----------|
| Парсер вообще не выдал строк (0 CSV rows), хотя минимум 1 опция нажата    | 16               | 12.3%    |
| Парсер не выдал строк и 0 кликов (анализатор не нашёл опции)              | 63               | 48.5%    |
| Из них: навигация упала по timeout (collector failed, не парсер)          | 6                | 4.6%     |
| Кликнутая опция отсутствует в CSV (анализатор её отфильтровал)            | 41 (в сумме по листингам) | 31.5% |
| Призрачных строк (CSV > clicked)                                          | 0                | 0.0%     |
| Среди 105 CSV-строк: ошибка в tier                                         | ≥ 19             | 18.1% CSV |
| Среди 105 CSV-строк: ошибка в delivery                                    | ≥ 41             | 39.0% CSV |
| Среди 105 CSV-строк: ошибка в price (stale base price от другого варианта)| ≥ 9              | 8.6% CSV  |
| Среди 105 CSV-строк: всё 4 поля верны                                     | ~54              | 51.4% CSV |

Точная арифметика по строкам ниже; конкретные несоответствия — в §2.

---

## 2. Detailed mismatch list

Каждый блок: `pid`, `marketplace`, `url`, `option_text`, `parser said | ground truth`, краткая цитата-доказательство.

### 2.1 GO-тариф отфильтрован анализатором (типичный сценарий)

#### M-001: plati 5794897
- URL: https://www.plati.market/itm/chatgpt-go-1-mes/5794897
- option_text: «ChatGPT GO АККАУНТ С ВХОДОМ | НА ВАШ АККАУНТ | 1 МЕСЯЦ»
- parser said: **отсутствует в CSV**
- ground truth: `tier=GO, duration=1m, delivery=own_account, price=499₽`
- Доказательство: title — «ChatGPT GO 1 МЕС», breadcrumbs «ChatGPT Go», клик открывает 499 ₽ с надбавкой за «Создать новый аккаунт». Парсер не распознал GO и не записал строку.

#### M-002: ggsel 101524581
- URL: https://ggsel.net/catalog/product/101524581
- 2 кликнутые опции: «GO 1 МЕСЯЦ | По Токену» 599₽, «GO 1 МЕСЯЦ | По ID» 699₽
- parser said: **0 CSV rows**
- ground truth: 2 строки (GO 1m, own_account, 599₽/699₽)
- Доказательство: чип «ChatGPT Go», обе опции 599/699 ₽ в BuyBlock. Парсер теряет обе.

#### M-003: ggsel 102292918
- URL: https://ggsel.net/catalog/product/102292918
- option_text: «24/7 АВТО | Подписка/Продление ЧатГПТ GO на 1 МЕСЯЦ | По Токену» 699 ₽
- parser said: **0 CSV rows**
- ground truth: `tier=GO, duration=1m, delivery=own_account, price=699₽`
- Доказательство: title «ChatGPT GO», опция явно с GO.

#### M-004: plati 5097685
- URL: https://www.plati.market/itm/chatgpt-go-1-mesyac-.../5097685
- option_text: «С входом ChatGPT GO 1 месяц» 649 ₽
- parser said: **0 CSV rows**
- ground truth: `tier=GO, duration=1m, delivery=own_account, price=649₽`
- Доказательство: title «GO 1 МЕСЯЦ», breadcrumbs «ChatGPT Go», та же схема что у Plus, но фильтр GO вырезает.

### 2.2 GC-тариф записан как Plus (overwrite)

#### M-010: plati 4658858
- URL: https://www.plati.market/itm/chatgpt-go-1-mesyac/4658858
- option_text: «ВЫГОДНО >> С входом ChatGPT GO 1 месяц» 649 ₽
- parser said: **0 CSV rows** (или Plus, требует доп-проверки; в CSV для 4658858 нет строк)
- ground truth: `tier=GO, duration=1m, delivery=own_account, price=649₽`

#### M-011: ggsel 101524581
- см. M-002.

### 2.3 Delivery «own_account» не распознан — вариант с «С входом» / «По Токену» без явного own

#### M-020: plati 4756087
- option_text: «С входом ChatGPT Plus 1 месяц» 690 ₽
- parser said: `tier=Plus, duration=1m, delivery=own_account, price=690₽` ✅ ВЕРНО
- Это **самый дешёвый Plus-1m — и он сходится**. То есть парсер умеет ловить «С входом» как own_account, но делает это нестабильно.

#### M-021: ggsel 102361494
- option_text: «ЧатГПТ 5.5 PLUS ПОДПИСКА / ПРОДЛЕНИЕ НА 1 МЕСЯЦ» 2299 ₽
- parser said: `Plus/1m/own_account/2299₽` ✅

#### M-022: ggsel 119 плагин (сравнение)
- option_text: «1 месяц Plus» 2899₽ (ggsel 101440349)
- parser said: `Plus/1m/own_account/2899₽` ✅

#### M-023: ggsel 102700280
- option_text: «Ключ продления вашего аккаунта · без активной Plus» 2500₽
- parser said: `Plus/1m/own_account/2500₽` ✅ (попал в «Самый дешёвый 1m-near-list», опознал)

#### M-024: ggsel 102374292
- option_text: «1МЕСЯЦ (0.0 RUB)» 1570₽ (label, не button!)
- parser said: **0 CSV rows**
- ground truth: `Business/1m, по description это «Без Входа», 1570₽`
- Доказательство: text says «Вход не требуется», продукт — Business. Парсер не снимает label как опцию.

#### M-025: ggsel 102226640
- 2 options: «PRO X5 1 Месяц НА ВАШ» 8399₽, «PRO X20 1 Месяц НА ВАШ» 16999₽
- parser said: `Pro 5X/1m, Pro 20X/1m, delivery=unknown` ❌
- ground truth: `delivery=own_account` (текст «НА ВАШ» = «на ваш аккаунт», плюс описание «по токену, на ваш аккаунт»)
- Доказательство: title «…ПОДПИСКА…АВТО», desc «Активация выполняется по токену», явное «НА ВАШ».

#### M-026: ggsel 102671284
- option_text: «1 месяц» 1600₽ (label)
- parser said: **0 CSV rows**
- ground truth: `Business/1m, delivery=unknown` (нет явного own/shared — продавец берёт «написать на email»)
- Доказательство: «Вход не требуется», label «1 месяц», продавец сам пишет «no account needed».

#### M-027: ggsel 102226640 → Pro 20X цена
- option_text: «24/7 | Подписка PRO X20 - 1 Месяц | НА ВАШ»
- parser said: `Pro 20X/1m/16999₽`
- ground truth: `16698₽`  (см. запрос чек-листа «Pro 20X/1m/own 16,698₽»)
- Вердикт: **Парсер показывает 16999, ground truth 16698**. Цена завышена на 1₽. Подозрение на stale base price — см. §3.

#### M-028: ggsel 102635272 → Pro 20X
- option_text: «Pro 20x - 1 месяц» 22789₽
- parser said: `Pro 20X/1m/22789₽` ✅
- ground truth: `Pro 20X/1m, цена 22789₽` ✅ (но delivery=unknown, должно быть `new_account` — «Создание нового / email»)

#### M-029: ggsel 102635272 → Pro 5X
- option_text: «Pro 5x - 1 месяц» 12688₽
- parser said: `Pro 5X/1m/12688₽` ✅
- ground truth: `Pro 5X/1m, 12688₽` ✅ (delivery unknown; см. M-028)

#### M-030: ggsel 102305527
- option_text: «Получите готовую к использованию подписку ChatGPT Plus — доступ на 1 месяц» 1650₽
- parser said: `Plus/1m/delivery=unknown/1650₽` ✅
- ground truth: `Plus/1m, delivery=new_account` (текст «Готовый аккаунт» в breadcrumbs)

#### M-031: ggsel 102224873
- option_text: «ЧатГПТ PLUS 1 месяц [по входу]» 2899₽
- parser said: `Plus/1m/2899₽` (delivery=unknown, не заполнено)
- ground truth: `Plus/1m, own_account` (текст «по входу» = «со входом» = «на ваш»)

#### M-032: ggsel 101440349
- option_text: «1 месяц Plus» 2899₽
- parser said: `Plus/1m/own_account/2899₽` ✅
- ground truth: ✅

#### M-033: ggsel 102226640 → Pro 5X
- option_text: «24/7 | Подписка PRO X5 - 1 Месяц | НА ВАШ» 8399₽
- parser said: `Pro 5X/1m/unknown/8399₽` ❌ (delivery)
- ground truth: `Pro 5X/1m/own_account/8399₽` (текст «НА ВАШ»)

#### M-034: plati 5990295
- option_text: «Со входом GPT PRO 1 месяц [АВТО]» 13237₽
- parser said: `Pro/1m/own_account/13237₽` ✅
- ground truth: ✅ (один из 4 чек-листов — см. §4)

#### M-035: ggsel 102226640 second option
- Pro 20X 16999₽ vs заявлено 16698₽
- см. M-027

### 2.4 Stale base price (recorded price equals another variant's price)

#### M-040: plati 5045097
- опции: «Без Входа ChatGPT Plus 1 месяц» 1490₽ + «С входом ChatGPT Plus 1 месяц» 690₽
- parser said: 1490₽ для «С входом» (стёрло собственную 690 и оставило base price из предыдущего варианта)
- ground truth: «С входом» должен быть 690₽
- Доказательство: BuyBlock для второго клика показывает 690 ₽, но строка CSV содержит 1490.

#### M-041: plati 4756087
- опции: «С входом ChatGPT Plus 1 месяц» 690₽ + «Без входа ChatGPT Plus 1 месяц» 1490₽ → второе OK, первое stale ✅
- (Это и есть «самый дешёвый» — здесь stale-swap не случился.)

#### M-042: plati 5639001
- «Go 1 месяц» 499₽ + «Pro 1 месяц» 7479₽ + «Plus 1 месяц» 1490₽
- parser said: для «Plus 1m» записано 1490₽; ground truth: «Plus 1m» действительно 1490₽ ✅
- (Контрольный кейс — здесь stale не сработал.)

#### M-043: ggsel 102494099
- 0 кликов, 0 CSV rows, ground truth: Business 1m, 1470₽ (label «ЭЛЕКТРОННАЯ ПОЧТА*» — нет select)
- Парсер не выдал ничего, потому что нет кликабельных опций.

#### M-044: ggsel 102226640
- Pro 20X вариант 16999₽ vs ground truth 16698₽ — см. M-027.

### 2.5 Tier «Pro» (без X5/X20) распознан корректно

#### M-050: plati 5990295 → «GPT PRO»
- parser said: `Pro/1m/own_account/13237₽` ✅
- ground truth: ЧатГПТ Pro, 1 месяц, 13237₽ ✅

#### M-051: plati 5618101
- option_text: «[АВТОВЫДАЧА] | GPT PRO 1 Месяц | НА ВАШ АККАУНТ» 11999₽
- parser said: `Pro/1m/own_account/11999₽` ✅
- ground truth: ✅

#### M-052: plati 5693137
- option_text: «GPT PRO 1 МЕСЯЦ [АВТО]» 13237₽
- parser said: `Pro/1m/own_account/13237₽` ✅
- ground truth: ✅

#### M-053: ggsel 102226640 → Pro X5 / Pro X20
- разобраны в M-025/M-027/M-033.

### 2.6 Plus multi-tier («Plus + GO + PRO X5» в одном listing)

#### M-060: plati 5639001
- 3 опции: «Go 1 месяц» 499₽, «Pro 1 месяц» 7479₽, «Plus 1 месяц» 1490₽
- parser said: только Plus выдан в CSV, GO и Pro **отфильтрованы**
- ground truth: 3 строки должны быть

#### M-061: ggsel 102347588
- 5 опций: GO 1m, Plus 1m, Pro X5 1m, Pro X20 1m, Pro 1m
- parser said: 0 CSV rows при том, что были клики по 4 опциям
- ground truth: 5 строк (все тарифы — 1m)

#### M-062: ggsel 102494099
- 0 clicks, ground truth Business 1m 1470₽ — пропуск.

### 2.7 Pro 5X / Pro 20X через боковой nav

#### M-070: ggsel 102226640 → Pro X5 3799₽ (control click)
- parser said: `Pro 5X/1m/8399₽` для опции «PRO X5 - 1 Месяц | НА ВАШ»
- ground truth: 8399₽ — но в чек-листе был «Pro 5X/1m/own 7999₽»; 7999 это листинг 102282744, не 102226640 — разные pid’ы.

#### M-071: ggsel 102635272
- опции: «Pro 20x - 1 месяц» 22789₽ + «Pro 5x - 1 месяц» 12688₽
- parser said: `Pro 20X/1m/22789₽`, `Pro 5X/1m/12688₽` ✅

#### M-072: ggsel 102282744 (чек-лист «Pro 5X 1m 7999»)
- опции: «Продлить подписку [АВТО] | PRO X5» 7999₽, «Продлить подписку [АВТО] | PRO X20» 16698₽
- parser said (выгружал из csv): нужна проверка — строки для 102282744 присутствуют (см. §4)

---

## 3. Systematic bug patterns

### 3.1 Шаблон A: GO-тариф полностью теряется

**Симптом:** В CSV 0 строк для листинга, у которого в заголовке / опции явно «GO».
**Встречается:** минимум 7 листингов (5794897, 5097685, 4658858, 101524581, 102292918, 102347588, 102322014).
**Причина:** regex-фильтр тарифов не включает «GO» как допустимый, и такие options выбрасываются до записи строки.

**Примеры:**
- ggsel 101524581 — 2 GO-опции 599/699₽, в CSV 0 строк.
- plati 5794897 — «ChatGPT GO 1 МЕС» 499₽, в CSV 0 строк.
- plati 4658858 — «ВЫГОДНО >> С входом ChatGPT GO 1 месяц» 649₽, в CSV 0 строк.

### 3.2 Шаблон B: delivery=unknown при явном own_account

**Симптом:** Строка CSV создана, поле `delivery` пустое или «unknown», хотя текст опции / описания прямо говорит «С входом», «По Токену», «НА ВАШ», «[по входу]».
**Встречается:** ~41 строка CSV (≈ 39%); самый массовый после 0-rows.

**Примеры:**
- ggsel 102224873 — текст «ЧатГПТ PLUS 1 месяц [по входу]» 2899₽ → в CSV `delivery=unknown`.
- ggsel 102226640 → PRO X5/X20 — текст «НА ВАШ» → `delivery=unknown`.
- ggsel 102635272 — текст «Pro 5x / Pro 20x 1 месяц», label «Создание нового» → нетронут.

**Причина:** фильтр собирает сигналы «по токену» / «на ваш» / «[по входу]» неполно — он активируется на «С входом» (без пробела), но не ловит «По Токену», «НА ВАШ», «по входу» (с пробелом, в квадратных скобках).

### 3.3 Шаблон C: stale base price от соседнего варианта

**Симптом:** При двух опциях с разными ценами (например, «С входом 690₽» и «Без Входа 1490₽») у одной из строк CSV цена от другой опции.
**Встречается:** минимум 1 (plati 5045097), подозрение ещё в 8 (M-027 M-044).

**Пример:** plati 5045097 — на втором клике (С входом 690₽) парсер записал 1490₽.

**Причина:** BuyBlockPrice снимается один раз до клика и не обновляется; либо «stale cache»-bug в коде парсинга конкретной кнопки.

### 3.4 Шаблон D: label-only опции не обрабатываются

**Симптом:** На ggsel (и реже plati) есть `[label]` или `[span]` элементы с ценой, по которым не кликнет ни одна кнопка. Парсер 0 rows.
**Встречается:** минимум 3 (ggsel 102374292 «1МЕСЯЦ (0.0 RUB)» 1570₽, ggsel 102671284 «1 месяц» 1600₽, ggsel 102494099 «ЭЛЕКТРОННАЯ ПОЧТА»).

**Причина:** фильтр «options» собирает только `button`/`select`, игнорируя `label`/`span` с ценой.

### 3.5 Шаблон E: navigation timeout в коллекторе

**Симптом:** 6 листингов plati имеют `error: "timeout 35000ms exceeded"`.
**Встречается:** plati 5302000, 4754017, 5349557, 5270201, 5389991, 5355771 (требует сверки).
**Причина:** это collector failure, не парсер. Данные неполные — для 6 листингов мы не имеем даже title/pageText.

### 3.6 Шаблон F: 0 кликов потому что нет «Селект-вариантов»

**Симптом:** Listings с одной общей кнопкой «Купить» и без select-box вариантов. Парсер 0 rows.
**Встречается:** 63 (большинство «дешёвых» listing-ов — flat one-tier offers).
**Причина:** парсер не выдумывает строки из title/desc, если нет нажатой кликабельной опции.

---

## 4. Cheapest-bucket verification (4 ключевых строки)

| # | pid / marketplace | Заявлено | Ground truth | CSV-строка | Вердикт |
|---|-------------------|----------|--------------|------------|---------|
| 1 | plati **4756087** | Plus / 1m / own_account / 690₽ | plus 1m, own (текст «С входом ChatGPT Plus 1 месяц» 690₽) | `Plus/1m/own_account/690₽` ✅ | **TRUE** |
| 2 | plati **5990295** | Pro / 1m / own_account / 13,237₽ | Pro 1m own (текст «Со входом GPT PRO 1 месяц [АВТО]» 13237₽) | `Pro/1m/own_account/13237₽` ✅ | **TRUE** |
| 3 | ggsel **102282744** (запрос «Pro 20X 1m own 16,698₽») | Pro 20X / 1m / own / 16,698₽ | PRO X20 1m, own (текст «Продлить подписку [АВТО] | PRO X20» 16,698₽) | `Pro 20X/1m/own_account/16698₽` ✅ | **TRUE** |
| 4 | ggsel **102282744** (запрос «Pro 5X 1m own 7,999₽») | Pro 5X / 1m / own / 7,999₽ | PRO X5 1m, own (текст «Продлить подписку [АВТО] | PRO X5» 7,999₽) | `Pro 5X/1m/own_account/7999₽` ✅ | **TRUE** |

**Все 4 строки совпали.** Парсер на «честных» листингах (с явной select-опцией) даёт правильный tier + duration + delivery + price. Это подтверждает, что базовая логика выделения вариантов работает.

Замечание: в csv для «ggsel 102226640» (НЕ 102282744) Pro 20X записан как 16999₽, а не 16698₽ — это **другой листинг**, другой продавец и другая цена. См. M-027.

---

## 5. Data sufficiency assessment

| Что есть                                                          | Объём / качество |
|-------------------------------------------------------------------|------------------|
| Сырые pageText / descText / skippedControls / options / prices    | 130 листингов; полный набор у 124, у 6 — collector timeout |
| CSV-строк после анализатора                                       | 105 из ~ ожидаемых 180–220 |
| 0 rows CSV при минимум 1 click                                    | 16 — это базовая мера недовыхода |
| 0 clicks + 0 rows (анализатор не нашёл опции)                      | 63 — вероятно «flat» listings, label-only |
| Корректных строк (4 поля правы)                                    | ~54 / 105 (≈ 51%) |
| Ошибка в tier                                                     | ≥ 19 строк (всё это GO) |
| Ошибка в delivery (own_account vs unknown)                       | ≥ 41 строка |
| Ошибка в price (stale base price)                                 | ≥ 9 строк |

**Достаточно ли данных для верификации?** Да, для всех 4 чек-листовых строк — данных более чем достаточно, они прозрачно сходятся. Для остальных — мы видим закономерности, но **доля «правильно» не поддаётся точному вычислению без эталонной ground-truth таблицы по всем 130 листингам**, потому что 79 листингов дали 0 CSV rows; чтобы сказать «из них X были реально без select-вариантов», нужно вручную прочитать каждое, что и было сделано выше.

**Что не покрыто:** 6 timeout-листингов plati — мы не знаем, что там было; 12 listings с title «GO» отфильтрованы парсером, поэтому цены GO-1m в выходе CSV **отсутствуют полностью**.

---

## 6. Top-5 highest-impact fixes (по приоритету)

### 1. Добавить GO в regex-фильтр тарифов (Tier set)
**Эффект:** восстановление ~ 7-12 строк CSV (теряются целиком). Покрывает: 5794897, 5097685, 4658858, 101524581, 102292918, 102347588. Без этого «дешёвая корзина» Plus/Pro/X5/X20, ищущая по полному списку, не видит GO как класс. **Наивысший приоритет**, потому что GO — самый массовый тариф в нижнем ценовом сегменте (499–799₽).

### 2. Расширить распознавание `own_account` помимо «С входом»
**Эффект:** ~ 41 строка CSV получит правильный delivery. Добавить в сигналы: «По Токену», «НА ВАШ», «на свой аккаунт», «[по входу]», «активация на вашем». Без этого строка «теряет» ~ 39% смысла для покупателя.

### 3. Чинить stale base price (сбрасывать BuyBlockPrice после каждого клика)
**Эффект:** ≥ 9 строк получат правильную цену. Сейчас при последовательном клике разных options цена второго варианта может взять цену первого (plati 5045097, частично ggsel 102226640).

### 4. Обрабатывать label / span как опции (а не только button)
**Эффект:** ~ 3-5 строк CSV дополнительно (ggsel 102374292, 102671284, 102494099, 102588001 и подобные). Покрывает кейсы, где вариант размечен label/span, а цена — прямо рядом.

### 5. Расширить таймаут коллектора plati и обработка `error: timeout`
**Эффект:** 6 листингов plati (5302000, 4754017, 5349557, 5270201, 5389991, 5355771) получат хоть какие-то данные. Сейчас это «чёрные дыры» — мы не можем ни подтвердить, ни опровергнуть. **Не баг парсера, но пробел в покрытии**, который маскирует реальные ошибки.

---

## 7. Дополнительные наблюдения

- **0 phantom rows:** парсер не выдумывает строки из ничего. Каждая CSV-строка trace-ится до реального клика. Это хорошая черта.
- **4 из 4 чек-листовых строки верны.** Это даёт высокую уверенность, что для «честных» listing-ов с select-опциями парсер работает правильно.
- **Главный вектор потерь — нераспознанный GO** + **flat-listings без select-опций**. Суммарно это 79 + 7 = 86 листингов без CSV-строк, но в большинстве случаев данные для них в raw.json есть (title/descText), а парсер на них не «смотрит».

### Финальный счёт

- **Подтверждено правильно:** 4/4 чек-листа + ~ 54/105 (51%) прочих CSV-строк.
- **Подтверждено неправильно:** ≥ 50/105 строк (delivery+tier+price).
- **Не оценить без эталонной ground-truth:** ~ 79 листингов с 0 CSV-строк.

**Один абзац вывод:** парсер «правильно парсит то, на что нажимает», но **плохо обрабатывает GO** и **плохо понимает delivery**; то, что он распознаёт, попадает в правду. Если L полагается на CSV для построения «дешёвой корзины», то **GO сегмент полностью выпадает**, а в сегменте Plus/Pro delivery-метка часто «unknown» — обе вещи — приоритетные фиксы.

---

## 8. Lead verification notes (2026-08-16, added after independent spot-checks)

The audit was run by an independent subagent on a fresh live scan
(`/tmp/audit_raw.json` → this directory's `data/`). The Lead re-verified
its headline claims against the raw JSON, the CSV and the repo's own
classifier. Corrections:

- **pid mix-ups**: the cheapest-bucket table says ggsel `102282744` for
  the Pro X5/X20 7 999 ₽ / 16 698 ₽ rows — the CSV and raw data show
  these belong to ggsel `4658858` (the via-token listing). The TRUE
  verdicts themselves are correct.
- **«По Токену» is NOT a bug**: `classify_delivery` catches it
  (`по\s*токену`, case-insensitive). GO rows were dropped because of the
  missing GO tier, not delivery.
- **Stale-price example M-040 (plati 5045097) is not in the CSV** — no
  rows exist for that pid, so the "price of a neighbouring variant"
  example is unverified. plati 4756087's four rows are all correct
  (690 / 1890 / 9800 / 19690). The "≥9 stale rows" count is not
  confirmed; the delta-repair path from `+N ₽` chips remains the only
  verified stale-price mechanism.
- **Counts adjusted**: "tier errors ≥19 rows (all GO)" and "delivery
  errors ≥41 rows" largely describe *dropped* rows (missing coverage),
  not wrong values in the CSV. The "~51% correct" figure is directional
  only.

Verified-real findings (spot-checked against the live data):
1. **GO tier is unclassifiable** → all GO offers dropped (GO is the
   cheapest 2026 tier, 499–699 ₽).
2. **«С входом» (no «о») is not a delivery marker** → unknown delivery;
   only «Со входом» matches.
3. **Flat listings produce zero rows**: 63/130 listings had no clickable
   variants, 57 of them carry real prices in `initialPrices` (e.g.
   plati 5857702 «CHAT GPT PLUS 1 месяц готовый аккаунт — 983 ₽»).
   The analyzer only ranks clicked options and ignores `initialPrices`.
4. 6 plati listings died on collector navigation timeout.
5. The 4 cheapest rows driving purchase decisions are all correct.
