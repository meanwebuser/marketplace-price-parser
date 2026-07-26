# ChatGPT Plus best price helpers

Скрипты сравнивают цены на ChatGPT Plus/подписки из двух каталогов:

- GGSEL: `https://ggsel.net/catalog/cgpt-plus-upgrade`
- Plati: `https://plati.market/games/chatgpt/1267/?id_c=7396`

## Файлы

- `ggsel_chatgptplus_crawler.py` — достаёт товары GGSEL из JSON payload, заходит в карточки, сохраняет JSON/CSV.
- `plati_chatgptplus_crawler.py` — парсит видимые карточки каталога Plati из HTML первой выдачи.
- `best_chatgptplus_prices.py` — запускает оба парсера и печатает топ предложений по минимальной цене. По умолчанию `--top 3`.

## Запуск

```bash
cd ~/apps/best_price_helpers/chatgptplus
./best_chatgptplus_prices.py
```

Больше строк:

```bash
./best_chatgptplus_prices.py --top 10
```

JSON:

```bash
./best_chatgptplus_prices.py --top 10 --json
```

## Результаты

Runner пишет сырые результаты в:

```text
/tmp/best_price_helpers/chatgptplus/
```

Файлы:

- `ggsel_results.json`
- `ggsel_results.csv`
- `plati_results.json`
- `plati_results.csv`

## Нюанс по Plati

В HTML страницы Plati видно `Найдено товаров: 137`, но обычных ссылок пагинации в HTML нет; первая выдача содержит видимые карточки. Скрипт парсит эти карточки. Если понадобится полный обход всех 137, нужно дополнительно найти XHR/API lazy-load каталога через Network.

## Фильтр тарифа

`best_chatgptplus_prices.py` поддерживает выбор тарифа:

```bash
./best_chatgptplus_prices.py --plan plus --top 10
./best_chatgptplus_prices.py --plan go --top 10
./best_chatgptplus_prices.py --plan pro --top 10
```

По умолчанию используется `--plan plus`.

Для Plati скрипт заходит в detail-страницу и ищет radio-options с `data-delta-price`. Это исправляет ситуацию, когда в каталоге показана минимальная цена GO, а Plus находится как опция с доплатой.

## Plati: browser-click mode

Plati-парсер теперь использует браузерный режим:

1. Открывает каталог Plati.
2. Берёт видимые карточки.
3. Заходит в каждую карточку.
4. Выбирает radio-option нужного тарифа, например `--plan plus`.
5. Читает реальную цену из кнопки/цены после JS-пересчёта.

Это нужно потому, что цена в каталоге часто является минимальной ценой GO, а Plus появляется только после выбора опции внутри карточки.

Ограничение количества проверяемых карточек:

```bash
./best_chatgptplus_prices.py --plan plus --top 10 --detail-limit 25
```

По умолчанию:

```text
--plan plus
--top 3
--detail-limit 30
```
