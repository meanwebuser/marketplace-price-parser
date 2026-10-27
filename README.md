# Удобный парсер цен GGSEL и Plati

Семейство-ориентированный парсер для двух маркетплейсов — [GGSEL](https://ggsel.net/) и [Plati](https://plati.market/). Канонический путь — `cli.py --family <name>`: добавить новый продукт (Cursor, Claude, Grok, Kimi) теперь стоит 30 строк конфига, а не копию всего сканера.

Поддерживаемые семейства: `minimax` (M Plan GO / Explore / Build и Token Plan Plus / Max / Ultra), `zai` (GLM Coding), `chatgpt` (Plus / Pro / Pro X5 / Pro X20), `claude` (Pro / Max), `kimi` (Kimi AI / Kimi K3 Plus / Pro / Max / Ultra), `apple_gift_card` (отдельный prepaid-каталог по региону и номиналу).

Kimi uses the parser's `1m`, `3m`, `6m`, and `12m` durations and includes all four delivery types for the public catalogue, including shared and unknown delivery. API, top-up, balance, and credit listings are excluded during discovery and eligibility filtering. GGSEL category discovery merges curated listing IDs from the 2026-10-02 snapshot without importing historical prices. The scanner compares prices only; it does not inspect or infer seller availability or inventory.

## Что умеет

- автоматически искать кандидатов в каталоге GGSEL и API каталога Plati;
- при настройке пользователя загружать HTTP-прокси из endpoint и менять proxy по карточкам, не сохраняя адреса прокси в снимках;
- открывать карточки товаров в браузере и кликать каждый вариант (Max / Pro+ / Lite × 1/3/12 мес × свой аккаунт / случайный email);
- читать финальную цену выбранного варианта, а не доверять минимальной цене каталога;
- получать цену Plati для выбранных вариантов через `price_options.asp`, без последовательного открытия страниц в браузере;
- различать `own_account`, `new_account`, `shared_account` и `unknown` условия выдачи;
- различать варианты ChatGPT Pro X5 / Pro X20 как отдельные тарифы;
- pass 2 по умолчанию через `adaptive`: deterministic-first, LLM получает
  только неоднозначные строки и до трёх представителей нового отпечатка
  структуры страницы; `--analyzer regex` всегда остаётся zero-call режимом;
- без `LLM_API_KEY` адаптивный режим не делает вызовов и оставляет
  неподтверждённые поля неизвестными; `--analyzer llm` включает полный разбор
  явно, `--analyzer regex` — чистый офлайн-анализ;
- свежие сканы записываются в уникальный `.tmp/scans/<run-id>/`, чтобы
  предыдущие карточки не смешивались с новым проходом;
- до двух семейств могут собираться параллельно в пределах общего бюджета
  до 10 HTTP и 2 браузерных workers; Plati HTTP и GGSEL SSR тоже работают
  параллельно, браузер получает только неподдержанные или заблокированные карточки;
- каждый свежий снимок сравнивает отпечатки структуры карточек с последним
  снимком, помечая новые шаблоны сайта без сохранения динамических цен или текста;
- GGSEL discovery объединяет категорию с rendered search aliases, если семья
  задаёт их явно; новые ID повторно разбираются тем же парсером вариантов;
- чинить цену варианта, когда блок цены не успел обновиться после клика (чип «+N ₽» = наценка к базовой цене лота);
- фильтровать по eligibility-правилам конкретного семейства (tier × duration × delivery, purpose preset);
- детектить UI-глитчи цен (12-мес Max за 1.5M RUB вместо 162K — отбрасываем);
- до 10 параллельных headless HTTP-запросов Impit/curl_cffi для SSR-вариантов GGSEL и Plati, с Playwright-fallback до 2 воркеров только для неподдержанных страниц;
- расчёт самой дешёвой точной комбинации Apple Gift Card; цена допускает повтор одного лота, количество не проверяется;
- выводить результат в CSV + Markdown.

## Быстрый запуск

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci --prefix ggsel_plati
```

Канонический CLI:

```bash
# Свежий скан: discovery → collect → deterministic analyze (без LLM по умолчанию)
# Перед запуском при необходимости локально задайте свой
# MARKETPLACE_PROXY_SOURCE_URL; значение и endpoint не сохраняются в репозитории.
PYTHONPATH=. .venv/bin/python cli.py \
  --family minimax,zai,chatgpt,claude,kimi --full-discovery \
  --require-proxy --parallel-families 2 --http-workers 10 --workers 2 \
  --headless --analyzer adaptive

# Kimi AI / Kimi K3: fresh subscription catalogue, no visible browser windows
PYTHONPATH=. .venv/bin/python cli.py --family kimi --http-workers 10 --workers 2 --headless

# Exhaust result/load-more pagination (up to 100 pages and 10,000 candidates
# per marketplace); scan metadata marks any reached cap as partial.
PYTHONPATH=. .venv/bin/python cli.py --family apple_gift_card --region US \
  --full-discovery --http-workers 10 --workers 2 --headless

# Headless collection for either marketplace
PYTHONPATH=. .venv/bin/python cli.py --family chatgpt --http-workers 10 --workers 2 --headless

# Повторный анализ по уже собранным данным
PYTHONPATH=. .venv/bin/python cli.py --family zai --skip-discover --raw .tmp/zai_raw.json

# С фильтром только Max / 1 месяц / свой аккаунт
PYTHONPATH=. .venv/bin/python cli.py --family zai --tier Max --duration 1m --delivery own_account

# ChatGPT в режиме «продлить на свой аккаунт» (purpose preset)
PYTHONPATH=. .venv/bin/python cli.py --family chatgpt --purpose renew

# Pass 2 через LLM: батчи evidence-pack'ов, классификация без регэкспов
# (нужен LLM_API_KEY; OpenAI-совместимый эндпоинт, по умолчанию gemma4)
PYTHONPATH=. .venv/bin/python cli.py --family chatgpt --purpose renew --analyzer llm

# Проверить размер контекста LLM без реальных вызовов (дампы в .tmp/llm-efficiency/llm_prompts)
PYTHONPATH=. .venv/bin/python cli.py --family chatgpt --analyzer llm --llm-dry-run \
  --skip-discover --raw docs/audits/data/2026-08-16-audit-raw.json
```

Подробный порядок прокси-сканирования, LLM-калибровки и детерминированного
повторного анализа описан в [marketplace parser skill](skills/marketplace-price-parser/SKILL.md)
и его [повторяемом workflow](skills/marketplace-price-parser/references/proxy-and-two-pass.md).

Чтобы подключить собственный HTTP proxy-list endpoint, задайте локально
`MARKETPLACE_PROXY_SOURCE_URL`. Endpoint должен возвращать `text/plain`, по
одному HTTP(S) URL прокси на непустую строку. Если источнику нужен bearer token,
передайте его через `MARKETPLACE_PROXY_SOURCE_TOKEN`; не включайте token в URL.
`MARKETPLACE_PROXY_URL` задаёт один rotating proxy для catalog discovery.
Если обе переменные заданы, список идёт в параллельный сбор карточек и цен,
а одиночный rotating proxy — только в discovery.
Не добавляйте endpoint, прокси, user-info или token в Git. Если переменная URL
не задана, используется прямое подключение; если настроенный источник ошибся
или вернул пустой список, сбор завершается с ошибкой вместо скрытого перехода
на direct.

## Бюджет локального сравнения (Mac, 2026-10-22)

База замера: 32 GiB RAM, 10 CPU; browser fallback ограничен 2 headless workers. 27 октября 2026 Impit загрузил 7 GGSEL карточек с 27 option prices за 5.97 секунды (27/27 совпали с браузером после округления до рубля, peak RSS около 59 MiB). Plati HTTP canary получил 32/32 option totals через `/asp/price_options.asp` за 17 секунд; вариант $2 дал 214 ₽, как и browser buy-block. Предел: до 10 HTTP workers и до 2 Playwright workers; один нагрузочный запуск за раз, 40 дочерних процессов, 4 GiB soft / 6 GiB hard RAM, swap growth ≤1 GiB, temp ≤1 GiB и минимум 100 GiB свободного диска. LLM batch concurrency — 1, GPU не используется. Остановить запуск при превышении этих пределов.

Артефакты:
- `.tmp/scans/<run-id>/raw.<family>.json` — уникальные исходные снимки каждого семейства
- `.tmp/scans/<run-id>/table.csv` — нормализованные офферы (pass 2)
- `.tmp/scans/<run-id>/table.md` — канонический отчёт с самой дешёвой ценой по (tier × duration × delivery)
- `.tmp/llm-efficiency/llm_prompts/` — сохранённые prompt batches для `--llm-dry-run`

### Backward-compat wrappers

Старые CLI продолжают работать как тонкие шимы над `cli.py`:

```bash
# Старый MiniMax CLI — передаёт в cli.py --family minimax
PYTHONPATH=. .venv/bin/python minimax_max_prices.py --search-query MiniMax --usd-rub 78.0308

# Старый ChatGPT Plus CLI — передаёт в cli.py --family chatgpt
PYTHONPATH=. .venv/bin/python ggsel_plati/best_chatgptplus_prices.py --purpose renew
```

Legacy-реализации (с ручным Gemma4, manual candidates, USD-сравнением) сохранены в `minimax_max_prices.legacy.py` для обратной совместимости.

## Структура

```
low_price/
├── cli.py                          # Универсальный entry point: --family <name>
├── click.py                        # Node.js parallel Playwright (4 UI template)
│
├── families/                       # Per-product configs
│   ├── __init__.py                 # FAMILY_REGISTRY
│   ├── base.py                     # FamilyConfig dataclass
│   ├── minimax.py                  # MiniMax M Plan / Token Plan
│   ├── zai.py                      # Z.ai GLM Coding Max
│   ├── chatgpt.py                  # ChatGPT Plus / Pro (purpose presets)
│   ├── claude.py                   # Claude Pro / Max
│   └── kimi.py                     # Kimi AI / Kimi K3 subscriptions
│
├── marketplaces/                   # Per-marketplace adapters
│
├── scanner/                        # Pass 1: collect raw data
│   ├── discover.py                 # Plati API + GGSEL category pagination
│   ├── ggsel_ssr.py                # 10-way Impit/curl_cffi SSR price capture
│   ├── plati_http.py               # selected-option totals via Plati HTTP endpoint
│   └── collect.py                  # SSR fast path + bounded click.py fallback
│
├── analyzer/                       # Pass 2: interpret
│   ├── price.py                    # tier × duration × delivery classification
│   └── output.py                   # CSV + Markdown
│
├── minimax_max_prices.py           # Backward-compat wrapper → cli.py
├── minimax_max_prices.legacy.py    # Original implementation (preserved)
├── ggsel_plati/best_chatgptplus_prices.py  # Backward-compat wrapper → cli.py
│
├── tests/                          # pytest suite
└── skills/marketplace-price-parser/ # Public AI-skill instructions
```

### Как добавить новое семейство

```python
# families/cursor.py
from families.base import FamilyConfig

CONFIG = FamilyConfig(
    name="cursor",
    search_terms=["Cursor", "cursor ai"],
    purpose_preset="renew",
    marketplaces=["plati", "ggsel"],
    tier_filter=["Pro", "Pro+", "Ultra"],
    duration_filter=["1m"],
    delivery_filter=["own_account"],
    ggssel_category="cursor",  # /catalog/cursor on GGSEL
    description="Cursor AI Pro / Pro+ / Ultra monthly",
)
```

Add the module's `CONFIG` to `families/__init__.py`; the canonical CLI then resolves it through `FAMILY_REGISTRY`.

### Crawlee backends

`scanner/discover.py` использует Crawlee. Альтернативные клиенты (раскомментируйте по необходимости):
- `ImpitHttpClient` — browser-impersonating HTTP (impit) — для Plati
- `CurlImpersonateHttpClient` — curl-impersonate
- `HttpxHttpClient` — plain httpx
- `PlaywrightCrawler` — реальный Chromium (используется для GGSEL, который 401-ит всех остальных)

### GGSEL: подтверждённые варианты

Для ранжирования учитываются только цены, где сборщик подтвердил выбранный
вариант. Если GGSEL не применяет реактивный переключатель в изолированном
Playwright, такой лот остаётся в сыром снимке, но не может стать «самым
дешёвым» в итоговой таблице.

Для проверки GGSEL через уже открытый реальный Chrome можно передать CDP URL:

```bash
node click.py --cdp-url http://127.0.0.1:9222 --workers 1 \
  --ggsel-ids 102608819 --out .tmp/minimax-raw.json
```

Chrome должен быть предварительно запущен владельцем с включённым remote
debugging. В этом режиме сборщик открывает только свои вкладки, не копирует
cookies и не закрывает браузер пользователя.

## Тесты

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
PYTHONPATH=. .venv/bin/python -m py_compile cli.py scanner/*.py analyzer/*.py families/*.py
node --check < click.py
```

## Важно

Цены и тексты карточек меняются; результат — снимок на время запуска. Сборщик намеренно не проверяет наличие и остатки. Проект не хранит учётные данные маркетплейсов и не должен использоваться для передачи продавцу паролей без осознанного решения пользователя.

## Лицензия

MIT — см. [LICENSE](LICENSE).
