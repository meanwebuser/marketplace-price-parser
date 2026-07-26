# Удобный парсер цен GGSEL и Plati

Небольшой инструмент для сравнения предложений на двух маркетплейсах — [GGSEL](https://ggsel.net/) и [Plati](https://plati.market/). Основной сценарий проекта — найти актуальную цену MiniMax Max на один месяц для существующего аккаунта и отсеять похожие, но неподходящие товары.

## Что умеет

- автоматически искать кандидатов в каталоге GGSEL и API каталога Plati;
- открывать карточки товаров в браузере и выбирать вариант `Max / 1 месяц`;
- читать финальную цену выбранного варианта, а не доверять минимальной цене каталога;
- различать свой аккаунт, готовый/shared-аккаунт и неизвестную выдачу;
- исключать Hailuo-only/legacy, кредиты, пополнения и товары с неподходящим сроком;
- сравнивать официальный MiniMax Token Plan с маркетплейсами;
- по желанию проверять смысл карточки через Gemma4 в OpenAI-совместимом API;
- выводить результат в человекочитаемом виде или JSON.

## Быстрый запуск

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci --prefix ggsel_plati

.venv/bin/python minimax_max_prices.py \
  --search-query MiniMax \
  --usd-rub 78.0308
```

Для машинного чтения:

```bash
.venv/bin/python minimax_max_prices.py \
  --search-query MiniMax \
  --usd-rub 78.0308 \
  --json \
  --out /tmp/minimax-price-comparison.json
```

Без сетевого обхода можно проверить официальный вариант:

```bash
.venv/bin/python minimax_max_prices.py --skip-marketplaces --json
```

## Дополнительная проверка Gemma4

Ключ не хранится в репозитории и читается только из окружения:

```bash
export MINIMAX_LLM_API_KEY='...'
.venv/bin/python minimax_max_prices.py --llm --llm-required --json
```

LLM проверяет семейство продукта, тариф, срок, доступность и способ выдачи. Итоговая цена всё равно берётся из браузерного evidence, а не из ответа модели.

## Структура

| Путь | Назначение |
|---|---|
| `minimax_max_prices.py` | основной CLI: официальный оффер, фильтрация и сравнение |
| `minimax_discovery.py` | автоматический поиск кандидатов на GGSEL и Plati |
| `minimax_browser_crawler.js` | Playwright-сбор карточек и выбор варианта |
| `minimax_candidates.json` | официальный URL и legacy-список для ручного режима |
| `skills/marketplace-price-parser/` | публичный skill-инструктаж для AI-агентов |
| `tests/` | unit- и integration-smoke тесты |
| `ggsel_plati/` | отдельные legacy-хелперы для ChatGPT-предложений |

## Тесты

```bash
python3 -m pytest -q
python3 -m py_compile minimax_max_prices.py minimax_discovery.py
node --check minimax_browser_crawler.js
```

## Важно

Цены, наличие и тексты карточек меняются. Результат нужно считать снимком на время запуска. Проект не хранит учётные данные маркетплейсов и не должен использоваться для передачи продавцу паролей без осознанного решения пользователя.

## Лицензия

MIT — см. [LICENSE](LICENSE).
