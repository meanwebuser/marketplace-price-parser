# Удобный парсер цен GGSEL и Plati

Семейство-ориентированный парсер для двух маркетплейсов — [GGSEL](https://ggsel.net/) и [Plati](https://plati.market/). Канонический путь — `cli.py --family <name>`: добавить новый продукт (Cursor, Claude, Grok, Kimi) теперь стоит 30 строк конфига, а не копию всего сканера.

Поддерживаемые семейства: `minimax` (Token Plan Max), `zai` (GLM Coding Max), `chatgpt` (Plus / Pro / Pro X5 / Pro X20), `claude` (Pro / Max — placeholder).

## Что умеет

- автоматически искать кандидатов в каталоге GGSEL и API каталога Plati;
- открывать карточки товаров в браузере и кликать каждый вариант (Max / Pro+ / Lite × 1/3/12 мес × свой аккаунт / случайный email);
- читать финальную цену выбранного варианта, а не доверять минимальной цене каталога;
- различать `own_account`, `new_account`, `shared_account` и `unknown` виды выдачи;
- различать варианты ChatGPT Pro X5 / Pro X20 как отдельные тарифы;
- pass 2 через LLM: `--analyzer llm` строит компактные evidence-pack'и
  (описание, зона товара, чипы с ценами, пропущенные варианты, цены
  «плоских» лотов) и классифицирует батчами ~24 КБ — контекст не
  накапливается, `--llm-dry-run` показывает точные размеры промптов;
  регэксп-анализатор остаётся офлайн-фолбэком (`--analyzer regex`);
- чинить цену варианта, когда блок цены не успел обновиться после клика (чип «+N ₽» = наценка к базовой цене лота);
- фильтровать по eligibility-правилам конкретного семейства (tier × duration × delivery, purpose preset);
- детектить UI-глитчи цен (12-мес Max за 1.5M RUB вместо 162K — отбрасываем);
- параллельный сбор через 6 Playwright-воркеров (~90 сек на 42 листинга);
- выводить результат в CSV + Markdown.

## Быстрый запуск

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci --prefix ggsel_plati
```

Канонический CLI:

```bash
# Свежий скан: discovery → collect → analyze
PYTHONPATH=. .venv/bin/python cli.py --family zai --workers 6

# Повторный анализ по уже собранным данным
PYTHONPATH=. .venv/bin/python cli.py --family zai --skip-discover --raw /tmp/zai_raw.json

# С фильтром только Max / 1 месяц / свой аккаунт
PYTHONPATH=. .venv/bin/python cli.py --family zai --tier Max --duration 1m --delivery own_account

# ChatGPT в режиме «продлить на свой аккаунт» (purpose preset)
PYTHONPATH=. .venv/bin/python cli.py --family chatgpt --purpose renew

# Pass 2 через LLM: батчи evidence-pack'ов, классификация без регэкспов
# (нужен LLM_API_KEY; OpenAI-совместимый эндпоинт, по умолчанию gemma4)
PYTHONPATH=. .venv/bin/python cli.py --family chatgpt --purpose renew --analyzer llm

# Проверить размер контекста LLM без реальных вызовов (дампы в /tmp/llm_prompts)
PYTHONPATH=. .venv/bin/python cli.py --family chatgpt --analyzer llm --llm-dry-run \
  --skip-discover --raw docs/audits/data/2026-08-16-audit-raw.json
```

Артефакты:
- `/tmp/zai_raw.json` — сырой сбор (pass 1)
- `/tmp/table.csv` — все офферы с классификацией (pass 2)
- `/tmp/table.md` — канонический отчёт с самой дешёвой ценой по (tier × duration × delivery)

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
│   ├── minimax.py                  # MiniMax Token Plan Max
│   ├── zai.py                      # Z.ai GLM Coding Max
│   ├── chatgpt.py                  # ChatGPT Plus / Pro (purpose presets)
│   └── claude.py                   # Claude Pro / Max (placeholder)
│
├── marketplaces/                   # Per-marketplace adapters
│
├── scanner/                        # Pass 1: collect raw data
│   ├── discover.py                 # Plati API + Crawlee PlaywrightCrawler
│   └── collect.py                  # Run click.py via subprocess
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

`from families import FAMILY_REGISTRY` уже подхватит его автоматически.

### Crawlee backends

`scanner/discover.py` использует Crawlee. Альтернативные клиенты (раскомментируйте по необходимости):
- `ImpitHttpClient` — browser-impersonating HTTP (impit) — для Plati
- `CurlImpersonateHttpClient` — curl-impersonate
- `HttpxHttpClient` — plain httpx
- `PlaywrightCrawler` — реальный Chromium (используется для GGSEL, который 401-ит всех остальных)

## Тесты

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
PYTHONPATH=. .venv/bin/python -m py_compile cli.py scanner/*.py analyzer/*.py families/*.py
node --check click.py
```

## Важно

Цены, наличие и тексты карточек меняются. Результат нужно считать снимком на время запуска. Проект не хранит учётные данные маркетплейсов и не должен использоваться для передачи продавцу паролей без осознанного решения пользователя.

## Лицензия

MIT — см. [LICENSE](LICENSE).
