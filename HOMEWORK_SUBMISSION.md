# Домашнее задание: PDF-генератор чеков

## Что сделано

Создан CLI-скрипт `receipt_generator.py`, который подставляет данные из CSV в HTML-шаблон, генерирует HTML и PDF через WeasyPrint, сохраняет результат в папку `output` и автоматически открывает созданные PDF-файлы в браузере.

## Файлы для сдачи

- `receipt_generator.py` - основной Python-скрипт.
- `homework_receipt_template.html` - простой HTML-шаблон с плейсхолдерами `{{ product }}`, `{{ price }}`, `{{ qty }}`, `{{ total }}`.
- `homework_products.csv` - тестовый CSV-файл с 5 строками данных на русском языке.
- `requirements.txt` - зависимости проекта.
- `PROMPT_USED.md` - зафиксированный составной промпт.
- `OFFER.md` - оффер для фриланс-биржи.

## Быстрый запуск

```powershell
.\.venv\Scripts\python.exe receipt_generator.py --template homework_receipt_template.html --data homework_products.csv --all --output output
```

## Интерактивный запуск

```powershell
.\.venv\Scripts\python.exe receipt_generator.py
```

В меню можно выбрать шаблон, CSV-файл и конкретные строки для генерации.

## Проверка результата

После успешного запуска в папке `output` появляются отдельные `.html` и `.pdf` файлы для каждой строки CSV. Созданные PDF автоматически открываются в браузере.
